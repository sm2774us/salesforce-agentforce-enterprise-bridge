"""Role-based access control policy."""

from __future__ import annotations

from collections.abc import Mapping

from bridge.models import Role

DEFAULT_GRANTS: Mapping[Role, frozenset[str]] = {
    Role.VIEWER: frozenset({"events:read"}),
    Role.AGENT: frozenset(
        {
            "events:write",
            "events:read",
            "action:create_case",
            "action:escalate_case",
            "action:create_financial_review",
        }
    ),
    Role.APPROVER: frozenset({"events:read", "approvals:decide"}),
    Role.ADMIN: frozenset({"*"}),
}


class RbacPolicy:
    """Maps roles to permission strings (``*`` grants everything)."""

    def __init__(self, grants: Mapping[Role, frozenset[str]] | None = None):
        """Initializes with explicit grants or the defaults."""
        self._grants = grants or DEFAULT_GRANTS

    def allows(self, role: Role, permission: str) -> bool:
        """Returns True if ``role`` holds ``permission``."""
        granted = self._grants.get(role, frozenset())
        return "*" in granted or permission in granted
