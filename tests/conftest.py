import os

import pytest

from bridge.config import Settings, parse_api_keys
from bridge.container import build_container
from bridge.salesforce import InMemorySalesforce

KEYS = "ak=svc:AGENT,vk=vic:VIEWER,pk=pat:APPROVER,xk=root:ADMIN"


@pytest.fixture
def settings():
    return Settings(api_keys=parse_api_keys(KEYS))


@pytest.fixture
def sf():
    return InMemorySalesforce(["Acme Corporation"])


@pytest.fixture
def container(settings, sf):
    return build_container(settings, gateway=sf)


async def no_sleep(_):
    return None


_ENV_PREFIXES = ("SF_", "BRIDGE_", "ANTHROPIC_")


@pytest.fixture(autouse=True)
def hermetic_env(request, monkeypatch, tmp_path):
    """Isolates every offline test from the developer's shell and `.env`.

    The CLI auto-loads `.env` from the working directory, so tests run from
    an empty temp directory with all bridge-related variables cleared.

    Tests marked ``live`` are exempt: they exist to exercise the developer's
    real credentials, so they must see the real environment (they load
    ``.env`` themselves, see ``tests/live``).
    """
    if request.node.get_closest_marker("live"):
        return
    for key in [k for k in os.environ if k.startswith(_ENV_PREFIXES)]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
