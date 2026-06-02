# Opus 4.6 Feedback: Federated Retrieval + Re-ranking Design

---

## Summary of position

The diagnosis is correct: single-index vector search with hand-written route patches is a scaling dead-end. Federated parallel search with a cross-encoder re-ranker is the right architectural move. But the proposal underestimates what you'll lose when you deprecate routes, and overestimates what a cross-encoder can do without legal domain knowledge.

My suggestion: **implement federated search + cross-encoder re-ranking, but keep routes as hard constraints (not hints) for the first 3 months. Deprecate routes only after benchmarking proves the re-ranker matches or exceeds route-based quality on every regression test.**

---

## Where I agree

### ✅ The crowding problem is real

If `nz_legal` has 200 RTA chunks and 40 HHS2019 chunks, a single vector search with `top_k=6` will almost always return 5-6 RTA sections even when the question is about heating. Embedding similarity doesn't know about corpus imbalance. This is a well-known problem in information retrieval (document frequency bias).

Federated search with per-source `top_k` quotas is the textbook solution. Correct.

### ✅ Cross-encoder is the right re-ranker for production

`bge-reranker-v2-m3` is a strong choice:
- 568M params, runs on CPU in ~150ms for 30 pairs
- Trained on MS MARCO + multilingual data — handles legal English well
- No GPU contention with your generation model
- Deterministic: same input → same output (critical for regression testing)

The privacy argument against GPT-4o-mini / Haiku is also correct. For a free legal tool where users paste their personal rental situations, sending queries to OpenAI is a consent minefield.

### ✅ Option B (local LLM for reranking) correctly flagged as impractical

With `--parallel 1` and a single 8GB GPU, using Qwen3-8B for both re-ranking AND generation means serializing them. That's +3-5s latency added to every query. Not viable in the hot path. Good that the doc recommends it only for offline/batch.

### ✅ Migration path is sensible

Gradual migration with A/B comparison before deprecating routes is the right approach.

---

## Where I disagree or want to push back

### 1. Routes should not become "optional boost hints" in Phase 2

The document proposes:
> Routes become optional boost hints rather than hard overrides. A route can suggest "consider these sections" but the re-ranker makes the final call.

This is dangerous. Here's why:

Your routes encode **domain knowledge that no cross-encoder has**. For example:

| Route | What it knows |
|-------|---------------|
| `property_change` → s42A, s42B | "planted trees" → fixture/alteration consent (not s40 general tenant duties) |
| `bond` → s18 | "work and income" bond → s18 specifically (not s13 which is Smoke Alarms Regulations) |
| `wear_and_tear` → s49A, s49B | "damage claim" → exemplary damages + compensation provisions |

A cross-encoder scores (query, passage) similarity. It does **not** know:
- That "s13" resolves to Smoke Alarms Regulations, not "Form of agreement"
- That s16A (overseas landlord agent) is a false positive for bond queries
- That Schedule 1A penalty table rows look like section text but aren't

These are hard-won correctness constraints. Downgrading them to "+0.1 boost" means the re-ranker can override them with a wrong-but-higher-scoring passage.

**My proposal:** Keep routes as **hard floor constraints** (guaranteed inclusion in candidates, not removable by re-ranker). The re-ranker ranks *within* the candidate pool, but route-forced sections always make it into the pool:

```python
async def federated_retrieve(question, question_vector, jurisdiction):
    # Phase 1: federated search (per-source quotas)
    candidates = await federated_search(question_vector, jurisdiction.sources)
    
    # Phase 2: route injection (guaranteed candidates)
    matched_routes = match_routes(question, jurisdiction.routes)
    for route in matched_routes:
        for section_id in route.forced_sections:
            if section_id not in [c.id for c in candidates]:
                section = await fetch_section(section_id)
                candidates.append(section)
    
    # Phase 3: re-rank everything together
    ranked = reranker.rerank(question, candidates, top_k=8)
    
    # Phase 4: ensure route-forced sections survive (floor guarantee)
    forced_ids = {s for r in matched_routes for s in r.forced_sections}
    result = [c for c in ranked if c.id in forced_ids or c in ranked[:5]]
    
    return result
```

This gets you the best of both worlds:
- Re-ranker handles crowding (picks the best across sources)
- Routes guarantee critical sections aren't lost
- You can measure how often the re-ranker *would have* dropped a route-forced section (observability)
- When that number hits zero for 30 days, you can safely deprecate that specific route

### 2. The cross-encoder will underperform on legal reasoning queries

Cross-encoders are trained on "is this passage relevant to this query?" which works great for factual retrieval. But legal retrieval often requires reasoning:

**Example:** "My landlord hasn't fixed the broken oven for 3 months. What can I do?"

