from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .agent import ContentPlanningAgent
from .decision import OfflinePolicyModel, OpenAIDecisionModel
from .models import PlanningRequest
from .tools import PlanningTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="预算与截止时间约束下的内容任务规划 Agent")
    parser.add_argument("--theme", required=True)
    parser.add_argument("--budget", type=float)
    parser.add_argument("--deadline-hours", type=float)
    parser.add_argument("--fail-script-once", action="store_true")
    parser.add_argument("--simulate-save-failure", action="store_true")
    parser.add_argument("--mode", choices=["offline", "openai"], default="offline")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--plan-file", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[2]
    tools = PlanningTools(root / "data", args.plan_file)
    model = OpenAIDecisionModel(args.model) if args.mode == "openai" else OfflinePolicyModel()
    agent = ContentPlanningAgent(model, tools, args.max_steps)
    result = agent.run(
        PlanningRequest(
            args.theme, args.budget, args.deadline_hours,
            args.fail_script_once, args.simulate_save_failure,
        )
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
