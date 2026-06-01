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
    acquire, get_client_ip, queue_status, queue_wait_estimate, release, will_wait,
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
_PUBLIC_TOKEN = os.getenv("PUBLIC_TOKEN", "")
_DEBUG_KEY = os.getenv("DEBUG_KEY", "")
_ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")
_WEB_CACHE_TTL = 604800
_WEB_CACHE_PREFIX = "astraea:web_verify:"
_VALID_STRATEGIES = {"vector", "mmr"}

_REWRITE_SYSTEM_DEFAULT = (
    "Rewrite the following as a concise formal legal question. "
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


async def _retrieve_anchor(
    question: str,
    original_question: str,
    pipeline: RAGPipeline,
    leg_store: VectorStore,
    jurisdiction: JurisdictionBase,
) -> tuple[str, list[dict]]:
    """Embed forced statute sections and inject them ahead of vector results.

    Returns (anchor_text_from_vstore, leg_sources).
    leg_sources is used by the caller to build a live-text anchor if available.
    """
    if leg_store is None:
        return "", []
    try:
        vector = await pipeline._embedder.embed(question)
        raw = leg_store.search(vector, top_k=12)

        matched = match_routes(original_question or question, question, jurisdiction.routes)
        injected_ids: list[str] = []
        injections: list = []
        seen_inject: set[str] = set()
        for route in matched:
            synth_vector = await pipeline._embedder.embed(route.synthetic_query)
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


def _confidence(scores: list[float]) -> dict:
    n = len(scores)
    if n == 0:
        return {"level": "low", "chunks": 0, "message": "No relevant decisions found."}
    top = max(scores)
    level = "high" if top >= 0.82 and n >= 4 else "medium" if top >= 0.77 and n >= 2 else "low"
    messages = {
        "high": f"Found {n} directly relevant decisions.",
        "medium": f"Found {n} relevant decisions - review the cited sources carefully.",
        "low": f"Found only {n} loosely related decisions - verify independently before acting.",
    }
    return {"level": level, "chunks": n, "message": messages[level]}


class AskRequest(BaseModel):
    question: str
    debug_key: str = ""
    strategy: str = "vector"
    irac: bool = False
    verify: bool = True
    alwaysonline: bool = False


class RetrieveRequest(BaseModel):
    question: str
    strategy: str = "vector"


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
    ts_start: str = ""
    ts_end: str = ""
    user_agent: str = ""
    answer: str = ""
    sources: list = []
    legislation: list = []
    confidence: dict | None = None
    web_results: dict | None = None
    verification: list | None = None


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

                retrieve_kwargs: dict = {"top_k": 5, "strategy": strategy, "min_score": 0.75, "min_chunks": 2}

                retrieval_question = (
                    question if skip_rewrite
                    else await _rewrite_query(question, rewrite_system)
                )

                (context_texts, sources), (anchor_vstore, leg_sources) = await asyncio.gather(
                    pipeline.retrieve(retrieval_question, **retrieve_kwargs),
                    _retrieve_anchor(retrieval_question, question, pipeline, leg_store, jur),
                )
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

                yield f"data: {json.dumps({'type': 'sources', 'sources': public_sources, 'legislation': leg_sources})}\n\n"
                if web_results:
                    yield f"data: {json.dumps({'type': 'web_results', 'results': web_results, 'cached': from_cache})}\n\n"
                yield f"data: {json.dumps({'type': 'confidence', **_confidence(scores)})}\n\n"

                if debug_mode:
                    yield f"data: {json.dumps({'type': 'debug', 'strategy': strategy, 'retrieve_ms': round(t_retrieve * 1000), 'scores': scores, 'chunks': len(scores)})}\n\n"

                t_gen = time.monotonic()
                full_answer: list[str] = []
                async for tok in pipeline._generator.generate_stream(
                    question, context_texts, sources, legislation_anchor=anchor or None
                ):
                    full_answer.append(tok)
                    yield f"data: {json.dumps({'type': 'token', 'text': tok})}\n\n"

                if debug_mode:
                    yield f"data: {json.dumps({'type': 'debug_done', 'generate_ms': round((time.monotonic() - t_gen) * 1000), 'total_ms': round((time.monotonic() - t0) * 1000)})}\n\n"

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

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

        strategy = req.strategy if req.strategy in _VALID_STRATEGIES else "vector"
        retrieval_question = (
            question if skip_rewrite
            else await _rewrite_query(question, rewrite_system)
        )

        (context_texts, sources), (anchor_vstore, leg_sources) = await asyncio.gather(
            pipeline.retrieve(retrieval_question, top_k=5, strategy=strategy, min_score=0.75, min_chunks=2),
            _retrieve_anchor(retrieval_question, question, pipeline, leg_store, jur),
        )

        live_anchor = ""
        if jur.legislation:
            first_act_id = next(iter(jur.legislation.acts), None)
            if first_act_id:
                live_text = leg_cache.get(first_act_id, jur.legislation.cache_ttl_seconds)
                if live_text and leg_sources:
                    live_anchor = leg_cache.build_anchor(first_act_id, live_text, leg_sources, jur)

        anchor = live_anchor or anchor_vstore
        public_sources = [{k: v for k, v in s.items() if k not in ("title", "_score")} for s in sources]

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
        }
        write_feedback_full(request, entry)
        return {"ok": True}

    return app
