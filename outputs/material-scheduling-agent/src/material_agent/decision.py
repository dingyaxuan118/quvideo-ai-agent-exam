from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from .models import Action, ScheduleRequest


class DecisionArguments(BaseModel):
    material_id: str | None
    desired_time: str | None
    requested_time: str | None
    scheduled_time: str | None
    simulate_failure: bool | None
    status: Literal[
        "draft_saved", "pending_confirmation", "blocked", "incomplete", "failed"
    ] | None
    suggested_time: str | None


class StructuredDecision(BaseModel):
    name: Literal[
        "read_material", "check_rules", "query_slots", "save_draft", "finish"
    ]
    arguments: DecisionArguments
    reason: str


class DecisionModel(Protocol):
    def decide(
        self, request: ScheduleRequest, observations: list[dict[str, Any]], step: int
    ) -> Action: ...


class OfflinePolicyModel:
    """Deterministic offline mock used to verify the orchestration flow."""

    def decide(
        self, request: ScheduleRequest, observations: list[dict[str, Any]], step: int
    ) -> Action:
        if not observations:
            return Action("read_material", {"material_id": request.material_id}, "先读取素材元数据")

        last = observations[-1]
        if not last.get("ok"):
            return Action("finish", {"status": "failed"}, "工具失败，不能继续或虚报成功")

        if "material" in last:
            return Action(
                "check_rules", {"material_id": last["material"]["id"]}, "素材存在，执行规则审核"
            )

        if "missing_fields" in last:
            if last["status"] == "incomplete":
                return Action("finish", {"status": "incomplete"}, "关键信息不足，请求补充")
            if last["status"] == "blocked":
                return Action("finish", {"status": "blocked"}, "规则风险必须阻断")
            return Action("query_slots", {"desired_time": request.desired_time}, "审核通过，查询时段")

        if "available" in last:
            if last["available"]:
                chosen = request.desired_time
            else:
                candidate = last["alternatives"][0] if last["alternatives"] else None
                if not candidate:
                    return Action("finish", {"status": "incomplete"}, "没有可替代时段")
                alternatives = last["alternatives"]
                if request.confirmed_time in alternatives:
                    chosen = request.confirmed_time
                elif request.allow_alternative:
                    chosen = candidate
                else:
                    return Action(
                        "finish",
                        {"status": "pending_confirmation", "suggested_time": candidate},
                        "原时段冲突，替代时段未经用户确认",
                    )
            return Action(
                "save_draft",
                {
                    "material_id": request.material_id,
                    "requested_time": request.desired_time,
                    "scheduled_time": chosen,
                    "simulate_failure": request.simulate_save_failure,
                },
                "时段可用且边界已确认，仅保存草稿",
            )

        if "saved" in last:
            status = "draft_saved" if last["saved"] else "failed"
            return Action("finish", {"status": status}, "根据真实保存结果结束")

        return Action("finish", {"status": "failed"}, "无法识别工具结果，安全停止")


class OpenAIDecisionModel:
    """Real model-driven decision maker using the OpenAI Responses API."""

    def __init__(self, model: str = "gpt-5-mini", client: Any | None = None):
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client
        self.model = model

    def decide(
        self, request: ScheduleRequest, observations: list[dict[str, Any]], step: int
    ) -> Action:
        prompt = {
            "role": "你是素材审核与发布排期 Agent，只能保存草稿，绝不能声称已发布。",
            "request": request.__dict__,
            "observations": observations,
            "step": step,
            "tools": {
                "read_material": ["material_id"],
                "check_rules": ["material_id"],
                "query_slots": ["desired_time"],
                "save_draft": [
                    "material_id", "requested_time", "scheduled_time", "simulate_failure"
                ],
                "finish": ["status", "suggested_time?"],
            },
            "rules": [
                "先读素材并审核规则，再查时段，最后才能保存草稿",
                "素材缺失或信息不足时停止并请求补充",
                "规则风险必须阻断",
                "时段冲突时可建议替代时段；未经确认不得改变硬性要求",
                "工具失败必须如实返回失败",
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
            parsed.name,
            parsed.arguments.model_dump(exclude_none=True),
            parsed.reason,
        )
