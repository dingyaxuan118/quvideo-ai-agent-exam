from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskStatus = Literal[
    "draft_saved", "pending_confirmation", "blocked", "incomplete", "failed"
]


@dataclass(frozen=True)
class ScheduleRequest:
    material_id: str
    desired_time: str
    allow_alternative: bool = False
    confirmed_time: str | None = None
    simulate_save_failure: bool = False


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
    next_decision_reason: str


@dataclass
class AgentResult:
    material_id: str
    review_status: str
    risk_reasons: list[str]
    requested_time: str
    suggested_time: str | None
    pending_confirmation: list[str]
    draft_save_status: str
    task_status: TaskStatus
    message: str
    draft_id: str | None = None
    trace: list[TraceStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
