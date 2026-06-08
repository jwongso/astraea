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

## Installation

```bash
pip install astraea-framework
```

For local development:

```bash
git clone https://github.com/jwongso/astraea
pip install -e .
```

Client apps should pin to a minor version floor:

```toml
# pyproject.toml
dependencies = ["astraea-framework>=0.2.0"]
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
| NZ Tenancy (`nz_tenancy`) | Live - tenancy.localrun.ai | 31,000+ Tenancy Tribunal decisions, RTA 1986 + Healthy Homes Standards 2019, 35 official guidance docs (Tenancy Services, NZ Legislation, OPC) |
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

### Statute routing (`StatuteRoute`)

**The retrieval problem routes solve**

Vector search ranks sections by embedding similarity to the user's query. That works well
when the question and the legislation share vocabulary. It fails in two common patterns:

- **Sparse query coverage** - "sell the house" does not embed near "fixed-term tenancy becomes
  periodic on expiry". The critical section never enters the top-k, even with a good model.
- **Act crowding** - when the corpus contains a large Act (RTA, ~100+ sections) alongside a
  small one (HHS 2019, ~20 sections), the large Act dominates embedding similarity. Every
  healthy homes question returns mostly RTA chunks.

A `StatuteRoute` fixes both problems for a known question type. It is not a reasoning patch -
it is a retrieval patch. The LLM still has to reason correctly over whatever lands in context;
routes ensure the right sections land there in the first place.

**Defining a route**

```python
from core.routing import StatuteRoute

