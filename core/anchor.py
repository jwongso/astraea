from __future__ import annotations

import asyncio
import logging
import os

from core.jurisdiction import JurisdictionBase
from core.pipeline import RAGPipeline
from core.retriever import VectorStore
from core.routing import allow_section, build_route_decision, normalize_query

_ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "true").lower() not in ("0", "false", "no")

# Cross-encoder relevance gate for legislation retrieval.
# Loaded lazily at first scored query; None when ENABLE_RERANKER=false.
_reranker = None

# Cache for synthetic query embeddings.
# Route synthetic_query strings are fixed at startup - computing them once eliminates
# per-request embed calls that add 1-2s latency each.
_synth_vector_cache: dict[str, list[float]] = {}


def _get_reranker():
    global _reranker
    if not _ENABLE_RERANKER:
        return None
    if _reranker is None:
        from core.reranker import CrossEncoderReranker
        _reranker = CrossEncoderReranker()
    return _reranker


def _is_leg_chunk(case_id: str) -> bool:
    return "LEG" in case_id.upper().split("/")[0] if "/" in case_id else False


async def _federated_leg_search(
    vector: list[float],
    leg_store: VectorStore,
    leg_sources: list,
    boosted_act_ids: set[str],
) -> list:
    """Run one Qdrant search per registered Act in parallel.

    Each Act gets its own top_k quota so smaller Acts are not crowded out
    by larger ones in a single global search.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    async def _search_one(src):
        top_k = src.boost_top_k if src.act_id in boosted_act_ids else src.default_top_k
        filt = Filter(must=[FieldCondition(key="court_name", match=MatchValue(value=src.court_name))])
        return await asyncio.to_thread(leg_store.search_filtered, vector, filt, top_k)

    batches = await asyncio.gather(*[_search_one(s) for s in leg_sources])
    return [r for batch in batches for r in batch]


async def _retrieve_anchor(
    question: str,
    original_question: str,
    pipeline: RAGPipeline,
    leg_store: VectorStore,
    jurisdiction: JurisdictionBase,
) -> tuple[str, list[dict], list[dict]]:
    """Retrieve legislation sections as anchor context.

    Uses federated per-Act search when the jurisdiction registers leg_sources,
    otherwise falls back to a single global legislation search. Route-forced
    sections are always included as hard floor guarantees regardless of scores.

    Returns (anchor_text_from_vstore, leg_sources, ce_gate_log).
    ce_gate_log contains one entry per candidate: case_id, ce_score, forced, kept.
    Empty list when ENABLE_RERANKER=false.
    """
    if leg_store is None:
        return "", [], []
    try:
        _ce_log: list[dict] = []
        # Build route decision before embedding - keyword matching, no network call
        decision = build_route_decision(
            original_question or question, question, jurisdiction.routes
        )

        vector = await pipeline._embedder.embed(question)

        # Federated search: one search per registered Act with per-source top_k quotas.
        # Falls back to single global search for jurisdictions without leg_sources.
        leg_srcs = jurisdiction.leg_sources
        if leg_srcs:
            raw = await _federated_leg_search(vector, leg_store, leg_srcs, decision.boosted_act_ids)
        else:
            raw = leg_store.search(vector, top_k=12)

        # Route injection - floor guarantee: forced sections always reach the candidate pool.
        # Synthetic query embeddings are cached; strings are fixed at startup so cost is
        # paid once per unique query string, not per request.
        injected_ids: list[str] = []
        injections: list = []
        seen_inject: set[str] = set()
        forced_sections_set = set(decision.forced_sections)
        leg_courts = list({
            sid.split("/")[0] for sid in decision.forced_sections
            if "/" in sid and "LEG" in sid.split("/")[0].upper()
        })
        for synth_q in decision.leg_synthetic_queries:
            if synth_q not in _synth_vector_cache:
                _synth_vector_cache[synth_q] = await pipeline._embedder.embed(synth_q)
            synth_vector = _synth_vector_cache[synth_q]
            synth_raw = leg_store.search(
                synth_vector,
                top_k=len(decision.forced_sections) + 10,
                courts=leg_courts or None,
            )
            existing_ids = {h.case_id for h in raw}
            for h in synth_raw:
                if h.case_id in forced_sections_set and h.case_id not in seen_inject:
                    if h.case_id in existing_ids:
                        raw = [x for x in raw if x.case_id != h.case_id]
                    injections.append(h)
                    seen_inject.add(h.case_id)
                    injected_ids.append(h.case_id)
        for sid in decision.forced_sections:
            if sid not in seen_inject:
                h = leg_store.fetch_by_case_id(sid)
                if h:
                    raw = [x for x in raw if x.case_id != h.case_id]
                    injections.append(h)
                    seen_inject.add(sid)
                    injected_ids.append(sid)
        raw = injections + raw

        combined_q = normalize_query((original_question or question) + " " + question)
        lp = jurisdiction.low_priority_sections
        raw = [h for h in raw if allow_section(h.case_id, combined_q, lp)]

        if decision.leg_allow_list:
            allow_set = set(decision.leg_allow_list)
            raw = [h for h in raw if not _is_leg_chunk(h.case_id) or h.case_id in allow_set]

        # Keep only legislation chunks - prevent case decisions from the same
        # collection leaking into leg_sources (e.g. nz_legal has both).
        raw = [h for h in raw if _is_leg_chunk(h.case_id)]

        # Cross-encoder relevance gate: drop sections that are semantically
        # irrelevant to the query. Runs after structural filters to minimise the
        # candidate set the CE model sees. Route-forced sections always pass.
        reranker = _get_reranker()
        if reranker is not None:
            try:
                raw, _ce_log = await asyncio.to_thread(
                    reranker.score_and_filter,
                    question,
                    raw,
                    jurisdiction.leg_ce_min_score,
                    set(injected_ids),
                )
                if _ce_log:
                    logging.getLogger(__name__).debug("ce_gate %s", _ce_log)
            except Exception as exc:
                logging.getLogger(__name__).warning("ce_gate error: %s", exc)

        seen: set[str] = set()
        hits = []
        max_hits = max(3, len(injected_ids)) if injected_ids else 2
        for h in raw:
            if h.case_id not in seen:
                seen.add(h.case_id)
                hits.append(h)
            if len(hits) >= max_hits:
                break

        if not hits:
            return "", [], []

        lines = [
            "Relevant Act sections "
            "(legislative context - use for grounding section numbers only, "
            "do not cite with [SN] notation):"
        ]
        for h in hits:
            lines.append(f"\n{h.title}\n{h.text[:600]}")

        leg_sources_out = [
            {"case_id": h.case_id, "title": h.title, "url": h.url}
            for h in hits
        ]
        return "\n".join(lines), leg_sources_out, _ce_log
    except Exception:
        return "", [], []


async def _augment_case_retrieval(
    question: str,
    retrieval_question: str,
    pipeline: "RAGPipeline",
    jurisdiction: "JurisdictionBase",
    context_texts: list[str],
    sources: list[dict],
) -> tuple[list[str], list[dict]]:
    """Run supplementary case retrieval for any matched route with case_synthetic_query."""
    decision = build_route_decision(question, retrieval_question, jurisdiction.routes)
    if not decision.case_synthetic_queries:
        return context_texts, sources
    existing_ids = {s["case_id"] for s in sources}
    for csq in decision.case_synthetic_queries:
        extra_texts, extra_sources = await pipeline.retrieve(
            csq, top_k=5, strategy="vector", min_score=0.70, min_chunks=1,
        )
        for txt, src in zip(extra_texts, extra_sources):
            if src["case_id"] not in existing_ids and len(sources) < 8:
                context_texts.append(txt)
                sources.append(src)
                existing_ids.add(src["case_id"])
    return context_texts, sources


def _dedupe_queries(original: str, rewritten: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for q in (original, rewritten):
        norm = " ".join(q.lower().split())
        if norm not in seen:
            seen.add(norm)
            result.append(q)
    return result


async def _refine_retrieve(
    original_question: str,
    rewritten_question: str,
    pipeline: "RAGPipeline",
    existing_sources: list[dict],
    existing_texts: list[str],
) -> tuple[list[str], list[dict]]:
    """Second retrieval pass when initial confidence is low.

    Uses the original (non-rewritten) question with relaxed parameters so that
    context the rewriter dropped has a chance to surface.
    """
    existing_ids = {s["case_id"] for s in existing_sources}

    new_texts: list[str] = []
    new_sources: list[dict] = []

    for query in _dedupe_queries(original_question, rewritten_question):
        extra_texts, extra_sources = await pipeline.retrieve(
            query, top_k=8, strategy="vector", min_score=0.65, min_chunks=1,
        )
        for txt, src in zip(extra_texts, extra_sources):
            if src["case_id"] not in existing_ids:
                new_texts.append(txt)
                new_sources.append(src)
                existing_ids.add(src["case_id"])

    combined_texts = existing_texts + new_texts
    combined_sources = existing_sources + new_sources
    # Re-sort by score, keep at most 6
    paired = sorted(
        zip(combined_sources, combined_texts),
        key=lambda x: x[0].get("_score", 0.0),
        reverse=True,
    )
    paired = paired[:6]
    if not paired:
        return existing_texts, existing_sources
    out_sources, out_texts = zip(*paired)
    return list(out_texts), list(out_sources)
