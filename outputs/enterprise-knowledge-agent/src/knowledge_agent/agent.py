from __future__ import annotations

from typing import Any

from .decision import DecisionModel
from .models import Action, AgentResult, KnowledgeRequest, TraceStep
from .tools import KnowledgeTools


class KnowledgeAgent:
    def __init__(self, model: DecisionModel, tools: KnowledgeTools, max_steps: int = 10):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.model = model
        self.tools = tools
        self.max_steps = max_steps

    def run(self, request: KnowledgeRequest) -> AgentResult:
        resolved = self._resolve_question(request.question, request.history)
        if not request.question.strip():
            return AgentResult(request.question, resolved, "请输入要查询的问题。", [], [], ["缺少问题"], "你想查询什么制度或产品问题？", "needs_clarification", [])

        observations: list[dict[str, Any]] = []
        trace: list[TraceStep] = []
        searched_ids: set[str] = set()
        searched_docs: dict[str, dict[str, Any]] = {}
        read_docs: dict[str, dict[str, Any]] = {}
        successful_searches = 0

        for step in range(1, self.max_steps + 1):
            try:
                action = self.model.decide(request, resolved, observations, step)
            except Exception as exc:
                trace.append(TraceStep(step, "model_error", {}, {"ok": False, "error": type(exc).__name__}, "模型调用失败，安全停止"))
                return self._failure(request, resolved, trace, "决策模型调用失败")
            if not isinstance(action, Action) or not isinstance(action.arguments, dict):
                trace.append(TraceStep(step, "model_error", {}, {"ok": False, "error": "invalid_action"}, "模型动作格式无效"))
                return self._failure(request, resolved, trace, "决策模型返回无效动作")

            if action.name == "finish":
                pending = self._pending_same_topic(action.arguments, searched_docs, read_docs)
                if pending:
                    observation = {"ok": False, "error": "verification_incomplete", "pending_document_ids": pending, "retryable": True}
                    observations.append(observation)
                    trace.append(TraceStep(step, "finish", action.arguments, observation, "同主题候选尚未全部查证，拒绝提前结束"))
                    continue
                if action.arguments.get("status") == "out_of_scope" and successful_searches == 0:
                    observation = {"ok": False, "error": "search_required_before_out_of_scope", "retryable": True}
                    observations.append(observation)
                    trace.append(TraceStep(step, "finish", action.arguments, observation, "未检索不能断言资料外"))
                    continue
                result, observation = self._finish(request, resolved, action.arguments, read_docs, trace)
                trace.append(TraceStep(step, "finish", action.arguments, observation, action.reason))
                result.trace = trace
                return result

            safe_args, violation = self._guard_action(action, request, searched_ids)
            observation = {"ok": False, "error": f"policy_violation:{violation}", "retryable": False} if violation else self.tools.call(action.name, safe_args)
            observations.append(observation)
            if action.name == "search_documents" and observation.get("ok"):
                successful_searches += 1
                searched_ids.update(hit["document_id"] for hit in observation["hits"])
                searched_docs.update({hit["document_id"]: hit for hit in observation["hits"]})
            if action.name == "read_excerpt" and observation.get("ok"):
                read_docs[observation["document_id"]] = observation
            trace.append(TraceStep(step, action.name, safe_args, observation, action.reason))

        return AgentResult(
            request.question, resolved, f"达到最大执行步数 {self.max_steps}，尚未形成可靠答案。",
            [], [], ["执行步数已耗尽"], None, "incomplete", trace,
        )

    @staticmethod
    def _resolve_question(question: str, history: list[dict[str, str]]) -> str:
        compact = question.strip()
        contextual = len(compact) <= 8 or any(token in compact for token in ("它", "这个", "那", "呢", "支持哪些", "要提前多久", "多久", "哪些格式"))
        if not contextual or not history:
            return compact
        prior = next((item.get("content", "") for item in reversed(history) if item.get("role") == "user" and item.get("content")), "")
        return f"上下文主题：{prior}；当前追问：{compact}" if prior else compact

    @staticmethod
    def _guard_action(action: Action, request: KnowledgeRequest, searched_ids: set[str]) -> tuple[dict[str, Any], str | None]:
        if action.name == "search_documents":
            query = action.arguments.get("query")
            safe = {"query": query, "simulate_failure": request.fail_search_once}
            return safe, None if isinstance(query, str) and query.strip() else "invalid_query"
        if action.name == "read_excerpt":
            document_id = action.arguments.get("document_id")
            safe = {"document_id": document_id, "simulate_failure": document_id in request.fail_read_ids}
            return safe, None if document_id in searched_ids else "document_not_in_search_results"
        return action.arguments, "unknown_action"

    def _finish(
        self,
        request: KnowledgeRequest,
        resolved: str,
        args: dict[str, Any],
        read_docs: dict[str, dict[str, Any]],
        trace: list[TraceStep],
    ) -> tuple[AgentResult, dict[str, Any]]:
        requested = args.get("status", "failed")
        citations = args.get("citations", [])
        valid: list[dict[str, str]] = []
        invalid_reason: str | None = None
        for citation in citations:
            doc = read_docs.get(citation.get("document_id"))
            quote = citation.get("quote", "")
            if not doc:
                invalid_reason = "citation_document_not_read"
                break
            if citation.get("version_date") != doc["version_date"] or not quote or quote not in doc["excerpt"]:
                invalid_reason = "citation_not_supported_by_source"
                break
            valid.append({"document_id": doc["document_id"], "version_date": doc["version_date"], "quote": quote})

        conflict_groups: list[list[dict[str, Any]]] = []
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for doc in read_docs.values():
            by_topic.setdefault(doc["topic"], []).append(doc)
        for docs in by_topic.values():
            claim_values: dict[str, set[str]] = {}
            for doc in docs:
                for key, value in doc.get("claims", {}).items():
                    claim_values.setdefault(key, set()).add(str(value))
            if any(len(values) > 1 for values in claim_values.values()):
                conflict_groups.append(docs)

        status = requested if requested in {"answered", "needs_clarification", "out_of_scope", "failed"} else "failed"
        answer = args.get("answer") or "任务未完成。"
        conflicts = args.get("conflicts", [])
        gaps = args.get("information_gaps", [])
        follow_up = args.get("follow_up_question")
        if invalid_reason or (status == "answered" and not valid):
            status, answer, valid = "failed", "引用校验失败，当前不能输出该答案。", []
            gaps = ["模型提供的引用未被已读取原文支持"]
        elif conflict_groups:
            status = "needs_clarification"
            answer = "检索到的资料存在冲突，目前不能可靠地给出唯一结论。"
            required_ids = {doc["document_id"] for group in conflict_groups for doc in group}
            valid_by_id = {item["document_id"]: item for item in valid}
            for doc_id in required_ids:
                if doc_id not in valid_by_id:
                    doc = read_docs[doc_id]
                    valid.append({"document_id": doc_id, "version_date": doc["version_date"], "quote": doc["excerpt"]})
            conflicts = conflicts or [{"document_ids": sorted(required_ids), "description": "同一事项的原文规定不一致，且缺少适用范围或优先级。"}]
            gaps = gaps or ["缺少冲突文档的适用范围或优先级"]
            follow_up = follow_up or "请制度负责人确认应适用哪份规定。"
        elif status == "answered":
            # The user-facing answer is reconstructed from verified evidence.
            # This prevents a model from attaching a real quote to a contradictory answer.
            answer = "\n".join(item["quote"] for item in valid)

        result = AgentResult(request.question, resolved, answer, valid, conflicts, gaps, follow_up, status, trace)
        return result, {"status": status, "requested_status": requested, "citation_validation": invalid_reason or "passed"}

    @staticmethod
    def _failure(request: KnowledgeRequest, resolved: str, trace: list[TraceStep], gap: str) -> AgentResult:
        return AgentResult(request.question, resolved, "系统未能形成有依据的答案。", [], [], [gap], None, "failed", trace)

    @staticmethod
    def _pending_same_topic(args: dict[str, Any], searched_docs: dict[str, dict[str, Any]], read_docs: dict[str, dict[str, Any]]) -> list[str]:
        if args.get("status") not in {"answered", "needs_clarification"}:
            return []
        cited_ids = {item.get("document_id") for item in args.get("citations", []) if isinstance(item, dict)}
        topics = {searched_docs[doc_id]["topic"] for doc_id in cited_ids if doc_id in searched_docs}
        if not topics:
            return []
        return sorted(doc_id for doc_id, hit in searched_docs.items() if hit["topic"] in topics and doc_id not in read_docs)