A cross-encoder will correctly score s45 (repair obligations) highly. But it may NOT score s50 (Tribunal orders) highly, because the passage text talks about "application to Tribunal" not "broken oven." Yet s50 is highly relevant — it's the remedy pathway.

Routes handle this by encoding expert knowledge: `repairs_maintenance` → s45 AND the Tribunal remedy section. A pure similarity re-ranker won't make this leap.

**Suggestion:** After implementing the cross-encoder, run your full `retrieval_gold.jsonl` benchmark comparing:
1. Routes only (current)
2. Federated + cross-encoder only (no routes)
3. Federated + cross-encoder + route floor (my proposal above)

I predict (3) will score highest because it combines empirical relevance scoring with expert domain constraints.

### 3. Per-source `top_k` allocation needs thought

The sketch shows:
```
search(nztt_moj, top_k=10)        # TT decisions
search(nz_legal, filter=RTA, top_k=6)
search(nz_legal, filter=HHS2019, top_k=4)
search(nz_legal, filter=NZLEG/BA2004, top_k=4)
```

Questions:
- Who decides these quotas? Are they static (hardcoded per jurisdiction) or dynamic (based on route match)?
- What happens when you add the Building Act with 200 sections? `top_k=4` might miss the right one.
- If the question is purely about HHS2019 heating, do you still waste 6 RTA slots + 10 TT decision slots?

**Suggestion:** Make `top_k` a property of the source registration, not hardcoded:

```python
@dataclass
class LegislationSource:
    act_id: str               # "RTA", "HHS2019", "BA2004"
    qdrant_filter: dict       # court prefix filter
    default_top_k: int        # baseline candidates
    boost_top_k: int          # when route suggests this act is relevant
```

When a route matches and its `forced_sections` belong to HHS2019, bump HHS2019's `top_k` from 4 to 8. This lets the federated search be informed by routes without hard-injecting specific sections.

### 4. The document doesn't address latency budget

Current retrieval (single search + route injection): ~100-200ms.

Proposed retrieval:
- N parallel Qdrant searches: ~50-100ms (parallel, so wall-clock is max of all)
- Cross-encoder inference on 30-50 pairs: ~150-300ms on CPU

Total: ~200-400ms. That's 2x the current retrieval latency.

Is this acceptable? For your single-user-at-a-time setup (parallel=1), probably yes — the LLM generation dominates at 5-30s. But document the latency budget explicitly so future changes don't regress:

```
Budget:
  Retrieval (federated search): < 150ms
  Re-ranking (cross-encoder):   < 300ms
  Total pre-generation:         < 500ms (currently ~150ms)
  Generation (LLM):             5-30s (unchanged)
```

### 5. Model choice: consider `bge-reranker-v2-m3` vs lighter alternatives

`bge-reranker-v2-m3` is 568M params. For 30-50 pairs on CPU:
- Cold inference: ~300ms
- Warm inference: ~150ms

If you want sub-100ms, consider:
- `cross-encoder/ms-marco-MiniLM-L-6-v2` (22M params, ~30ms for 30 pairs on CPU)
- `BAAI/bge-reranker-base` (109M params, ~80ms)

The accuracy gap between MiniLM-L6 and bge-reranker-v2-m3 on MS MARCO is ~2-3% NDCG@10. For your use case (legal passages, already pre-filtered by embedding search), the smaller model may be sufficient.

**Suggestion:** Benchmark both on your `retrieval_gold.jsonl`. If MiniLM-L6 matches bge-v2-m3 on your data, use the faster model.

### 6. Missing: what happens when the re-ranker is wrong?

The current route system has a clear debugging story: thumbs-down → check `statute_routing` in feedback → see which route fired → fix the route. It's deterministic and greppable.

With a cross-encoder re-ranker, the debugging story becomes:
- User got wrong legislation section
- Why? "The cross-encoder scored passage X at 0.73 and passage Y at 0.71, so X won"
- What do you do about it? Retrain the model? That's not feasible.

**You need an escape hatch.** When the re-ranker is wrong, you need a way to force correct behavior without retraining. That escape hatch IS routes.

So the observability story should be:
```json
{
  "reranker": {
    "candidates_in": 34,
    "top_8_selected": ["NZLEG/RTA/s45", "NZLEG/HHS2019/s8", ...],
    "route_forced_included": ["NZLEG/RTA/s45"],
    "route_forced_dropped_by_reranker": [],
    "scores": {"NZLEG/RTA/s45": 0.89, "NZLEG/HHS2019/s8": 0.84, ...}
  }
}
```

Log this in `feedback_full.jsonl`. When a thumbs-down comes in, you can see exactly what the re-ranker did and whether a route override would have helped.

---

## Additional suggestions

### A. Hybrid scoring: combine embedding similarity + cross-encoder

Don't throw away the original embedding scores. Use a weighted combination:

```python
final_score = alpha * embedding_score + (1 - alpha) * cross_encoder_score
```

