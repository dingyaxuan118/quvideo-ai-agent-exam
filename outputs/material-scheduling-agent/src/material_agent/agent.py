from __future__ import annotations

from typing import Any

from .decision import DecisionModel
from .models import Action, AgentResult, ScheduleRequest, TraceStep
from .tools import BusinessTools


class MaterialSchedulingAgent:
    def __init__(self, model: DecisionModel, tools: BusinessTools, max_steps: int = 8):
        self.model = model
        self.tools = tools
        self.max_steps = max_steps

    def run(self, request: ScheduleRequest) -> AgentResult:
        observations: list[dict[str, Any]] = []
        trace: list[TraceStep] = []
        review_status = "not_checked"
        risks: list[str] = []
        suggested_time: str | None = None
        draft_status = "not_attempted"
        draft_id: str | None = None
        material_read = False
        slot_result: dict[str, Any] | None = None

        for step in range(1, self.max_steps + 1):
            try:
                action = self.model.decide(request, observations, step)
            except Exception as exc:  # Model/network/invalid JSON failures must be reportable.
                trace.append(
                    TraceStep(
                        step,
                        "model_error",
                        {},
                        {"ok": False, "error": type(exc).__name__},
                        "模型调用失败，安全停止",
                    )
                )
                return self._result(
                    request, review_status, risks, suggested_time, draft_status,
                    "failed", draft_id, trace,
                )
            if not isinstance(action, Action) or not isinstance(action.arguments, dict):
                trace.append(
                    TraceStep(
                        step, "model_error", {},
                        {"ok": False, "error": "invalid_action"},
                        "模型返回格式无效，安全停止",
                    )
                )
                return self._result(
                    request, review_status, risks, suggested_time, draft_status,
                    "failed", draft_id, trace,
                )
            if action.name == "finish":
                requested_status = action.arguments.get("status", "failed")
                status, suggested_time = self._normalize_finish(
                    requested_status, action.arguments.get("suggested_time") or suggested_time,
                    review_status, slot_result, draft_status, request,
                )
                trace.append(
                    TraceStep(
                        step, "finish", action.arguments,
                        {"status": status, "requested_status": requested_status}, action.reason,
                    )
                )
                return self._result(
                    request, review_status, risks, suggested_time, draft_status,
                    status, draft_id, trace,
                )

            safe_arguments, violation = self._guard_action(
                action.name, action.arguments, request, material_read,
                review_status, slot_result,
            )
            observation = (
                {"ok": False, "error": f"policy_violation:{violation}"}
                if violation
                else self.tools.call(action.name, safe_arguments)
            )
            observations.append(observation)
            if action.name == "read_material" and observation.get("ok"):
                material_read = True
            elif action.name == "check_rules" and observation.get("ok"):
                review_status = observation.get("status", "unknown")
                risks = list(observation.get("risks", []))
                if observation.get("missing_fields"):
                    risks.append("缺少字段：" + ", ".join(observation["missing_fields"]))
            elif action.name == "query_slots" and observation.get("ok"):
                slot_result = observation
                if not observation.get("available", True):
                    alternatives = observation.get("alternatives", [])
                    suggested_time = alternatives[0] if alternatives else None
            elif action.name == "save_draft":
                draft_status = "saved" if observation.get("saved") else "failed"
                if observation.get("duplicate"):
                    draft_status = "already_saved"
                draft_id = observation.get("draft_id")
                if (
                    observation.get("saved")
                    and safe_arguments.get("scheduled_time") != request.desired_time
                ):
                    suggested_time = safe_arguments.get("scheduled_time")
            trace.append(
                TraceStep(step, action.name, safe_arguments, observation, action.reason)
            )

        return AgentResult(
            request.material_id,
            review_status,
            risks,
            request.desired_time,
            suggested_time,
            [],
            draft_status,
            "incomplete",
            f"达到最大执行步数 {self.max_steps}，任务未完成",
            draft_id,
            trace,
        )

    @staticmethod
    def _guard_action(
        name: str,
        arguments: dict[str, Any],
        request: ScheduleRequest,
        material_read: bool,
        review_status: str,
        slot_result: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str | None]:
        if name == "read_material":
            safe = {"material_id": request.material_id}
            return safe, None if arguments.get("material_id") == request.material_id else "wrong_material"
        if name == "check_rules":
            safe = {"material_id": request.material_id}
            if not material_read:
                return safe, "material_not_read"
            return safe, None if arguments.get("material_id") == request.material_id else "wrong_material"
        if name == "query_slots":
            safe = {"desired_time": request.desired_time}
            if review_status != "approved":
                return safe, "material_not_approved"
            return safe, None if arguments.get("desired_time") == request.desired_time else "wrong_time"
        if name == "save_draft":
            chosen = arguments.get("scheduled_time")
            safe = {
                "material_id": request.material_id,
                "requested_time": request.desired_time,
                "scheduled_time": chosen,
                "simulate_failure": request.simulate_save_failure,
            }
            if review_status != "approved" or not slot_result:
                return safe, "prerequisites_not_met"
            if slot_result.get("available"):
                permitted = chosen == request.desired_time
            else:
                alternatives = slot_result.get("alternatives", [])
                permitted = chosen in alternatives and (
                    request.allow_alternative or request.confirmed_time == chosen
                )
            return safe, None if permitted else "unconfirmed_or_unavailable_time"
        return arguments, "unknown_action"

    @staticmethod
    def _normalize_finish(
        requested_status: str,
        proposed_time: str | None,
        review_status: str,
        slot_result: dict[str, Any] | None,
        draft_status: str,
        request: ScheduleRequest,
    ) -> tuple[str, str | None]:
        if draft_status in {"saved", "already_saved"}:
            return "draft_saved", proposed_time
        if draft_status == "failed":
            return "failed", proposed_time
        if requested_status == "draft_saved":
            return "failed", proposed_time
        if requested_status == "blocked":
            return ("blocked", proposed_time) if review_status == "blocked" else ("failed", proposed_time)
        if requested_status == "pending_confirmation":
            alternatives = slot_result.get("alternatives", []) if slot_result else []
            has_consent = request.allow_alternative or request.confirmed_time in alternatives
            if slot_result and not slot_result.get("available") and alternatives and not has_consent:
                return "pending_confirmation", proposed_time if proposed_time in alternatives else alternatives[0]
            return "failed", proposed_time
        if requested_status == "incomplete":
            return "incomplete", proposed_time
        return "failed", proposed_time

    def _result(
        self,
        request: ScheduleRequest,
        review_status: str,
        risks: list[str],
        suggested_time: str | None,
        draft_status: str,
        status: str,
        draft_id: str | None,
        trace: list[TraceStep],
    ) -> AgentResult:
        return AgentResult(
            request.material_id, review_status, risks, request.desired_time,
            suggested_time,
            ["请确认替代发布时间"] if status == "pending_confirmation" else [],
            draft_status, status, self._message(status, suggested_time), draft_id, trace,
        )

    @staticmethod
    def _message(status: str, suggested_time: str | None) -> str:
        messages = {
            "draft_saved": "审核通过，排期草稿已保存；内容尚未发布。",
            "pending_confirmation": f"原时段冲突，建议 {suggested_time}；等待用户确认，未保存草稿。",
            "blocked": "素材存在规则风险，已阻断排期。",
            "incomplete": "素材信息或可用资源不足，任务未完成。",
            "failed": "决策或工具执行失败，任务未完成且未宣称保存成功。",
        }
        return messages.get(status, "任务安全停止。")
