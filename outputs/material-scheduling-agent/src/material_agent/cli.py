from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .agent import MaterialSchedulingAgent
from .decision import OfflinePolicyModel, OpenAIDecisionModel
from .models import ScheduleRequest
from .tools import BusinessTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="素材审核与发布排期 Agent（仅保存草稿）")
    parser.add_argument("--material-id", required=True)
    parser.add_argument("--desired-time", required=True, help="ISO 时间，如 2026-11-01T19:00")
    parser.add_argument("--allow-alternative", action="store_true")
    parser.add_argument("--confirmed-time")
    parser.add_argument("--simulate-save-failure", action="store_true")
    parser.add_argument("--mode", choices=["offline", "openai"], default="offline")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--draft-file", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[2]
    tools = BusinessTools(root / "data", args.draft_file)
    model = OpenAIDecisionModel(args.model) if args.mode == "openai" else OfflinePolicyModel()
    agent = MaterialSchedulingAgent(model, tools, max_steps=args.max_steps)
    result = agent.run(
        ScheduleRequest(
            material_id=args.material_id,
            desired_time=args.desired_time,
            allow_alternative=args.allow_alternative,
            confirmed_time=args.confirmed_time,
            simulate_save_failure=args.simulate_save_failure,
        )
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
