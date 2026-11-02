from __future__ import annotations

import json
from pathlib import Path

import pytest

from script_agent import OfflinePolicyModel, ScriptAgent, ScriptRequest, ScriptTools
from script_agent.models import Action


ROOT = Path(__file__).resolve().parents[1]


def request(**overrides):
    values = dict(topic="VideoPro 字幕功能", audience="短视频创作者", platform="抖音", target_duration=30.0, style="简洁")
    values.update(overrides)
    return ScriptRequest(**values)


def run(**overrides):
    return ScriptAgent(OfflinePolicyModel(), ScriptTools(ROOT / "data")).run(request(**overrides))


def test_normal_generation_revises_overtime_draft():
    result = run()
    assert result.task_status == "completed"
    estimates = [s for s in result.trace if s.action == "estimate_duration"]
    assert estimates[0].observation["estimated_duration"] > 30
    assert estimates[-1].observation["estimated_duration"] <= 30
    assert result.material_source_ids == ["P01"]
    assert len(result.storyboard) == 2


@pytest.mark.parametrize("field,value", [("topic", ""), ("audience", ""), ("platform", ""), ("style", ""), ("target_duration", None), ("target_duration", -1)])
def test_missing_or_invalid_input(field, value):
    result = run(**{field: value})
    assert result.task_status == "needs_input"
    assert result.trace[0].action == "validate_input"


def test_no_material_reports_gap_after_rewritten_search():
    result = run(topic="咖啡机维修")
    assert result.task_status == "needs_input"
    searches = [s for s in result.trace if s.action == "search_materials"]
    assert len(searches) == 2
    assert searches[0].arguments["query"] != searches[1].arguments["query"]


def test_search_failure_is_observed_then_retried():
    result = run(fail_search_once=True)
    assert result.task_status == "completed"
    assert result.trace[0].observation["error"] == "material_search_timeout"
    assert result.trace[1].action == "search_materials"


def test_estimate_failure_retries_same_draft():
    result = run(fail_estimate_once=True)
    assert result.task_status == "completed"
    failed = next(s for s in result.trace if s.observation.get("error") == "duration_service_timeout")
    assert failed.action == "estimate_duration"


def test_rule_tool_failure_cannot_succeed():
    result = run(fail_rule_check=True)
    assert result.task_status == "failed"
    assert result.title is None


def test_impossibly_short_duration_stops_explicitly():
    result = run(target_duration=1.0)
    assert result.task_status == "needs_input"
    assert "时长" in result.message


def test_max_steps_returns_incomplete():
    result = ScriptAgent(OfflinePolicyModel(), ScriptTools(ROOT / "data"), max_steps=1).run(request())
    assert result.task_status == "incomplete"


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, *args):
        return next(self.actions)


def draft(narration="VideoPro 支持导入 SRT 和 VTT 字幕文件。"):
    return {"title": "字幕演示", "storyboard": [{"shot": "界面", "narration": narration, "subtitle": "字幕功能"}], "source_ids": ["P01"]}


def test_unsearched_source_is_rejected():
    model = ScriptedModel([Action("estimate_duration", draft(), "绕过检索"), Action("finish", {"status": "failed"}, "停止")])
    result = ScriptAgent(model, ScriptTools(ROOT / "data")).run(request())
    assert result.trace[0].observation["error"] == "policy_violation:source_not_in_search_results"


def test_cannot_check_unestimated_draft():
    model = ScriptedModel([Action("search_materials", {"query": "VideoPro 字幕"}, "搜索"), Action("check_rules", draft(), "跳过估算"), Action("finish", {"status": "failed"}, "停止")])
    result = ScriptAgent(model, ScriptTools(ROOT / "data")).run(request())
    assert result.trace[1].observation["error"] == "policy_violation:current_draft_not_estimated"


def test_unsupported_effect_claim_fails_rule_check():
    bad = draft("VideoPro 支持导入 SRT 和 VTT 字幕文件。效率提升 80%。")
    model = ScriptedModel([Action("search_materials", {"query": "VideoPro 字幕"}, "搜索"), Action("estimate_duration", bad, "估算"), Action("check_rules", bad, "检查"), Action("finish", {**bad, "status": "completed"}, "虚报")])
    result = ScriptAgent(model, ScriptTools(ROOT / "data")).run(request())
    rule = next(s for s in result.trace if s.action == "check_rules")
    assert not rule.observation["passed"]
    assert result.task_status == "failed"


def test_changed_draft_cannot_reuse_old_check():
    good = draft()
    changed = draft("VideoPro 支持导入 SRT 和 VTT 字幕文件。新增一句。")
    model = ScriptedModel([
        Action("search_materials", {"query": "VideoPro 字幕"}, "搜索"),
        Action("estimate_duration", good, "估算"), Action("check_rules", good, "检查"),
        Action("estimate_duration", changed, "修改后估算"), Action("finish", {**changed, "status": "completed"}, "复用旧检查"),
    ])
    result = ScriptAgent(model, ScriptTools(ROOT / "data")).run(request())
    assert result.task_status == "failed"


def test_replacing_material_changes_script(tmp_path):
    data = json.loads((ROOT / "data/materials.json").read_text())
    data["materials"][0]["facts"][0] = "VideoPro 支持自动生成双语字幕。"
    (tmp_path / "materials.json").write_text(json.dumps(data, ensure_ascii=False))
    result = ScriptAgent(OfflinePolicyModel(), ScriptTools(tmp_path)).run(request())
    assert result.task_status == "completed"
    assert "自动生成双语字幕" in json.dumps(result.storyboard, ensure_ascii=False)
    assert "SRT" not in json.dumps(result.storyboard, ensure_ascii=False)


