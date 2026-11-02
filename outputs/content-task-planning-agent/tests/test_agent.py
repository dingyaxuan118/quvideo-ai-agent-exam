from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from content_planner.agent import ContentPlanningAgent
from content_planner.decision import OfflinePolicyModel, OpenAIDecisionModel
from content_planner.models import Action, PlanningRequest
from content_planner.tools import PlanningTools


ROOT = Path(__file__).resolve().parents[1]


class DirectSaveModel:
    def decide(self, request, observations, step):
        if observations:
            return Action("finish", {"status": "plan_saved"}, "声称成功")
        return Action("save_plan", {"variant": "premium"}, "跳过前置步骤")


class FalseSuccessModel:
    def decide(self, request, observations, step):
        return Action("finish", {"status": "plan_saved"}, "未保存却声称成功")


class LoopingModel:
    def decide(self, request, observations, step):
        return Action("search_assets", {"theme": request.theme}, "重复检索")


class BrokenModel:
    def decide(self, request, observations, step):
        raise ValueError("invalid output")


class FakeResponses:
    def parse(self, text_format, **kwargs):
        return type(
            "FakeResponse",
            (),
            {
                "output_parsed": text_format(
                    name="search_assets",
                    arguments={
                        "theme": "新品推广",
                        "variant": None,
                        "budget": None,
                        "deadline_hours": None,
                        "total_cost": None,
                        "estimated_hours": None,
                        "fail_once": None,
                        "simulate_failure": None,
                        "status": None,
                    },
                    reason="检索",
                )
            },
        )()


