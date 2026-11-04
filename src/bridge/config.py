"""Environment-driven settings. Secrets never have in-code defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

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


def load_dotenv(
    path: str | Path, environ: MutableMapping[str, str] | None = None
) -> int:
    """Loads ``KEY=VALUE`` lines from a dotenv file without overriding env.

    Blank lines, ``#`` comment lines and an optional ``export`` prefix are
    handled; matching surrounding quotes are stripped. Inline comments are
    not supported (put comments on their own line).

    Args:
      path: Dotenv file; a missing file is not an error.
      environ: Target mapping (defaults to ``os.environ``).

    Returns:
      Number of variables newly set.
    """
    env = os.environ if environ is None else environ
    file = Path(path)
    if not file.is_file():
        return 0
    loaded = 0
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in env:
            env[key] = value
            loaded += 1
    return loaded


def _read_private_key(env: Mapping[str, str]) -> str:
    """Reads the PEM from SF_PRIVATE_KEY (inline) or SF_PRIVATE_KEY_PATH.

    Inline values may encode newlines as a literal backslash-n (CI secrets).
    """
    inline = env.get("SF_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    if inline:
        return inline
    path = env.get("SF_PRIVATE_KEY_PATH", "")
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"cannot read SF_PRIVATE_KEY_PATH: {exc}") from exc


@dataclass(frozen=True)
class Settings:
    """Runtime configuration."""

    sf_login_url: str = "https://login.salesforce.com"
    sf_client_id: str = field(default="", repr=False)
    sf_client_secret: str = field(default="", repr=False)
    sf_username: str = ""
    sf_private_key: str = field(default="", repr=False)
    sf_private_key_passphrase: str = field(default="", repr=False)
    sf_jwt_audience: str = "https://login.salesforce.com"
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
    def uses_jwt(self) -> bool:
        """True when key-based (JWT bearer) auth is configured."""
        return bool(self.sf_private_key and self.sf_username)

    @property
    def salesforce_enabled(self) -> bool:
        """True when a usable Salesforce credential set is configured."""
        return bool(
            self.sf_client_id and (self.uses_jwt or self.sf_client_secret)
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Builds settings from environment variables."""
        e = os.environ if env is None else env
        d = cls()
        return cls(
            sf_login_url=e.get("SF_LOGIN_URL", d.sf_login_url).rstrip("/"),
            sf_client_id=e.get("SF_CLIENT_ID", ""),
            sf_client_secret=e.get("SF_CLIENT_SECRET", ""),
            sf_username=e.get("SF_USERNAME", ""),
            sf_private_key=_read_private_key(e),
            sf_private_key_passphrase=e.get("SF_PRIVATE_KEY_PASSPHRASE", ""),
            sf_jwt_audience=e.get("SF_JWT_AUDIENCE", d.sf_jwt_audience),
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