def test_model_exception_is_safe():
    class Broken:
        def decide(self, *args):
            raise RuntimeError("private detail")
    result = ScriptAgent(Broken(), ScriptTools(ROOT / "data")).run(request())
    assert result.task_status == "failed"
    assert "private detail" not in json.dumps(result.to_dict())


def test_unknown_action_is_rejected():
    model = ScriptedModel([Action("publish_video", {}, "越权"), Action("finish", {"status": "failed"}, "停止")])
    result = ScriptAgent(model, ScriptTools(ROOT / "data")).run(request())
    assert result.trace[0].observation["error"] == "policy_violation:unknown_action"


def test_rule_check_requires_a_real_material_fact():
    tools = ScriptTools(ROOT / "data")
    result = tools.check_rules("普通标题", [{"shot": "界面", "narration": "欢迎使用产品。", "subtitle": "开始"}], ["P01"])
    assert not result["passed"]


def test_unlisted_product_claim_is_rejected_even_with_one_real_fact():
    tools = ScriptTools(ROOT / "data")
    narration = "VideoPro 支持导入 SRT 和 VTT 字幕文件。VideoPro 支持 4K 云端渲染。"
    result = tools.check_rules("功能介绍", [{"shot": "界面", "narration": narration, "subtitle": "功能"}], ["P01"])
    assert not result["passed"]
    assert any("4K" in violation for violation in result["violations"])


def test_fake_claim_in_same_sentence_as_real_fact_is_rejected():
    tools = ScriptTools(ROOT / "data")
    narration = "VideoPro 支持导入 SRT 和 VTT 字幕文件，同时支持 8K 云端渲染。"
    result = tools.check_rules("功能介绍", [{"shot": "界面", "narration": narration, "subtitle": "功能"}], ["P01"])
    assert not result["passed"]
    assert any("8K" in violation for violation in result["violations"])


def test_fake_claim_without_known_marker_is_rejected():
    tools = ScriptTools(ROOT / "data")
    narration = "VideoPro 支持导入 SRT 和 VTT 字幕文件。内置 8K 云端渲染引擎。"
    result = tools.check_rules("功能介绍", [{"shot": "界面", "narration": narration, "subtitle": "功能"}], ["P01"])
    assert not result["passed"]
    assert any("8K" in violation for violation in result["violations"])


def test_subtitle_only_scene_has_nonzero_reading_duration():
    tools = ScriptTools(ROOT / "data")
    subtitle = "VideoPro 支持导入 SRT 和 VTT 字幕文件。" + "说明文字" * 100
    result = tools.estimate_duration("字幕视频", [{"shot": "静态画面", "narration": "", "subtitle": subtitle}], ["P01"])
    assert result["estimated_duration"] > 30
    assert result["scene_durations"][0]["subtitle_reading_seconds"] > 30


def test_irrelevant_but_searched_material_is_rejected():
    off_topic = {"title": "画幅", "storyboard": [{"shot": "界面", "narration": "VideoPro 可以将视频裁剪为 9:16、1:1 和 16:9 画幅。", "subtitle": "画幅"}], "source_ids": ["P02"]}
    model = ScriptedModel([Action("search_materials", {"query": "VideoPro 画幅"}, "搜索无关素材"), Action("estimate_duration", off_topic, "估算"), Action("finish", {"status": "failed"}, "停止")])
    result = ScriptAgent(model, ScriptTools(ROOT / "data")).run(request())
    assert result.trace[1].observation["error"] == "policy_violation:source_not_relevant_to_original_topic"


def test_string_brand_rule_from_data_is_enforced(tmp_path):
    data = json.loads((ROOT / "data/materials.json").read_text())
    data["brand_rules"]["rules"].append("不得使用“永久免费”表述")
    (tmp_path / "materials.json").write_text(json.dumps(data, ensure_ascii=False))
    tools = ScriptTools(tmp_path)
    narration = "VideoPro 支持导入 SRT 和 VTT 字幕文件。永久免费。"
    result = tools.check_rules("功能介绍", [{"shot": "界面", "narration": narration, "subtitle": "功能"}], ["P01"])
    assert not result["passed"]
    assert any("永久免费" in violation for violation in result["violations"])


def test_none_string_input_returns_needs_input():
    bad = ScriptRequest(None, "创作者", "抖音", 30, "简洁")  # type: ignore[arg-type]
    result = ScriptAgent(OfflinePolicyModel(), ScriptTools(ROOT / "data")).run(bad)
    assert result.task_status == "needs_input"


def test_audience_platform_and_style_affect_draft():
    result = run(audience="新手用户", platform="小红书", style="轻松")
    rendered = json.dumps(result.to_dict(), ensure_ascii=False)
    assert result.task_status == "completed"
    assert "新手用户" in result.title and "小红书" in rendered and "轻松" in rendered


def test_output_duration_matches_final_trace():
    result = run()
    estimates = {s.observation["draft_id"]: s.observation["estimated_duration"] for s in result.trace if s.action == "estimate_duration" and s.observation.get("ok")}
    finish = result.trace[-1].observation
    assert result.estimated_duration == estimates[finish["draft_id"]]
    assert all(scene["estimated_seconds"] for scene in result.storyboard)


def test_more_relevant_material_is_selected():
    result = run(topic="VideoPro 画幅裁剪")
    assert result.task_status == "completed"
    assert result.material_source_ids == ["P02"]
    assert "9:16" in json.dumps(result.storyboard, ensure_ascii=False)
