"""AI Control Tower: RBAC, PII stripping, risk gating, execution, audit."""

from __future__ import annotations

from pydantic import ValidationError

from bridge.actions import (
    ActionDefinition,
    ActionRegistry,
    RiskTier,
    UnknownActionError,
)
from bridge.approvals import ApprovalCapacityError, ApprovalStore
from bridge.audit import AuditLog
from bridge.metrics import Metrics
from bridge.models import (
    ActionOutcome,
    ActionRequest,
    AuditRecord,
    Decision,
    Principal,
)
from bridge.pii import redact_value
from bridge.rbac import RbacPolicy


class ControlTower:
    """Single choke point through which every agent tool call passes."""

    def __init__(
        self,
        registry: ActionRegistry,
        audit: AuditLog,
        approvals: ApprovalStore,
        metrics: Metrics,
        policy: RbacPolicy | None = None,
    ) -> None:
        """Wires collaborators."""
        self._registry = registry
        self._audit = audit
        self._approvals = approvals
        self._metrics = metrics
        self._policy = policy or RbacPolicy()

    async def _finish(
        self,
        actor: Principal,
        request: ActionRequest,
        decision: Decision,
        detail: str,
        *,
        result: dict | None = None,
        approval_id: str | None = None,
    ) -> ActionOutcome:
        await self._audit.record(
            AuditRecord(
                actor=actor.name,
                action=request.action,
                decision=decision,
                event_id=request.event_id,
                detail=detail,
                payload=request.params,
            )
        )
        self._metrics.incr(f"decision_{decision.value}")
        return ActionOutcome(
            decision=decision,
            action=request.action,
            detail=detail,
            result=result,
            approval_id=approval_id,
        )

    async def _execute(
        self,
        actor: Principal,
        definition: ActionDefinition,
        request: ActionRequest,
        prefix: str = "",
    ) -> ActionOutcome:
        try:
            params = definition.params_model.model_validate(request.params)
            result = await definition.handler(params)
        except Exception as exc:
            return await self._finish(
                actor,
                request,
                Decision.FAILED,
                f"{prefix}{type(exc).__name__}: {exc}"[:500],
            )
        return await self._finish(
            actor, request, Decision.EXECUTED, f"{prefix}ok", result=result
        )

    async def submit(
        self, principal: Principal, request: ActionRequest
    ) -> ActionOutcome:
        """Evaluates a request: deny, reject, queue for approval, or run."""
        clean_params, _ = redact_value(request.params)
        request = request.model_copy(update={"params": clean_params})
        try:
            definition = self._registry.get(request.action)
        except UnknownActionError:
            return await self._finish(
                principal, request, Decision.DENIED, "unknown action"
            )
        if not self._policy.allows(principal.role, definition.permission):
            return await self._finish(
                principal,
                request,
                Decision.DENIED,
                f"role {principal.role.value} lacks {definition.permission}",
            )
        try:
            definition.params_model.model_validate(request.params)
        except ValidationError as exc:
            return await self._finish(
                principal,
                request,
                Decision.REJECTED,
                f"invalid parameters ({exc.error_count()} error(s))",
            )
        if definition.risk is RiskTier.HIGH:
            try:
                pending = self._approvals.create(principal, request)
            except ApprovalCapacityError as exc:
                return await self._finish(
                    principal, request, Decision.FAILED, str(exc)
                )
            return await self._finish(
                principal,
                request,
                Decision.PENDING_APPROVAL,
                "awaiting human approval",
                approval_id=pending.approval_id,
            )
        return await self._execute(principal, definition, request)

    async def decide(
        self,
        approver: Principal,
        approval_id: str,
        approve: bool,
        note: str = "",
    ) -> ActionOutcome:
        """Approves or rejects a pending request.

        Raises:
          ApprovalNotFoundError: Unknown approval id.
          ApprovalExpiredError: The approval expired.
        """
        pending = self._approvals.get(approval_id)
        request = pending.request
        if not self._policy.allows(approver.role, "approvals:decide"):
            return await self._finish(
                approver, request, Decision.DENIED, "approver role required"
            )
        if approver.name == pending.requester.name:
            return await self._finish(
                approver,
                request,
                Decision.DENIED,
                "separation of duties: requester cannot approve",
            )
        self._approvals.remove(approval_id)
        if not approve:
            return await self._finish(
                approver,
                request,
                Decision.REJECTED,
                f"rejected by {approver.name}: {note}"[:500],
            )
        definition = self._registry.get(request.action)
        return await self._execute(
            approver,
            definition,
            request,
            prefix=(
                f"approved by {approver.name} for {pending.requester.name}; "
            ),
        )
