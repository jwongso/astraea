# Contributing to Astraea

The primary way to contribute is to add a new jurisdiction.

This guide covers two paths:

- **Quickstart** - fork the repo, build a new jurisdiction, and run it end to end
- **Reference** - full interface documentation for `JurisdictionBase`, routing, and testing

---

## Quickstart: fork to running in 8 steps

### 1. Fork and clone

```bash
git clone https://github.com/YOUR_USERNAME/astraea
cd astraea
pip install -e ".[dev]"
```

### 2. Start the local stack

Qdrant and Redis are required. An LLM server is optional for Tier 1 smoke tests but needed for Tier 2/3.

```bash
# Qdrant + Redis only (fastest start)
docker run -d -p 6333:6333 qdrant/qdrant:v1.9.7
docker run -d -p 6379:6379 redis:7-alpine

# Or use Docker Compose (also starts llama.cpp if you set LLAMA_MODEL_PATH)
cd deployment
LLAMA_MODEL_PATH=/path/to/model.gguf docker compose up qdrant redis
```

### 3. Create your jurisdiction package

```bash
cp -r examples/minimal_jurisdiction jurisdictions/vic_tenancy
```

Edit `jurisdictions/vic_tenancy/jurisdiction.py` with your 4 required properties
(name, corpus, system_prompt, routes). See the Reference section below for details.

### 4. Run the contract tests (no corpus needed)

```bash
pytest tests/core/test_jurisdiction_contract.py --jurisdiction vic_tenancy
```

All 11 should pass. These only check the interface - no Qdrant data required.

### 5. Ingest your corpus

Write a scraper in `jurisdictions/vic_tenancy/scraper.py` that fetches source
documents and yields `ingest.base.Chunk` objects conforming to
`schemas/qdrant_payload.schema.json`.

Run it to populate Qdrant:

```bash
python -m ingest.run --jurisdiction vic_tenancy --collection vic_tenancy
```

Or start with a small hand-built sample to test the pipeline before committing
to a full scrape.

### 6. Add smoke fixtures and run Tier 1 tests

Add `smoke_fixtures` to your jurisdiction class - one fixture per common question
type you want to verify. Then:

```bash
pytest tests/jurisdictions/test_smoke.py --jurisdiction vic_tenancy -m retrieval -v
```

### 7. Create the app entry point

```bash
# apps/vic_tenancy_app.py
from jurisdictions.vic_tenancy import jurisdiction
from core.api import create_app

app = create_app(jurisdiction)
```

Run it:

```bash
uvicorn apps.vic_tenancy_app:app --host 0.0.0.0 --port 8003 --reload
```

Test it:

```bash
curl -X POST http://localhost:8003/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Can my landlord enter without notice?"}'
```

### 8. Open a PR

Make sure the checklist at the bottom of this file is green.

---

## Reference

### The 4 required properties

```python
from core.jurisdiction import CorpusConfig, JurisdictionBase, SmokeFixture
from core.routing import StatuteRoute


class VicTenancyJurisdiction(JurisdictionBase):

    @property
    def name(self) -> str:
        return "vic-tenancy"          # short slug, used in logs and service names

    @property
    def corpus(self) -> CorpusConfig:
        return CorpusConfig(
            qdrant_collection="vic_tenancy",     # Qdrant collection for case decisions
            courts=["VCAT"],                     # court codes to filter results by
            leg_collection="vic_tenancy",        # collection containing legislation chunks
        )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a legal research assistant specialising in Victorian tenancy law. "
            "Answer only from the provided sources. "
            "Cite every claim with [SN] notation. "
            "If the context is insufficient, say so clearly. "
            "This is not legal advice."
        )

    @property
    def routes(self) -> list[StatuteRoute]:
        return []          # or import ROUTES from routes.py

    def get_scraper(self):
        raise NotImplementedError


jurisdiction = VicTenancyJurisdiction()
```

