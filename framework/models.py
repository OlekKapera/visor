from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Status(str, Enum):
    OK = "ok"
    FAIL = "fail"


class ErrorCode(str, Enum):
    INPUT_ERROR = "INPUT_ERROR"
    TARGET_ERROR = "TARGET_ERROR"
    ACTION_ERROR = "ACTION_ERROR"
    ASSERTION_ERROR = "ASSERTION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


@dataclass
class ErrorPayload:
    code: ErrorCode
    message: str
    likely_cause: str
    next_step: str


@dataclass
class CommandResponse:
    status: Status
    command_id: str
    started_at: str
    ended_at: str
    artifacts: List[str] = field(default_factory=list)
    next_action: str = ""
    error: Optional[ErrorPayload] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Step:
    id: str
    command: str
    args: Dict[str, Any]


@dataclass
class Assertion:
    id: str
    type: str
    target: str


@dataclass
class Scenario:
    meta: Dict[str, Any]
    config: Dict[str, Any]
    steps: List[Step]
    assertions: List[Assertion]
    output: Dict[str, Any]


@dataclass
class StepResult:
    id: str
    command: str
    status: Status
    duration_ms: int
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[ErrorPayload] = None


@dataclass
class RunResult:
    run_id: str
    platform: str
    device: str
    started_at: str
    ended_at: str
    status: Status
    steps: List[StepResult]
    assertions: List[Dict[str, Any]]
    artifacts: List[str]
    determinism_signature: str
    seed: Optional[int] = None
    error: Optional[ErrorPayload] = None
