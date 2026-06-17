"""Qdrant vector store: search and upsert with optional metadata filters."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import defaultdict
from typing import Any

from core.timing import get_timer

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchAny,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

_QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
_TOP_K_DEFAULT = int(os.getenv("TOP_K", "5"))

_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def point_id(case_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_NS, f"{case_id}:{chunk_index}"))


class SearchResult:
    def __init__(self, payload: dict[str, Any], score: float) -> None:
        self.payload = payload
        self.score = score

    @property
    def text(self) -> str:
        return self.payload.get("text", "")

    @property
    def case_id(self) -> str:
        return self.payload.get("case_id", "")

    @property
    def title(self) -> str:
        return self.payload.get("title", "")

    @property
    def court_name(self) -> str:
        return self.payload.get("court_name", "")

    @property
    def url(self) -> str:
        return self.payload.get("url", "")

    @property
    def date(self) -> str:
        return self.payload.get("date", "")


class VectorStore:
    def __init__(self, collection: str, qdrant_url: str | None = None) -> None:
        self._client = QdrantClient(url=qdrant_url or _QDRANT_URL)
        self._collection = collection

    def ensure_collection(self, dim: int) -> None:
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            for field in ("court", "court_name", "case_id"):
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field,
                    field_schema="keyword",
                )
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name="year",
                field_schema="integer",
            )

    def case_ids_exist(self, case_ids: list[str]) -> set[str]:
        ids = [point_id(cid, 0) for cid in case_ids]
        results = self._client.retrieve(
            collection_name=self._collection,
            ids=ids,
            with_payload=["case_id"],
        )
        return {r.payload["case_id"] for r in results}

    def upsert(self, vectors: list[list[float]], payloads: list[dict[str, Any]]) -> None:
        points = [
            PointStruct(
                id=point_id(p["case_id"], p["chunk_index"]),
                vector=v,
                payload=p,
            )
            for v, p in zip(vectors, payloads)
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def search(
        self,
        query_vector: list[float],
        top_k: int = _TOP_K_DEFAULT,
        courts: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        flags: list[str] | None = None,
    ) -> list[SearchResult]:
        must: list = []
        should: list = []

        if courts:
            must.append(FieldCondition(key="court", match=MatchAny(any=courts)))
        if year_from is not None or year_to is not None:
            must.append(FieldCondition(
                key="year",
                range=Range(
                    gte=year_from if year_from is not None else 1900,
                    lte=year_to if year_to is not None else 2100,
                ),
            ))
        if flags:
            for f in flags:
                should.append(FieldCondition(key="flags", match=MatchValue(value=f)))

        query_filter = Filter(must=must or None, should=should or None) if (must or should) else None

        t0 = time.perf_counter_ns()
        hits = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        ).points
        if timer := get_timer():
            timer.record("qdrant_search", (time.perf_counter_ns() - t0) // 1000,
                         collection=self._collection, top_k=top_k, hits=len(hits))
        return [SearchResult(h.payload, h.score) for h in hits]

    # Patterns that identify amendment/transitional chunk text.
    _AMENDMENT_TEXT_RE = re.compile(
        r"amendments? made by section"
        r"|as inserted by section \d+"
        r"|as amended by section \d+"
        r"|does not apply to (an increase|any|whether)",
        re.IGNORECASE,
    )

    # Patterns in a section TITLE that mark it as non-operative.
    _TRANSITIONAL_TITLE_RE = re.compile(
        r"\b(application|savings|transitional|commencement|repeal|covid|inserted)\b",
        re.IGNORECASE,
    )

    def _is_amendment_chunk(self, payload: dict) -> bool:
        text = payload.get("text", "")[:400]
        return bool(self._AMENDMENT_TEXT_RE.search(text))

    def _is_transitional_title(self, title: str) -> bool:
        return bool(self._TRANSITIONAL_TITLE_RE.search(title))

    def fetch_by_case_id(self, case_id: str) -> "SearchResult | None":
        """Return the best chunk for a case_id: correct operative section, lowest chunk_index.

        The nz_legal Qdrant collection has two corruption patterns:
        (a) Long sections are split into overlapping 120-word windows. limit=1 scroll
            returns a random window, usually not the section opening.
        (b) Historical or amendment-act provisions share a section number with the
            current operative rule (case_id collision from the legislation scraper).
            E.g. NZLEG/RTA/s40 contains both "Remuneration of Principal Tenancy
            Adjudicator" (old section) and "Tenant's responsibilities" (current).

        Resolution strategy:
        1. Fetch all chunks (limit=64), sort by chunk_index ascending.
        2. Group by title. Discard groups whose title looks transitional/amendment.
        3. Among remaining groups, prefer the one with the most chunks (the longer
           operative section was split into more windows; the wrong/old section is short).
        4. Within the winning group, skip chunks whose text starts with amendment language.
        5. Return the first (lowest chunk_index) operative chunk.
        """
        t0 = time.perf_counter_ns()
        results, _ = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(must=[FieldCondition(key="case_id", match=MatchValue(value=case_id))]),
            limit=64,
            with_payload=True,
            with_vectors=False,
        )
        if timer := get_timer():
            timer.record("qdrant_fetch", (time.perf_counter_ns() - t0) // 1000,
                         collection=self._collection, case_id=case_id, found=bool(results))
        if not results:
            return None

        # Sort by chunk_index so the section opening comes first within each group.
        results.sort(key=lambda p: p.payload.get("chunk_index", 0))

        # Group chunks by their section title.
        by_title: dict[str, list] = defaultdict(list)
        for r in results:
            by_title[r.payload.get("title", "")].append(r)

        # Discard title groups that look like transitional/amendment provisions.
        operative_groups = [
            (title, chunks)
            for title, chunks in by_title.items()
            if not self._is_transitional_title(title)
        ]

        # If everything looks transitional, fall back to all groups.
        if not operative_groups:
            operative_groups = list(by_title.items())

        # Prefer the group with the most chunks (longer = more likely to be the
        # current operative section; historical sections tend to be short).
        operative_groups.sort(key=lambda x: len(x[1]), reverse=True)
        _title, best_chunks = operative_groups[0]

        # Within the winning group, skip chunks with amendment text in the body.
        clean = [r for r in best_chunks if not self._is_amendment_chunk(r.payload)]
        chosen = (clean or best_chunks)[0]
        return SearchResult(chosen.payload, 1.0)

    @property
    def client(self) -> QdrantClient:
        return self._client

    @property
    def collection_name(self) -> str:
        return self._collection

    def search_filtered(
        self,
        query_vector: list[float],
        query_filter: "Filter",
        top_k: int = _TOP_K_DEFAULT,
    ) -> list[SearchResult]:
        t0 = time.perf_counter_ns()
        hits = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        ).points
        if timer := get_timer():
            timer.record("qdrant_search_filtered", (time.perf_counter_ns() - t0) // 1000,
                         collection=self._collection, top_k=top_k, hits=len(hits))
        return [SearchResult(h.payload, h.score) for h in hits]

    def scroll_filtered(
        self,
        query_filter,
        limit: int = 200,
    ) -> list[SearchResult]:
        raw, _ = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [SearchResult(r.payload, 1.0) for r in raw]

    def search_within(
        self,
        query_vector: list[float],
        point_ids: list[str],
        top_k: int = _TOP_K_DEFAULT,
    ) -> list[SearchResult]:
        if not point_ids:
            return []
        hits = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=top_k,
            query_filter=Filter(must=[HasIdCondition(has_id=point_ids)]),
            with_payload=True,
        ).points
        return [SearchResult(h.payload, h.score) for h in hits]
