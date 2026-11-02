from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskStatus = Literal["plan_saved", "incomplete", "failed"]


@dataclass(frozen=True)
class PlanningRequest:
    theme: str
    budget: float | None
    deadline_hours: float | None
    fail_script_once: bool = False
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
    decision_reason: str


@dataclass
class AgentResult:
    theme: str
    budget: float | None
    deadline_hours: float | None
    selected_variant: str | None
    script: str | None
    asset_ids: list[str]
    task_plan: list[dict[str, Any]]
    step_status: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    total_cost: float | None
    estimated_hours: float | None
    save_status: str
    task_status: TaskStatus
    message: str
    plan_id: str | None = None
    trace: list[TraceStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