StatuteRoute(
    intent="fixed_term_sell",
    include_any=(
        "sell the house", "selling the property", "before listing",
        "vacant possession", "fixed term end early",
    ),
    forced_sections=("NZLEG/RTA/s60A", "NZLEG/RTA/s50"),
    synthetic_query=(
        "landlord fixed term tenancy sell house vacant possession terminate early "
        "mutual agreement section 50 section 60A periodic tenancy"
    ),
    notes="Landlord wants to sell during fixed-term (s60A, s50).",
)
```

Fields:

| Field | Purpose |
|---|---|
| `intent` | Slug used in logs and traces |
| `include_any` | Lowercase substrings - any match triggers the route |
| `forced_sections` | Document IDs always added to the candidate pool regardless of vector search |
| `synthetic_query` | Alternative query run instead of (or alongside) the user query for legislation retrieval |
| `notes` | Human note for code reviewers |

**The hard floor guarantee**

`forced_sections` are injected into the candidate pool before any ranking or deduplication.
This means a cross-encoder reranker (Phase 2) can reorder freely without risking a critical
section being dropped. Routes are the floor; reranking is the ceiling.

**What routes do not fix**

Routes are retrieval infrastructure. They do not fix:
- LLM reasoning errors (applying the right section to the wrong party)
- Hallucinated section numbers (the LLM inventing citations not in context)
- Incorrect legal conclusions from correctly retrieved text

These require system prompt tuning or a stronger model.

**When routes become less necessary**

Routes are a manual approximation of what a trained reranker learns automatically. As the
corpus accumulates real user feedback (thumbs-up/down), a cross-encoder reranker trained on
that signal will learn to surface the right sections without explicit keyword rules. Routes
shrink from a large maintained list to a small set of hard guarantees for the most critical
sections.

A sufficiently capable model in an agentic loop (iterative tool-call retrieval) can also
eliminate routes by asking for the sections it needs mid-generation. That architecture trades
latency for route maintenance. For a single-pass streaming API the current approach is
simpler and cheaper.

---

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

### Official guidance injection (`guidance_sources` on `StatuteRoute`)

**The retrieval problem guidance solves**

Legislation retrieval and case retrieval compete in the same vector pool. Tribunal decisions are
semantically dense (facts, disputes, outcomes, legal terms) and consistently outscore official
guidance pages (broader, explanatory prose). A Tenancy Services "How to apply for a bond refund"
page often ranks sixth or seventh even when it is exactly what the user needs.

This is not a scoring failure. It is an architectural mismatch: case decisions and official guidance
are different source classes and should not compete in a flat top-k ranking.

Astraea solves this with a third parallel retrieval path alongside legislation and case retrieval:

```text
legislation retrieval  ->  what the law says              (anchor, before cases)
official guidance      ->  official plain-language process (injected above cases)
case decisions         ->  how disputes are decided        (corpus top-k)
```

**Route-forced guidance (`guidance_sources`)**

Add `guidance_sources` to a `StatuteRoute` to bind specific MANUAL docs to that route.
When the route fires, the listed docs are resolved from the vector search results (highest-scoring
wins), then fetched directly if none are in the results. The winning doc is prepended to context
above the case decisions regardless of its vector score.

```python
StatuteRoute(
    intent="bond",
    include_any=("bond refund", "get my bond back", ...),
    forced_sections=("NZLEG/RTA/s18",),
    synthetic_query="...",
    guidance_sources=(
        "MANUAL/how-to-apply-for-a-bond-refund",
        "MANUAL/bonds",
    ),
)
```

When multiple guidance docs are listed, the one with the highest vector score for the specific
query wins - so "bond refund" queries surface the refund guide while "bond lodgement" queries
surface the general bonds page.

**Vector threshold fallback**

When no matched route specifies `guidance_sources`, the guidance path falls back to a vector search
over MANUAL official guidance chunks with a relevance threshold (default 0.75, configurable via
`GUIDANCE_THRESHOLD` env var). If a chunk scores above the threshold it is injected. This catches
high-traffic practical questions that have no specific route configured (e.g. pets, discrimination).

**Source types and score discounts**

MANUAL sources are typed. Sources in `["official_guidance", "official_policy"]` are authoritative
and eligible for the guidance injection path. Secondary sources carry a score discount so they
provide background context without crowding out authoritative results:

```python
# core/pipeline.py
_MANUAL_DISCOUNTS = {
    "law_review":              0.85,
    "advocacy_submission":     0.85,
    "community_legal_guidance":0.85,
    "commercial_commentary":   0.80,
}
```

Ingest MANUAL docs with the type that reflects their authority:

```bash
python -m ingest.ingest_manual page.pdf --source-type official_guidance
python -m ingest.ingest_manual submission.pdf --source-type advocacy_submission
python -m ingest.ingest_manual https://www.tenancy.govt.nz/bonds/  # defaults to official_guidance
```

**Smoke testing guidance injection**

Use `expected_guidance_sources` on `SmokeFixture` to assert that the correct guidance doc is
injected for a question. The `/retrieve` endpoint returns a `guidance` field so this assertion
runs without LLM inference:

```python
SmokeFixture(
    question="How do I get my bond back after moving out?",
    expected_sections=["NZLEG/RTA/s18"],
    expected_guidance_sources=["MANUAL/how-to-apply-for-a-bond-refund", "MANUAL/bonds"],
    description="bond route - guidance injection: bond refund page",
)
```

**Debug observability**

Every `/ask/stream` response includes a `guidance` sub-object in the `context_debug` SSE event:

```json
{
  "injected": true,
  "source": "MANUAL/how-to-apply-for-a-bond-refund",
  "court_name": "Tenancy Services",
  "score": 0.82,
  "threshold": 0.75,
  "reason": "route_forced_vector"
}
```

`reason` is one of `route_forced_vector` (route-guided, doc found in vector results),
`route_forced` (route-guided, fetched directly), `vector_search` (threshold fallback), or
`""` (nothing injected).

---

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

### Shared frontend utilities (`window.Astraea`)

All Astraea apps automatically serve `/static/astraea/astraea.js` from `core/frontend/`.
Load it before your jurisdiction's `app.js`:

```html
<script src="/static/astraea/astraea.js"></script>
<script src="/static/app.js"></script>
```

This exposes a `window.Astraea` namespace with shared rendering and API utilities:

| Function | Purpose |
|---|---|
| `renderAnswer(text)` | Markdown-to-HTML: lists, tables, headings, bold, citations, URL auto-link |
| `renderSources(sources, leg, opts)` | Source cards with optional legislation toggle |
| `renderConfidence(ev, container)` | Confidence badge insertion |
| `streamEvents(response, onEvent)` | SSE reader loop (async) |
| `loadToken()` | Fetch public API token from `/token` |
| `pollQueue(el)` | Update queue status notice element from `/health` |
| `saveFullFeedback(payload, rating, comment, isDebug, token)` | POST to `/feedback/full` |
| `initDisclaimer(storageKey)` | localStorage-keyed disclaimer modal (reads existing HTML) |
| `initUserContext(storageKey)` | Floating context panel - see below |
| `getUserContext(storageKey)` | Read stored context string for inclusion in requests |

### User-local memory (`initUserContext`)

Users can store persistent personal context (role, location, situation) in `localStorage`.
It is prepended to the LLM anchor on every request and never stored server-side.

Client apps opt in with two calls:

```javascript
// Init once - injects a floating person-icon button into the page
Astraea.initUserContext('myapp_user_ctx');

