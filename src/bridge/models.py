"""Domain models shared across the bridge."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Returns the current timezone-aware UTC time."""
    return datetime.now(UTC)


class Severity(str, enum.Enum):
    """Operational severity of a telemetry event."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Returns a sortable integer (higher is more severe)."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


class Role(str, enum.Enum):
    """RBAC roles."""

    VIEWER = "VIEWER"
    AGENT = "AGENT"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class Principal(BaseModel):
    """An authenticated caller (human or service)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=80)
    role: Role


class Decision(str, enum.Enum):
    """Outcome of a control-tower evaluation."""

    EXECUTED = "executed"
    PENDING_APPROVAL = "pending_approval"
    DENIED = "denied"
    REJECTED = "rejected"
    FAILED = "failed"


class TelemetryEvent(BaseModel):
    """Versioned inbound contract; unknown fields signal schema drift."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=64
    )
    source: str = Field(min_length=1, max_length=64)
    account_name: str = Field(min_length=1, max_length=255)
    severity: Severity
    message: str = Field(min_length=1, max_length=4000)
    amount_usd: float = Field(default=0.0, ge=0)
    occurred_at: datetime = Field(default_factory=utcnow)


class UnifiedEvent(BaseModel):
    """Data Cloud DMO-style unified record (PII already redacted)."""

    event_id: str
    account_key: str
    account_name: str
    source: str
    severity: Severity
    message: str
    amount_usd: float
    occurred_at: datetime


class SimilarIncident(BaseModel):
    """A prior incident retrieved by vector similarity."""

    event_id: str
    score: float
    message: str


class GroundedContext(BaseModel):
    """Trusted, entity-scoped context handed to the planner."""

    account_key: str
    event_count: int
    exposure_usd: float
    max_severity: Severity
    similar: list[SimilarIncident] = Field(default_factory=list)


class Plan(BaseModel):
    """Planner output: an action name (or None) and its parameters."""

    action: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=2000)


class ActionRequest(BaseModel):
    """A request to invoke a registered Agentforce Action."""

    action: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None


class ActionOutcome(BaseModel):
    """Result of submitting an action through the control tower."""

    decision: Decision
    action: str
    detail: str
    result: dict[str, Any] | None = None
    approval_id: str | None = None


class AuditRecord(BaseModel):
    """Immutable audit entry mirrored to Bridge_Audit_Log__c."""

    audit_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=utcnow)
    actor: str
    action: str
    decision: Decision
    event_id: str | None = None
    detail: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    """End-to-end result for one processed event."""

    event_id: str
    account_key: str
    action: str | None
    rationale: str
    outcome: ActionOutcome | None
    latency_ms: float
