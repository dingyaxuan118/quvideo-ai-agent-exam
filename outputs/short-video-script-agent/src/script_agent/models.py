from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ScriptRequest:
    topic: str
    audience: str
    platform: str
    target_duration: float | None
    style: str
    fail_search_once: bool = False
    fail_estimate_once: bool = False
    fail_rule_check: bool = False


@dataclass(frozen=True)
class Action:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class TraceStep:
    step: int
    action: str
    arguments: dict[str, Any]
    observation: dict[str, Any]
    decision_reason: str


@dataclass
class ScriptResult:
    title: str | None
    storyboard: list[dict[str, Any]]
    estimated_duration: float | None
    material_source_ids: list[str]
    risks: list[str]
    information_gaps: list[str]
    task_status: Literal["completed", "needs_input", "failed", "incomplete"]
    message: str
    trace: list[TraceStep]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
