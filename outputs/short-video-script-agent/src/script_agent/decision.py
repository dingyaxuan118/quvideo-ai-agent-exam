from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .models import Action, ScriptRequest


class SceneDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot: str
    narration: str
    subtitle: str


class DecisionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None
    title: str | None
    storyboard: list[SceneDecision]
    source_ids: list[str]
    status: Literal["completed", "needs_input", "failed"] | None
    message: str | None
    risks: list[str]
    information_gaps: list[str]


class StructuredDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["search_materials", "estimate_duration", "check_rules", "finish"]
    arguments: DecisionArguments
    reason: str


class DecisionModel(Protocol):
    def decide(self, request: ScriptRequest, observations: list[dict[str, Any]], step: int) -> Action: ...


class OfflinePolicyModel:
    """Deterministic orchestration mock; not a substitute for an LLM evaluation."""

    def decide(self, request: ScriptRequest, observations: list[dict[str, Any]], step: int) -> Action:
        if not observations:
            return Action("search_materials", {"query": request.topic}, "先检索主题相关的产品素材")
        last = observations[-1]
        if not last.get("ok"):
            if last.get("retryable"):
                if last.get("_action") == "search_materials":
                    return Action("search_materials", {"query": request.topic}, "素材检索暂时失败，根据观察重试")
                return Action("estimate_duration", last["_arguments"], "时长工具暂时失败，保留草稿并重试估算")
            return Action("finish", {"status": "failed", "message": "关键检查工具不可用，无法可靠完成脚本。", "risks": [last.get("error", "tool_failure")], "information_gaps": []}, "工具不可恢复，停止且不虚报成功")

        if "hits" in last:
            if not last["hits"]:
                searches = [item for item in observations if "hits" in item]
                if len(searches) < 2:
                    return Action("search_materials", {"query": self._rewrite_query(request.topic)}, "首次无素材，提取产品或功能词补充检索")
                return Action("finish", {"status": "needs_input", "message": "没有找到可支持脚本事实的素材。", "risks": [], "information_gaps": ["缺少主题相关产品素材"]}, "补充检索仍无结果，请求用户补充素材")
            draft = self._make_draft(request, last["hits"], compact=False)
            return Action("estimate_duration", draft, "生成有来源的首稿并估算真实时长")

        if "estimated_duration" in last:
            args = last["_arguments"]
            if last["estimated_duration"] > request.target_duration:
                same_draft_attempts = sum(1 for item in observations if item.get("draft_id") == last.get("draft_id"))
                if same_draft_attempts > 1:
                    return Action("finish", {"status": "needs_input", "message": "保留必要事实后仍无法满足目标时长。", "risks": ["目标时长过短"], "information_gaps": ["需要放宽时长或减少必须表达的事实"]}, "压缩后的最小草稿仍超时，明确停止")
                hits = self._latest_hits(observations)
                draft = self._make_draft(request, hits, compact=True)
                return Action("estimate_duration", draft, "首稿超时，压缩旁白后重新估算")
            return Action("check_rules", args, "时长合格，对同一草稿执行品牌与事实规则检查")

        if "passed" in last:
            args = last["_arguments"]
            if not last["passed"]:
                cleaned = self._clean(args)
                return Action("estimate_duration", cleaned, "规则不通过，移除违规表达并重新进入检查链")
            return Action("finish", {**args, "status": "completed", "message": "脚本已通过时长与规则检查。", "risks": [], "information_gaps": []}, "最终草稿的真实时长和规则检查均通过")
        return Action("finish", {"status": "failed", "message": "无法识别工具结果。", "risks": ["unknown_observation"], "information_gaps": []}, "安全停止")

    @staticmethod
    def _latest_hits(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return next(item["hits"] for item in reversed(observations) if "hits" in item and item["hits"])

    @staticmethod
    def _rewrite_query(topic: str) -> str:
        words = re.findall(r"VideoPro|[A-Za-z0-9]+|字幕|裁剪|画幅|视频", topic, re.I)
        return " ".join(words) if words else f"{topic} 产品功能"

    @staticmethod
    def _make_draft(request: ScriptRequest, hits: list[dict[str, Any]], compact: bool) -> dict[str, Any]:
        source = hits[0]
        fact = source["facts"][0]
        title = f"{source['product']}：{request.topic}｜给{request.audience}"
        base = fact.rstrip("。") + "。"
        desired = max(4.0, request.target_duration - 2 if compact else request.target_duration + 8)
        narration = base
        filler = "跟随画面查看操作步骤，按需编辑你的短视频。" if request.style != "轻松" else "跟着画面一起试试，轻松编辑你的短视频。"
        while (len(re.findall(r"[\u4e00-\u9fff]", narration)) + len(re.findall(r"[A-Za-z0-9]+", narration))) / 4 < desired:
            narration += filler
        if compact:
            max_units = max(1, int(desired * 4))
            chars = list(narration)
            narration = "".join(chars[:max_units])
            if fact.rstrip("。") not in narration:
                narration = base
        return {
            "title": title,
            "storyboard": [
                {"shot": f"{request.platform}画幅中的产品界面与功能入口", "narration": narration, "subtitle": fact},
                {"shot": "结尾展示可编辑时间线", "narration": "现在开始创作。", "subtitle": "按需编辑"},
            ],
            "source_ids": [source["material_id"]],
        }

    @staticmethod
    def _clean(args: dict[str, Any]) -> dict[str, Any]:
        forbidden = ("最强", "绝对", "100%")
        clean = {"title": args["title"], "storyboard": [dict(s) for s in args["storyboard"]], "source_ids": list(args["source_ids"])}
        for term in forbidden:
            clean["title"] = clean["title"].replace(term, "")
            for scene in clean["storyboard"]:
                scene["narration"] = scene["narration"].replace(term, "")
                scene["subtitle"] = scene["subtitle"].replace(term, "")
        return clean


class OpenAIDecisionModel:
    def __init__(self, model: str = "gpt-5-mini", client: Any | None = None):
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        self.client = client
        self.model = model

    def decide(self, request: ScriptRequest, observations: list[dict[str, Any]], step: int) -> Action:
        prompt = {
            "role": "你是短视频脚本 Agent，每一步只能选择一个动作并根据工具观察调整。",
            "request": request.__dict__, "step": step, "observations": observations,
            "tools": ["search_materials(query)", "estimate_duration(title,storyboard,source_ids)", "check_rules(title,storyboard,source_ids)", "finish(...)"],
            "rules": [
                "先检索素材，脚本中的产品事实只能来自 hits.facts，不得编造效果数据",
                "生成或修改脚本后必须重新估算时长；超时则压缩并再次估算",
                "时长合格后对完全相同的草稿检查规则；规则失败则修改并重新估算、重新检查",
                "只有最新草稿的估算不超目标且规则检查通过才能 completed",
                "无素材时改写查询一次或请求补充；工具失败不得虚报成功",
                "无关标量填 null，无关列表填空列表",
            ],
        }
        response = self.client.responses.parse(model=self.model, input=json.dumps(prompt, ensure_ascii=False), text_format=StructuredDecision)
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("model returned no structured decision")
        return Action(parsed.name, parsed.arguments.model_dump(exclude_none=True), parsed.reason)
