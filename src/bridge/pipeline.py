"""End-to-end event pipeline: ground -> plan -> govern -> act."""

from __future__ import annotations

import logging
import time

from bridge.agent import Planner
from bridge.control_tower import ControlTower
from bridge.grounding import GroundingService
from bridge.metrics import Metrics
from bridge.models import (
    ActionRequest,
    PipelineResult,
    Principal,
    TelemetryEvent,
    UnifiedEvent,
)
from bridge.salesforce import SalesforceGateway

_LOG = logging.getLogger(__name__)


class Pipeline:
    """Processes one telemetry event end to end."""

    def __init__(
        self,
        grounding: GroundingService,
        planner: Planner,
        tower: ControlTower,
        gateway: SalesforceGateway,
        metrics: Metrics,
        agent: Principal,
    ) -> None:
        """Wires the stages."""
        self._grounding = grounding
        self._planner = planner
        self._tower = tower
        self._gateway = gateway
        self._metrics = metrics
        self._agent = agent

    async def _mirror(self, e: UnifiedEvent) -> None:
        """Best-effort copy into Telemetry_Event__c (never blocks triage)."""
        try:
            await self._gateway.create_record(
                "Telemetry_Event__c",
                {
                    "Event_Id__c": e.event_id,
                    "Source__c": e.source,
                    "Severity__c": e.severity.value,
                    "Message__c": e.message,
                    "Amount_Usd__c": e.amount_usd,
                    "Account_Key__c": e.account_key,
                },
            )
        except Exception:
            _LOG.warning("telemetry mirror failed", exc_info=True)
            self._metrics.incr("mirror_failures")

    async def process(self, event: TelemetryEvent) -> PipelineResult:
        """Runs the full pipeline for ``event``."""
        start = time.perf_counter()
        unified = self._grounding.ingest(event)
        await self._mirror(unified)
        plan = await self._planner.plan(
            unified, self._grounding.context_for(unified)
        )
        outcome = None
        if plan.action:
            outcome = await self._tower.submit(
                self._agent,
                ActionRequest(
                    action=plan.action,
                    params=plan.params,
                    event_id=event.event_id,
                ),
            )
        elapsed = time.perf_counter() - start
        self._metrics.observe_latency(elapsed)
        self._metrics.incr("events_processed")
        return PipelineResult(
            event_id=event.event_id,
            account_key=unified.account_key,
            action=plan.action,
            rationale=plan.rationale,
            outcome=outcome,
            latency_ms=round(elapsed * 1000, 3),
        )