Export it from `__init__.py`:

```python
from jurisdictions.vic_tenancy.jurisdiction import VicTenancyJurisdiction

jurisdiction = VicTenancyJurisdiction()
```

### CorpusConfig fields

| Field | Required | Description |
|---|---|---|
| `qdrant_collection` | yes | Qdrant collection name for case decisions |
| `courts` | yes | List of court codes used to filter Qdrant payload. Must match the `court` field in your chunks |
| `leg_collection` | no | Collection containing legislation section chunks. Required for statute routing to work |
| `pg_database` | no | PostgreSQL database name (future use) |

### Statute routing

Statute routing forces specific legislation sections into the retrieval result for
question types that vector search frequently misses. Skip it if your corpus has no
dominant statute, or if you want to validate retrieval first before adding routing.

```python
# jurisdictions/vic_tenancy/routes.py
from core.routing import StatuteRoute

ROUTES: list[StatuteRoute] = [
    StatuteRoute(
        intent="repairs",
        include_any=(
            "repair", "not working", "broken", "maintenance",
            "landlord fix", "hasn't fixed", "won't fix",
        ),
        forced_sections=("VICLEG/RTA1997/s68",),
        synthetic_query=(
            "landlord obligation maintain premises good repair section 68 "
            "residential tenancies act victoria"
        ),
        notes="s68 - landlord repair obligations",
    ),
]
```

Route fields:

| Field | Required | Description |
|---|---|---|
| `intent` | yes | Machine label (used in debug output) |
| `include_any` | yes | Any of these substrings in the question triggers the route |
| `forced_sections` | yes | Section IDs to prepend to retrieval results |
| `synthetic_query` | yes | Embedded to locate forced sections in the leg collection |
| `include_all` | no | ALL of these must also match |
| `exclude_any` | no | If any of these match, skip this route |
| `leg_allow_list` | no | When set, only these section IDs appear as legislation anchors |
| `priority` | no | Highest priority wins when multiple routes define `leg_allow_list` |

Section IDs follow the pattern `XLEG/ACTID/sN`:

| Jurisdiction | Example |
|---|---|
| NZ | `NZLEG/RTA/s45` |
| NSW | `NSWLEG/RTA2010/s63` |
| Victoria | `VICLEG/RTA1997/s68` |

Legislation chunks in Qdrant must have `court = "XLEG"` and `case_id` matching
the section ID (e.g. `"VICLEG/RTA1997/s68"`).

### Smoke fixtures

```python
@property
def smoke_fixtures(self) -> list[SmokeFixture]:
    return [
        SmokeFixture(
            question="The heater hasn't worked for three weeks. Is the landlord responsible?",
            expected_sections=["VICLEG/RTA1997/s68"],
            description="repairs route",
        ),
        SmokeFixture(
            question="Can the landlord keep my bond for cleaning?",
            expected_sections=["VICLEG/RTA1997/s412"],
            forbidden_sections=["VICLEG/RTA1997/s19"],
            description="bond deduction route",
        ),
    ]
```

At least 3 fixtures covering your most important routes is expected before a PR.

### Optional overrides

These have working defaults. Only override when you need different behaviour.

| Property | Default | When to override |
|---|---|---|
| `legislation` | `None` | Live statute URL to anchor the LLM against |
| `web_verify` | `None` | DDG search verification after retrieval |
| `low_priority_sections` | `{}` | Suppress sections rarely relevant to most questions |
| `rewrite_prompt` | Core default | Custom query rewriting instruction |
| `max_question_chars` | `1200` | Shorter or longer question limit |
| `format_source_label` | `"Court - Date"` | Custom citation display in the UI |
| `extract_section` | Heading-aware | If the legislation site has unusual HTML structure |

Live legislation example:

