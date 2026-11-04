import pytest

from bridge.config import Settings, parse_api_keys
from bridge.metrics import Metrics
from bridge.models import Role, Severity
from bridge.pii import redact, redact_value
from bridge.rbac import RbacPolicy
from bridge.resilience import CircuitBreaker, CircuitState, retry_async


def test_parse_keys():
    k = parse_api_keys("a=x:agent, b=y:APPROVER,")
    assert k["a"].role is Role.AGENT and k["b"].name == "y"
    assert parse_api_keys("") == {}


@pytest.mark.parametrize("raw", ["nokey", "a=b", "=x:AGENT", "a=x:BOGUS"])
def test_parse_keys_bad(raw):
    with pytest.raises(ValueError):
        parse_api_keys(raw)


def test_settings_env():
    s = Settings.from_env(
        {
            "SF_CLIENT_ID": "i",
            "SF_CLIENT_SECRET": "s",
            "SF_LOGIN_URL": "https://x.my.salesforce.com/",
            "BRIDGE_WORKERS": "2",
        }
    )
    assert s.salesforce_enabled and s.workers == 2
    assert s.sf_login_url == "https://x.my.salesforce.com"
    assert "sf_client_secret" not in repr(s)
    assert not Settings().salesforce_enabled


def test_settings_default_env(monkeypatch):
    monkeypatch.setenv("BRIDGE_QUEUE_CAPACITY", "7")
    assert Settings.from_env().queue_capacity == 7


def test_redact():
    t, n = redact(
        "a@b.com 123-45-6789 4111 1111 1111 1111 (415) 555-0100 1234567890123"
    )
    assert n == 4 and "1234567890123" in t
    assert "[REDACTED:CARD]" in t and "@" not in t


def test_redact_value():
    v, n = redact_value({"a": ["x@y.io", 3], "b": 1.5, "c": {"d": "ok"}})
    assert n == 1 and v["a"][1] == 3 and v["c"]["d"] == "ok"


def test_rbac():
    p = RbacPolicy()
    assert p.allows(Role.ADMIN, "anything")
    assert p.allows(Role.AGENT, "action:create_case")
    assert not p.allows(Role.VIEWER, "events:write")
    assert not RbacPolicy({}).allows(Role.AGENT, "x")


def test_severity_rank():
    assert Severity.CRITICAL.rank > Severity.LOW.rank


async def test_retry_paths():
    calls = []
    sleeps = []

    async def sleep(d):
        sleeps.append(d)

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("x")
        return "ok"

    assert await retry_async(flaky, sleep=sleep, rng=lambda: 1.0) == "ok"
    assert sleeps == [0.2, 0.4]

    async def bad():
        raise KeyError("n")

    with pytest.raises(KeyError):
        await retry_async(bad, is_retryable=lambda e: False, sleep=sleep)
    with pytest.raises(KeyError):
        await retry_async(bad, attempts=2, sleep=sleep)
    with pytest.raises(ValueError):
        await retry_async(bad, attempts=0)


def test_breaker():
    t = [0.0]
    b = CircuitBreaker(2, 10, clock=lambda: t[0])
    assert b.allow()
    b.record_failure()
    assert b.state is CircuitState.CLOSED
    b.record_failure()
    assert not b.allow()
    t[0] = 11
    assert b.state is CircuitState.HALF_OPEN and b.allow()
    b.record_failure()
    assert b.state is CircuitState.OPEN
    t[0] = 22
    assert b.allow()
    b.record_success()
    assert b.state is CircuitState.CLOSED


def test_metrics():
    m = Metrics(3)
    assert m.percentile(50) == 0.0
    for x in (0.3, 0.1, 0.2, 0.9):
        m.observe_latency(x)
    m.incr("a", 2)
    assert m.counter("a") == 2 and m.counter("zz") == 0
    assert m.percentile(50) == 0.2
    assert "bridge_a_total 2" in m.render()