// Include in every /ask/stream POST body
body: JSON.stringify({
  question,
  user_context: Astraea.getUserContext('myapp_user_ctx'),
  // ...
})
```

The backend field is `user_context: str = ""` on `AskRequest` (capped at 500 chars).
It is inserted above session history and legislation in the prompt anchor under the label
`"User's personal context (apply throughout your answer):"`.

The floating button turns blue when context is set. Context persists until the user clears it.

---

## MCP tool servers

Every jurisdiction ships with an MCP server entry point so any MCP-capable agent
(Claude Code, Claude Desktop, OpenClaw, or a custom agent) can call it as a tool.

### Tools exposed by every jurisdiction

| Tool | What it does |
|---|---|
| `legal_search` | Semantic search - returns sources with title, court, date, URL, score |
| `legal_ask` | Full RAG - retrieves context, generates answer with section citations |
| `legal_get_source` | Fetch the full text of a case/decision by its source ID |
| `legal_get_legislation` | Fetch a legislation section by ID (e.g. `NZLEG/RTA/s42A`) |

Building consents adds one extra tool:

| Tool | What it does |
|---|---|
| `lookup_building_zone` | Geocode an NZ address and return its district plan zone (12 councils) |

### Claude Desktop / Claude Code config

Add to `~/.claude.json` (Claude Code) or `~/.claude_desktop_config.json` (Claude Desktop):

```json
{
  "mcpServers": {
    "nz-tenancy": {
      "command": "python3",
      "args": ["-m", "jurisdictions.nz_tenancy.mcp_server"],
      "cwd": "/path/to/astraea"
    },
    "nz-legal": {
      "command": "python3",
      "args": ["-m", "jurisdictions.nz_legal.mcp_server"],
      "cwd": "/path/to/astraea"
    },
    "nz-building": {
      "command": "python3",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/buildingconsents"
    }
  }
}
```

### Typical agent workflow

For building consents, the agent should look up the zone first, then ask:

```
1. lookup_building_zone("123 Main Street, Nelson")
   -> {"found": true, "council": "Nelson", "zone_name": "Inner City - Centre", ...}

2. legal_ask("[Zone context: Nelson Inner City - Centre]\n\nDo I need a consent for a deck?")
   -> {"answer": "...", "sources": [...]}
```

For tenancy, call `legal_ask` directly:

```
legal_ask("My landlord gave me 90 days notice to vacate. Is this valid?")
```

### Adding jurisdiction-specific tools

Override `register_mcp_tools` on your jurisdiction class to add extra tools beyond the 4 core ones:

```python
def register_mcp_tools(self, mcp, service) -> None:
    async def my_tool(param: str) -> str:
        """Description the LLM uses to decide when to call this."""
        ...
    mcp.add_tool(my_tool, name="my_tool", description="...")
```

Called automatically by `create_mcp_server()` after the core tools are registered.

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
- [x] Milestone 6 - published to PyPI as `astraea-framework`, shared frontend utilities (`window.Astraea` namespace served from core), modular core (`anchor.py`, `web_verify.py`, `session.py`), user-local memory (`initUserContext` / `getUserContext`)
- [x] Milestone 7 - three-tier retrieval: official guidance injection layer runs in parallel with legislation anchor and case retrieval; route-specific `guidance_sources` on `StatuteRoute` for high-traffic topics (bond, rent increase, termination, rent arrears); vector threshold fallback for unconfigured routes; MANUAL source type taxonomy with score discounts for secondary sources; `expected_guidance_sources` on `SmokeFixture` for regression testing; `guidance` debug field in every `/ask/stream` `context_debug` event

---

## Related projects

| App | URL | Source |
|---|---|---|
| NZ Tenancy Help | https://tenancy.localrun.ai | this repo (`jurisdictions/nz_tenancy/`) |
| NZ Legal Research | https://nz-legal-rag.localrun.ai | this repo (`jurisdictions/nz_legal/`) |
| NZ Building Consents Help | https://buildingconsents.localrun.ai | https://github.com/jwongso/buildingconsents |
| Corpus ingestion scripts | - | https://github.com/jwongso/nz-legal-rag (archived) |

---

MIT License. Not legal advice.
