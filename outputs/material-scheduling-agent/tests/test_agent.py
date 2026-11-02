from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from material_agent.agent import MaterialSchedulingAgent
from material_agent.decision import OfflinePolicyModel, OpenAIDecisionModel
from material_agent.models import Action, ScheduleRequest
from material_agent.tools import BusinessTools


ROOT = Path(__file__).resolve().parents[1]


class LoopingModel:
    def decide(self, request, observations, step):
        return Action("read_material", {"material_id": request.material_id}, "继续读取")


class DirectSaveModel:
    def decide(self, request, observations, step):
        if observations:
            return Action("finish", {"status": "draft_saved"}, "声称成功")
        return Action(
            "save_draft",
            {"material_id": request.material_id, "scheduled_time": request.desired_time},
            "跳过审核直接保存",
        )


class FalseSuccessModel:
    def decide(self, request, observations, step):
        return Action("finish", {"status": "draft_saved"}, "未执行工具却声称成功")


class WrongPostSaveStatusModel:
    def __init__(self):
        self.policy = OfflinePolicyModel()

    def decide(self, request, observations, step):
        if observations and "saved" in observations[-1]:
            return Action("finish", {"status": "incomplete"}, "错误地声称未完成")
        return self.policy.decide(request, observations, step)


class BrokenModel:
    def decide(self, request, observations, step):
        raise ValueError("invalid model output")


class FakeResponses:
    def parse(self, text_format, **kwargs):
        return type(
            "FakeResponse",
            (),
            {
                "output_parsed": text_format(
                    name="read_material",
                    arguments={
                        "material_id": "M01",
                        "desired_time": None,
                        "requested_time": None,
                        "scheduled_time": None,
                        "simulate_failure": None,
                        "status": None,
                        "suggested_time": None,
                    },
                    reason="读取",
                )
            },
        )()


class FakeClient:
    responses = FakeResponses()


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.draft_file = Path(self.temp_dir.name) / "drafts.json"
        self.tools = BusinessTools(ROOT / "data", self.draft_file)
        self.agent = MaterialSchedulingAgent(OfflinePolicyModel(), self.tools)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normal_schedule_saves_draft(self):
        result = self.agent.run(ScheduleRequest("M01", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "draft_saved")
        self.assertEqual(result.review_status, "approved")
        self.assertEqual(result.draft_save_status, "saved")
        self.assertIn("尚未发布", result.message)

    def test_missing_material_data_is_incomplete(self):
        result = self.agent.run(ScheduleRequest("M02", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "incomplete")
        self.assertIn("缺少字段", " ".join(result.risk_reasons))
        self.assertEqual(result.draft_save_status, "not_attempted")

    def test_rule_risk_blocks_scheduling(self):
        result = self.agent.run(ScheduleRequest("M03", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "blocked")
        self.assertTrue(result.risk_reasons)
        self.assertFalse(any(step.action == "save_draft" for step in result.trace))

    def test_conflict_requires_confirmation(self):
        result = self.agent.run(ScheduleRequest("M01", "2026-11-01T18:00"))
        self.assertEqual(result.task_status, "pending_confirmation")
        self.assertEqual(result.suggested_time, "2026-11-01T19:00")
        self.assertEqual(result.draft_save_status, "not_attempted")

    def test_confirmed_alternative_can_be_saved(self):
        result = self.agent.run(
            ScheduleRequest(
                "M01", "2026-11-01T18:00", confirmed_time="2026-11-01T19:00"
            )
        )
        self.assertEqual(result.task_status, "draft_saved")
        self.assertEqual(result.draft_save_status, "saved")
        self.assertEqual(result.suggested_time, "2026-11-01T19:00")

    def test_second_confirmed_alternative_can_be_saved(self):
        result = self.agent.run(
            ScheduleRequest(
                "M01", "2026-11-01T18:00", confirmed_time="2026-11-01T20:00"
            )
        )
        self.assertEqual(result.task_status, "draft_saved")
        saved_step = next(step for step in result.trace if step.action == "save_draft")
        self.assertEqual(saved_step.arguments["scheduled_time"], "2026-11-01T20:00")
        self.assertEqual(result.suggested_time, "2026-11-01T20:00")

    def test_duplicate_request_is_idempotent(self):
        request = ScheduleRequest("M01", "2026-11-01T19:00")
        first = self.agent.run(request)
        second = self.agent.run(request)
        self.assertEqual(first.draft_id, second.draft_id)
        self.assertEqual(second.draft_save_status, "already_saved")
        self.assertEqual(len(json.loads(self.draft_file.read_text(encoding="utf-8"))), 1)

    def test_save_failure_is_reported(self):
        result = self.agent.run(
            ScheduleRequest("M01", "2026-11-01T19:00", simulate_save_failure=True)
        )
        self.assertEqual(result.task_status, "failed")
        self.assertEqual(result.draft_save_status, "failed")
        self.assertIn("未完成", result.message)

    def test_max_steps_returns_incomplete(self):
        agent = MaterialSchedulingAgent(LoopingModel(), self.tools, max_steps=2)
        result = agent.run(ScheduleRequest("M01", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "incomplete")
        self.assertIn("最大执行步数", result.message)
        self.assertEqual(len(result.trace), 2)

    def test_unknown_slot_is_not_treated_as_available(self):
        result = self.tools.query_slots("2026-11-03T09:00")
        self.assertFalse(result["available"])
        self.assertEqual(result["alternatives"], [])

    def test_invalid_time_is_reported(self):
        result = self.tools.query_slots("tomorrow evening")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_time_format")

    def test_tool_rejects_unreviewed_risky_material(self):
        result = self.tools.save_draft(
            "M03", "2026-11-01T19:00", "2026-11-01T19:00"
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "material_not_approved")

    def test_model_cannot_save_before_review(self):
        agent = MaterialSchedulingAgent(DirectSaveModel(), self.tools)
        result = agent.run(ScheduleRequest("M01", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "failed")
        self.assertEqual(result.draft_save_status, "failed")
        self.assertIn("policy_violation", result.trace[0].observation["error"])
        self.assertFalse(self.draft_file.exists())

    def test_model_cannot_claim_false_success(self):
        agent = MaterialSchedulingAgent(FalseSuccessModel(), self.tools)
        result = agent.run(ScheduleRequest("M01", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "failed")
        self.assertEqual(result.draft_save_status, "not_attempted")

    def test_persisted_draft_overrides_wrong_final_status(self):
        agent = MaterialSchedulingAgent(WrongPostSaveStatusModel(), self.tools)
        result = agent.run(ScheduleRequest("M01", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "draft_saved")
        self.assertEqual(result.draft_save_status, "saved")

    def test_model_error_returns_failed_result(self):
        agent = MaterialSchedulingAgent(BrokenModel(), self.tools)
        result = agent.run(ScheduleRequest("M01", "2026-11-01T19:00"))
        self.assertEqual(result.task_status, "failed")
        self.assertEqual(result.trace[0].action, "model_error")

    def test_openai_adapter_parses_action(self):
        model = OpenAIDecisionModel(client=FakeClient())
        action = model.decide(ScheduleRequest("M01", "2026-11-01T19:00"), [], 1)
        self.assertEqual(action.name, "read_material")
        self.assertEqual(action.arguments, {"material_id": "M01"})


if __name__ == "__main__":
    unittest.main()
