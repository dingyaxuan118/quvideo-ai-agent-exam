from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ScriptTools:
    def __init__(self, data_dir: Path):
        data = json.loads((data_dir / "materials.json").read_text(encoding="utf-8"))
        self.materials = data["materials"]
        self.by_id = {item["material_id"]: item for item in self.materials}
        self.brand_rules = data["brand_rules"]
        self._search_failed = False
        self._estimate_failed = False

    @staticmethod
    def fingerprint(title: str, storyboard: list[dict[str, str]], source_ids: list[str]) -> str:
        raw = json.dumps([title, storyboard, source_ids], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _score(query: str, item: dict[str, Any]) -> int:
        terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", query.lower()))
        haystack = " ".join([item["product"], *item["keywords"]]).lower()
        return sum(2 for keyword in item["keywords"] if keyword.lower() in query.lower()) + sum(1 for term in terms if term in haystack)

    def top_material_ids(self, query: str) -> set[str]:
        scored = [(self._score(query, item), item["material_id"]) for item in self.materials]
        best = max((score for score, _ in scored), default=0)
        return {material_id for score, material_id in scored if score == best and score > 0}

    def search_materials(self, query: str, simulate_failure: bool = False) -> dict[str, Any]:
        if simulate_failure and not self._search_failed:
            self._search_failed = True
            return {"ok": False, "error": "material_search_timeout", "retryable": True}
        if not query.strip():
            return {"ok": False, "error": "query_required", "retryable": False}
        ranked = []
        for item in self.materials:
            score = self._score(query, item)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["material_id"]))
        hits = [{"material_id": item["material_id"], "product": item["product"], "facts": item["facts"], "score": score} for score, item in ranked]
        return {"ok": True, "query": query, "hits": hits}

    def estimate_duration(self, title: str, storyboard: list[dict[str, str]], source_ids: list[str], simulate_failure: bool = False) -> dict[str, Any]:
        if simulate_failure and not self._estimate_failed:
            self._estimate_failed = True
            return {"ok": False, "error": "duration_service_timeout", "retryable": True}
        scene_durations = []
        total_units = 0
        for index, scene in enumerate(storyboard):
            narration = scene.get("narration", "")
            subtitle = scene.get("subtitle", "")
            narration_units = len(re.findall(r"[\u4e00-\u9fff]", narration)) + len(re.findall(r"[A-Za-z0-9]+", narration))
            subtitle_units = len(re.findall(r"[\u4e00-\u9fff]", subtitle)) + len(re.findall(r"[A-Za-z0-9]+", subtitle))
            narration_seconds = narration_units / 4.0
            reading_seconds = subtitle_units / 5.0
            seconds = round(max(1.5, narration_seconds, reading_seconds), 1)
            scene_durations.append({"scene_index": index, "narration_seconds": round(narration_seconds, 1), "subtitle_reading_seconds": round(reading_seconds, 1), "estimated_seconds": seconds})
            total_units += narration_units
        total = round(sum(item["estimated_seconds"] for item in scene_durations), 1)
        return {"ok": True, "draft_id": self.fingerprint(title, storyboard, source_ids), "estimated_duration": total, "unit_count": total_units, "scene_durations": scene_durations}

    def check_rules(self, title: str, storyboard: list[dict[str, str]], source_ids: list[str], simulate_failure: bool = False) -> dict[str, Any]:
        if simulate_failure:
            return {"ok": False, "error": "rule_service_unavailable", "retryable": False}
        content_blocks = [value for item in storyboard for value in (item.get("narration", ""), item.get("subtitle", ""))]
        blocks = [title, *content_blocks]
        text = "。".join(blocks)
        source_facts = " ".join(fact for sid in source_ids if sid in self.by_id for fact in self.by_id[sid]["facts"])
        rule_types = {rule.get("type") for rule in self.brand_rules.get("rules", []) if isinstance(rule, dict)}
        dynamic_terms = list(self.brand_rules.get("forbidden_terms", []))
        for rule in self.brand_rules.get("rules", []):
            if isinstance(rule, str):
                dynamic_terms.extend(re.findall(r"不得使用[“\"](.+?)[”\"]", rule))
        violations = [f"绝对化用语：{term}" for term in dynamic_terms if term in text] if "forbid_terms" in rule_types or dynamic_terms else []
        if "reject_unsupported_percentage" in rule_types:
            for claim in re.findall(r"\d+(?:\.\d+)?%|[一二三四五六七八九十两]+成", text):
                if claim not in source_facts:
                    violations.append(f"素材未支持的效果数据：{claim}")
        product_names = {self.by_id[sid]["product"] for sid in source_ids if sid in self.by_id}
        allowed_facts = [fact.rstrip("。") for sid in source_ids if sid in self.by_id for fact in self.by_id[sid]["facts"]]
        if "require_source_fact" in rule_types and source_ids and not any(fact in text for fact in allowed_facts):
            violations.append("脚本未包含任何可核验的素材事实")
        claim_markers = ("支持", "可以", "具备", "采用", "提升", "降低", "增长")
        if "reject_unsupported_claim" in rule_types:
            for block in content_blocks:
                residual = block
                for fact in allowed_facts:
                    residual = residual.replace(fact, "")
                for sentence in re.split(r"[。！？!?；;，,]", residual):
                    looks_factual = (
                        any(marker in sentence for marker in claim_markers)
                        or any(product in sentence for product in product_names)
                        or bool(re.search(r"\d|[A-Z]{2,}", sentence))
                    )
                    if looks_factual and sentence.strip():
                        violations.append(f"素材未支持的产品陈述：{sentence.strip()}")
        mentioned_known = {item["product"] for item in self.materials if item["product"] in text}
        if mentioned_known - product_names:
            violations.append("脚本提及了未授权素材中的产品")
        if not source_ids:
            violations.append("缺少素材来源")
        return {"ok": True, "draft_id": self.fingerprint(title, storyboard, source_ids), "passed": not violations, "violations": violations}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {"search_materials": self.search_materials, "estimate_duration": self.estimate_duration, "check_rules": self.check_rules}
        if name not in allowed:
            return {"ok": False, "error": f"unknown_tool:{name}"}
        try:
            return allowed[name](**arguments)
        except (TypeError, ValueError, OSError) as exc:
            return {"ok": False, "error": f"tool_error:{type(exc).__name__}:{exc}"}
