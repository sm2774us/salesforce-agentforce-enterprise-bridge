"""Metadata-driven Agentforce Action registry."""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from bridge.salesforce import SalesforceGateway, soql_quote

Handler = Callable[[Any], Awaitable[dict[str, Any]]]


class RiskTier(str, enum.Enum):
    """Risk tier; HIGH requires human approval."""

    LOW = "low"
    HIGH = "high"


class UnknownActionError(KeyError):
    """The requested action is not registered."""


class CreateCaseParams(BaseModel):
    """Parameters for ``create_case``."""

    account_name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=32000)
    priority: Literal["Low", "Medium", "High"] = "Medium"


class EscalateCaseParams(BaseModel):
    """Parameters for ``escalate_case``."""

    case_id: str = Field(pattern=r"^[A-Za-z0-9]{15,18}$")
    reason: str = Field(min_length=1, max_length=2000)


class FinancialReviewParams(BaseModel):
    """Parameters for ``create_financial_review``."""

    account_name: str = Field(min_length=1, max_length=255)
    amount_usd: float = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True)
class ActionDefinition:
    """One invocable action and its governance metadata."""

    name: str
    description: str
    params_model: type[BaseModel]
    permission: str
    risk: RiskTier
    handler: Handler

    def manifest(self) -> dict[str, Any]:
        """Returns the Agentforce-facing description of this action."""
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk.value,
            "permission": self.permission,
            "requiresApproval": self.risk is RiskTier.HIGH,
            "inputSchema": self.params_model.model_json_schema(),
        }


class ActionRegistry:
    """Name-indexed collection of action definitions."""

    def __init__(self) -> None:
        """Creates an empty registry."""
        self._defs: dict[str, ActionDefinition] = {}

    def register(self, definition: ActionDefinition) -> None:
        """Adds a definition.

        Raises:
          ValueError: If the name is already registered.
        """
        if definition.name in self._defs:
            raise ValueError(f"duplicate action: {definition.name}")
        self._defs[definition.name] = definition

    def get(self, name: str) -> ActionDefinition:
        """Returns a definition or raises UnknownActionError."""
        try:
            return self._defs[name]
        except KeyError:
            raise UnknownActionError(name) from None

    def names(self) -> list[str]:
        """Returns sorted action names."""
        return sorted(self._defs)

    def manifest(self) -> list[dict[str, Any]]:
        """Returns the sorted action catalog."""
        return [self._defs[n].manifest() for n in self.names()]


async def _account_id(sf: SalesforceGateway, name: str) -> str | None:
    rows = await sf.query(
        f"SELECT Id FROM Account WHERE Name = {soql_quote(name)} LIMIT 1"
    )
    return rows[0]["Id"] if rows else None


def build_default_registry(sf: SalesforceGateway) -> ActionRegistry:
    """Builds the registry of Salesforce-backed actions."""

    async def _new_case(
        account_name: str, subject: str, description: str, priority: str
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "Subject": subject,
            "Description": description,
            "Priority": priority,
            "Origin": "Web",
        }
        account_id = await _account_id(sf, account_name)
        if account_id:
            fields["AccountId"] = account_id
        return {
            "case_id": await sf.create_record("Case", fields),
            "account_linked": account_id is not None,
        }

    async def create_case(p: CreateCaseParams) -> dict[str, Any]:
        return await _new_case(
            p.account_name, p.subject, p.description, p.priority
        )

    async def escalate_case(p: EscalateCaseParams) -> dict[str, Any]:
        await sf.update_record(
            "Case",
            p.case_id,
            {"Status": "Escalated", "Priority": "High"},
        )
        return {"case_id": p.case_id, "status": "Escalated"}

    async def financial_review(p: FinancialReviewParams) -> dict[str, Any]:
        return await _new_case(
            p.account_name,
            f"Financial review: ${p.amount_usd:,.2f}",
            p.reason,
            "High",
        )

    registry = ActionRegistry()
    for definition in (
        ActionDefinition(
            "create_case",
            "Open a Salesforce Case for an operational incident.",
            CreateCaseParams,
            "action:create_case",
            RiskTier.LOW,
            create_case,
        ),
        ActionDefinition(
            "escalate_case",
            "Escalate an existing Case to Escalated/High.",
            EscalateCaseParams,
            "action:escalate_case",
            RiskTier.HIGH,
            escalate_case,
        ),
        ActionDefinition(
            "create_financial_review",
            "Open a High-priority Case for a financial discrepancy.",
            FinancialReviewParams,
            "action:create_financial_review",
            RiskTier.HIGH,
            financial_review,
        ),
    ):
        registry.register(definition)
    return registry
