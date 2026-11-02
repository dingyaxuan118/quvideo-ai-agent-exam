from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class BusinessTools:
    """Local business tools. They save drafts only and never publish content."""

    def __init__(self, data_dir: Path, draft_file: Path | None = None):
        self.data_dir = data_dir
        self.materials = self._read_json(data_dir / "materials.json")
        self.rules = self._read_json(data_dir / "rules.json")
        self.schedule = self._read_json(data_dir / "schedule.json")
        self.draft_file = draft_file or data_dir / "drafts.local.json"

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def read_material(self, material_id: str) -> dict[str, Any]:
        material = next(
            (item for item in self.materials if item["id"] == material_id), None
        )
        if material is None:
            return {"ok": False, "error": "material_not_found", "material_id": material_id}
        return {"ok": True, "material": material}

    def check_rules(self, material_id: str) -> dict[str, Any]:
        material = next(
            (item for item in self.materials if item["id"] == material_id), None
        )
        if material is None:
            return {"ok": False, "error": "material_not_found", "material_id": material_id}
        missing = [key for key in self.rules["required_fields"] if not material.get(key)]
        text = f'{material.get("title", "")} {material.get("caption", "")}'.lower()
        risks = [
            f"命中禁用表述：{term}"
            for term in self.rules["forbidden_claims"]
            if term.lower() in text
        ]
        if missing:
            return {
                "ok": True,
                "status": "incomplete",
                "missing_fields": missing,
                "risks": risks,
            }
        if risks:
            return {"ok": True, "status": "blocked", "missing_fields": [], "risks": risks}
        return {"ok": True, "status": "approved", "missing_fields": [], "risks": []}

    def query_slots(self, desired_time: str) -> dict[str, Any]:
        try:
            desired_dt = datetime.strptime(desired_time, "%Y-%m-%dT%H:%M")
        except ValueError:
            return {"ok": False, "error": "invalid_time_format", "requested_time": desired_time}
        occupied = set(self.schedule["occupied"])
        available = list(self.schedule["available"])
        if desired_time in available and desired_time not in occupied:
            return {
                "ok": True,
                "requested_time": desired_time,
                "available": True,
                "alternatives": [],
            }
        later = [
            slot for slot in available if datetime.strptime(slot, "%Y-%m-%dT%H:%M") > desired_dt
        ]
        alternatives = later
        return {
            "ok": True,
            "requested_time": desired_time,
            "available": False,
            "alternatives": alternatives[:3],
        }

    def save_draft(
        self,
        material_id: str,
        requested_time: str,
        scheduled_time: str,
        simulate_failure: bool = False,
    ) -> dict[str, Any]:
        if simulate_failure:
            return {"ok": False, "error": "draft_store_unavailable", "saved": False}
        review = self.check_rules(material_id)
        if not review.get("ok") or review.get("status") != "approved":
            return {"ok": False, "error": "material_not_approved", "saved": False}
        known_times = set(self.schedule["occupied"]) | set(self.schedule["available"])
        if requested_time not in known_times:
            return {"ok": False, "error": "requested_time_unknown", "saved": False}
        if (
            scheduled_time in self.schedule["occupied"]
            or scheduled_time not in self.schedule["available"]
        ):
            return {"ok": False, "error": "slot_not_available", "saved": False}

        request_key = f"{material_id}|{requested_time}|{scheduled_time}"

        drafts: list[dict[str, Any]] = []
        if self.draft_file.exists():
            drafts = self._read_json(self.draft_file)
        existing = next((d for d in drafts if d["request_key"] == request_key), None)
        if existing:
            return {
                "ok": True,
                "saved": True,
                "duplicate": True,
                "draft_id": existing["draft_id"],
            }

        draft_id = "D-" + hashlib.sha256(request_key.encode()).hexdigest()[:10]
        drafts.append(
            {
                "draft_id": draft_id,
                "request_key": request_key,
                "material_id": material_id,
                "scheduled_time": scheduled_time,
                "status": "draft",
            }
        )
        self.draft_file.parent.mkdir(parents=True, exist_ok=True)
        self.draft_file.write_text(
            json.dumps(drafts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {"ok": True, "saved": True, "duplicate": False, "draft_id": draft_id}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "read_material": self.read_material,
            "check_rules": self.check_rules,
            "query_slots": self.query_slots,
            "save_draft": self.save_draft,
        }
        if name not in allowed:
            return {"ok": False, "error": f"unknown_tool:{name}"}
        try:
            return allowed[name](**arguments)
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"tool_error:{type(exc).__name__}:{exc}"}
