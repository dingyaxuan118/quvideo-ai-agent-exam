from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .models import Action, KnowledgeRequest


class CitationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    version_date: str
    quote: str


class ConflictDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str]
    description: str


class DecisionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # All fields are required by the strict JSON schema. Irrelevant scalar
    # values must be null and irrelevant collections must be empty.
    query: str | None
    document_id: str | None
    status: Literal["answered", "needs_clarification", "out_of_scope", "failed"] | None
    answer: str | None
    citations: list[CitationDecision]
    conflicts: list[ConflictDecision]
    information_gaps: list[str]
    follow_up_question: str | None


class StructuredDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["search_documents", "read_excerpt", "finish"]
    arguments: DecisionArguments
    reason: str


class DecisionModel(Protocol):
    def decide(
        self,
        request: KnowledgeRequest,
        resolved_question: str,
        observations: list[dict[str, Any]],
        step: int,
    ) -> Action: ...


class OfflinePolicyModel:
    """Deterministic mock. It validates orchestration without pretending to be an LLM."""

    def decide(
        self,
        request: KnowledgeRequest,
        resolved_question: str,
        observations: list[dict[str, Any]],
        step: int,
    ) -> Action:
        searches = [item for item in observations if "hits" in item]
        reads = {
            item["document_id"]: item
            for item in observations
            if item.get("ok") and "excerpt" in item
        }
        if not observations:
            return Action("search_documents", {"query": resolved_question}, "先按完整问题检索候选文档")

        last = observations[-1]
        if not last.get("ok"):
            if last.get("retryable"):
                return Action("search_documents", {"query": resolved_question}, "检索暂时失败，依据观察结果重试一次")
            return Action(
                "finish",
                {
                    "status": "failed",
                    "answer": "知识工具不可用，当前无法形成有依据的答案。",
                    "information_gaps": ["未能读取所需知识来源"],
                },
                "关键工具失败，停止并避免无依据回答",
            )

        if "hits" in last:
            if not last["hits"]:
                if len(searches) < 2:
                    return Action("search_documents", {"query": self._broaden(resolved_question)}, "首轮无结果，改写为核心主题补充检索")
                return Action(
                    "finish",
                    {
                        "status": "out_of_scope",
                        "answer": "现有企业知识库中没有足以回答该问题的资料。",
                        "information_gaps": [f"缺少与“{resolved_question}”相关的制度或产品文档"],
                        "follow_up_question": "可以提供相关文档名称、产品名称或制度范围吗？",
                    },
                    "两轮检索均无结果，说明资料缺口",
                )
            pending = [hit["document_id"] for hit in last["hits"] if hit["document_id"] not in reads]
            if pending:
                return Action("read_excerpt", {"document_id": pending[0]}, "读取候选文档原文后再判断")

        latest_search = searches[-1] if searches else {"hits": []}
        pending = [hit["document_id"] for hit in latest_search["hits"] if hit["document_id"] not in reads]
        if pending:
            return Action("read_excerpt", {"document_id": pending[0]}, "继续读取同一主题的候选原文，排查冲突")

        relevant = [reads[hit["document_id"]] for hit in latest_search["hits"] if hit["document_id"] in reads]
        topics: dict[str, list[dict[str, Any]]] = {}
        for item in relevant:
            topics.setdefault(item["topic"], []).append(item)
        conflicted = None
        for items in topics.values():
            values_by_key: dict[str, set[str]] = {}
            for item in items:
                for key, value in item.get("claims", {}).items():
                    values_by_key.setdefault(key, set()).add(str(value))
            if any(len(values) > 1 for values in values_by_key.values()):
                conflicted = items
                break
        citations = [
            {"document_id": item["document_id"], "version_date": item["version_date"], "quote": item["excerpt"]}
            for item in (conflicted or relevant[:1])
        ]
        if conflicted:
            ids = [item["document_id"] for item in conflicted]
            return Action(
                "finish",
                {
                    "status": "needs_clarification",
                    "answer": "检索到的资料存在冲突，目前不能可靠地给出唯一结论。",
                    "citations": citations,
                    "conflicts": [{"document_ids": ids, "description": "同一事项的规定不一致，且文档未说明适用范围或优先级。"}],
                    "information_gaps": ["缺少两份规定的适用范围或优先级"],
                    "follow_up_question": "请财务或制度负责人确认应适用哪份规定。",
                },
                "原文对同一事项给出不同规定，列出冲突并请求确认",
            )
        item = relevant[0]
        return Action(
            "finish",
            {
                "status": "answered",
                "answer": self._answer(item),
                "citations": citations,
            },
            "原文能够直接支持答案，附真实引用后结束",
        )

    @staticmethod
    def _broaden(question: str) -> str:
        core = question.replace("请问", "").replace("公司", "").strip()
        return f"{core} 制度 产品 FAQ"

    @staticmethod
    def _answer(item: dict[str, Any]) -> str:
        return item["excerpt"]


class OpenAIDecisionModel:
    """Real model entry using OpenAI Responses API structured outputs."""

    def __init__(self, model: str = "gpt-5-mini", client: Any | None = None):
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client
        self.model = model

    def decide(
        self,
        request: KnowledgeRequest,
        resolved_question: str,
        observations: list[dict[str, Any]],
        step: int,
    ) -> Action:
        prompt = {
            "role": "你是企业知识问答 Agent。每一步只选择一个动作，并根据工具观察调整。",
            "question": request.question,
            "resolved_question": resolved_question,
            "history": request.history,
            "observations": observations,
            "step": step,
            "tools": {
                "search_documents": {"query": "检索语句"},
                "read_excerpt": {"document_id": "必须来自检索结果"},
                "finish": {"status": "任务状态", "answer": "答案", "citations": "引用", "conflicts": "冲突", "information_gaps": "缺口", "follow_up_question": "追问"},
            },
            "rules": [
                "必须先检索；回答或引用前必须读取原文",
                "引用 quote 必须逐字来自 read_excerpt 的 excerpt，并带文档 ID 和版本日期",
                "同一事项存在不一致时，读取相关原文，列出冲突并请求确认；不得按日期自行选择",
                "无资料时可改写补充检索；仍无结果则说明资料缺口",
                "工具失败后根据 retryable 决定改写、重试或停止，绝不能编造答案",
                "所有与当前动作无关的标量参数填 null，列表填空列表",
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
        return Action(parsed.name, parsed.arguments.model_dump(exclude_none=True), parsed.reason)
