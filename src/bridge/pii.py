"""PII redaction applied before data reaches prompts, audit or Salesforce."""

from __future__ import annotations

import re
from typing import Any

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,15}\d\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:\+1[ .-])?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")


def _luhn(digits: str) -> bool:
    """Returns True if ``digits`` passes the Luhn checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact(text: str) -> tuple[str, int]:
    """Redacts SSNs, Luhn-valid card numbers, emails and phone numbers.

    Args:
      text: Arbitrary free text.

    Returns:
      A tuple of (redacted text, number of redactions).
    """
    hits = 0

    def labeled(label: str):
        def _sub(_: re.Match[str]) -> str:
            nonlocal hits
            hits += 1
            return f"[REDACTED:{label}]"

        return _sub

    def card(match: re.Match[str]) -> str:
        nonlocal hits
        if not _luhn(re.sub(r"\D", "", match.group(0))):
            return match.group(0)
        hits += 1
        return "[REDACTED:CARD]"

    text = _SSN.sub(labeled("SSN"), text)
    text = _CARD.sub(card, text)
    text = _EMAIL.sub(labeled("EMAIL"), text)
    text = _PHONE.sub(labeled("PHONE"), text)
    return text, hits


def redact_value(value: Any) -> tuple[Any, int]:
    """Recursively redacts strings inside dicts, lists and scalars."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        total = 0
        for k, v in value.items():
            out[k], n = redact_value(v)
            total += n
        return out, total
    if isinstance(value, list):
        items = [redact_value(v) for v in value]
        return [v for v, _ in items], sum(n for _, n in items)
    return value, 0
