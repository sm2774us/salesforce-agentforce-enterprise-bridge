"""Audit trail with a durable-retry outbox to Bridge_Audit_Log__c."""

from __future__ import annotations

import collections
import json
import logging

from bridge.models import AuditRecord
from bridge.salesforce import SalesforceGateway

_LOG = logging.getLogger(__name__)


class AuditLog:
    """Records every control-tower decision locally and in Salesforce.

    Salesforce write failures never block the caller; records wait in a
    bounded outbox and are retried on the next write or via ``flush``.
    """

    def __init__(
        self, gateway: SalesforceGateway | None = None, capacity: int = 10_000
    ) -> None:
        """Initializes the log."""
        self._gateway = gateway
        self._records: collections.deque[AuditRecord] = collections.deque(
            maxlen=capacity
        )
        self._outbox: collections.deque[AuditRecord] = collections.deque(
            maxlen=capacity
        )

    @property
    def pending_sync(self) -> int:
        """Number of records not yet written to Salesforce."""
        return len(self._outbox)

    async def _write(self, rec: AuditRecord) -> None:
        assert self._gateway is not None
        await self._gateway.create_record(
            "Bridge_Audit_Log__c",
            {
                "Audit_Id__c": rec.audit_id,
                "Actor__c": rec.actor[:80],
                "Action__c": rec.action[:80],
                "Decision__c": rec.decision.value,
                "Event_Id__c": rec.event_id or "",
                "Detail__c": rec.detail[:1000],
                "Payload_Json__c": json.dumps(rec.payload, default=str)[:32000],
            },
        )

    async def record(self, rec: AuditRecord) -> None:
        """Appends a record and attempts to sync it."""
        self._records.append(rec)
        if self._gateway is None:
            return
        if self._outbox:
            await self.flush()
        try:
            await self._write(rec)
        except Exception:
            _LOG.warning("audit sync deferred", exc_info=True)
            self._outbox.append(rec)

    async def flush(self) -> int:
        """Retries the outbox in order; returns how many were synced."""
        synced = 0
        while self._outbox:
            try:
                await self._write(self._outbox[0])
            except Exception:
                break
            self._outbox.popleft()
            synced += 1
        return synced

    def recent(self, limit: int = 50) -> list[AuditRecord]:
        """Returns the newest records first."""
        return list(self._records)[-limit:][::-1]
