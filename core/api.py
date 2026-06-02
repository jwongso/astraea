"""create_app() factory - turns a JurisdictionBase into a working FastAPI app.

Environment variables (all optional with defaults):
  LLM_BASE_URL      LLM endpoint (default: http://localhost:8080/v1)
  LLM_MODEL         model name (default: qwen3)
  QDRANT_URL        Qdrant endpoint (default: http://localhost:6333)
  REDIS_URL         Redis for web-verify cache (default: redis://127.0.0.1:6379/0)
  PUBLIC_TOKEN      token required in X-API-Key header (default: no auth)
  DEBUG_KEY         unlocks /ask/stream debug mode
  ALLOWED_ORIGIN    CORS origin (default: *)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.browser import BrowserSession
from core.feedback import write_feedback, write_feedback_full
from core.jurisdiction import JurisdictionBase
from core.legislation import LegislationCache, extract_section_refs
from core.pipeline import RAGPipeline
from core.queue import (
    _AVG_QUERY_SECONDS,
    acquire, get_client_ip, global_llm_acquire, global_llm_release,
    global_llm_will_wait, LLM_GLOBAL_CONCURRENCY,
    queue_status, queue_wait_estimate, release, will_wait,
)
from core.retriever import VectorStore
from core.routing import (
    allow_section, get_dominant_leg_allow_list, match_routes, normalize_query,
)
from core.sanitize import sanitize_question
from core.security import BodySizeLimitMiddleware, SecurityHeadersMiddleware

_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")
_LLM_MODEL = os.getenv("LLM_MODEL", "qwen3")
_REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
_ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "true").lower() not in ("0", "false", "no")

# Module-level cross-encoder reranker (log-only in Phase 1).
# Loaded lazily at first scored query; None when ENABLE_RERANKER=false.
_reranker = None


def _get_reranker():
    global _reranker
    if not _ENABLE_RERANKER:
        return None
    if _reranker is None:
        from core.reranker import CrossEncoderReranker
        _reranker = CrossEncoderReranker(log_only=True)
    return _reranker


# Cache for synthetic query embeddings.
# Route synthetic_query strings are fixed at startup - computing them once eliminates
# per-request embed calls that add 1-2s latency each.
_synth_vector_cache: dict[str, list[float]] = {}
_PUBLIC_TOKEN = os.getenv("PUBLIC_TOKEN", "")
_DEBUG_KEY = os.getenv("DEBUG_KEY", "")
_ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")
_WEB_CACHE_TTL = 604800
_WEB_CACHE_PREFIX = "astraea:web_verify:"
_SESSION_PREFIX = "astraea:session"
_SESSION_TTL = 7 * 24 * 3600   # 7-day sliding window
_SESSION_MAX_TURNS = 10         # stored per UUID
_SESSION_INJECT_TURNS = 3       # injected into each prompt
_SESSION_ANSWER_CAP = 400       # chars stored per answer
_SESSION_ID_RE = re.compile(r"^[0-9a-f\-]{32,36}$")
_VALID_STRATEGIES = {"vector", "mmr"}

_REWRITE_SYSTEM_DEFAULT = (
    "Rewrite the following as a concise formal legal question optimised for retrieving relevant case decisions. "
    "Focus on the underlying legal dispute, facts, and claims (e.g. what damage is alleged, what the landlord or tenant is claiming, what the legal issue is). "
    "If the question includes procedural sub-questions about the tribunal process (wait times, hearing format, evidence deadlines), ignore those entirely - they are not useful for case retrieval. "
    "Output only the rewritten question, no explanation, no preamble."
)


def _check_token(request: Request) -> None:
    if not _PUBLIC_TOKEN:
        return
    if request.headers.get("X-API-Key") != _PUBLIC_TOKEN:
        raise HTTPException(status_code=401, detail={"error": "Invalid or missing API token."})


async def _check_llm() -> None:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{_LLM_BASE_URL}/models")
            if r.status_code != 200:
                raise Exception()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"error": "The AI model is currently loading. Please try again in 30 seconds."},
        )


def _strip_context_prefixes(question: str) -> str:
    """Remove leading [Key: value] context lines added by preprocess_question.

    Zone prefixes like '[Zone context: ...]' must not reach the rewriter - they
    bias vector retrieval toward planning/RMA sections instead of building law.
    The full prefixed question is still sent to the LLM for generation.
    """
    return re.sub(r"^(\[[^\]]+\]\s*\n+)+", "", question)


async def _rewrite_query(question: str, system_prompt: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{_LLM_BASE_URL}/chat/completions",
                json={
                    "model": _LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    "max_tokens": 100,
                    "temperature": 0.0,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            r.raise_for_status()
            rewritten = r.json()["choices"][0]["message"]["content"].strip()
            return rewritten if rewritten else question
    except Exception:
        return question


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
) -> tuple[str, list[dict]]:
    """Retrieve legislation sections as anchor context.

    Uses federated per-Act search when the jurisdiction registers leg_sources,
    otherwise falls back to a single global legislation search. Route-forced
    sections are always included as hard floor guarantees regardless of scores.

    Returns (anchor_text_from_vstore, leg_sources).
    """
    if leg_store is None:
        return "", []
    try:
        # Match routes before embedding - keyword matching, no network call
        matched = match_routes(original_question or question, question, jurisdiction.routes)

        vector = await pipeline._embedder.embed(question)

        # Federated search: one search per registered Act with per-source top_k quotas.
        # Falls back to single global search for jurisdictions without leg_sources.
        leg_srcs = jurisdiction.leg_sources
        if leg_srcs:
            boosted_act_ids: set[str] = set()
            for route in matched:
                for sid in route.forced_sections:
                    parts = sid.split("/")
                    if len(parts) >= 2:
                        boosted_act_ids.add(parts[1])
            raw = await _federated_leg_search(vector, leg_store, leg_srcs, boosted_act_ids)
        else:
            raw = leg_store.search(vector, top_k=12)

        # Route injection - floor guarantee: forced sections always reach the candidate pool.
        # The re-ranker (future Phase 2) may reorder within the pool but cannot drop these.
        injected_ids: list[str] = []
        injections: list = []
        seen_inject: set[str] = set()
        for route in matched:
            # Synth-vector embeddings are cached across requests because route.synthetic_query
            # is a fixed string that never changes after startup.
            if route.synthetic_query not in _synth_vector_cache:
                _synth_vector_cache[route.synthetic_query] = await pipeline._embedder.embed(route.synthetic_query)
            synth_vector = _synth_vector_cache[route.synthetic_query]
            leg_courts = list({
                sid.split("/")[0] for sid in route.forced_sections
                if "/" in sid and "LEG" in sid.split("/")[0].upper()
            })
            synth_raw = leg_store.search(
                synth_vector,
                top_k=len(route.forced_sections) + 10,
                courts=leg_courts or None,
            )
            existing_ids = {h.case_id for h in raw}
            for h in synth_raw:
                if h.case_id in route.forced_sections and h.case_id not in seen_inject:
                    if h.case_id in existing_ids:
                        raw = [x for x in raw if x.case_id != h.case_id]
                    injections.append(h)
                    seen_inject.add(h.case_id)
                    injected_ids.append(h.case_id)
            for sid in route.forced_sections:
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

        dominant_allow = get_dominant_leg_allow_list(matched)
        if dominant_allow:
            allow_set = set(dominant_allow)
            raw = [h for h in raw if not _is_leg_chunk(h.case_id) or h.case_id in allow_set]

        # Keep only legislation chunks - prevent case decisions from the same
        # collection leaking into leg_sources (e.g. nz_legal has both).
        raw = [h for h in raw if _is_leg_chunk(h.case_id)]

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
            return "", []

        # Phase 1 - log cross-encoder scores for observability without affecting ranking.
        # Compare these logs against route-based order to decide if/when to promote CE to ranking.
        reranker = _get_reranker()
        ce_log: list[dict] = []
        if reranker is not None:
            try:
                scored = await asyncio.to_thread(reranker.score, question, hits)
                ce_log = [
                    {"case_id": h.case_id, "ce_score": round(float(s), 4), "route_rank": i}
                    for i, (h, s) in enumerate(scored)
                ]
                if ce_log:
                    logging.getLogger(__name__).debug(
                        "reranker_log federated=%s %s",
                        bool(leg_srcs),
                        ce_log,
                    )
            except Exception as exc:
                logging.getLogger(__name__).warning("reranker score failed: %s", exc)

        lines = [
            "Relevant Act sections "
            "(legislative context - use for grounding section numbers only, "
            "do not cite with [SN] notation):"
        ]
        for h in hits:
            lines.append(f"\n{h.title}\n{h.text[:600]}")

        leg_sources = [
            {"case_id": h.case_id, "title": h.title, "url": h.url}
            for h in hits
        ]
        return "\n".join(lines), leg_sources
    except Exception:
        return "", []


def _is_leg_chunk(case_id: str) -> bool:
    return "LEG" in case_id.upper().split("/")[0] if "/" in case_id else False


def _web_cache_key(leg_sources: list[dict], fallback: str, prefix: str) -> str:
    ids = sorted({s.get("case_id", "") for s in leg_sources if s.get("case_id")})
    slug = "|".join(ids) if ids else fallback[:80].lower().strip()
    return f"{prefix}{slug}"


async def _web_verify(
    question: str,
    leg_sources: list[dict],
    browser: BrowserSession,
    redis: aioredis.Redis | None,
    jurisdiction: JurisdictionBase,
    alwaysonline: bool = False,
) -> tuple[str, list[dict], bool]:
    if not jurisdiction.web_verify or browser is None:
        return "", [], False

    wv = jurisdiction.web_verify
    cache_key = _web_cache_key(leg_sources, question, _WEB_CACHE_PREFIX + jurisdiction.name + ":")

    if not alwaysonline and redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                payload = json.loads(cached)
                return payload["text"], payload["results"], True
        except Exception:
            pass

    query = f"{wv.search_prefix} {question[:120]}"
    try:
        results = await asyncio.wait_for(
            browser.search_ddg(query, max_results=wv.max_results),
            timeout=20,
        )
    except Exception as exc:
        logging.warning("_web_verify failed: %s", exc)
        return "", [], False

    if not results:
        return "", [], False

    lines = ["Current online sources (use to verify recent law changes):"]
    for r in results:
        lines.append(f"- {r['title']} | {r['url']}\n  {r['body']}")
    text = "\n".join(lines)

    if redis is not None:
        try:
            payload = json.dumps({"text": text, "results": results, "query": query})
            await redis.setex(cache_key, wv.cache_ttl_seconds, payload)
        except Exception:
            pass

    return text, results, False


async def _verify_sections(
    answer: str,
    leg_sources: list[dict],
    leg_cache: LegislationCache,
    jurisdiction: JurisdictionBase,
) -> list[dict]:
    if not jurisdiction.legislation:
        return []

    leg_refs: list[str] = []
    seen: set[str] = set()
    for s in leg_sources:
        m = re.search(r"/s?(\d+[A-Z]?)$", s.get("case_id", ""), re.IGNORECASE)
        if m:
            key = m.group(1).upper()
            if key not in seen:
                seen.add(key)
                leg_refs.append(m.group(1))
    for ref in extract_section_refs(answer):
        if ref.upper() not in seen:
            seen.add(ref.upper())
            leg_refs.append(ref)

    first_act_id = next(iter(jurisdiction.legislation.acts), None)
    if not first_act_id:
        return []
    first_act_url = jurisdiction.legislation.acts[first_act_id]

    full_text = leg_cache.get(first_act_id, jurisdiction.legislation.cache_ttl_seconds)
    if not full_text:
        return []

    results = []
    for ref in leg_refs[:4]:
        excerpt = leg_cache.extract_section(first_act_id, ref, full_text, jurisdiction)
        if excerpt:
            results.append({"reference": f"s{re.sub(r'^[sS]', '', ref)}", "excerpt": excerpt, "url": first_act_url})
    return results


async def _augment_case_retrieval(
    question: str,
    retrieval_question: str,
    pipeline: "RAGPipeline",
    jurisdiction: "JurisdictionBase",
    context_texts: list[str],
    sources: list[dict],
) -> tuple[list[str], list[dict]]:
    """Run supplementary case retrieval for any matched route with case_synthetic_query."""
    matched = match_routes(question, retrieval_question, jurisdiction.routes)
    synth_queries = [r.case_synthetic_query for r in matched if r.case_synthetic_query]
    if not synth_queries:
        return context_texts, sources
    existing_ids = {s["case_id"] for s in sources}
    for csq in synth_queries:
        extra_texts, extra_sources = await pipeline.retrieve(
            csq, top_k=5, strategy="vector", min_score=0.70, min_chunks=1,
        )
        for txt, src in zip(extra_texts, extra_sources):
            if src["case_id"] not in existing_ids and len(sources) < 8:
                context_texts.append(txt)
                sources.append(src)
                existing_ids.add(src["case_id"])
    return context_texts, sources


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


def _dedupe_queries(original: str, rewritten: str) -> list[str]:
    """Return queries to try in the retry pass, deduplicating if identical."""
    seen: set[str] = set()
    result: list[str] = []
    for q in (original, rewritten):
        norm = " ".join(q.lower().split())
        if norm not in seen:
            seen.add(norm)
            result.append(q)
    return result


async def _load_session(
    redis: "aioredis.Redis | None",
    jurisdiction_name: str,
    session_id: str,
) -> list[dict]:
    """Return the last _SESSION_INJECT_TURNS turns for this session, refreshing TTL."""
    if not redis or not session_id or not _SESSION_ID_RE.match(session_id):
        return []
    key = f"{_SESSION_PREFIX}:{jurisdiction_name}:{session_id}"
    try:
        raw = await redis.get(key)
        if not raw:
            return []
        await redis.expire(key, _SESSION_TTL)
        return json.loads(raw)[-_SESSION_INJECT_TURNS:]
    except Exception:
        return []


async def _save_session(
    redis: "aioredis.Redis | None",
    jurisdiction_name: str,
    session_id: str,
    question: str,
    answer: str,
) -> None:
    """Append a Q&A turn and persist with a sliding 7-day TTL."""
    if not redis or not session_id or not _SESSION_ID_RE.match(session_id):
        return
    key = f"{_SESSION_PREFIX}:{jurisdiction_name}:{session_id}"
    try:
        raw = await redis.get(key)
        turns = json.loads(raw) if raw else []
        turns.append({"q": question, "a": answer[:_SESSION_ANSWER_CAP], "ts": time.time()})
        turns = turns[-_SESSION_MAX_TURNS:]
        await redis.setex(key, _SESSION_TTL, json.dumps(turns))
    except Exception:
        pass


def _format_session_context(turns: list[dict]) -> str:
    """Format prior Q&A turns as a block prepended to the legislation anchor."""
    if not turns:
        return ""
    lines = ["Recent conversation (use only if directly relevant to the current question):"]
    for t in turns:
        a = t["a"]
        if len(a) >= _SESSION_ANSWER_CAP:
            a += "..."
        lines.append(f"\nQ: {t['q']}\nA: {a}")
    return "\n".join(lines)


def _confidence(scores: list[float], cfg=None) -> dict:
    from core.jurisdiction import ConfidenceConfig
    if cfg is None:
        cfg = ConfidenceConfig()
    n = len(scores)
    if n == 0:
        return {"level": "low", "chunks": 0, "message": cfg.messages.get("none", "No relevant sources found.")}
    top = max(scores)
    level = "high" if top >= cfg.high_score and n >= cfg.high_n else "medium" if top >= cfg.medium_score and n >= cfg.medium_n else "low"
    msg = cfg.messages.get(level, "").format(n=n)
    return {"level": level, "chunks": n, "message": msg}


class AskRequest(BaseModel):
    question: str
    session_id: str = ""
    debug_key: str = ""
    strategy: str = "vector"
    irac: bool = False
    verify: bool = True
    alwaysonline: bool = False
    address: str | None = None  # optional: geocoded to inject zone context via preprocess_question
    feedback_context: bool = False  # always emit context_debug for feedback capture (no debug_key required)


class RetrieveRequest(BaseModel):
    question: str
    strategy: str = "vector"
    address: str | None = None


class FeedbackRequest(BaseModel):
    question: str
    rating: int
    comment: str = ""


class FeedbackFullRequest(BaseModel):
    question: str
    rating: int
    comment: str = ""
    strategy: str = ""
    irac: bool = False
    think: bool = False
    debug_mode: bool = False
    ts_start: str = ""
    ts_end: str = ""
    user_agent: str = ""
    answer: str = ""
    sources: list = []
    legislation: list = []
    confidence: dict | None = None
    web_results: dict | None = None
    verification: list | None = None
    debug: dict | None = None
    debug_timing: dict | None = None
    context_debug: dict | None = None


def create_app(
    jurisdiction: JurisdictionBase,
    pipeline_factory: type | None = None,
    static_dir: "Path | str | None" = None,
) -> FastAPI:
    """Return a fully configured FastAPI app for this jurisdiction.

    pipeline_factory: optional RAGPipeline subclass to instantiate instead of the default.
                      Must accept (collection, system_prompt, courts) keyword args.
    static_dir:       explicit path to a static files directory. Falls back to
                      jurisdictions/<name>/static/ inside the astraea package tree.
    """
    _default_static = (
        Path(__file__).parent.parent / "jurisdictions" / jurisdiction.name.replace("-", "_") / "static"
    )
    _static_dir = Path(static_dir) if static_dir is not None else _default_static

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        corpus = jurisdiction.corpus
        factory = pipeline_factory or RAGPipeline
        pipeline = factory(
            collection=corpus.qdrant_collection,
            system_prompt=jurisdiction.system_prompt,
            courts=corpus.courts or None,
        )
        leg_store = VectorStore(collection=corpus.leg_collection) if corpus.leg_collection else None
        leg_cache = LegislationCache()

        needs_browser = bool(jurisdiction.legislation or jurisdiction.web_verify)
        browser: BrowserSession | None = None
        if needs_browser:
            browser = BrowserSession()
            await browser.open()

        redis: aioredis.Redis | None = None
        if jurisdiction.web_verify:
            try:
                redis = aioredis.from_url(_REDIS_URL, decode_responses=True)
                await redis.ping()
            except Exception:
                redis = None

        if browser and jurisdiction.legislation:
            asyncio.create_task(leg_cache.warm(jurisdiction, browser))

        app.state.pipeline = pipeline
        app.state.leg_store = leg_store
        app.state.browser = browser
        app.state.redis = redis
        app.state.leg_cache = leg_cache
        app.state.jurisdiction = jurisdiction

        yield

        await pipeline.close()
        if browser:
            await browser.close()
        if redis:
            await redis.aclose()

    rewrite_system = (
        jurisdiction.rewrite_prompt
        if jurisdiction.rewrite_prompt is not None
        else _REWRITE_SYSTEM_DEFAULT
    )
    skip_rewrite = jurisdiction.rewrite_prompt == ""

    app = FastAPI(
        title=jurisdiction.description,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_ALLOWED_ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    # Mount static files if the jurisdiction provides a static directory
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def ui() -> FileResponse:
            return FileResponse(_static_dir / "index.html")

        robots_file = _static_dir / "robots.txt"
        if robots_file.exists():
            @app.get("/robots.txt", include_in_schema=False)
            async def robots() -> FileResponse:
                return FileResponse(robots_file, media_type="text/plain")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "jurisdiction": jurisdiction.name, **queue_status()}

    @app.get("/token")
    async def token() -> dict:
        return {"token": _PUBLIC_TOKEN}

    @app.get("/debug/ping", include_in_schema=False)
    async def debug_ping(request: Request) -> dict:
        _check_token(request)
        key = request.headers.get("X-Debug-Key", "")
        if not _DEBUG_KEY or key != _DEBUG_KEY:
            raise HTTPException(status_code=403, detail="Invalid debug key.")
        return {"ok": True}

    @app.post("/ask/stream")
    async def ask_stream(req: AskRequest, request: Request) -> StreamingResponse:
        _check_token(request)
        await _check_llm()
        question = sanitize_question(req.question.strip(), jurisdiction.max_question_chars)

        pipeline: RAGPipeline = request.app.state.pipeline
        leg_store: VectorStore | None = request.app.state.leg_store
        browser: BrowserSession | None = request.app.state.browser
        redis = request.app.state.redis
        leg_cache: LegislationCache = request.app.state.leg_cache
        jur: JurisdictionBase = request.app.state.jurisdiction
        question = jur.preprocess_question(question, address=req.address)

        debug_mode = bool(_DEBUG_KEY and req.debug_key == _DEBUG_KEY)
        strategy = req.strategy if debug_mode and req.strategy in _VALID_STRATEGIES else "vector"

        async def _event_stream():
            ip: str | None = None
            t0 = time.monotonic()
            try:
                if will_wait():
                    yield f"data: {json.dumps({'type': 'queue', **queue_wait_estimate()})}\n\n"
                try:
                    ip = await acquire(request)
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
                    yield f"data: {json.dumps({'type': 'error', 'message': detail.get('error', 'Server busy.')})}\n\n"
                    return

                prior_turns = await _load_session(redis, jur.name, req.session_id)

                retrieve_kwargs: dict = {"top_k": 5, "strategy": strategy, "min_score": 0.75, "min_chunks": 2}

                rewrite_input = _strip_context_prefixes(question)
                retrieval_question = (
                    rewrite_input if skip_rewrite
                    else await _rewrite_query(rewrite_input, rewrite_system)
                )

                (context_texts, sources), (anchor_vstore, leg_sources) = await asyncio.gather(
                    pipeline.retrieve(retrieval_question, **retrieve_kwargs),
                    _retrieve_anchor(retrieval_question, question, pipeline, leg_store, jur),
                )

                context_texts, sources = await _augment_case_retrieval(
                    question, retrieval_question, pipeline, jur, context_texts, sources,
                )

                refine_used = False
                if _confidence([s["_score"] for s in sources], jur.confidence_config)["level"] == "low":
                    context_texts, sources = await _refine_retrieve(
                        question, retrieval_question, pipeline, sources, context_texts,
                    )
                    refine_used = True

                t_retrieve = time.monotonic() - t0

                web_text, web_results, from_cache = "", [], False
                if req.verify and browser:
                    web_text, web_results, from_cache = await _web_verify(
                        retrieval_question, leg_sources, browser, redis, jur,
                        alwaysonline=req.alwaysonline,
                    )

                if not context_texts:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'I could not find enough relevant decisions to answer this question reliably.'})}\n\n"
                    return

                scores = [s["_score"] for s in sources]
                public_sources = [{k: v for k, v in s.items() if k not in ("title", "_score")} for s in sources]

                # Build live anchor if cached legislation text is available (zero extra latency)
                live_anchor = ""
                if jur.legislation:
                    first_act_id = next(iter(jur.legislation.acts), None)
                    if first_act_id:
                        live_text = leg_cache.get(first_act_id, jur.legislation.cache_ttl_seconds)
                        if live_text and leg_sources:
                            live_anchor = leg_cache.build_anchor(first_act_id, live_text, leg_sources, jur)

                anchor = live_anchor or anchor_vstore
                if web_text:
                    anchor = (anchor + "\n\n---\n\n" if anchor else "") + web_text

                session_ctx = _format_session_context(prior_turns)
                if session_ctx:
                    anchor = session_ctx + ("\n\n---\n\n" + anchor if anchor else "")

                yield f"data: {json.dumps({'type': 'sources', 'sources': public_sources, 'legislation': leg_sources})}\n\n"
                if web_results:
                    yield f"data: {json.dumps({'type': 'web_results', 'results': web_results, 'cached': from_cache})}\n\n"
                yield f"data: {json.dumps({'type': 'confidence', **_confidence(scores, jur.confidence_config)})}\n\n"

                if debug_mode:
                    yield f"data: {json.dumps({'type': 'debug', 'strategy': strategy, 'retrieve_ms': round(t_retrieve * 1000), 'scores': scores, 'chunks': len(scores), 'refine_used': refine_used})}\n\n"

                if debug_mode or req.feedback_context:
                    def _tok(text: str) -> int:
                        return max(1, round(len(text) / 4))

                    matched_routes = match_routes(question, retrieval_question, jur.routes)
                    routing_ev = {
                        "triggered": bool(matched_routes),
                        "matched_routes": [r.intent for r in matched_routes],
                        "trigger_terms": list({
                            t for r in matched_routes for t in r.include_any
                        }),
                        "forced_sections": [
                            s for r in matched_routes for s in r.forced_sections
                        ],
                    }
                    anchor_sections = [
                        {
                            "document_id": s.get("case_id", ""),
                            "title": s.get("title", ""),
                            "tokens": 0,
                            "preview": "",
                            "forbidden_terms": {},
                        }
                        for s in leg_sources
                    ]
                    chunk_cards = [
                        {
                            "source_index": i + 1,
                            "score": s.get("_score", 0),
                            "passed_gate": True,
                            "document_id": s.get("case_id", ""),
                            "date": s.get("date", ""),
                            "tokens": _tok(txt),
                            "preview": txt[:300],
                            "full_text": txt,
                        }
                        for i, (s, txt) in enumerate(zip(sources, context_texts))
                    ]
                    anchor_tok = _tok(anchor)
                    chunk_tok = sum(_tok(txt) for txt in context_texts)
                    budget = {
                        "total_tokens": anchor_tok + chunk_tok,
                        "ctx_limit": 8192,
                        "anchor_tokens": anchor_tok,
                        "chunk_tokens": chunk_tok,
                        "sources_sent": len(sources),
                        "truncated_chunks": 0,
                    }
                    yield f"data: {json.dumps({'type': 'context_debug', 'original_query': question, 'rewrite_input': rewrite_input, 'rewritten_query': retrieval_question, 'rewrite_used': retrieval_question != rewrite_input, 'statute_routing': routing_ev, 'anchor': {'method': 'vector+cache', 'sections': anchor_sections}, 'chunks': chunk_cards, 'budget': budget})}\n\n"

                # Global LLM semaphore: serialize generation across all app
                # processes when LLM_GLOBAL_CONCURRENCY > 0. Retrieval above
                # already ran in parallel; only inference is serialized.
                if LLM_GLOBAL_CONCURRENCY and await global_llm_will_wait(redis):
                    yield f"data: {json.dumps({'type': 'queue', 'position': 1, 'reason': 'llm_busy', 'estimated_wait_s': _AVG_QUERY_SECONDS, 'message': 'Another query is generating - queued.'})}\n\n"

                global_acquired = await global_llm_acquire(redis, timeout=90.0)
                if not global_acquired:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'The server is too busy right now. Please try again in a moment.'})}\n\n"
                    return

                t_gen = time.monotonic()
                full_answer: list[str] = []
                try:
                    async for tok in pipeline._generator.generate_stream(
                        question, context_texts, sources, legislation_anchor=anchor or None
                    ):
                        full_answer.append(tok)
                        yield f"data: {json.dumps({'type': 'token', 'text': tok})}\n\n"
                finally:
                    await global_llm_release(redis)

                if debug_mode:
                    yield f"data: {json.dumps({'type': 'debug_done', 'generate_ms': round((time.monotonic() - t_gen) * 1000), 'total_ms': round((time.monotonic() - t0) * 1000)})}\n\n"

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

                await _save_session(redis, jur.name, req.session_id, question, "".join(full_answer))

                verification = await _verify_sections("".join(full_answer), leg_sources, leg_cache, jur)
                if verification:
                    yield f"data: {json.dumps({'type': 'verification', 'sections': verification})}\n\n"

            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            finally:
                if ip:
                    release(ip)

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/retrieve")
    async def retrieve(req: RetrieveRequest, request: Request) -> dict:
        _check_token(request)
        question = sanitize_question(req.question.strip(), jurisdiction.max_question_chars)

        pipeline: RAGPipeline = request.app.state.pipeline
        leg_store: VectorStore | None = request.app.state.leg_store
        leg_cache: LegislationCache = request.app.state.leg_cache
        jur: JurisdictionBase = request.app.state.jurisdiction
        question = jur.preprocess_question(question, address=req.address)

        strategy = req.strategy if req.strategy in _VALID_STRATEGIES else "vector"
        rewrite_input = _strip_context_prefixes(question)
        retrieval_question = (
            rewrite_input if skip_rewrite
            else await _rewrite_query(rewrite_input, rewrite_system)
        )

        (context_texts, sources), (anchor_vstore, leg_sources) = await asyncio.gather(
            pipeline.retrieve(retrieval_question, top_k=5, strategy=strategy, min_score=0.75, min_chunks=2),
            _retrieve_anchor(retrieval_question, question, pipeline, leg_store, jur),
        )

        context_texts, sources = await _augment_case_retrieval(
            question, retrieval_question, pipeline, jur, context_texts, sources,
        )

        if _confidence([s["_score"] for s in sources], jur.confidence_config)["level"] == "low":
            context_texts, sources = await _refine_retrieve(
                question, retrieval_question, pipeline, sources, context_texts,
            )

        live_anchor = ""
        if jur.legislation:
            first_act_id = next(iter(jur.legislation.acts), None)
            if first_act_id:
                live_text = leg_cache.get(first_act_id, jur.legislation.cache_ttl_seconds)
                if live_text and leg_sources:
                    live_anchor = leg_cache.build_anchor(first_act_id, live_text, leg_sources, jur)

        anchor = live_anchor or anchor_vstore
        public_sources = [
            {**{k: v for k, v in s.items() if k != "title"}, "_score": s.get("_score")}
            for s in sources
        ]

        return {
            "context_texts": context_texts,
            "sources": public_sources,
            "legislation": leg_sources,
            "anchor": anchor,
        }

    @app.post("/feedback")
    async def feedback(req: FeedbackRequest, request: Request) -> dict:
        _check_token(request)
        write_feedback(request, req.question, req.rating, req.comment)
        return {"ok": True}

    @app.post("/feedback/full")
    async def feedback_full(req: FeedbackFullRequest, request: Request) -> dict:
        _check_token(request)
        if req.rating not in (1, -1):
            raise HTTPException(status_code=400, detail="Rating must be 1 or -1.")
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "jurisdiction": jurisdiction.name,
            "rating": req.rating,
            "comment": req.comment[:1000],
            "strategy": req.strategy,
            "irac": req.irac,
            "think": req.think,
            "debug_mode": req.debug_mode,
            "ts_start": req.ts_start,
            "ts_end": req.ts_end,
            "user_agent": req.user_agent[:300],
            "question": req.question[:2000],
            "answer": req.answer[:8000],
            "sources": req.sources,
            "legislation": req.legislation,
            "confidence": req.confidence,
            "web_results": req.web_results,
            "verification": req.verification,
            "debug": req.debug,
            "debug_timing": req.debug_timing,
            "context_debug": req.context_debug,
        }
        write_feedback_full(request, entry)
        return {"ok": True}

    jurisdiction.register_routes(app)

    return app
