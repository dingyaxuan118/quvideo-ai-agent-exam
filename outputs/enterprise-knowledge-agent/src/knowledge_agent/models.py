from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

TaskStatus = Literal["answered", "needs_clarification", "out_of_scope", "failed", "incomplete"]


@dataclass(frozen=True)
class KnowledgeRequest:
    question: str
    history: list[dict[str, str]] = field(default_factory=list)
    fail_search_once: bool = False
    fail_read_ids: list[str] = field(default_factory=list)


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
    question: str
    resolved_question: str
    answer: str
    citations: list[dict[str, str]]
    conflicts: list[dict[str, Any]]
    information_gaps: list[str]
    follow_up_question: str | None
    task_status: TaskStatus
    trace: list[TraceStep]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
