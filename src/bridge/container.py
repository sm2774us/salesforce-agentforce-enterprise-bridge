"""Composition root wiring all collaborators."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from bridge.actions import ActionRegistry, build_default_registry
from bridge.agent import (
    AnthropicPlanner,
    Planner,
    ResilientPlanner,
    RuleBasedPlanner,
)
from bridge.approvals import ApprovalStore
from bridge.audit import AuditLog
from bridge.bus import EventBus
from bridge.config import Settings
from bridge.control_tower import ControlTower
from bridge.grounding import GroundingService
from bridge.metrics import Metrics
from bridge.models import Principal, Role
from bridge.pipeline import Pipeline
from bridge.salesforce import (
    InMemorySalesforce,
    SalesforceClient,
    SalesforceGateway,
)

AGENT = Principal(name="agentforce-bridge-agent", role=Role.AGENT)


@dataclass
class Container:
    """Holds the wired object graph."""

    settings: Settings
    metrics: Metrics
    gateway: SalesforceGateway
    registry: ActionRegistry
    audit: AuditLog
    approvals: ApprovalStore
    tower: ControlTower
    grounding: GroundingService
    pipeline: Pipeline
    bus: EventBus
    _closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def aclose(self) -> None:
        """Closes owned network clients."""
        for closer in self._closers:
            await closer()


def build_container(
    settings: Settings,
    gateway: SalesforceGateway | None = None,
    planner: Planner | None = None,
) -> Container:
    """Builds the object graph.

    Args:
      settings: Runtime settings.
      gateway: Optional CRM gateway override (tests/offline demo).
      planner: Optional planner override.
    """
    closers: list[Callable[[], Awaitable[None]]] = []
    metrics = Metrics()
    if gateway is None:
        if settings.salesforce_enabled:
            client = SalesforceClient(settings)
            closers.append(client.aclose)
            gateway = client
        else:
            gateway = InMemorySalesforce()
    registry = build_default_registry(gateway)
    if planner is None:
        rules = RuleBasedPlanner(settings.financial_threshold_usd)
        planner = rules
        if settings.anthropic_api_key:
            http = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
            closers.append(http.aclose)
            planner = ResilientPlanner(
                AnthropicPlanner(
                    settings.anthropic_api_key,
                    settings.llm_model,
                    registry.names(),
                    http,
                ),
                rules,
                metrics,
            )
    audit = AuditLog(gateway)
    approvals = ApprovalStore(
        settings.approval_ttl_seconds, settings.max_pending_approvals
    )
    tower = ControlTower(registry, audit, approvals, metrics)
    grounding = GroundingService()
    pipeline = Pipeline(grounding, planner, tower, gateway, metrics, AGENT)
    bus = EventBus(pipeline.process, settings.queue_capacity, settings.workers)
    return Container(
        settings,
        metrics,
        gateway,
        registry,
        audit,
        approvals,
        tower,
        grounding,
        pipeline,
        bus,
        closers,
    )
