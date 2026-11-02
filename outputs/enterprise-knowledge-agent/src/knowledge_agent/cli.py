from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .agent import KnowledgeAgent
from .decision import OfflinePolicyModel, OpenAIDecisionModel
from .models import KnowledgeRequest
from .tools import KnowledgeTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="企业知识问答 Agent")
    parser.add_argument("question", help="员工问题")
    parser.add_argument("--history-json", default="[]", help="对话历史 JSON 数组")
    parser.add_argument("--backend", choices=["offline", "openai"], default="offline")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--fail-search-once", action="store_true")
    parser.add_argument("--fail-read-id", action="append", default=[])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        history = json.loads(args.history_json)
        if not isinstance(history, list):
            raise ValueError("history must be a JSON list")
    except (json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"invalid --history-json: {exc}") from exc
    root = Path(__file__).resolve().parents[2]
    tools = KnowledgeTools(root / "data")
    model = OfflinePolicyModel() if args.backend == "offline" else OpenAIDecisionModel(args.model)
    request = KnowledgeRequest(args.question, history, args.fail_search_once, args.fail_read_id)
    result = KnowledgeAgent(model, tools, args.max_steps).run(request)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
