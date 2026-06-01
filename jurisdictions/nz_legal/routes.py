"""Extra routes for the nz_legal jurisdiction.

Registered via NZLegalJurisdiction.register_routes(). These endpoints expose
structured-data queries (notable cases, sentencing, personal grievance, contrasting
outcomes) that are specific to the nz_legal Qdrant payload schema and do not
belong in Astraea core.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from core.pipeline import RAGPipeline
from jurisdictions.nz_legal.contrasting import find_contrasting_cases
from jurisdictions.nz_legal.scroll import scroll_notable, scroll_pg, scroll_sentencing


# ---------------------------------------------------------------------------
# /search
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    case_id: str
    title: str
    court_name: str
    date: str
    url: str
    text: str
    score: float


# ---------------------------------------------------------------------------
# /notable
# ---------------------------------------------------------------------------

class NotableRequest(BaseModel):
    flags: list[str] | None = None
    min_osi: float | None = None
    max_osi: float | None = None
    min_recovery: float | None = None
    max_recovery: float | None = None
    min_awarded: float | None = None
    max_awarded: float | None = None
    counsel_surname: str | None = None
    crown_counsel: str | None = None
    courts: list[str] | None = None
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 30


class NotableResult(BaseModel):
    case_id: str
    title: str
    court_name: str
    date: str
    url: str
    flags: list[str]
    penalty: dict
    counsel: dict


# ---------------------------------------------------------------------------
# /sentencing-tracker
# ---------------------------------------------------------------------------

class SentencingRequest(BaseModel):
    flags: list[str] | None = None
    courts: list[str] | None = None
    year_from: int | None = None
    year_to: int | None = None
    sentence_type: str | None = None
    min_starting_point: float | None = None
    max_starting_point: float | None = None
    min_final_sentence: float | None = None
    max_final_sentence: float | None = None
    has_guilty_plea: bool | None = None
    limit: int = 30


class SentencingResult(BaseModel):
    case_id: str
    title: str
    court_name: str
    date: str
    url: str
    flags: list[str]
    sentencing: dict
    penalty: dict
    counsel: dict


# ---------------------------------------------------------------------------
# /pg-tracker
# ---------------------------------------------------------------------------

class PGRequest(BaseModel):
    grievance_types: list[str] | None = None
    reinstatement: bool | None = None
    min_contributory: float | None = None
    max_contributory: float | None = None
    min_compensation: float | None = None
    max_compensation: float | None = None
    courts: list[str] | None = None
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 30


class PGResult(BaseModel):
    case_id: str
    title: str
    court_name: str
    date: str
    url: str
    pg: dict
    penalty: dict
    counsel: dict


# ---------------------------------------------------------------------------
# /contrasting-cases
# ---------------------------------------------------------------------------

class ContrastingRequest(BaseModel):
    query: str
    domain: str = "criminal"
    split_by: str | None = None
    courts: list[str] | None = None
    year_from: int | None = None
    year_to: int | None = None
    top_k: int = 5


class ContrastingCaseItem(BaseModel):
    case_id: str
    title: str
    court_name: str
    date: str
    url: str
    score: float
    structured: dict


class ContrastingGroupItem(BaseModel):
    label: str
    description: str
    cases: list[ContrastingCaseItem]


class ContrastingResponse(BaseModel):
    query: str
    domain: str
    split_by: str
    group_a: ContrastingGroupItem
    group_b: ContrastingGroupItem
    explanation: str | None = None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:

    @app.get("/search", response_model=list[SearchResult])
    async def search(
        request: Request,
        q: Annotated[str, Query(description="Search query")],
        courts: Annotated[list[str] | None, Query()] = None,
        year_from: int | None = None,
        year_to: int | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Semantic search without generation. Returns matching chunks."""
        pipeline: RAGPipeline = request.app.state.pipeline
        vector = await pipeline.embed(q)
        hits = pipeline.store.search(
            vector,
            top_k=min(top_k, 20),
            courts=courts,
            year_from=year_from,
            year_to=year_to,
        )
        return [
            SearchResult(
                case_id=h.case_id,
                title=h.title,
                court_name=h.court_name,
                date=h.date,
                url=h.url,
                text=h.text,
                score=round(h.score, 4),
            )
            for h in hits
        ]

    @app.post("/notable", response_model=list[NotableResult])
    async def notable(req: NotableRequest, request: Request) -> list[NotableResult]:
        """Filter notable cases by flags and penalty severity."""
        pipeline: RAGPipeline = request.app.state.pipeline
        hits = scroll_notable(
            pipeline.store,
            flags=req.flags or None,
            min_outcome_osi=req.min_osi,
            max_outcome_osi=req.max_osi,
            min_recovery_rate=req.min_recovery,
            max_recovery_rate=req.max_recovery,
            min_awarded=req.min_awarded,
            max_awarded=req.max_awarded,
            counsel_surname=req.counsel_surname or None,
            crown_counsel=req.crown_counsel or None,
            courts=req.courts or None,
            year_from=req.year_from,
            year_to=req.year_to,
            limit=min(req.limit, 100),
        )
        return [
            NotableResult(
                case_id=h.case_id,
                title=h.title,
                court_name=h.court_name,
                date=h.date,
                url=h.url,
                flags=h.payload.get("flags") or [],
                penalty=h.payload.get("penalty") or {},
                counsel=h.payload.get("counsel") or {},
            )
            for h in hits
        ]

    @app.post("/sentencing-tracker", response_model=list[SentencingResult])
    async def sentencing_tracker(req: SentencingRequest, request: Request) -> list[SentencingResult]:
        """Criminal sentencing tracker."""
        pipeline: RAGPipeline = request.app.state.pipeline
        hits = scroll_sentencing(
            pipeline.store,
            flags=req.flags or None,
            courts=req.courts or None,
            year_from=req.year_from,
            year_to=req.year_to,
            sentence_type=req.sentence_type or None,
            min_starting_point=req.min_starting_point,
            max_starting_point=req.max_starting_point,
            min_final_sentence=req.min_final_sentence,
            max_final_sentence=req.max_final_sentence,
            has_guilty_plea=req.has_guilty_plea,
            limit=min(req.limit, 100),
        )
        return [
            SentencingResult(
                case_id=h.case_id,
                title=h.title,
                court_name=h.court_name,
                date=h.date,
                url=h.url,
                flags=h.payload.get("flags") or [],
                sentencing=h.payload.get("sentencing") or {},
                penalty=h.payload.get("penalty") or {},
                counsel=h.payload.get("counsel") or {},
            )
            for h in hits
        ]

    @app.post("/pg-tracker", response_model=list[PGResult])
    async def pg_tracker(req: PGRequest, request: Request) -> list[PGResult]:
        """Personal grievance tracker."""
        pipeline: RAGPipeline = request.app.state.pipeline
        hits = scroll_pg(
            pipeline.store,
            grievance_types=req.grievance_types or None,
            reinstatement=req.reinstatement,
            min_contributory=req.min_contributory,
            max_contributory=req.max_contributory,
            min_compensation=req.min_compensation,
            max_compensation=req.max_compensation,
            courts=req.courts or None,
            year_from=req.year_from,
            year_to=req.year_to,
            limit=min(req.limit, 100),
        )
        return [
            PGResult(
                case_id=h.case_id,
                title=h.title,
                court_name=h.court_name,
                date=h.date,
                url=h.url,
                pg=h.payload.get("pg") or {},
                penalty=h.payload.get("penalty") or {},
                counsel=h.payload.get("counsel") or {},
            )
            for h in hits
        ]

    @app.post("/contrasting-cases", response_model=ContrastingResponse)
    async def contrasting_cases(req: ContrastingRequest, request: Request) -> ContrastingResponse:
        """Find semantically similar cases that reached opposite outcomes."""
        if not req.query.strip():
            raise HTTPException(status_code=400, detail="Query must not be empty")
        if req.domain not in ("criminal", "employment"):
            raise HTTPException(status_code=400, detail="domain must be 'criminal' or 'employment'")

        pipeline: RAGPipeline = request.app.state.pipeline
        vector = await pipeline.embed(req.query)
        try:
            result = find_contrasting_cases(
                query=req.query,
                domain=req.domain,
                query_vector=vector,
                store=pipeline.store,
                split_by=req.split_by,
                courts=req.courts,
                year_from=req.year_from,
                year_to=req.year_to,
                top_k=min(req.top_k, 10),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        d = result.to_dict()
        return ContrastingResponse(
            query=d["query"],
            domain=d["domain"],
            split_by=d["split_by"],
            group_a=ContrastingGroupItem(**d["group_a"]),
            group_b=ContrastingGroupItem(**d["group_b"]),
            explanation=d["explanation"],
        )
