from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .agent import ScriptAgent
from .decision import OfflinePolicyModel, OpenAIDecisionModel
from .models import ScriptRequest
from .tools import ScriptTools


def main() -> None:
    parser = argparse.ArgumentParser(description="短视频脚本 Agent")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--style", required=True)
    parser.add_argument("--backend", choices=["offline", "openai"], default="offline")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--fail-search-once", action="store_true")
    parser.add_argument("--fail-estimate-once", action="store_true")
    parser.add_argument("--fail-rule-check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    model = OfflinePolicyModel() if args.backend == "offline" else OpenAIDecisionModel(args.model)
    request = ScriptRequest(args.topic, args.audience, args.platform, args.duration, args.style, args.fail_search_once, args.fail_estimate_once, args.fail_rule_check)
    result = ScriptAgent(model, ScriptTools(root / "data"), args.max_steps).run(request)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
