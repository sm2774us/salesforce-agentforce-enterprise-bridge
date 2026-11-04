"""Realistic sample telemetry used by the demo, benchmark and docs."""

from typing import Any

ACCOUNTS = ("Acme Corporation", "Globex Ltd", "Initech")

SAMPLE_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "source": "payments",
        "account_name": "Acme Corporation",
        "severity": "critical",
        "message": "Gateway outage: jane.doe@example.com card "
        "4111 1111 1111 1111 declined repeatedly",
    },
    {
        "source": "erp",
        "account_name": "Globex Ltd",
        "severity": "high",
        "message": "Invoice reconciliation mismatch between ERP and billing",
        "amount_usd": 25000.0,
    },
    {
        "source": "payments",
        "account_name": "ACME Corp.",
        "severity": "high",
        "message": "Gateway outage persists; card declines continue",
    },
    {
        "source": "heartbeat",
        "account_name": "Initech",
        "severity": "low",
        "message": "Heartbeat ok",
    },
    {
        "source": "telemetry",
        "account_name": "Initech",
        "severity": "medium",
        "message": "p95 latency above SLO; call +1 415-555-0100",
    },
    {
        "source": "erp",
        "account_name": "Globex Ltd",
        "severity": "medium",
        "message": "Invoice reconciliation mismatch between ERP and billing",
    },
)
