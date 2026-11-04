"""Bounded, TTL-based human-in-the-loop approval store."""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from bridge.models import ActionRequest, Principal


class ApprovalError(RuntimeError):
    """Base class for approval store errors."""


class ApprovalNotFoundError(ApprovalError):
    """No pending approval has this id."""


class ApprovalExpiredError(ApprovalError):
    """The approval's time-to-live elapsed."""


class ApprovalCapacityError(ApprovalError):
    """Too many approvals are pending."""


@dataclass(frozen=True)
class PendingApproval:
    """A high-risk request awaiting a human decision."""

    approval_id: str
    requester: Principal
    request: ActionRequest
    expires_at: float


class ApprovalStore:
    """Holds pending approvals; O(1) create/get/remove, lazy expiry."""

    def __init__(
        self,
        ttl_seconds: float = 900.0,
        max_pending: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initializes the store."""
        self._ttl = ttl_seconds
        self._max = max_pending
        self._clock = clock
        self._items: OrderedDict[str, PendingApproval] = OrderedDict()

    def _purge(self) -> None:
        now = self._clock()
        while self._items:
            oldest = next(iter(self._items.values()))
            if oldest.expires_at > now:
                break
            self._items.popitem(last=False)

    def create(
        self, requester: Principal, request: ActionRequest
    ) -> PendingApproval:
        """Registers a pending approval.

        Raises:
          ApprovalCapacityError: If the pending queue is full.
        """
        self._purge()
        if len(self._items) >= self._max:
            raise ApprovalCapacityError("approval queue full")
        item = PendingApproval(
            uuid.uuid4().hex, requester, request, self._clock() + self._ttl
        )
        self._items[item.approval_id] = item
        return item

    def get(self, approval_id: str) -> PendingApproval:
        """Fetches a pending approval.

        Raises:
          ApprovalExpiredError: If it expired.
          ApprovalNotFoundError: If unknown.
        """
        item = self._items.get(approval_id)
        if item is None:
            raise ApprovalNotFoundError(approval_id)
        if item.expires_at <= self._clock():
            del self._items[approval_id]
            raise ApprovalExpiredError(approval_id)
        return item

    def remove(self, approval_id: str) -> None:
        """Removes a decided approval."""
        self._items.pop(approval_id, None)

    def list_pending(self) -> list[PendingApproval]:
        """Returns live pending approvals, oldest first."""
        self._purge()
        return list(self._items.values())