class FakeClient:
    responses = FakeResponses()


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.plan_file = Path(self.temp.name) / "plans.json"
        self.tools = PlanningTools(ROOT / "data", self.plan_file)
        self.agent = ContentPlanningAgent(OfflinePolicyModel(), self.tools)

    def tearDown(self):
        self.temp.cleanup()

    def test_normal_plan_uses_premium(self):
        result = self.agent.run(PlanningRequest("新品推广", 20, 12))
        self.assertEqual(result.task_status, "plan_saved")
        self.assertEqual(result.selected_variant, "premium")
        self.assertEqual(result.total_cost, 12)
        self.assertEqual(result.save_status, "saved")
        stored = json.loads(self.plan_file.read_text(encoding="utf-8"))[0]
        self.assertEqual(stored["asset_ids"], ["A01", "A02", "A03"])
        self.assertIn("完整脚本", stored["script"])
        self.assertEqual(len(stored["tasks"]), 3)

    def test_missing_budget_is_incomplete(self):
        result = self.agent.run(PlanningRequest("新品推广", None, 12))
        self.assertEqual(result.task_status, "incomplete")
        self.assertIn("budget", result.message)
        self.assertEqual(result.save_status, "not_attempted")
        self.assertEqual(result.trace[0].action, "validate_input")

    def test_missing_deadline_is_incomplete(self):
        result = self.agent.run(PlanningRequest("新品推广", 20, None))
        self.assertEqual(result.task_status, "incomplete")
        self.assertIn("deadline_hours", result.message)

    def test_non_finite_constraints_are_rejected(self):
        result = self.agent.run(PlanningRequest("新品推广", float("nan"), float("inf")))
        self.assertEqual(result.task_status, "incomplete")
        self.assertIn("budget_must_be_non_negative", result.message)
        self.assertIn("deadline_hours_must_be_positive", result.message)

    def test_budget_overrun_replans_to_lean(self):
        result = self.agent.run(PlanningRequest("新品推广", 10, 12))
        self.assertEqual(result.task_status, "plan_saved")
        self.assertEqual(result.selected_variant, "lean")
        self.assertEqual(result.total_cost, 8)
        variants = [s.arguments.get("variant") for s in result.trace]
        self.assertIn("premium", variants)
        self.assertIn("lean", variants)

    def test_deadline_overrun_replans_to_lean(self):
        result = self.agent.run(PlanningRequest("新品推广", 20, 6))
        self.assertEqual(result.task_status, "plan_saved")
        self.assertEqual(result.selected_variant, "lean")
        self.assertEqual(result.estimated_hours, 5)

    def test_no_feasible_plan_is_incomplete(self):
        result = self.agent.run(PlanningRequest("新品推广", 7, 4))
        self.assertEqual(result.task_status, "incomplete")
        self.assertEqual(result.save_status, "not_attempted")
        self.assertEqual(result.task_plan[-1]["status"], "blocked")

    def test_tool_failure_recovers_and_keeps_success(self):
        result = self.agent.run(PlanningRequest("新品推广", 10, 12, fail_script_once=True))
        self.assertEqual(result.task_status, "plan_saved")
        self.assertEqual(result.selected_variant, "lean")
        statuses = [(s["step"], s["status"]) for s in result.step_status]
        self.assertIn(("search_assets", "succeeded"), statuses)
        self.assertIn(("generate_script", "failed"), statuses)
        self.assertIn(("generate_script", "succeeded"), statuses)
        self.assertEqual(result.task_plan[0]["task"], "准备素材")
        self.assertEqual(result.task_plan[-1]["status"], "pending")

    def test_duplicate_is_idempotent(self):
        request = PlanningRequest("新品推广", 20, 12)
        first = self.agent.run(request)
        second = self.agent.run(request)
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(second.save_status, "already_saved")
        self.assertEqual(len(json.loads(self.plan_file.read_text(encoding="utf-8"))), 1)

    def test_duplicate_returns_existing_plan_when_new_run_replans_differently(self):
        first = self.agent.run(PlanningRequest("新品推广", 20, 12))
        second_tools = PlanningTools(ROOT / "data", self.plan_file)
        second_agent = ContentPlanningAgent(OfflinePolicyModel(), second_tools)
        second = second_agent.run(
            PlanningRequest("新品推广", 20, 12, fail_script_once=True)
        )
        self.assertEqual(second.plan_id, first.plan_id)
        self.assertEqual(second.save_status, "already_saved")
        self.assertEqual(second.selected_variant, "premium")
        self.assertEqual(second.total_cost, 12)

    def test_save_failure_is_explicit(self):
        result = self.agent.run(PlanningRequest("新品推广", 20, 12, simulate_save_failure=True))
        self.assertEqual(result.task_status, "failed")
        self.assertEqual(result.save_status, "failed")

    def test_save_tool_rejects_forged_estimate(self):
        result = self.tools.save_plan(
            "新品推广", 10, 12, "premium", 1, 1
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "estimate_mismatch")

    def test_save_tool_rejects_forged_plan_content(self):
        result = self.tools.save_plan(
            "新品推广", 20, 12, "premium", 12, 8,
            script="伪造脚本", asset_ids=["UNKNOWN"],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "plan_content_mismatch")

    def test_model_cannot_save_without_estimate(self):
        agent = ContentPlanningAgent(DirectSaveModel(), self.tools)
        result = agent.run(PlanningRequest("新品推广", 20, 12))
        self.assertEqual(result.task_status, "failed")
        self.assertFalse(self.plan_file.exists())
        self.assertIn("policy_violation", result.trace[0].observation["error"])

    def test_model_cannot_claim_false_success(self):
        agent = ContentPlanningAgent(FalseSuccessModel(), self.tools)
        result = agent.run(PlanningRequest("新品推广", 20, 12))
        self.assertEqual(result.task_status, "failed")

    def test_model_error_is_reported(self):
        agent = ContentPlanningAgent(BrokenModel(), self.tools)
        result = agent.run(PlanningRequest("新品推广", 20, 12))
        self.assertEqual(result.task_status, "failed")
        self.assertEqual(result.trace[0].action, "model_error")

    def test_max_steps_returns_incomplete(self):
        agent = ContentPlanningAgent(LoopingModel(), self.tools, max_steps=2)
        result = agent.run(PlanningRequest("新品推广", 20, 12))
        self.assertEqual(result.task_status, "incomplete")
        self.assertEqual(len(result.trace), 2)

    def test_saved_plan_is_success_even_if_finish_step_hits_limit(self):
        agent = ContentPlanningAgent(OfflinePolicyModel(), self.tools, max_steps=4)
        result = agent.run(PlanningRequest("新品推广", 20, 12))
        self.assertEqual(result.save_status, "saved")
        self.assertEqual(result.task_status, "plan_saved")

    def test_openai_adapter_parses_action(self):
        model = OpenAIDecisionModel(client=FakeClient())
        action = model.decide(PlanningRequest("新品推广", 20, 12), [], 1)
        self.assertEqual(action.name, "search_assets")
        self.assertEqual(action.arguments, {"theme": "新品推广"})


if __name__ == "__main__":
    unittest.main()
