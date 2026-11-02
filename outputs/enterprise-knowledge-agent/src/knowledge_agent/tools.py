from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class KnowledgeTools:
    """Trusted retrieval tools backed by replaceable synthetic documents."""

    def __init__(self, data_dir: Path):
        self.documents: list[dict[str, Any]] = json.loads(
            (data_dir / "documents.json").read_text(encoding="utf-8")
        )
        self.by_id = {doc["document_id"]: doc for doc in self.documents}
        self._search_failure_consumed = False

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lower = text.lower()
        latin = set(re.findall(r"[a-z0-9]+", lower))
        chinese = re.sub(r"[^\u4e00-\u9fff]", "", lower)
        grams = {chinese[i : i + 2] for i in range(max(0, len(chinese) - 1))}
        aliases = {
            "休假": "年假", "假期": "年假", "多早": "提前", "几天": "多久",
            "多久内": "期限", "费用申请": "报销", "文本轨": "字幕",
        }
        alias_tokens: set[str] = set()
        for source, target in aliases.items():
            if source in lower:
                alias_tokens.add(target)
                alias_tokens.update(target[i : i + 2] for i in range(max(0, len(target) - 1)))
        phrases = set(re.findall(r"[\u4e00-\u9fff]{2,}", lower))
        return latin | grams | phrases | alias_tokens

    def search_documents(self, query: str, simulate_failure: bool = False) -> dict[str, Any]:
        if simulate_failure and not self._search_failure_consumed:
            self._search_failure_consumed = True
            return {"ok": False, "error": "search_service_timeout", "retryable": True}
        if not query.strip():
            return {"ok": False, "error": "query_required", "retryable": False}
        query_tokens = self._tokens(query)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for doc in self.documents:
            haystack = " ".join([doc["title"], *doc["keywords"]])
            score = len(query_tokens & self._tokens(haystack))
            # A single generic overlap (for example “多久”) is too weak and
            # would make unrelated policies look relevant.
            if score >= 2:
                ranked.append((score, doc))
        ranked.sort(key=lambda item: (-item[0], item[1]["document_id"]))
        hits = [
            {
                "document_id": doc["document_id"],
                "title": doc["title"],
                "version_date": doc["version_date"],
                "topic": doc["topic"],
                "match_summary": f"命中关键词：{', '.join(doc['keywords'][:3])}",
                "score": score,
            }
            for score, doc in ranked[:5]
        ]
        return {"ok": True, "query": query, "hits": hits}

    def read_excerpt(self, document_id: str, simulate_failure: bool = False) -> dict[str, Any]:
        if simulate_failure:
            return {"ok": False, "error": "document_store_unavailable", "document_id": document_id}
        doc = self.by_id.get(document_id)
        if not doc:
            return {"ok": False, "error": "document_not_found", "document_id": document_id}
        return {
            "ok": True,
            "document_id": doc["document_id"],
            "title": doc["title"],
            "version_date": doc["version_date"],
            "topic": doc["topic"],
            "claims": self._effective_claims(doc),
            "excerpt": doc["content"],
        }

    @staticmethod
    def _effective_claims(doc: dict[str, Any]) -> dict[str, str]:
        """Refresh numeric claims from replaceable content instead of trusting stale metadata."""
        claims = dict(doc.get("claims", {}))
        numeric_patterns = {
            "deadline_days": r"(\d+)\s*天",
            "notice_workdays": r"(\d+)\s*个?工作日",
            "max_file_mb": r"(\d+)\s*MB",
        }
        for key, pattern in numeric_patterns.items():
            if key in claims:
                match = re.search(pattern, doc["content"], re.I)
                if match:
                    claims[key] = match.group(1)
                else:
                    claims.pop(key, None)
        return claims

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "search_documents":
                return self.search_documents(**arguments)
            if name == "read_excerpt":
                return self.read_excerpt(**arguments)
            return {"ok": False, "error": f"unknown_tool:{name}"}
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"tool_error:{type(exc).__name__}:{exc}"}
