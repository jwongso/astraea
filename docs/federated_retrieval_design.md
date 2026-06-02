# Federated Retrieval + Re-ranking Design

**Status:** Proposed  
**Context:** Replace the current route-injection system with per-source parallel
search and a re-ranking step that selects the most relevant legislation sections.

---

## Problem with current architecture

The current legislation retrieval does one vector search across the entire
`nz_legal` collection (RTA + HHS2019 + future acts). Results are sorted by
embedding similarity score alone. This causes two failure modes:

1. **Crowding** - many moderately-relevant RTA sections outrank a highly relevant
   HHS2019 section simply because there are more RTA chunks in the index.
2. **Routing brittleness** - we patch the first failure mode by hand-writing routes
   that force-inject specific sections for known question patterns. Every new Act
   added to the corpus needs new routes or it will be systematically underrepresented.

As the legislation corpus grows (Building Act, HHS, RMA, district plan rules) the
route table becomes unmanageable.

---

## Proposed architecture

### Phase 1 - Federated parallel search

Instead of one search across all legislation, run one search per registered Act
(filtered by `court` prefix in Qdrant), all in parallel:

```
User question (rewritten)
        |
        +---> asyncio.gather(
        |         search(nztt_moj, top_k=10),        # TT decisions
        |         search(nz_legal, filter=RTA, top_k=6),
        |         search(nz_legal, filter=HHS2019, top_k=4),
        |         search(nz_legal, filter=NZLEG/BA2004, top_k=4),
        |         ...one per registered Act
        |     )
        |
        v
   Pool all candidates
   (decisions + legislation sections, ~30-50 total)
        |
        v
   Re-ranker
   (scores each candidate for relevance to question)
        |
        v
   Top N selected (e.g. 5 decisions + 3 legislation sections)
        |
        v
   Build context + generate answer
```

Each Act gets a guaranteed quota of candidates before re-ranking. The re-ranker
then picks the best across all sources - so a highly relevant HHS2019 section
beats a loosely relevant RTA section naturally, without any manual routing.

### Phase 2 - Route deprecation

Routes become optional boost hints rather than hard overrides. A route can suggest
"consider these sections" but the re-ranker makes the final call. Eventually routes
are removed entirely as the re-ranker handles all cases.

---

## Re-ranker options

The re-ranker receives: the question + N (passage, score) pairs and outputs a
relevance score or ranking for each.

### Option A - Cross-encoder model (Recommended for v1)

A dedicated bi-encoder/cross-encoder model like `BAAI/bge-reranker-v2-m3` or
`cross-encoder/ms-marco-MiniLM-L-6-v2`. Takes (query, passage) pairs and outputs
a relevance score directly.

**Pros:**
- Runs locally, no API cost, no privacy concern
- Fast: ~100-200ms for 30 pairs on CPU
- No GPU needed - runs alongside the embedding model without contention
- Deterministic - same input always gives same output
- Sub-100ms with a smaller model like MiniLM-L6

**Cons:**
- Less flexible than an LLM - can score relevance but cannot explain reasoning
- Needs a separate model download (~300-500MB)
- May miss nuanced legal relevance that requires domain understanding

**Best for:** High-volume production where latency matters and per-query cost
must be zero.

---

### Option B - Local LLM (Qwen3.6-35B already running)

Use the already-loaded generation model with a short structured prompt:

```
Given this question: "..."
Which of the following passages are directly relevant? Output a JSON array
of indices ranked by relevance. Output [] if none are relevant.

[0] NZLEG/HHS2019/s8: "Main living room must have qualifying heater..."
[1] NZLEG/RTA/s45: "Landlord's responsibility to maintain premises..."
...
```

**Pros:**
- No additional model or API needed - already loaded
- Can reason about legal relevance, not just semantic similarity
- Can handle nuanced cases a cross-encoder would miss
- Free to run

**Cons:**
- Adds 2-5 seconds latency per query (model already handling generation queue)
- Potential GPU memory contention if generation and re-ranking run simultaneously
- Non-deterministic (temperature > 0)
- Overkill for simple relevance scoring

**Best for:** Offline batch re-ranking, or as a quality check on a sample of
live queries rather than in the hot path.

---

### Option C - GPT-4o-mini (OpenAI)

Fast, cheap external API. At $0.15/1M input tokens, re-ranking 30 short passages
costs roughly $0.001-0.002 per query.

