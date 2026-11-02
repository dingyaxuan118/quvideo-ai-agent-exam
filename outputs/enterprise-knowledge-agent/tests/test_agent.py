from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_agent.agent import KnowledgeAgent
from knowledge_agent.decision import OfflinePolicyModel
from knowledge_agent.models import Action, KnowledgeRequest
from knowledge_agent.tools import KnowledgeTools


ROOT = Path(__file__).resolve().parents[1]


def run(question: str, **kwargs):
    request = KnowledgeRequest(question, **kwargs)
    return KnowledgeAgent(OfflinePolicyModel(), KnowledgeTools(ROOT / "data")).run(request)


def test_clear_answer_has_supported_citation():
    result = run("年假要提前多久申请？")
    assert result.task_status == "answered"
    assert "3 个工作日" in result.answer
    assert result.citations[0]["document_id"] == "D03"
    assert result.citations[0]["quote"] in (ROOT / "data/documents.json").read_text()


def test_conflict_is_not_silently_resolved():
    result = run("费用发生后多久内报销？")
    assert result.task_status == "needs_clarification"
    assert {c["document_id"] for c in result.citations} == {"D01", "D02"}
    assert result.conflicts and result.follow_up_question
    assert "15 天" not in result.answer and "30 天" not in result.answer


def test_out_of_scope_reports_gap():
    result = run("办公室咖啡机怎么维修？")
    assert result.task_status == "out_of_scope"
    assert result.information_gaps and not result.citations
    assert [t.action for t in result.trace] == ["search_documents", "search_documents", "finish"]


@pytest.mark.parametrize("question", ["休假至少要多早申请？", "年休假需要几天前提？"])
def test_paraphrase(question):
    result = run(question)
    assert result.task_status == "answered"
    assert result.citations[0]["document_id"] == "D03"


def test_context_follow_up_uses_history():
    history = [{"role": "user", "content": "我想申请年假，需要走什么流程？"}, {"role": "assistant", "content": "请在考勤系统提交。"}]
    result = run("要提前多久？", history=history)
    assert result.task_status == "answered"
    assert "上下文主题" in result.resolved_question
    assert result.citations[0]["document_id"] == "D03"


def test_retryable_search_failure_changes_next_action():
    result = run("VideoPro 支持哪些字幕？", fail_search_once=True)
    actions = [step.action for step in result.trace]
    assert actions[:2] == ["search_documents", "search_documents"]
    assert result.trace[0].observation["error"] == "search_service_timeout"
    assert result.task_status == "answered"


def test_read_failure_stops_without_answer():
    result = run("年假要提前多久申请？", fail_read_ids=["D03"])
    assert result.task_status == "failed"
    assert not result.citations
    assert any(step.observation.get("error") == "document_store_unavailable" for step in result.trace)


def test_max_steps_is_explicit():
    result = KnowledgeAgent(OfflinePolicyModel(), KnowledgeTools(ROOT / "data"), max_steps=1).run(KnowledgeRequest("年假要提前多久申请？"))
    assert result.task_status == "incomplete"
    assert "最大执行步数" in result.answer


def test_empty_question_requests_clarification():
    result = run("  ")
    assert result.task_status == "needs_clarification"
    assert not result.trace


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, request, resolved_question, observations, step):
        return next(self.actions)


def test_cannot_read_document_that_was_not_searched():
    model = ScriptedModel([
        Action("read_excerpt", {"document_id": "D03"}, "绕过检索"),
        Action("finish", {"status": "failed", "answer": "停止"}, "停止"),
    ])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.trace[0].observation["error"].startswith("policy_violation")


def test_fabricated_quote_is_rejected():
    model = ScriptedModel([
        Action("search_documents", {"query": "年假 提前"}, "搜索"),
        Action("read_excerpt", {"document_id": "D03"}, "读取"),
        Action("finish", {"status": "answered", "answer": "提前一天", "citations": [{"document_id": "D03", "version_date": "2025-02-15", "quote": "提前一天"}]}, "伪造"),
    ])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.task_status == "failed"
    assert not result.citations


def test_real_quote_with_contradictory_answer_is_reconstructed_from_evidence():
    quote = "员工申请年假，应至少提前 3 个工作日在考勤系统中提交申请，并经直属主管批准后方可休假。"
    model = ScriptedModel([
        Action("search_documents", {"query": "年假 提前"}, "搜索"),
        Action("read_excerpt", {"document_id": "D03"}, "读取"),
        Action("finish", {"status": "answered", "answer": "年假无需提前申请。", "citations": [{"document_id": "D03", "version_date": "2025-02-15", "quote": quote}]}, "错误总结"),
    ])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.task_status == "answered"
    assert result.answer == quote
    assert "无需" not in result.answer


