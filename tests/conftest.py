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
