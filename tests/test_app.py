import dataclasses

from fastapi.testclient import TestClient

from bridge import cli
from bridge.api import create_app
from bridge.container import build_container
from bridge.grounding import (
    EntityResolver,
    GroundingService,
    VectorIndex,
    cosine,
    embed,
    normalize_account,
)
from bridge.models import Severity, TelemetryEvent
from bridge.samples import SAMPLE_EVENTS

A, V, P = {"X-API-Key": "ak"}, {"X-API-Key": "vk"}, {"X-API-Key": "pk"}
EVT = dict(SAMPLE_EVENTS[0])
FIN = dict(SAMPLE_EVENTS[1])


def test_grounding_units():
    assert normalize_account("ACME, Inc.") == "acme"
    assert normalize_account("Co") == "co"
    assert normalize_account("!!!") == "!!!"
    r = EntityResolver()
    assert r.resolve("Globex Ltd") == r.resolve("globex") == "globex"
    assert r.resolve("Globex Ltd") == "globex"
    assert r.resolve("Globexx") == "globex"
    assert r.resolve("Initech") == "initech"
    assert embed("!!!") == {}
    assert cosine(embed("a b c"), embed("a b c")) > 0.99
    assert cosine(embed("x y z q w"), embed("a b c")) < 0.99
    ix = VectorIndex(2)
    for i, t in enumerate(["db outage now", "db outage again", "other thing"]):
        ix.add(str(i), t)
    hits = ix.search("db outage", 5, "none", 0.0)
    assert {h.event_id for h in hits} <= {"1", "2"}
    ix.add("1", "replaced text")


def test_grounding_service_scoped():
    g = GroundingService(history_per_account=5)

    def e(acct, msg, sev=Severity.LOW, amt=0.0):
        return TelemetryEvent(
            source="s",
            account_name=acct,
            severity=sev,
            message=msg,
            amount_usd=amt,
        )

    u1 = g.ingest(e("Acme Inc", "gateway timeout error x@y.com"))
    u2 = g.ingest(e("Acme", "gateway timeout error", Severity.HIGH, 5))
    g.ingest(e("Other", "gateway timeout error"))
    c = g.context_for(u2)
    assert c.event_count == 2 and c.exposure_usd == 5
    assert c.max_severity is Severity.HIGH
    assert [s.event_id for s in c.similar] == [u1.event_id]
    assert "y.com" not in u1.message


def test_api_end_to_end(settings, sf):
    c = build_container(settings, gateway=sf)
    with TestClient(create_app(settings, c)) as cl:
        assert cl.get("/healthz").json() == {"status": "ok"}
        assert cl.get("/readyz").status_code == 200
        assert cl.get("/v1/actions").status_code == 401
        assert (
            cl.get("/v1/actions", headers={"X-API-Key": "wrong"}).status_code
            == 401
        )
        assert cl.get("/v1/actions", headers=V).status_code == 200
        assert cl.post("/v1/events", json=EVT, headers=V).status_code == 403
        r = cl.post("/v1/events", json={**EVT, "event_id": "a1"}, headers=A)
        assert r.status_code == 202
        r = cl.post("/v1/events", json={**EVT, "event_id": "a1"}, headers=A)
        assert r.json()["status"] == "duplicate"
        assert (
            cl.post("/v1/events", json={"bad": 1}, headers=A).status_code == 422
        )
        assert cl.post("/v1/events", content=b"{", headers=A).status_code == 400
        assert cl.post("/v1/events", json=[1], headers=A).status_code == 422
        r = cl.post("/v1/events?wait=true", json=FIN, headers=A)
        assert r.json()["outcome"]["decision"] == "pending_approval"
        aid = r.json()["outcome"]["approval_id"]
        assert (
            cl.post(
                "/v1/events?wait=true", json={"x": 1}, headers=A
            ).status_code
            == 422
        )
        assert cl.get("/v1/approvals", headers=A).status_code == 403
        assert (
            cl.get("/v1/approvals", headers=P).json()[0]["approval_id"] == aid
        )
        d = cl.post(
            f"/v1/approvals/{aid}/decision", json={"approve": True}, headers=P
        )
        assert d.status_code == 200
        assert (
            cl.post(
                f"/v1/approvals/{aid}/decision",
                json={"approve": True},
                headers=P,
            ).status_code
            == 404
        )
        r = cl.post(
            "/v1/actions/create_case",
            headers=A,
            json={
                "params": {"account_name": "Acme Corporation", "subject": "s"}
            },
        )
        assert r.status_code == 200
        assert (
            cl.post("/v1/actions/bogus", json={}, headers=A).status_code == 403
        )
        assert cl.get("/v1/audit?limit=2", headers=V).status_code == 200
        assert "bridge_events_processed_total" in cl.get("/metrics").text


