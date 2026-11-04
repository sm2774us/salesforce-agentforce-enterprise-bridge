import json

import httpx
import pytest

from bridge.actions import (
    ActionRegistry,
    UnknownActionError,
    build_default_registry,
)
from bridge.agent import (
    AnthropicPlanner,
    PlannerError,
    ResilientPlanner,
    RuleBasedPlanner,
)
from bridge.approvals import (
    ApprovalCapacityError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalStore,
)
from bridge.audit import AuditLog
from bridge.bus import BusFullError, EventBus, SchemaDriftError
from bridge.models import (
    ActionRequest,
    AuditRecord,
    Decision,
    GroundedContext,
    Principal,
    Role,
    Severity,
    TelemetryEvent,
    UnifiedEvent,
    utcnow,
)
from bridge.salesforce import SalesforceError

AGENT = Principal(name="svc", role=Role.AGENT)
BOSS = Principal(name="pat", role=Role.APPROVER)
VIEW = Principal(name="vic", role=Role.VIEWER)


def req(action, **params):
    return ActionRequest(action=action, params=params, event_id="e1")


CASE = {"account_name": "Acme Corporation", "subject": "s"}


async def test_low_risk_executes_and_links_account(container, sf):
    o = await container.tower.submit(AGENT, req("create_case", **CASE))
    assert o.decision is Decision.EXECUTED and o.result["account_linked"]
    o = await container.tower.submit(
        AGENT, req("create_case", account_name="Nobody", subject="s")
    )
    assert not o.result["account_linked"]
    assert len(sf.records["Bridge_Audit_Log__c"]) == 2


async def test_deny_reject_unknown(container):
    t = container.tower
    assert (await t.submit(AGENT, req("nope"))).decision is Decision.DENIED
    assert (
        await t.submit(VIEW, req("create_case", **CASE))
    ).decision is Decision.DENIED
    assert (
        await t.submit(AGENT, req("create_case", subject="s"))
    ).decision is Decision.REJECTED


async def test_pii_redacted_before_audit(container):
    await t_submit(container, subject="mail a@b.com")
    rec = container.audit.recent(1)[0]
    assert "a@b.com" not in json.dumps(rec.payload)


async def t_submit(c, **kw):
    return await c.tower.submit(
        AGENT, req("create_case", account_name="Acme Corporation", **kw)
    )


FIN = {"account_name": "Acme Corporation", "amount_usd": 5.0, "reason": "r"}


async def test_hitl_approve_flow(container, sf):
    t = container.tower
    o = await t.submit(AGENT, req("create_financial_review", **FIN))
    assert o.decision is Decision.PENDING_APPROVAL and o.approval_id
    assert (
        await t.decide(AGENT, o.approval_id, True)
    ).decision is Decision.DENIED  # not an approver
    admin = Principal(name="svc", role=Role.ADMIN)
    assert "separation" in (await t.decide(admin, o.approval_id, True)).detail
    d = await t.decide(BOSS, o.approval_id, True)
    assert d.decision is Decision.EXECUTED and "approved by pat" in d.detail
    assert sf.records["Case"]
    with pytest.raises(ApprovalNotFoundError):
        await t.decide(BOSS, o.approval_id, True)


async def test_hitl_reject_and_failure(container, sf):
    t = container.tower
    o = await t.submit(AGENT, req("create_financial_review", **FIN))
    d = await t.decide(BOSS, o.approval_id, False, "no")
    assert d.decision is Decision.REJECTED
    o = await t.submit(
        AGENT, req("escalate_case", case_id="X" * 15, reason="r")
    )
    d = await t.decide(BOSS, o.approval_id, True)
    assert d.decision is Decision.FAILED and "SalesforceError" in d.detail
    case = await sf.create_record("Case", {})
    o = await t.submit(AGENT, req("escalate_case", case_id=case, reason="r"))
    d = await t.decide(BOSS, o.approval_id, True)
    assert sf.records["Case"][case]["Status"] == "Escalated"


async def test_approval_capacity(settings, sf):
    from bridge.container import build_container
    import dataclasses

    c = build_container(
        dataclasses.replace(settings, max_pending_approvals=0), gateway=sf
    )
    o = await c.tower.submit(AGENT, req("create_financial_review", **FIN))
    assert o.decision is Decision.FAILED


def test_approval_store_ttl():
    t = [0.0]
    s = ApprovalStore(10, 2, clock=lambda: t[0])
    a = s.create(AGENT, req("x"))
    b = s.create(AGENT, req("y"))
    with pytest.raises(ApprovalCapacityError):
        s.create(AGENT, req("z"))
    assert len(s.list_pending()) == 2
    t[0] = 5
    s.remove(a.approval_id)
    s.remove("missing")
    assert s.get(b.approval_id) is b
    t[0] = 11
    with pytest.raises(ApprovalExpiredError):
        s.get(b.approval_id)
    s.create(AGENT, req("w"))
    t[0] = 30
    assert s.list_pending() == []


