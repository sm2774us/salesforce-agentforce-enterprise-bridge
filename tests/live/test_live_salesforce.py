"""Live smoke test against a real org (``pytest -m live -o addopts=``)."""

import os
import uuid

import pytest

from bridge.config import Settings
from bridge.salesforce import SalesforceClient

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not os.environ.get("SF_CLIENT_ID"), reason="SF_* secrets not set"
)
async def test_case_roundtrip():
    client = SalesforceClient(Settings.from_env())
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