Start with `alpha = 0.3`. The embedding score provides a prior ("this passage is in the right semantic neighborhood"), the cross-encoder refines it ("this passage directly answers the question"). This is more robust than using cross-encoder scores alone.

### B. Consider re-ranking legislation and decisions separately

Legislation sections and case decisions serve different purposes:
- Legislation: "what does the law say?" (authority)
- Decisions: "how was it applied?" (precedent)

You want BOTH in the context, regardless of relative scores. A highly relevant decision should not crowd out the authoritative legislation section.

**Proposal:** Re-rank within two pools, then merge:

```python
leg_candidates = [c for c in all_candidates if c.source_type == "legislation"]
case_candidates = [c for c in all_candidates if c.source_type == "case"]

top_legislation = reranker.rerank(query, leg_candidates, top_k=3)
top_decisions = reranker.rerank(query, case_candidates, top_k=5)

context = top_legislation + top_decisions  # guaranteed mix
```

This prevents a pure relevance ranking from returning 8 decisions and 0 legislation (or vice versa). You always get statute context AND application context.

### C. Warm up the cross-encoder at startup

Cross-encoders have a cold-start penalty (model loading + first inference JIT compilation). Add a warmup call in the FastAPI `lifespan` event:

```python
@asynccontextmanager
async def lifespan(app):
    reranker.rerank("warmup query", [dummy_result], top_k=1)
    yield
```

This ensures the first real user query doesn't eat a 2-3s model load.

### D. Consider ColBERT-style late interaction for the future

If you outgrow cross-encoders (too slow at scale, or need to re-rank 100+ candidates), ColBERT-style models (e.g., `colbert-ir/colbertv2.0`) offer a middle ground: pre-compute token embeddings for all passages at index time, then do fast MaxSim scoring at query time. This gives cross-encoder-quality reranking at bi-encoder speed.

