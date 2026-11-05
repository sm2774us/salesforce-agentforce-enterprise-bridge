"""Live smoke test against a real org (``pytest -m live -o addopts=``).

Unlike the offline suite this test must see real credentials, so:

* ``conftest.hermetic_env`` skips tests marked ``live`` (it would otherwise
  wipe every ``SF_*`` variable and the test would send an empty client id,
  which Salesforce reports as ``invalid_client_id``);
* the repo-root ``.env`` is loaded here (real environment variables still
  win, as with the CLI) and relative paths such as ``SF_PRIVATE_KEY_PATH``
  resolve against the repo root;
* the "credentials present?" decision is made at run time, from the fully
  resolved settings, not at import time.
"""

from pathlib import Path
import uuid

import pytest

from bridge.config import Settings, load_dotenv
from bridge.salesforce import SalesforceClient

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    if not settings.salesforce_enabled:
        pytest.skip("SF_* credentials not set (env or .env)")
    return settings


async def test_case_roundtrip(live_settings):
    client = SalesforceClient(live_settings)
    try:
        subject = f"bridge-live-{uuid.uuid4().hex[:8]}"
        case_id = await client.create_record(
            "Case", {"Subject": subject, "Origin": "Web"}
        )
        rows = await client.query(f"SELECT Id FROM Case WHERE Id = '{case_id}'")
        assert rows[0]["Id"] == case_id
        await client.update_record("Case", case_id, {"Priority": "High"})
    finally:
        await client.aclose()