def test_answer_without_citation_is_rejected():
    model = ScriptedModel([Action("finish", {"status": "answered", "answer": "随便回答"}, "无引用")])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.task_status == "failed"


def test_controller_overrides_answered_when_sources_conflict():
    docs = json.loads((ROOT / "data/documents.json").read_text())
    citations = [{"document_id": d["document_id"], "version_date": d["version_date"], "quote": d["content"]} for d in docs[:2]]
    model = ScriptedModel([
        Action("search_documents", {"query": "费用 报销 期限"}, "搜索"),
        Action("read_excerpt", {"document_id": "D01"}, "读取"),
        Action("read_excerpt", {"document_id": "D02"}, "读取"),
        Action("finish", {"status": "answered", "answer": "按 15 天", "citations": citations}, "擅自选择"),
    ])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("报销期限"))
    assert result.task_status == "needs_clarification"
    assert "15 天" not in result.answer


def test_cannot_finish_after_reading_only_one_conflicting_candidate():
    d02 = "费用报销申请需要在费用发生后 15 天内提交，申请时应上传清晰的票据影像。"
    model = ScriptedModel([
        Action("search_documents", {"query": "费用 报销 期限"}, "搜索"),
        Action("read_excerpt", {"document_id": "D02"}, "只读一份"),
        Action("finish", {"status": "answered", "answer": "15 天", "citations": [{"document_id": "D02", "version_date": "2025-03-01", "quote": d02}]}, "提前结束"),
    ])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("报销期限"))
    assert result.task_status != "answered"
    assert any(step.observation.get("error") == "verification_incomplete" for step in result.trace)


def test_out_of_scope_requires_a_real_search():
    model = ScriptedModel([Action("finish", {"status": "out_of_scope", "answer": "没有资料"}, "跳过检索")])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.task_status == "failed"
    assert result.trace[0].observation["error"] == "search_required_before_out_of_scope"


def test_unknown_action_is_a_policy_violation():
    model = ScriptedModel([Action("delete_document", {}, "越权"), Action("finish", {"status": "failed"}, "停止")])
    result = KnowledgeAgent(model, KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.trace[0].observation["error"] == "policy_violation:unknown_action"


def test_model_exception_is_safe():
    class Broken:
        def decide(self, *args):
            raise RuntimeError("secret details")

    result = KnowledgeAgent(Broken(), KnowledgeTools(ROOT / "data")).run(KnowledgeRequest("年假"))
    assert result.task_status == "failed"
    assert "secret details" not in json.dumps(result.to_dict(), ensure_ascii=False)


def test_replacing_document_changes_answer(tmp_path):
    docs = json.loads((ROOT / "data/documents.json").read_text())
    docs = [d for d in docs if d["document_id"] != "D02"]
    docs[0]["content"] = "员工应在费用发生之日起 45 天内提交报销申请。"
    (tmp_path / "documents.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    result = KnowledgeAgent(OfflinePolicyModel(), KnowledgeTools(tmp_path)).run(KnowledgeRequest("费用发生后多久内报销？"))
    assert result.task_status == "answered"
    assert "45 天" in result.answer


def test_replacing_only_conflict_text_changes_conflict_action(tmp_path):
    docs = json.loads((ROOT / "data/documents.json").read_text())
    docs[1]["content"] = "费用报销申请需要在费用发生后 30 天内提交。"
    (tmp_path / "documents.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    result = KnowledgeAgent(OfflinePolicyModel(), KnowledgeTools(tmp_path)).run(KnowledgeRequest("费用发生后多久内报销？"))
    assert result.task_status == "answered"
    assert not result.conflicts


def test_versions_are_taken_from_tool_not_model():
    result = run("VideoPro 字幕格式")
    assert result.citations == [{"document_id": "D04", "version_date": "2025-04-20", "quote": "VideoPro 支持导入 SRT 和 VTT 字幕文件；单个字幕文件不得超过 5 MB。当前不支持 ASS 格式。"}]


def test_short_context_follow_up_uses_history():
    result = run("多久？", history=[{"role": "user", "content": "我想申请年假"}])
    assert result.task_status == "answered"
    assert result.citations[0]["document_id"] == "D03"


def test_supplemental_search_really_changes_query():
    result = run("办公室咖啡机怎么维修？")
    queries = [step.arguments["query"] for step in result.trace if step.action == "search_documents"]
    assert len(queries) == 2 and queries[0] != queries[1]


def test_tool_missing_document():
    observation = KnowledgeTools(ROOT / "data").read_excerpt("D99")
    assert not observation["ok"] and observation["error"] == "document_not_found"


def test_tool_unknown_name():
    observation = KnowledgeTools(ROOT / "data").call("bad_tool", {})
    assert not observation["ok"] and "unknown_tool" in observation["error"]