Not needed now (you're re-ranking 30-50 candidates), but worth noting for when you scale to multiple jurisdictions with larger corpora.

---

## My overall recommendation

```
1. Implement federated search (per-source parallel queries with configurable top_k)
2. Add bge-reranker-v2-m3 (benchmark MiniLM-L6 as cheaper alternative)
3. Keep routes as FLOOR GUARANTEES, not hints (route-forced sections always in pool)
4. Re-rank within two pools (legislation + decisions), merge results
5. Log full reranker scores in feedback_full.jsonl for debugging
6. Run A/B on retrieval_gold.jsonl: (routes only) vs (federated+rerank) vs (federated+rerank+route floor)
7. Deprecate individual routes ONLY when data shows re-ranker matches their quality for 30+ days
8. Warmup cross-encoder at startup
9. Document latency budget explicitly
```

**Estimated implementation effort:**
- `core/reranker.py` + model download: 2 hours
- `federated_search()` in retriever: 2 hours
- Integration in `app.py` (replace `_retrieve_anchor`): 3 hours
- Benchmark comparison script: 2 hours
- Observability (log reranker decisions in feedback): 1 hour
- Total: ~10 hours of focused work

**Expected outcome:**
- Crowding eliminated (HHS2019, Building Act get fair representation)
- New Acts added by config, not code (register source + scrape + done)
- Routes become a safety net, not the primary retrieval mechanism
- Latency increase: +200-300ms (negligible vs 5-30s generation)

---

## Risk: the cross-encoder is a black box

The biggest risk in this proposal is replacing a **debuggable, deterministic** system (routes) with a **opaque, statistical** one (cross-encoder). When routes are wrong, you edit a Python dict and redeploy. When a cross-encoder is wrong, you... can't do much except add a route override.

This is exactly why I advocate keeping routes as floor guarantees indefinitely. They're your escape hatch. The re-ranker handles the common case; routes handle the edge cases you've already diagnosed.

Over time, as you accumulate data showing the re-ranker is reliable for specific intents, you can retire those routes one by one. But never remove the mechanism entirely — you'll always discover new edge cases that need a manual override.

---

## Response to GPT-5.5's feedback

After reading GPT-5.5's analysis on the same design document, I want to note where we converge, where we diverge, and how GPT-5.5's points change my position.

### Where GPT-5.5 and I fully agree

1. **Federated search is the correct fix for crowding.** No disagreement — per-Act quotas before ranking is textbook IR.
2. **Routes must stay as hard guarantees, not hints.** We both reject the document's "optional boost" framing.
3. **External LLM reranking is off the table for production** (privacy).
4. **Benchmark before replacing anything.** Both of us demand regression proof.
5. **The planted-trees / bond-proof / wear-and-tear regressions are the critical test set.** GPT-5.5 lists the exact same cases I would.

### Where we diverge

| Point | GPT-5.5 | Me (original) |
|-------|---------|---------------|
| Cross-encoder in production | No — benchmark/debug only until proven | Yes — ship it with route floor guarantee |
| Alternative ranking | Composite formula (7+ weighted signals) | Cross-encoder handles it; routes are the safety net |
| Phase approach | 4 phases, reranker only in Phase 3 | Ship reranker in Phase 1 alongside routes |
| Re-rank pools | Not addressed | Separate legislation + decision pools, then merge |

### GPT-5.5's strongest point (that changes my position)

GPT-5.5 states:

> Your own benchmarks already showed generic rerankers can hurt legal retrieval by promoting semantically dense but legally less useful chunks.

This is critical evidence I did not have when writing my original analysis. If `bge-reranker-v2-m3` (or a similar cross-encoder) was already tested on this data and **regressed** retrieval quality, then my recommendation to ship it in production immediately is too aggressive.

A cross-encoder trained on MS MARCO learns: "does this passage answer this question?" But legal retrieval often needs: "is this the *authoritative* passage?" — a distinction the model has no training signal for. An explanatory government guidance page about bonds might score higher than the terse text of s18 itself, but s18 is what the LLM needs to cite.

### GPT-5.5's composite scoring formula — my concern

GPT-5.5 proposes:

```
final_score = vector_score + federated_source_boost + route_match_boost
            + section_title_exact_match_boost + legal_allow_list_bonus
            - low_priority_section_penalty - failed_anchor_penalty
            + optional_cross_encoder_score
```

This is essentially a hand-tuned learning-to-rank formula with 7+ parameters. My concern:

- **Who tunes the weights?** Each weight is a hyperparameter. With 7 signals, you have a 7-dimensional space to search. Without a training set of (query, ideal_ranking) pairs, you're tuning by hand and gut — which is what routes already do more transparently.
- **It trades one maintenance burden for another.** Routes are ugly but greppable: "this query pattern → these sections." A composite scorer is harder to debug: "why did this section score 0.73 instead of 0.75?"
- **It's basically a linear model.** If you're going to learn a scoring function, you might as well use a model trained on relevance judgments (i.e., a cross-encoder). A hand-tuned linear combination is a poor man's model.

However, GPT-5.5's formula has one real advantage: **every signal is interpretable and overridable.** If `low_priority_section_penalty` is wrong, you change one number. If a cross-encoder is wrong, you have no lever.

### My revised position

After considering GPT-5.5's evidence about prior reranker regressions:

```
Phase 1 (ship now):
  - Federated per-Act search (replaces single global search)
  - Routes stay exactly as-is (floor guarantee, allow-lists, suppressions)
  - Cross-encoder scores logged in feedback_full.jsonl (NO ranking impact)
  - This alone fixes the crowding problem

Phase 2 (after 50+ logged queries):
  - Compare cross-encoder rankings vs actual route-based results
  - Measure: how often would cross-encoder have dropped a route-forced section?
  - Measure: how often does cross-encoder surface something routes missed?

Phase 3 (data-driven decision):
  IF cross-encoder agrees with routes 90%+ of the time:
    → Promote to production ranking with route floor (my original proposal)
  IF cross-encoder frequently disagrees:
    → GPT-5.5's composite scorer approach wins
    → Or: fine-tune cross-encoder on your legal relevance judgments
```

This is more conservative than my original recommendation but more progressive than GPT-5.5's "Phase 3 maybe." The key difference: I'm saying log cross-encoder scores from day 1 so you accumulate decision data immediately, rather than waiting months before even loading the model.

### Where GPT-5.5 under-specifies

GPT-5.5 doesn't address:
1. **Two-pool re-ranking** (legislation vs decisions separately) — important to prevent decisions crowding out statutes or vice versa
2. **Latency budget** — federated search adds parallel queries; composite scoring adds computation; neither is free
3. **What happens when composite scorer is wrong** — same debuggability problem as cross-encoder, just with more levers
4. **Frontend/UX implications** — if ranking changes, source card order changes, confidence indicators may need updating

### Final synthesis: the best architecture

Taking the strongest ideas from both analyses:

```
1. Federated per-Act search with configurable top_k     [both agree]
2. Routes as floor guarantees (always in candidate pool) [both agree]
3. Two-pool ranking: legislation + decisions separately  [my addition]
4. Cross-encoder scores LOGGED but not used for ranking  [GPT-5.5's caution + my observability]
5. Route allow-lists and suppressions unchanged          [both agree]
6. Promote cross-encoder to production ONLY with data    [revised — more conservative than my original]
7. No external API reranking in production               [both agree]
```

The one thing I'd push back on from GPT-5.5: don't build the 7-signal composite scorer unless the cross-encoder demonstrably fails. It's significant engineering for an approach that's essentially a worse version of a trained model. Try the trained model first (in logging mode), and only fall back to hand-tuned scoring if it can't learn your domain.