def test_api_misc(settings, sf):
    import time

    c = build_container(
        dataclasses.replace(settings, queue_capacity=1, workers=1), gateway=sf
    )
    app = create_app(settings, c)
    with TestClient(app) as cl:
        codes = {
            cl.post("/v1/events", json=dict(EVT), headers=A).status_code
            for _ in range(30)
        }
        assert codes <= {202, 429}
        time.sleep(0.2)
        c.approvals._ttl = -1
        r = cl.post(
            "/v1/actions/create_financial_review",
            headers=A,
            json={
                "params": {"account_name": "A", "amount_usd": 1, "reason": "r"}
            },
        )
        aid = r.json()["approval_id"]
        assert (
            cl.post(
                f"/v1/approvals/{aid}/decision",
                json={"approve": True},
                headers=P,
            ).status_code
            == 410
        )


def test_readyz_unready(settings, sf):
    c = build_container(settings, gateway=sf)
    cl = TestClient(create_app(settings, c))  # lifespan not started
    assert cl.get("/readyz").status_code == 503


def test_default_app_from_env(monkeypatch):
    monkeypatch.setenv("BRIDGE_API_KEYS", "k=u:ADMIN")
    with TestClient(create_app()) as cl:
        assert (
            cl.get("/v1/actions", headers={"X-API-Key": "k"}).status_code == 200
        )


def test_container_variants(settings):
    c = build_container(
        dataclasses.replace(
            settings,
            sf_client_id="i",
            sf_client_secret="s",
            anthropic_api_key="k",
        )
    )
    assert len(c._closers) == 2
    import asyncio

    asyncio.run(c.aclose())


async def test_pipeline_mirror_failure(container, sf):
    async def boom(o, f):
        raise RuntimeError("x")

    real = sf.create_record
    sf.create_record = boom
    r = await container.pipeline.process(
        TelemetryEvent(
            **{
                "source": "s",
                "account_name": "A",
                "severity": "low",
                "message": "m",
            }
        )
    )
    sf.create_record = real
    assert r.action is None and container.metrics.counter("mirror_failures")


def test_cli(capsys, monkeypatch):
    import io

    buf = io.StringIO()
    assert cli.main(["demo"], buf) == 0
    out = buf.getvalue()
    assert "pending_approval" in out and "human approval" in out
    monkeypatch.delenv("SF_CLIENT_ID", raising=False)
    buf = io.StringIO()
    assert cli.main(["demo", "--live"], buf) == 2
    monkeypatch.setenv("SF_CLIENT_ID", "i")
    monkeypatch.setenv("SF_CLIENT_SECRET", "s")
    from bridge.salesforce import InMemorySalesforce

    monkeypatch.setattr(
        cli, "InMemorySalesforce", lambda a: InMemorySalesforce(a)
    )
    s = cli._settings(True)
    assert s.salesforce_enabled
    buf = io.StringIO()
    assert cli.main(["bench", "-n", "50"], buf) == 0
    assert "events=50" in buf.getvalue()
    assert cli.main(["manifest"]) == 0
    assert "create_case" in capsys.readouterr().out
    called = {}
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, host, port: called.update(h=host, p=port),
    )
    assert cli.main(["serve", "--port", "9"]) == 0
    assert called == {"h": "127.0.0.1", "p": 9}


def test_container_custom_planner(settings, sf):
    from bridge.agent import RuleBasedPlanner

    c = build_container(settings, gateway=sf, planner=RuleBasedPlanner())
    assert c.pipeline is not None


def test_backpressure_429(settings, sf):
    c = build_container(
        dataclasses.replace(settings, queue_capacity=1), gateway=sf
    )
    cl = TestClient(create_app(settings, c))  # workers not started
    assert cl.post("/v1/events", json=dict(EVT), headers=A).status_code == 202
    r = cl.post("/v1/events", json=dict(EVT), headers=A)
    assert r.status_code == 429 and r.headers["Retry-After"] == "1"
