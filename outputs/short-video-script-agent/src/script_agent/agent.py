from __future__ import annotations

import math
from typing import Any

from .decision import DecisionModel
from .models import Action, ScriptRequest, ScriptResult, TraceStep
from .tools import ScriptTools


class ScriptAgent:
    def __init__(self, model: DecisionModel, tools: ScriptTools, max_steps: int = 12):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.model, self.tools, self.max_steps = model, tools, max_steps

    def run(self, request: ScriptRequest) -> ScriptResult:
        missing = []
        for name in ("topic", "audience", "platform", "style"):
            value = getattr(request, name)
            if not isinstance(value, str) or not value.strip():
                missing.append(name)
        if request.target_duration is None or not math.isfinite(request.target_duration) or request.target_duration <= 0:
            missing.append("target_duration_must_be_positive")
        if missing:
            trace = [TraceStep(1, "validate_input", {}, {"ok": False, "missing_or_invalid": missing}, "关键信息不足，不调用工具")]
            return ScriptResult(None, [], None, [], [], missing, "needs_input", "请补充或修正关键信息。", trace)

        observations: list[dict[str, Any]] = []
        trace: list[TraceStep] = []
        searched_ids: set[str] = set()
        drafts: dict[str, dict[str, Any]] = {}
        estimates: dict[str, dict[str, Any]] = {}
        checks: dict[str, dict[str, Any]] = {}
        latest_id: str | None = None

        for step in range(1, self.max_steps + 1):
            try:
                action = self.model.decide(request, observations, step)
            except Exception as exc:
                trace.append(TraceStep(step, "model_error", {}, {"ok": False, "error": type(exc).__name__}, "模型调用失败，安全停止"))
                return self._failed(trace, "决策模型调用失败")
            if not isinstance(action, Action) or not isinstance(action.arguments, dict):
                return self._failed(trace, "决策动作格式无效")

            if action.name == "finish":
                result, obs = self._finish(action.arguments, request, drafts, estimates, checks, latest_id, trace)
                trace.append(TraceStep(step, "finish", action.arguments, obs, action.reason))
                result.trace = trace
                return result

            safe, violation = self._guard(action, request, searched_ids, estimates)
            observation = {"ok": False, "error": f"policy_violation:{violation}", "retryable": False} if violation else self.tools.call(action.name, safe)
            if observation.get("ok") and action.name == "search_materials":
                searched_ids.update(hit["material_id"] for hit in observation["hits"])
            if observation.get("ok") and action.name in {"estimate_duration", "check_rules"}:
                draft_id = observation["draft_id"]
                draft = {k: safe[k] for k in ("title", "storyboard", "source_ids")}
                drafts[draft_id] = draft
                latest_id = draft_id
                (estimates if action.name == "estimate_duration" else checks)[draft_id] = observation
            model_observation = {**observation, "_action": action.name, "_arguments": safe}
            observations.append(model_observation)
            trace.append(TraceStep(step, action.name, safe, observation, action.reason))

        return ScriptResult(None, [], None, [], [], ["执行步数已耗尽"], "incomplete", f"达到最大执行步数 {self.max_steps}，未完成全部检查。", trace)

    def _guard(self, action: Action, request: ScriptRequest, searched_ids: set[str], estimates: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
        if action.name == "search_materials":
            query = action.arguments.get("query")
            return {"query": query, "simulate_failure": request.fail_search_once}, None if isinstance(query, str) and query.strip() else "invalid_query"
        if action.name in {"estimate_duration", "check_rules"}:
            title = action.arguments.get("title")
            storyboard = action.arguments.get("storyboard")
            source_ids = action.arguments.get("source_ids")
            safe = {"title": title, "storyboard": storyboard, "source_ids": source_ids, "simulate_failure": request.fail_estimate_once if action.name == "estimate_duration" else request.fail_rule_check}
            if not isinstance(title, str) or not title.strip() or not isinstance(storyboard, list) or not storyboard:
                return safe, "invalid_draft"
            if not isinstance(source_ids, list) or not source_ids or not set(source_ids) <= searched_ids:
                return safe, "source_not_in_search_results"
            if not set(source_ids) <= self.tools.top_material_ids(request.topic):
                return safe, "source_not_relevant_to_original_topic"
            if any(not isinstance(scene, dict) or not all(isinstance(scene.get(k), str) for k in ("shot", "narration", "subtitle")) for scene in storyboard):
                return safe, "invalid_storyboard"
            if action.name == "check_rules":
                draft_id = self.tools.fingerprint(title, storyboard, source_ids)
                estimate = estimates.get(draft_id)
                if not estimate:
                    return safe, "current_draft_not_estimated"
                if estimate["estimated_duration"] > request.target_duration:
                    return safe, "duration_exceeded"
            return safe, None
        return action.arguments, "unknown_action"

    def _finish(self, args: dict[str, Any], request: ScriptRequest, drafts: dict[str, dict[str, Any]], estimates: dict[str, dict[str, Any]], checks: dict[str, dict[str, Any]], latest_id: str | None, trace: list[TraceStep]) -> tuple[ScriptResult, dict[str, Any]]:
        requested = args.get("status", "failed")
        if requested == "completed":
            if not latest_id or latest_id not in drafts or latest_id not in estimates or latest_id not in checks:
                return self._failed(trace, "最终草稿缺少真实检查结果"), {"status": "failed", "requested_status": requested, "error": "missing_current_checks"}
            estimate, check = estimates[latest_id], checks[latest_id]
            if estimate["estimated_duration"] > request.target_duration or not check.get("passed"):
                return self._failed(trace, "最终草稿未通过时长或规则检查"), {"status": "failed", "requested_status": requested, "error": "checks_not_passed"}
            draft = drafts[latest_id]
            scene_times = {item["scene_index"]: item["estimated_seconds"] for item in estimate.get("scene_durations", [])}
            storyboard = [{**scene, "estimated_seconds": scene_times.get(index)} for index, scene in enumerate(draft["storyboard"])]
            result = ScriptResult(draft["title"], storyboard, estimate["estimated_duration"], draft["source_ids"], [], [], "completed", "脚本已通过时长与规则检查。", trace)
            return result, {"status": "completed", "requested_status": requested, "draft_id": latest_id}
        status = requested if requested in {"needs_input", "failed"} else "failed"
        return ScriptResult(None, [], None, [], list(args.get("risks", [])), list(args.get("information_gaps", [])), status, args.get("message") or "任务未完成。", trace), {"status": status, "requested_status": requested}

    @staticmethod
    def _failed(trace: list[TraceStep], reason: str) -> ScriptResult:
        return ScriptResult(None, [], None, [], [reason], [], "failed", "未能形成通过检查的可靠脚本。", trace)