```python
from core.jurisdiction import LegislationConfig

@property
def legislation(self) -> LegislationConfig:
    return LegislationConfig(
        acts={
            "RTA1997": "https://www.legislation.vic.gov.au/in-force/acts/residential-tenancies-act-1997/",
        },
        cache_ttl_seconds=3600,
    )
```

---

## Corpus ingestion

The API needs a populated Qdrant collection. The only constraint is the payload schema
in `schemas/qdrant_payload.schema.json`.

Required payload fields:

| Field | Type | Example |
|---|---|---|
| `document_id` | string | `"VCAT/2024/VSC/1234/chunk-3"` |
| `court` | string | `"VCAT"` (must match `corpus.courts`) |
| `court_name` | string | `"VCAT"` |
| `title` | string | `"Smith v Jones [2024] VCAT 1234"` |
| `date` | string | `"2024-03-15"` |
| `url` | string | Public URL for the source document |
| `text` | string | Chunk text (~120-word windows work well) |
| `source_type` | string | `"case"`, `"legislation"`, `"regulation"`, or `"guidance"` |

Legislation chunks additionally need:
- `case_id` set to the section ID (e.g. `"VICLEG/RTA1997/s68"`)
- `court` set to `"VICLEG"` (or your jurisdiction's legislation prefix)

Implement `ScraperBase` from `ingest/base.py`:

```python
from ingest.base import Chunk, ScraperBase

class VicTenancyScraper(ScraperBase):
    def iter_chunks(self, **kwargs):
        # fetch HTML from AustLII or legislation.vic.gov.au
        # parse, chunk, yield Chunk objects
        yield Chunk(
            document_id="VCAT/2024/1234/chunk-0",
            court="VCAT",
            court_name="VCAT",
            title="Smith v Jones [2024] VCAT 1234",
            date="2024-03-15",
            url="https://www.austlii.edu.au/...",
            text="...",
            source_type="case",
        )
```

Look at `ingest/base.py` for the full `Chunk` and `ScraperBase` interfaces.

---

## Test tiers

| Tier | Mark | Requires | What it checks |
|---|---|---|---|
| 1 - Retrieval | `retrieval` | Qdrant + corpus | Statute routing injects expected sections |
| 2 - Structural | `structural` | Qdrant + LLM | Answer format, citation count, length |
| 3 - LLM | `llm` | Qdrant + LLM | Semantic answer quality |

```bash
# Contract tests (no corpus)
pytest tests/core/test_jurisdiction_contract.py --jurisdiction vic_tenancy

# Tier 1 smoke tests
pytest tests/jurisdictions/test_smoke.py --jurisdiction vic_tenancy -m retrieval -v

# All tiers (requires LLM server)
pytest tests/ --jurisdiction vic_tenancy -v
```

---

## PR checklist

- [ ] Contract tests pass: `pytest tests/core/test_jurisdiction_contract.py --jurisdiction your_name`
- [ ] At least 3 smoke fixtures, all Tier 1 green
- [ ] `get_scraper()` returns a working scraper or raises `NotImplementedError` with a comment on status
- [ ] System prompt includes a disclaimer that answers are not legal advice
- [ ] No `print()` statements in jurisdiction code
- [ ] New jurisdiction listed in `README.md` supported jurisdictions table

---

## Project structure

```
astraea/
  core/               Runtime (api, pipeline, retriever, embedder, generator, browser, legislation)
  jurisdictions/      One package per jurisdiction
  apps/               Uvicorn entry points (one per jurisdiction)
  ingest/             Offline scrapers - not part of the API runtime
  tests/
    core/             Contract tests (all jurisdictions inherit these)
    jurisdictions/    Smoke tests (data-driven via jurisdiction.smoke_fixtures)
  schemas/            Qdrant payload JSON schema
  examples/           minimal_jurisdiction starter template
  deployment/         Docker Compose for local dev stack
```

---

## Questions

Open an issue on GitHub. For questions about NZ-specific law or corpus coverage,
open a discussion instead.