**Pros:**
- Very fast (~400-600ms round-trip)
- Strong at structured output (JSON ranking)
- No local resources needed
- Easy to prototype with

**Cons:**
- Every user question + retrieved passages sent to OpenAI - privacy concern for a
  legal tool where users may share sensitive rental situations
- Ongoing per-query cost (small but real at scale)
- External dependency - outage or rate limit breaks the pipeline
- Adds network round-trip latency
- OpenAI terms of service allow training on API inputs by default (opt-out needed)

**Privacy note:** For a legal Q&A tool, sending user questions to a third-party
API without explicit user consent is a real concern. Users asking about their rental
situation may not expect their question to leave your server. Mitigations exist
(anonymization, opt-out, terms disclosure) but add complexity.

**Best for:** Prototyping and quality benchmarking. Not recommended for production
without a privacy disclosure.

---

### Option D - Claude Haiku 4.5 (Anthropic)

Similar position to GPT-4o-mini but with Anthropic's privacy stance (no training
on API inputs by default without consent).

**Pros:**
- Fastest Claude model, comparable cost to GPT-4o-mini
- Anthropic does not train on API inputs by default
- Strong at structured reasoning tasks
- Good fit if you are already using Claude API for other things

**Cons:**
- Same external dependency and latency concerns as GPT-4o-mini
- Still sends user data off-premise

**Best for:** If you need an external LLM for re-ranking and privacy of the API
call is acceptable to you, Haiku is the better choice over GPT-4o-mini given the
default no-training policy.

---

### Option E - Claude Opus 4.8 (Anthropic)

The most capable model. Relevant for answer generation, not re-ranking.

**For re-ranking:** Overkill. Slower and more expensive than Haiku with no
meaningful accuracy gain on a structured re-ranking task. Do not use Opus for
re-ranking.

**For answer generation:** Genuinely interesting for complex multi-issue legal
questions (like Q11 - the 8-item landlord neglect list) where the answer requires
synthesizing across many sources and structuring a nuanced response. Could be
offered as a "deep analysis" mode at higher latency. Cost at ~$15/1M output tokens
makes it unsuitable as the default generation model for a free community tool.

**Best for:** Optional premium generation path for complex queries, or offline
analysis of difficult cases in the question log.

---

## Recommendation

| Role | Recommendation | Rationale |
|---|---|---|
| Re-ranking (production) | Cross-encoder (bge-reranker-v2-m3) | Local, fast, free, no privacy risk |
| Re-ranking (prototype) | Local Qwen3.6-35B | Already loaded, no new dependency |
| Answer generation (default) | Local Qwen3.6-35B | Already running, good quality |
| Answer generation (complex) | Claude Opus 4.8 (opt-in) | Best reasoning, worth the cost for hard cases |
| Benchmarking / eval | GPT-4o-mini or Claude Haiku | Cheap, fast, useful for comparing outputs |

---

## Implementation sketch

```python
# core/retriever.py addition
async def federated_search(
    question_vector: list[float],
    sources: list[tuple[VectorStore, str | None, int]],
    # (store, court_filter, top_k) per source
) -> list[SearchResult]:
    tasks = [
        store.search_async(question_vector, top_k=k, court=court)
        for store, court, k in sources
    ]
    results = await asyncio.gather(*tasks)
    return [r for batch in results for r in batch]  # flatten


# core/reranker.py (new)
class CrossEncoderReranker:
    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3"):
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(model)

    def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int = 8,
    ) -> list[SearchResult]:
        pairs = [(query, c.text) for c in candidates]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:top_k]]
```

The `_retrieve_anchor` function in `api.py` is replaced by `federated_search` +
`reranker.rerank()`. Routes are kept temporarily as a boost signal (bump score
by +0.1 for forced sections) and phased out once the re-ranker proves reliable.

---

## Migration path

1. Add `CrossEncoderReranker` to `core/reranker.py`
2. Add `search_filtered_by_court` method to `VectorStore`
3. Replace `_retrieve_anchor` with federated + rerank in `api.py`
4. Run A/B comparison: route-based vs federated on the question log
5. Phase out routes once re-ranker coverage is confirmed
6. Register new Acts in a `LEGISLATION_SOURCES` config rather than writing routes

---

_Last updated: 2026-06-02_
