from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from .models import Action, PlanningRequest


class DecisionArguments(BaseModel):
    theme: str | None
    variant: Literal["premium", "lean"] | None
    budget: float | None
    deadline_hours: float | None
    total_cost: float | None
    estimated_hours: float | None
    fail_once: bool | None
    simulate_failure: bool | None
    status: Literal["plan_saved", "incomplete", "failed"] | None


class StructuredDecision(BaseModel):
    name: Literal[
        "search_assets", "generate_script", "estimate_cost", "save_plan", "finish"
    ]
    arguments: DecisionArguments
    reason: str


class DecisionModel(Protocol):
    def decide(
        self, request: PlanningRequest, observations: list[dict[str, Any]], step: int
    ) -> Action: ...


class OfflinePolicyModel:
    """Deterministic offline mock for reproducible orchestration tests."""

    def decide(
        self, request: PlanningRequest, observations: list[dict[str, Any]], step: int
    ) -> Action:
        if not observations:
            return Action("search_assets", {"theme": request.theme}, "先检索可用素材与方案")

        last = observations[-1]
        if not last.get("ok"):
            if last.get("error") == "script_service_timeout" and last.get("retryable"):
                return Action(
                    "generate_script",
                    {"theme": request.theme, "variant": "lean", "fail_once": request.fail_script_once},
                    "脚本工具临时失败，保留素材结果并用精简方案续跑",
                )
            return Action("finish", {"status": "failed"}, "工具失败且无法安全恢复")

        if "variants" in last:
            return Action(
                "generate_script",
                {"theme": request.theme, "variant": "premium", "fail_once": request.fail_script_once},
                "素材检索成功，先尝试完整方案",
            )

        if "script" in last:
            return Action(
                "estimate_cost", {"variant": last["variant"]}, "脚本成功，估算实际成本与耗时"
            )

        if "total_cost" in last:
            feasible = (
                request.budget is not None
                and request.deadline_hours is not None
                and last["total_cost"] <= request.budget
                and last["estimated_hours"] <= request.deadline_hours
            )
            if feasible:
                return Action(
                    "save_plan",
                    {
                        "theme": request.theme,
                        "budget": request.budget,
                        "deadline_hours": request.deadline_hours,
                        "variant": last["variant"],
                        "total_cost": last["total_cost"],
                        "estimated_hours": last["estimated_hours"],
                        "simulate_failure": request.simulate_save_failure,
                    },
                    "成本和耗时均满足约束，保存方案",
                )
            if last["variant"] == "premium":
                return Action(
                    "generate_script",
                    {"theme": request.theme, "variant": "lean", "fail_once": request.fail_script_once},
                    "完整方案超预算或超时，改用精简方案重新生成",
                )
            return Action(
                "finish", {"status": "incomplete"}, "精简方案仍不满足预算或截止时间"
            )

        if "saved" in last:
            return Action(
                "finish",
                {"status": "plan_saved" if last["saved"] else "failed"},
                "根据真实保存结果结束",
            )

        return Action("finish", {"status": "failed"}, "无法识别工具结果，安全停止")


class OpenAIDecisionModel:
    def __init__(self, model: str = "gpt-5-mini", client: Any | None = None):
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client
        self.model = model

    def decide(
        self, request: PlanningRequest, observations: list[dict[str, Any]], step: int
    ) -> Action:
        prompt = {
            "role": "你是内容任务规划 Agent，要在预算和截止时间内保存可执行方案。",
            "request": request.__dict__,
            "observations": observations,
            "step": step,
            "tools": {
                "search_assets": ["theme"],
                "generate_script": ["theme", "variant", "fail_once"],
                "estimate_cost": ["variant"],
                "save_plan": [
                    "theme", "budget", "deadline_hours", "variant", "total_cost",
                    "estimated_hours", "simulate_failure"
                ],
                "finish": ["status"],
            },
            "rules": [
                "先检索素材，再生成脚本、估算成本，满足约束后才能保存",
                "超预算或超时必须改用 lean 并重新生成、重新估算",
                "工具失败时可切换 lean 续跑；保留已成功结果",
                "保存失败不能声称成功",
                "所有不适用于当前动作的参数填 null",
            ],
        }
        response = self.client.responses.parse(
            model=self.model,
            input=json.dumps(prompt, ensure_ascii=False),
            text_format=StructuredDecision,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("model returned no structured decision")
        return Action(
            parsed.name, parsed.arguments.model_dump(exclude_none=True), parsed.reason
        )
