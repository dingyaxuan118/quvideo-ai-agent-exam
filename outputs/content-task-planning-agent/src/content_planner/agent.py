from __future__ import annotations

import math
from typing import Any

from .decision import DecisionModel
from .models import Action, AgentResult, PlanningRequest, TraceStep
from .tools import PlanningTools


class ContentPlanningAgent:
    def __init__(self, model: DecisionModel, tools: PlanningTools, max_steps: int = 10):
        self.model = model
        self.tools = tools
        self.max_steps = max_steps

    def run(self, request: PlanningRequest) -> AgentResult:
        missing = []
        if not request.theme.strip():
            missing.append("theme")
        if request.budget is None:
            missing.append("budget")
        elif not math.isfinite(request.budget) or request.budget < 0:
            missing.append("budget_must_be_non_negative")
        if request.deadline_hours is None:
            missing.append("deadline_hours")
        elif not math.isfinite(request.deadline_hours) or request.deadline_hours <= 0:
            missing.append("deadline_hours_must_be_positive")
        if missing:
            validation_trace = [
                TraceStep(
                    1, "validate_input", {},
                    {"ok": False, "missing_or_invalid": missing},
                    "输入不完整，停止执行工具",
                )
            ]
            return AgentResult(
                request.theme, request.budget, request.deadline_hours, None,
                None, [], [],
                [{"step": "validate_input", "status": "failed", "result": missing}],
                [], None, None, "not_attempted", "incomplete",
                "缺少或无效的输入：" + ", ".join(missing), None, validation_trace,
            )

        observations: list[dict[str, Any]] = []
        trace: list[TraceStep] = []
        step_status: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        search_done = False
        latest_script_variant: str | None = None
        latest_script: dict[str, Any] | None = None
        latest_estimate: dict[str, Any] | None = None
        selected_variant: str | None = None
        selected_script: str | None = None
        selected_asset_ids: list[str] = []
        total_cost: float | None = None
        estimated_hours: float | None = None
        save_status = "not_attempted"
        plan_id: str | None = None

        for step in range(1, self.max_steps + 1):
            try:
                action = self.model.decide(request, observations, step)
            except Exception as exc:
                trace.append(
                    TraceStep(step, "model_error", {}, {"ok": False, "error": type(exc).__name__}, "模型调用失败，安全停止")
                )
                return self._result(
                    request, selected_variant, selected_script, selected_asset_ids,
                    step_status, tool_results, total_cost,
                    estimated_hours, save_status, "failed", plan_id, trace,
                )
            if not isinstance(action, Action) or not isinstance(action.arguments, dict):
                trace.append(
                    TraceStep(step, "model_error", {}, {"ok": False, "error": "invalid_action"}, "模型动作格式无效")
                )
                return self._result(
                    request, selected_variant, selected_script, selected_asset_ids,
                    step_status, tool_results, total_cost,
                    estimated_hours, save_status, "failed", plan_id, trace,
                )

            if action.name == "finish":
                requested = action.arguments.get("status", "failed")
                status = self._normalize_status(requested, save_status)
                trace.append(
                    TraceStep(step, "finish", action.arguments, {"status": status, "requested_status": requested}, action.reason)
                )
                return self._result(
                    request, selected_variant, selected_script, selected_asset_ids,
                    step_status, tool_results, total_cost,
                    estimated_hours, save_status, status, plan_id, trace,
                )

            safe_args, violation = self._guard_action(
                action.name, action.arguments, request, search_done,
                latest_script_variant, latest_script, latest_estimate,
            )
            observation = (
                {"ok": False, "error": f"policy_violation:{violation}"}
                if violation
                else self.tools.call(action.name, safe_args)
            )
            observations.append(observation)
            tool_results.append(
                {"tool": action.name, "ok": observation.get("ok", False), "result": observation}
            )
            step_status.append(
                {
                    "step": action.name,
                    "variant": safe_args.get("variant"),
                    "status": "succeeded" if observation.get("ok") else "failed",
                }
            )

            if action.name == "search_assets" and observation.get("ok"):
                search_done = True
            elif action.name == "generate_script" and observation.get("ok"):
                latest_script_variant = observation["variant"]
                latest_script = observation
                selected_variant = observation["variant"]
                selected_script = observation["script"]
                selected_asset_ids = list(observation["asset_ids"])
                latest_estimate = None
            elif action.name == "estimate_cost" and observation.get("ok"):
                latest_estimate = observation
                selected_variant = observation["variant"]
                total_cost = observation["total_cost"]
                estimated_hours = observation["estimated_hours"]
            elif action.name == "save_plan":
                save_status = "saved" if observation.get("saved") else "failed"
                if observation.get("duplicate"):
                    save_status = "already_saved"
                    existing = observation.get("existing_plan", {})
                    selected_variant = existing.get("variant", selected_variant)
                    total_cost = existing.get("total_cost", total_cost)
                    estimated_hours = existing.get("estimated_hours", estimated_hours)
                    selected_script = existing.get("script", selected_script)
                    selected_asset_ids = list(existing.get("asset_ids", selected_asset_ids))
                plan_id = observation.get("plan_id")

            trace.append(
                TraceStep(step, action.name, safe_args, observation, action.reason)
            )

        final_status = self._normalize_status("incomplete", save_status)
        return self._result(
            request, selected_variant, selected_script, selected_asset_ids,
            step_status, tool_results, total_cost,
            estimated_hours, save_status, final_status, plan_id, trace,
            message=(
                f"达到最大执行步数 {self.max_steps}，任务未完成"
                if final_status == "incomplete" else None
            ),
        )

    @staticmethod
    def _guard_action(
        name: str,
        arguments: dict[str, Any],
        request: PlanningRequest,
        search_done: bool,
        latest_script_variant: str | None,
        latest_script: dict[str, Any] | None,
        latest_estimate: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str | None]:
        if name == "search_assets":
            safe = {"theme": request.theme}
            return safe, None if arguments.get("theme") == request.theme else "wrong_theme"
        if name == "generate_script":
            variant = arguments.get("variant")
            safe = {"theme": request.theme, "variant": variant, "fail_once": request.fail_script_once}
            if not search_done:
                return safe, "assets_not_searched"
            return safe, None if arguments.get("theme") == request.theme else "wrong_theme"
        if name == "estimate_cost":
            variant = arguments.get("variant")
            safe = {"variant": variant}
            return safe, None if latest_script_variant == variant else "script_not_generated"
        if name == "save_plan":
            variant = arguments.get("variant")
            safe = {
                "theme": request.theme,
                "budget": request.budget,
                "deadline_hours": request.deadline_hours,
                "variant": variant,
                "total_cost": latest_estimate.get("total_cost") if latest_estimate else None,
                "estimated_hours": latest_estimate.get("estimated_hours") if latest_estimate else None,
                "simulate_failure": request.simulate_save_failure,
                "script": latest_script.get("script") if latest_script else None,
                "asset_ids": latest_script.get("asset_ids") if latest_script else None,
            }
            if (
                not latest_script
                or latest_script.get("variant") != variant
                or not latest_estimate
                or latest_estimate.get("variant") != variant
            ):
                return safe, "estimate_missing_or_stale"
            if latest_estimate["total_cost"] > request.budget:
                return safe, "budget_exceeded"
            if latest_estimate["estimated_hours"] > request.deadline_hours:
                return safe, "deadline_exceeded"
            return safe, None
        return arguments, "unknown_action"

    @staticmethod
    def _normalize_status(requested: str, save_status: str) -> str:
        if save_status in {"saved", "already_saved"}:
            return "plan_saved"
        if save_status == "failed":
            return "failed"
        if requested == "plan_saved":
            return "failed"
        return requested if requested in {"incomplete", "failed"} else "failed"

    @staticmethod
    def _message(status: str, save_status: str) -> str:
        if status == "plan_saved" and save_status == "already_saved":
            return "相同方案已存在，未重复创建；已有方案保持可用。"
        messages = {
            "plan_saved": "方案满足预算和截止时间，已保存。",
            "incomplete": "没有方案能同时满足预算和截止时间，任务未完成。",
            "failed": "决策或工具执行失败，任务未完成且未虚报成功。",
        }
        return messages[status]

    def _result(
        self,
        request: PlanningRequest,
        selected_variant: str | None,
        selected_script: str | None,
        selected_asset_ids: list[str],
        step_status: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        total_cost: float | None,
        estimated_hours: float | None,
        save_status: str,
        status: str,
        plan_id: str | None,
        trace: list[TraceStep],
        message: str | None = None,
    ) -> AgentResult:
        task_plan: list[dict[str, Any]] = []
        if selected_variant and selected_script:
            task_plan = [
                {"task": "准备素材", "status": "completed", "result": selected_asset_ids},
                {"task": "生成脚本", "status": "completed", "result": selected_script},
                {
                    "task": "安排渠道投放",
                    "status": "pending" if status == "plan_saved" else "blocked",
                    "variant": selected_variant,
                },
            ]
        return AgentResult(
            request.theme, request.budget, request.deadline_hours, selected_variant,
            selected_script, selected_asset_ids, task_plan, step_status, tool_results,
            total_cost, estimated_hours, save_status,
            status, message or self._message(status, save_status), plan_id, trace,
        )