def test_registry(sf):
    r = build_default_registry(sf)
    assert r.names() == [
        "create_case",
        "create_financial_review",
        "escalate_case",
    ]
    assert r.manifest()[1]["requiresApproval"] is True
    with pytest.raises(UnknownActionError):
        r.get("zz")
    with pytest.raises(ValueError):
        r.register(r.get("create_case"))
    assert ActionRegistry().names() == []


async def test_audit_outbox(sf):
    calls = {"n": 0}
    real = sf.create_record

    async def flaky(o, f):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise SalesforceError("down")
        return await real(o, f)

    sf.create_record = flaky
    log = AuditLog(sf, capacity=5)
    rec = lambda: AuditRecord(
        actor="a",
        action="x",  # noqa: E731
        decision=Decision.EXECUTED,
    )
    await log.record(rec())
    await log.record(rec())  # flush fails again, new one fails too? n=2
    assert log.pending_sync >= 1
    await log.record(rec())
    assert log.pending_sync == 0
    assert len(log.recent(10)) == 3
    sf.create_record = real
    local = AuditLog()
    await local.record(rec())
    assert local.pending_sync == 0

    async def always(o, f):
        raise SalesforceError("down")

    sf.create_record = always
    stuck = AuditLog(sf)
    await stuck.record(rec())
    assert await stuck.flush() == 0


def ev(**kw):
    base = dict(
        source="s", account_name="Acme", severity=Severity.MEDIUM, message="m"
    )
    return TelemetryEvent(**{**base, **kw})


def uni(**kw):
    base = dict(
        event_id="1",
        account_key="acme",
        account_name="Acme",
        source="s",
        severity=Severity.MEDIUM,
        message="m",
        amount_usd=0.0,
        occurred_at=utcnow(),
    )
    return UnifiedEvent(**{**base, **kw})


def ctx(n=1):
    return GroundedContext(
        account_key="acme",
        event_count=n,
        exposure_usd=0,
        max_severity=Severity.LOW,
    )


async def test_rule_planner():
    p = RuleBasedPlanner(100)
    assert (
        await p.plan(uni(amount_usd=100), ctx())
    ).action == "create_financial_review"
    assert (await p.plan(uni(severity=Severity.LOW), ctx())).action is None
    assert (await p.plan(uni(), ctx())).params["priority"] == "Medium"
    assert (await p.plan(uni(), ctx(3))).params["priority"] == "High"
    assert (await p.plan(uni(severity=Severity.HIGH), ctx())).params[
        "priority"
    ] == "High"


def llm(handler, allowed=("create_case",)):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AnthropicPlanner("k", "m", allowed, http)


def text_resp(text):
    return httpx.Response(
        200,
        json={
            "content": [{"type": "thinking"}, {"type": "text", "text": text}]
        },
    )


async def test_llm_planner():
    good = 'Sure: {"action": "create_case", "params": {"a": 1}}'
    p = llm(lambda r: text_resp(good))
    assert (await p.plan(uni(), ctx())).action == "create_case"
    for bad in ("no json", '{"action": "drop_db"}', "} {"):
        with pytest.raises(PlannerError):
            await llm(lambda r, b=bad: text_resp(b)).plan(uni(), ctx())
    p = llm(lambda r: text_resp('{"action": null}'))
    assert (await p.plan(uni(), ctx())).action is None
    with pytest.raises(httpx.HTTPStatusError):
        await llm(lambda r: httpx.Response(500)).plan(uni(), ctx())


async def test_resilient_planner(container):
    primary = llm(lambda r: httpx.Response(500))
    p = ResilientPlanner(primary, RuleBasedPlanner(), container.metrics)
    assert (await p.plan(uni(), ctx())).action == "create_case"
    assert container.metrics.counter("planner_fallback") == 1
    ok = llm(lambda r: text_resp('{"action": null}'))
    p = ResilientPlanner(ok, RuleBasedPlanner(), container.metrics)
    assert (await p.plan(uni(), ctx())).action is None


async def test_bus_flow():
    seen = []

    async def handler(e):
        if e.message == "boom":
            raise RuntimeError("x")
        seen.append(e.event_id)

    bus = EventBus(handler, capacity=2, workers=1, dedupe_size=2)
    payload = {
        "source": "s",
        "account_name": "a",
        "severity": "low",
        "message": "m",
        "event_id": "1",
    }
    e, new = bus.publish_raw(payload)
    assert new and not bus.publish_raw(payload)[1]
    bus.publish_raw({**payload, "event_id": "2", "message": "boom"})
    with pytest.raises(BusFullError):
        bus.publish_raw({**payload, "event_id": "3"})
    with pytest.raises(SchemaDriftError) as ex:
        bus.publish_raw({**payload, "new_field": 1})
    assert ex.value.errors
    assert not bus.running
    await bus.start()
    await bus.start()
    assert bus.running
    await bus.stop()
    assert seen == ["1"] and not bus.running
    assert {d["reason"] for d in bus.dlq} == {"schema_drift", "handler_error"}
    bus.publish_raw({**payload, "event_id": "4"})
    bus.publish_raw({**payload, "event_id": "5"}) if False else None
