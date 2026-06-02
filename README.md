# Astraea

Open-justice RAG framework for building jurisdiction-specific legal Q&A tools over public court decisions.

Named after Astraea, the Greek goddess of justice who carried the scales.

---

## What it is

A small runtime framework that provides the infrastructure for legal RAG tools - SSE streaming,
concurrent request queue, statute routing, live legislation anchors, citation verification,
security hardening, and smoke tests - so that a new jurisdiction only needs to provide one Python module.

```python
from jurisdictions.nz_tenancy import jurisdiction
from core.api import create_app

app = create_app(jurisdiction)
```

---

## Design principles

- **One process = one jurisdiction.** No multi-tenancy, no plugin registry. Simple deployment.
- **Four required things.** A jurisdiction must provide: a name, a corpus config, a system prompt, and a route table. Everything else has a working default.
- **Security and queue are non-overridable.** Input sanitization, request body limits, security headers, and queue concurrency are enforced by core regardless of jurisdiction config.
- **Scraper is offline.** Ingestion runs separately from the API. Core only needs a populated Qdrant collection conforming to `schemas/qdrant_payload.schema.json`.
- **Tests are data-driven.** Jurisdictions provide smoke test fixtures; core runs the test suite against them automatically.

---

## Supported jurisdictions

| Jurisdiction | Status | Corpus |
|---|---|---|
| NZ Tenancy (`nz_tenancy`) | Live - tenancy.localrun.ai | 31,000+ Tenancy Tribunal decisions, RTA 1986 + Healthy Homes Standards 2019 |
| NZ Legal (`nz_legal`) | Live - nz-legal-rag.localrun.ai | All NZ courts, 3M+ chunks (NZHC, NZCA, NZSC, NZERA, NZEmpC, NZTT) |
| NZ Employment (`nz_employment`) | Ready | 300+ ERA + Employment Court decisions through May 2026, live ERA 2000 |
| NSW Tenancy (`nsw_tenancy`) | PoC (framework demo) | Proves interface generalises - not actively developed |

---

## Adding a new jurisdiction

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full fork-to-running walkthrough.

Quick version:

1. Copy `examples/minimal_jurisdiction/` to `jurisdictions/your_name/`
2. Implement the 4 required properties in `jurisdiction.py`
3. Run the contract tests: `pytest tests/core/test_jurisdiction_contract.py --jurisdiction your_name`
4. Ingest your corpus into Qdrant (see `ingest/` and `schemas/qdrant_payload.schema.json`)
5. Add smoke fixtures and run: `pytest tests/jurisdictions/test_smoke.py --jurisdiction your_name -m retrieval`

---

## Jurisdiction extension points

Beyond the 4 required properties, jurisdictions can opt into additional behaviour:

### Extra routes (`register_routes`)

Add jurisdiction-specific endpoints (e.g. structured data trackers) on top of the core API:

```python
def register_routes(self, app: FastAPI) -> None:
    from jurisdictions.nz_legal.routes import register
    register(app)
```

Called at the end of `create_app()`. Route handlers access pipeline and store via `request.app.state`.

`nz_legal` uses this to expose `/search`, `/notable`, `/sentencing-tracker`, `/pg-tracker`, and `/contrasting-cases`.

### Federated per-Act legislation retrieval (`leg_sources`)

By default, legislation retrieval does one vector search across the entire legislation collection.
As a corpus grows (more Acts), smaller Acts get crowded out by larger ones on embedding similarity alone.

Override `leg_sources` to run one search per registered Act in parallel, each with its own `top_k` quota.
The re-ranker phase (Phase 2) can then select the best sections across all sources without manual routes:

```python
from core.jurisdiction import LegislationSource

@property
def leg_sources(self) -> list[LegislationSource]:
    return [
        LegislationSource("RTA",    "Residential Tenancies Act 1986",                         default_top_k=6, boost_top_k=10),
        LegislationSource("HHS2019","Residential Tenancies (Healthy Homes Standards) Regulations 2019", default_top_k=4, boost_top_k=8),
    ]
```

When a matched route targets a specific Act (e.g. `healthy_homes` route targets `HHS2019`), that
Act's search uses `boost_top_k` instead of `default_top_k`, giving it more candidates before ranking.

Routes remain as hard floor guarantees - forced sections are always included in the candidate pool
regardless of federated search results. This means a cross-encoder re-ranker (Phase 2) can
reorder freely without risking that a critical section is dropped.

A `CrossEncoderReranker` (Phase 1: log-only) is available in `core/reranker.py`. It scores
candidates after federated search and logs the scores for observability without affecting ranking.
Promote to production ranking after benchmarking shows it matches route-based quality.

### Case retrieval augmentation (`case_synthetic_query` on `StatuteRoute`)

When a matched route defines `case_synthetic_query`, a supplementary case retrieval pass
runs with that query and unique results are merged into context (up to 8 total chunks).

Fixes cases where the query rewriter drops legally significant framing that is obvious
from the original question but lost in rewriting:

```python
StatuteRoute(
    intent="sham_flatmate_agreement",
    include_any=("flatmate agreement", "meant to be tenants", ...),
    forced_sections=("NZLEG/RTA/s5",),
    synthetic_query="...",
    case_synthetic_query=(
        "flatmate agreement landlord not living property sham tenancy RTA applies "
        "boarder licensee residential tenancy act tenant rights eviction notice"
    ),
)
```

### Smoke fixture source count (`min_sources` on `SmokeFixture`)

Assert that supplementary retrieval ran and returned the expected number of case sources:

```python
SmokeFixture(
    question="My landlord put us on a flatmate agreement...",
    expected_sections=[],
    min_sources=6,
    description="sham_flatmate_agreement route - case_synthetic_query augmentation",
)
```

---

## Qdrant payload schema

All jurisdictions must produce chunks conforming to `schemas/qdrant_payload.schema.json`.

Required fields: `document_id`, `court`, `court_name`, `title`, `date`, `url`, `text`, `source_type`.

---

## Stack

| Component | Technology |
|---|---|
| Vector database | Qdrant |
| Embeddings | nomic-embed-text-v1.5 / Qwen3-Embedding-0.6B via sentence-transformers |
| LLM inference | llama.cpp (OpenAI-compatible) |
| API | FastAPI + SSE streaming |
| Cache | Redis (web verify results) |
| Queue | Semaphore-based, per-IP fairness |

---

## Milestones

- [x] Milestone 0 - core interface design, runtime modules, `nz_tenancy` jurisdiction
- [x] Milestone 1 - `nsw_tenancy` skeleton + `nz_legal` + `nz_employment` prove interface generalises
- [x] Milestone 2 - smoke test runner wired to pytest (Tier 1/2/3), Docker Compose
- [x] Milestone 3 - CONTRIBUTING.md, packaging, NSW NCAT scraper + corpus (225+ decisions)
- [x] Milestone 4 - `nz_legal` migration: tracker endpoints, contrasting cases, `register_routes` hook
- [x] Milestone 5 - federated per-Act legislation retrieval, Healthy Homes Standards 2019 corpus, cross-encoder reranker (Phase 1 log-only), Qdrant payload indexes for fast filtered search

---

## Related project

The NZ tenancy tool running on this framework: https://tenancy.localrun.ai

Source: https://github.com/jwongso/nz-legal-rag

---

MIT License. Not legal advice.
