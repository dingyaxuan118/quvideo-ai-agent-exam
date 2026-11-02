from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


class PlanningTools:
    """Synthetic business tools for content planning."""

    def __init__(self, data_dir: Path, plan_file: Path | None = None):
        self.catalog = self._read_json(data_dir / "catalog.json")
        self.plan_file = plan_file or data_dir / "plans.local.json"
        self._script_failure_consumed = False

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def search_assets(self, theme: str) -> dict[str, Any]:
        if not theme.strip():
            return {"ok": False, "error": "theme_required"}
        return {
            "ok": True,
            "theme": theme,
            "variants": self.catalog["variants"],
        }

    def generate_script(
        self, theme: str, variant: str, fail_once: bool = False
    ) -> dict[str, Any]:
        if variant not in self.catalog["variants"]:
            return {"ok": False, "error": "unknown_variant", "variant": variant}
        if fail_once and not self._script_failure_consumed:
            self._script_failure_consumed = True
            return {
                "ok": False,
                "error": "script_service_timeout",
                "retryable": True,
                "variant": variant,
            }
        config = self.catalog["variants"][variant]
        return {
            "ok": True,
            "variant": variant,
            "script": f"{theme}｜{config['script_template']}",
            "asset_ids": config["asset_ids"],
        }

    def estimate_cost(self, variant: str) -> dict[str, Any]:
        config = self.catalog["variants"].get(variant)
        if not config:
            return {"ok": False, "error": "unknown_variant", "variant": variant}
        return {
            "ok": True,
            "variant": variant,
            "cost_breakdown": config["cost_breakdown"],
            "total_cost": sum(config["cost_breakdown"].values()),
            "estimated_hours": config["estimated_hours"],
        }

    def save_plan(
        self,
        theme: str,
        budget: float,
        deadline_hours: float,
        variant: str,
        total_cost: float,
        estimated_hours: float,
        simulate_failure: bool = False,
        script: str | None = None,
        asset_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if simulate_failure:
            return {"ok": False, "error": "plan_store_unavailable", "saved": False}
        if not all(
            math.isfinite(value)
            for value in (budget, deadline_hours, total_cost, estimated_hours)
        ):
            return {"ok": False, "error": "non_finite_number", "saved": False}
        if total_cost > budget:
            return {"ok": False, "error": "budget_exceeded", "saved": False}
        if estimated_hours > deadline_hours:
            return {"ok": False, "error": "deadline_exceeded", "saved": False}
        if variant not in self.catalog["variants"]:
            return {"ok": False, "error": "unknown_variant", "saved": False}
        config = self.catalog["variants"][variant]
        expected_cost = sum(config["cost_breakdown"].values())
        expected_hours = config["estimated_hours"]
        if total_cost != expected_cost or estimated_hours != expected_hours:
            return {"ok": False, "error": "estimate_mismatch", "saved": False}
        expected_script = f"{theme}｜{config['script_template']}"
        if script != expected_script or asset_ids != config["asset_ids"]:
            return {"ok": False, "error": "plan_content_mismatch", "saved": False}

        request_key = f"{theme}|{budget:.2f}|{deadline_hours:.2f}"
        plans: list[dict[str, Any]] = []
        if self.plan_file.exists():
            plans = self._read_json(self.plan_file)
        existing = next((p for p in plans if p["request_key"] == request_key), None)
        if existing:
            return {
                "ok": True,
                "saved": True,
                "duplicate": True,
                "plan_id": existing["plan_id"],
                "existing_plan": {
                    "variant": existing["variant"],
                    "total_cost": existing["total_cost"],
                    "estimated_hours": existing["estimated_hours"],
                    "script": existing["script"],
                    "asset_ids": existing["asset_ids"],
                },
            }

        plan_id = "P-" + hashlib.sha256(request_key.encode()).hexdigest()[:10]
        plans.append(
            {
                "plan_id": plan_id,
                "request_key": request_key,
                "theme": theme,
                "variant": variant,
                "total_cost": total_cost,
                "estimated_hours": estimated_hours,
                "script": script,
                "asset_ids": asset_ids,
                "tasks": [
                    {"name": "准备素材", "status": "planned", "asset_ids": asset_ids},
                    {"name": "生成并审核脚本", "status": "planned", "script": script},
                    {"name": "安排渠道投放", "status": "planned", "variant": variant},
                ],
                "status": "saved_plan",
            }
        )
        self.plan_file.parent.mkdir(parents=True, exist_ok=True)
        self.plan_file.write_text(
            json.dumps(plans, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "ok": True,
            "saved": True,
            "duplicate": False,
            "plan_id": plan_id,
            "saved_plan": {
                "variant": variant,
                "script": script,
                "asset_ids": asset_ids,
                "total_cost": total_cost,
                "estimated_hours": estimated_hours,
            },
        }

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "search_assets": self.search_assets,
            "generate_script": self.generate_script,
            "estimate_cost": self.estimate_cost,
            "save_plan": self.save_plan,
        }
        if name not in allowed:
            return {"ok": False, "error": f"unknown_tool:{name}"}
        try:
            return allowed[name](**arguments)
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"tool_error:{type(exc).__name__}:{exc}"}
