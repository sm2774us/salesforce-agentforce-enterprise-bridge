"""Environment-driven settings. Secrets never have in-code defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from bridge.models import Principal, Role


def parse_api_keys(raw: str) -> dict[str, Principal]:
    """Parses ``key=name:ROLE`` pairs separated by commas.

    Args:
      raw: Comma-separated specification, e.g. ``k1=svc:AGENT,k2=bob:APPROVER``.

    Returns:
      Mapping from API key to Principal.

    Raises:
      ValueError: If an entry is malformed or the role is unknown.
    """
    keys: dict[str, Principal] = {}
    for entry in filter(None, (e.strip() for e in raw.split(","))):
        key, sep, identity = entry.partition("=")
        name, sep2, role = identity.partition(":")
        if not (key and sep and name and sep2):
            raise ValueError(f"malformed BRIDGE_API_KEYS entry: {entry!r}")
        keys[key] = Principal(name=name, role=Role(role.upper()))
    return keys


@dataclass(frozen=True)
class Settings:
    """Runtime configuration."""

    sf_login_url: str = "https://login.salesforce.com"
    sf_client_id: str = field(default="", repr=False)
    sf_client_secret: str = field(default="", repr=False)
    sf_api_version: str = "62.0"
    anthropic_api_key: str = field(default="", repr=False)
    llm_model: str = "claude-sonnet-5-5"
    api_keys: dict[str, Principal] = field(default_factory=dict, repr=False)
    financial_threshold_usd: float = 10_000.0
    approval_ttl_seconds: float = 900.0
    max_pending_approvals: int = 1000
    queue_capacity: int = 1000
    workers: int = 4

    @property
    def salesforce_enabled(self) -> bool:
        """True when OAuth client credentials are configured."""
        return bool(self.sf_client_id and self.sf_client_secret)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Builds settings from environment variables."""
        e = os.environ if env is None else env
        d = cls()
        return cls(
            sf_login_url=e.get("SF_LOGIN_URL", d.sf_login_url).rstrip("/"),
            sf_client_id=e.get("SF_CLIENT_ID", ""),
            sf_client_secret=e.get("SF_CLIENT_SECRET", ""),
            sf_api_version=e.get("SF_API_VERSION", d.sf_api_version),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY", ""),
            llm_model=e.get("BRIDGE_LLM_MODEL", d.llm_model),
            api_keys=parse_api_keys(e.get("BRIDGE_API_KEYS", "")),
            financial_threshold_usd=float(
                e.get(
                    "BRIDGE_FINANCIAL_THRESHOLD_USD", d.financial_threshold_usd
                )
            ),
            approval_ttl_seconds=float(
                e.get("BRIDGE_APPROVAL_TTL_SECONDS", d.approval_ttl_seconds)
            ),
            max_pending_approvals=int(
                e.get("BRIDGE_MAX_PENDING", d.max_pending_approvals)
            ),
            queue_capacity=int(
                e.get("BRIDGE_QUEUE_CAPACITY", d.queue_capacity)
            ),
            workers=int(e.get("BRIDGE_WORKERS", d.workers)),
        )
