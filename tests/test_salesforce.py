import httpx
import pytest

from bridge.config import Settings
from bridge.resilience import CircuitBreaker, CircuitOpenError
from bridge.salesforce import (
    InMemorySalesforce,
    SalesforceClient,
    SalesforceError,
    soql_quote,
)
from tests.conftest import no_sleep

S = Settings(
    sf_client_id="i", sf_client_secret="s", sf_login_url="https://login.test"
)
TOKEN = {"access_token": "T", "instance_url": "https://inst.test"}
RID = "500000000000001AAA"


def client(handler, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SalesforceClient(S, http=http, sleep=no_sleep, rng=lambda: 0, **kw)


def router(routes):
    seq = {k: list(v) for k, v in routes.items()}

    def handler(req: httpx.Request):
        key = f"{req.method} {req.url.path}"
        item = seq[key].pop(0) if len(seq[key]) > 1 else seq[key][0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def R(status, body=None):
    return httpx.Response(status, json=body)


TOK = "POST /services/oauth2/token"
CASE = "POST /services/data/v62.0/sobjects/Case"


async def test_create_and_refresh_token():
    c = client(
        router({TOK: [R(200, TOKEN)], CASE: [R(401), R(201, {"id": RID})]})
    )
    assert await c.create_record("Case", {"Subject": "x"}) == RID
    assert c.breaker_state == "closed"
    await c.aclose()


async def test_retries_transient_then_success():
    c = client(
        router(
            {
                TOK: [R(200, TOKEN)],
                CASE: [httpx.ConnectError("boom"), R(503), R(201, {"id": RID})],
            }
        )
    )
    assert await c.create_record("Case", {}) == RID


async def test_non_retryable_and_validation():
    c = client(router({TOK: [R(200, TOKEN)], CASE: [R(400, [{"e": 1}])]}))
    with pytest.raises(SalesforceError) as e:
        await c.create_record("Case", {})
    assert e.value.status == 400
    with pytest.raises(ValueError):
        await c.create_record("Bad Name", {})
    with pytest.raises(ValueError):
        await c.update_record("Case", "short", {})


async def test_circuit_opens():
    b = CircuitBreaker(2, 999)
    c = client(router({TOK: [R(200, TOKEN)], CASE: [R(500)]}), breaker=b)
    with pytest.raises(CircuitOpenError):
        await c.create_record("Case", {})
    with pytest.raises(CircuitOpenError):
        await c.create_record("Case", {})


async def test_auth_failures():
    c = client(router({TOK: [R(400)]}))
    with pytest.raises(SalesforceError, match="OAuth"):
        await c.create_record("Case", {})
    c = client(
        router({TOK: [R(503), R(200, TOKEN)], CASE: [R(201, {"id": RID})]})
    )
    assert await c.create_record("Case", {}) == RID


async def test_update_and_query_pagination():
    q = "GET /services/data/v62.0/query"
    nxt = "GET /services/data/v62.0/query/01g-2000"
    c = client(
        router(
            {
                TOK: [R(200, TOKEN)],
                "PATCH /services/data/v62.0/sobjects/Case/" + RID: [R(204)],
                q: [
                    R(
                        200,
                        {
                            "records": [{"Id": "1"}],
                            "done": False,
                            "nextRecordsUrl": "/services/data/v62.0/query/01g-2000",
                        },
                    )
                ],
                nxt: [R(200, {"records": [{"Id": "2"}], "done": True})],
            }
        )
    )
    await c.update_record("Case", RID, {"Status": "Escalated"})
    assert [r["Id"] for r in await c.query("SELECT Id FROM Case")] == ["1", "2"]


async def test_owned_http_closed():
    c = SalesforceClient(S)
    await c.aclose()


def test_soql_quote():
    assert soql_quote("O'Re\\illy") == "'O\\'Re\\\\illy'"


async def test_inmemory():
    m = InMemorySalesforce(["O'Neil Co"])
    assert len(await m.query("SELECT Id FROM Account")) == 1
    assert await m.query(
        f"SELECT Id FROM Account WHERE Name = {soql_quote(chr(79) + chr(39) + 'Neil Co')}"
    )
    assert await m.query("SELECT Id FROM Account WHERE Name = 'zzz'") == []
    rid = await m.create_record("Case", {"a": 1})
    await m.update_record("Case", rid, {"b": 2})
    assert m.records["Case"][rid] == {"a": 1, "b": 2}
    with pytest.raises(SalesforceError):
        await m.update_record("Case", "nope", {})
    with pytest.raises(SalesforceError):
        await m.query("DELETE everything")
    with pytest.raises(ValueError):
        await m.create_record("x y", {})
