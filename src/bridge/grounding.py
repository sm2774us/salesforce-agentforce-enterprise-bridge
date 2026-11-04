"""Data Cloud-style grounding: entity resolution, DMO mapping, vector recall.

Everything is scoped per resolved account so one tenant's incidents never
ground another tenant's agent decisions.
"""

from __future__ import annotations

import collections
import difflib
import heapq
import math
import re
import zlib

from bridge.models import (
    GroundedContext,
    Severity,
    SimilarIncident,
    TelemetryEvent,
    UnifiedEvent,
)
from bridge.pii import redact

_TOKEN = re.compile(r"[a-z0-9]+")
_SUFFIXES = frozenset(
    {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "gmbh"}
)
Vector = dict[int, float]


def normalize_account(name: str) -> str:
    """Lower-cases, strips punctuation and trailing legal suffixes."""
    tokens = _TOKEN.findall(name.lower())
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or name.strip().lower()


class EntityResolver:
    """Maps name variants to one canonical account key (identity resolution)."""

    def __init__(self, cutoff: float = 0.88) -> None:
        """Initializes with a fuzzy-match similarity cutoff."""
        self._cutoff = cutoff
        self._keys: dict[str, None] = {}

    def resolve(self, name: str) -> str:
        """Returns the canonical key, registering new entities."""
        key = normalize_account(name)
        if key in self._keys:
            return key
        close = difflib.get_close_matches(key, self._keys, 1, self._cutoff)
        if close:
            return close[0]
        self._keys[key] = None
        return key


def embed(text: str, dim: int = 512) -> Vector:
    """Signed feature-hashing embedding, L2-normalised, sparse."""
    counts: collections.Counter[int] = collections.Counter()
    for token in _TOKEN.findall(text.lower()):
        h = zlib.crc32(token.encode())
        counts[h % dim] += 1 if (h >> 16) & 1 else -1
    norm = math.sqrt(sum(v * v for v in counts.values()))
    if norm == 0:
        return {}
    return {i: v / norm for i, v in counts.items() if v}


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity of two L2-normalised sparse vectors."""
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(i, 0.0) for i, v in a.items())


class VectorIndex:
    """Bounded in-memory vector index (FIFO eviction)."""

    def __init__(self, capacity: int = 100) -> None:
        """Initializes an empty index."""
        self._capacity = capacity
        self._docs: collections.OrderedDict[str, tuple[Vector, str]] = (
            collections.OrderedDict()
        )

    def add(self, doc_id: str, text: str) -> None:
        """Adds or replaces a document, evicting the oldest if full."""
        self._docs[doc_id] = (embed(text), text)
        self._docs.move_to_end(doc_id)
        while len(self._docs) > self._capacity:
            self._docs.popitem(last=False)

    def search(
        self, text: str, k: int, exclude_id: str, min_score: float
    ) -> list[SimilarIncident]:
        """Top-k documents by cosine similarity (O(n log k))."""
        query = embed(text)
        scored = (
            (cosine(query, vec), doc_id, doc)
            for doc_id, (vec, doc) in self._docs.items()
            if doc_id != exclude_id
        )
        best = heapq.nlargest(
            k, (s for s in scored if s[0] >= min_score), key=lambda s: s[0]
        )
        return [
            SimilarIncident(event_id=i, score=s, message=m) for s, i, m in best
        ]


class GroundingService:
    """Ingests events into the unified model and builds grounded context."""

    def __init__(self, history_per_account: int = 100) -> None:
        """Initializes empty state."""
        self._resolver = EntityResolver()
        self._history_len = history_per_account
        self._history: dict[str, collections.deque[UnifiedEvent]] = {}
        self._indexes: dict[str, VectorIndex] = {}

    def ingest(self, event: TelemetryEvent) -> UnifiedEvent:
        """Maps a raw event to a unified record and indexes it."""
        key = self._resolver.resolve(event.account_name)
        message, _ = redact(event.message)
        unified = UnifiedEvent(
            event_id=event.event_id,
            account_key=key,
            account_name=event.account_name,
            source=event.source,
            severity=event.severity,
            message=message,
            amount_usd=event.amount_usd,
            occurred_at=event.occurred_at,
        )
        self._history.setdefault(
            key, collections.deque(maxlen=self._history_len)
        ).append(unified)
        self._indexes.setdefault(key, VectorIndex(self._history_len)).add(
            unified.event_id, message
        )
        return unified

    def context_for(self, event: UnifiedEvent) -> GroundedContext:
        """Builds account-scoped context for the planner."""
        history = self._history[event.account_key]
        top = max(history, key=lambda e: e.severity.rank).severity
        return GroundedContext(
            account_key=event.account_key,
            event_count=len(history),
            exposure_usd=sum(e.amount_usd for e in history),
            max_severity=Severity(top),
            similar=self._indexes[event.account_key].search(
                event.message, 3, event.event_id, 0.5
            ),
        )
