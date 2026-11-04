"""Salesforce REST client (OAuth 2.0 client credentials) and an offline fake."""

from __future__ import annotations

import asyncio
import itertools
import random
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

import httpx

from bridge.config import Settings
from bridge.resilience import CircuitBreaker, CircuitOpenError, retry_async

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ID_RE = re.compile(r"^[A-Za-z0-9]{15,18}$")
_QUERY_RE = re.compile(
    r"FROM\s+(\w+)(?:\s+WHERE\s+Name\s*=\s*'((?:[^'\\]|\\.)*)')?", re.I
)


class SalesforceError(RuntimeError):
    """Non-retryable Salesforce failure."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Stores the HTTP status alongside the message."""
        super().__init__(message)
        self.status = status


class TransientSalesforceError(SalesforceError):
    """Retryable failure (429, 5xx, transport error, expired token)."""


def soql_quote(value: str) -> str:
    """Escapes a string literal for safe SOQL interpolation."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _check_sobject(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid sobject name: {name!r}")


class SalesforceGateway(Protocol):
    """Minimal CRM surface the bridge depends on."""

    async def create_record(self, sobject: str, fields: dict[str, Any]) -> str:
        """Creates a record and returns its Id."""

    async def update_record(
        self, sobject: str, record_id: str, fields: dict[str, Any]
    ) -> None:
        """Updates a record."""

    async def query(self, soql: str) -> list[dict[str, Any]]:
        """Runs a SOQL query and returns all records."""


class SalesforceClient:
    """Resilient async client for the Salesforce REST API."""

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        """Initializes the client (no network I/O)."""
        self._s = settings
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._owns_http = http is None
        self._breaker = breaker or CircuitBreaker()
        self._sleep = sleep
        self._rng = rng
        self._token: str | None = None
        self._instance_url = ""
        self._lock = asyncio.Lock()
        self._base = f"/services/data/v{settings.sf_api_version}"

    @property
    def breaker_state(self) -> str:
        """Circuit breaker state name."""
        return self.breaker.state.value

    @property
    def breaker(self) -> CircuitBreaker:
        """The underlying circuit breaker."""
        return self._breaker

    async def aclose(self) -> None:
        """Closes the HTTP client if owned."""
        if self._owns_http:
            await self._http.aclose()

    async def _ensure_token(self) -> tuple[str, str]:
        async with self._lock:
            if self._token is None:
                resp = await self._http.post(
                    f"{self._s.sf_login_url}/services/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._s.sf_client_id,
                        "client_secret": self._s.sf_client_secret,
                    },
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise TransientSalesforceError(
                        "token endpoint unavailable", resp.status_code
                    )
                if resp.status_code != 200:
                    raise SalesforceError(
                        f"OAuth failed: HTTP {resp.status_code}",
                        resp.status_code,
                    )
                body = resp.json()
                self._token = body["access_token"]
                self._instance_url = body["instance_url"]
            return self._token, self._instance_url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        async def attempt() -> httpx.Response:
            if not self._breaker.allow():
                raise CircuitOpenError("salesforce circuit open")
            try:
                token, base = await self._ensure_token()
                resp = await self._http.request(
                    method,
                    base + path,
                    json=json,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.TransportError as exc:
                self._breaker.record_failure()
                raise TransientSalesforceError(f"transport: {exc}") from exc
            if resp.status_code == 401:
                self._token = None
                raise TransientSalesforceError("token expired", 401)
            if resp.status_code == 429 or resp.status_code >= 500:
                self._breaker.record_failure()
                raise TransientSalesforceError(
                    f"HTTP {resp.status_code}", resp.status_code
                )
            if resp.status_code >= 400:
                raise SalesforceError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                    resp.status_code,
                )
            self._breaker.record_success()
            return resp

        return await retry_async(
            attempt,
            is_retryable=lambda e: isinstance(e, TransientSalesforceError),
            sleep=self._sleep,
            rng=self._rng,
        )

    async def create_record(self, sobject: str, fields: dict[str, Any]) -> str:
        """Creates an sObject record and returns its Id."""
        _check_sobject(sobject)
        resp = await self._request(
            "POST", f"{self._base}/sobjects/{sobject}", json=fields
        )
        return str(resp.json()["id"])

    async def update_record(
        self, sobject: str, record_id: str, fields: dict[str, Any]
    ) -> None:
        """Updates an sObject record."""
        _check_sobject(sobject)
        if not _ID_RE.match(record_id):
            raise ValueError(f"invalid record id: {record_id!r}")
        await self._request(
            "PATCH", f"{self._base}/sobjects/{sobject}/{record_id}", json=fields
        )

    async def query(self, soql: str) -> list[dict[str, Any]]:
        """Runs SOQL, following pagination, and returns all records."""
        resp = await self._request(
            "GET", f"{self._base}/query", params={"q": soql}
        )
        body = resp.json()
        records: list[dict[str, Any]] = list(body["records"])
        while not body["done"]:
            body = (await self._request("GET", body["nextRecordsUrl"])).json()
            records.extend(body["records"])
        return records


class InMemorySalesforce:
    """Deterministic offline stand-in implementing SalesforceGateway."""

    def __init__(self, accounts: Iterable[str] = ()) -> None:
        """Seeds Account records."""
        self.records: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._seq = itertools.count(1)
        for name in accounts:
            self.records["Account"][self._new_id("Account")] = {"Name": name}

    def _new_id(self, sobject: str) -> str:
        return f"{sobject[:3].upper()}{next(self._seq):015d}"

    async def create_record(self, sobject: str, fields: dict[str, Any]) -> str:
        """Stores a record and returns a synthetic 18-char Id."""
        _check_sobject(sobject)
        record_id = self._new_id(sobject)
        self.records[sobject][record_id] = dict(fields)
        return record_id

    async def update_record(
        self, sobject: str, record_id: str, fields: dict[str, Any]
    ) -> None:
        """Merges fields into an existing record."""
        if record_id not in self.records[sobject]:
            raise SalesforceError("NOT_FOUND", 404)
        self.records[sobject][record_id].update(fields)

    async def query(self, soql: str) -> list[dict[str, Any]]:
        """Supports ``SELECT ... FROM X [WHERE Name = '...']`` only."""
        match = _QUERY_RE.search(soql)
        if not match:
            raise SalesforceError("unsupported SOQL", 400)
        sobject, name = match.group(1), match.group(2)
        wanted = None if name is None else re.sub(r"\\(.)", r"\1", name)
        return [
            {"Id": rid, **fields}
            for rid, fields in self.records[sobject].items()
            if wanted is None or fields.get("Name") == wanted
        ]
