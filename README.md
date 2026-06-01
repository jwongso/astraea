# Astraea

Open-justice RAG framework for building jurisdiction-specific legal Q&A tools over public court decisions.

Named after Astraea, the Greek goddess of justice who carried the scales.

---

## What it is

A small runtime framework that provides the infrastructure for legal RAG tools - SSE streaming, concurrent request queue, statute routing, live legislation anchors, citation verification, security hardening, and smoke tests - so that a new jurisdiction only needs to provide one Python module.

```python
# apps/nz_tenancy_app.py
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
- **Tests are data-driven.** Jurisdictions provide smoke test fixtures; core runs the 3-tier test suite against them automatically.

---

## Supported jurisdictions

| Jurisdiction | Status | Corpus |
|---|---|---|
| NZ Tenancy (`nz_tenancy`) | Live - tenancy.localrun.ai | 31,000+ Tenancy Tribunal decisions, live RTA 1986 |
| NZ Employment (`nz_employment`) | Ready | 300+ ERA + Employment Court decisions through May 2026, live ERA 2000 |
| NZ Legal (`nz_legal`) | Ready | All NZ courts, 3M+ chunks (NZHC, NZCA, NZSC, NZERA, NZEmpC, NZTT) |
| NSW Tenancy (`nsw_tenancy`) | Ready | 225+ NCAT Consumer and Commercial Division decisions (2025-2026), live RTA 2010 |

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

---

## Related project

The NZ tenancy tool running on this framework: https://tenancy.localrun.ai

Source: https://github.com/jwongso/nz-legal-rag (being migrated into Astraea)

---

MIT License. Not legal advice.
