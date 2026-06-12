# StatuteRoute Redesign — Opus 4.6 Feedback

---

## Summary judgment

The design document correctly identifies three real problems: routing logic scattered across call sites, keyword collision on broad terms, and no way to express "bias retrieval without forcing sections." The proposed `RouteDecision` encapsulation is clearly correct and should ship first. The two-tier trigger system (precise/broad+context) solves a real collision problem elegantly.

However, the full proposal—RouteStrength tiers + specificity scoring + retrieval_passes—is solving tomorrow's problems at today's scale. You have 8 routes. The complexity budget should match.

**My recommended implementation order:**

```
1. RouteDecision encapsulation      (high value, low risk, ship now)
2. Negative test fixtures           (highest testing value, ship now)
3. Two-tier triggers                (solves real collisions, ship next)
4. RouteStrength tiers              (defer until 15+ routes exist)
5. Specificity scoring              (defer until two HARD routes actually collide)
```

---

## What the current code actually does well

Before redesigning, acknowledge what works in the 273-line `rta_routes.py`:

1. **Readable** — a non-programmer could audit the route table and understand what triggers what
2. **Fast** — substring matching on 8 routes is effectively free (<1ms)
3. **Debuggable** — `route_debug_info()` emits exactly which terms fired
4. **Correct** — the regression suite passes; your prior bugs were in retrieval/ranking, not routing
5. **Contained** — `match_routes()` + `get_dominant_leg_allow_list()` + `allow_section()` is the entire public surface

The proposal should preserve these qualities. Complexity that harms readability or auditability is wrong for a system where the route table IS the domain knowledge.

---

## What I agree with

### 1. `RouteDecision` is clearly correct — ship it

The current pattern:

```python
# anchor.py
matched = match_routes(original, rewritten)
forced = ... derive from matched ...
allow_list = get_dominant_leg_allow_list(matched)
synthetic_queries = [r.synthetic_query for r in matched]
boosted = ... derive from forced ...

# api.py (again!)
matched = match_routes(original, rewritten)
debug = route_debug_info(matched, ...)
```

This is three call sites computing overlapping derived state. One wrong derivation = retrieval bug that only shows up on specific query patterns. `RouteDecision` as the single computation point eliminates this class of bug.

**Concrete implementation I'd ship:**

```python
@dataclass(frozen=True)
class RouteDecision:
    triggered: bool
    matched_intents: tuple[str, ...]
    trigger_terms: tuple[str, ...]
    forced_sections: tuple[str, ...]
    leg_allow_list: tuple[str, ...]
    boosted_act_ids: frozenset[str]
    synthetic_queries: tuple[str, ...]

def build_route_decision(original: str, rewritten: str) -> RouteDecision:
    """Single entry point. Computes everything. Callers never inspect raw routes."""
    ...
```

Note I've dropped `retrieval_passes` from the first version (see "What I disagree with" below).

### 2. Negative test fixtures — highest-value testing change

This is the most important part of the document. The insight:

> A route without a negative fixture is a route that could be silently causing retrieval pollution on every similar question, with no test to catch it.

The proposed `SmokeFixture` extension with `expected_routes` / `forbidden_routes` is clean and testable without Qdrant. I'd ship this immediately, even before any route redesign:

```python
# Pure routing unit test, no HTTP, no GPU, no Qdrant
def test_property_change_does_not_fire_on_repairs():
    decision = build_route_decision(
        "The garden fence is broken and leaking",
        "tenant reports broken fence in garden area"
    )
    assert "property_change" not in decision.matched_intents
```

This is the kind of test that catches regressions before they reach users. Write one positive + one negative per route. That's 16 tests for 8 routes. Can be done in an afternoon.

### 3. Two-tier triggers solve a real problem

The "garden" collision is real:

```
"I planted trees in the garden without consent" → property_change ✓
"The garden fence is broken and leaking"        → property_change ✗ (should be repairs)
```

The precise/broad+context split handles this cleanly:

```python
StatuteRoute(
    intent=RouteIntent.PROPERTY_CHANGE,
    include_any_precise=("fixture", "alteration", "plant trees", "planted", "written consent"),
    include_any_broad=("garden", "fence", "tree", "backyard", "lawn"),
    require_context_any=("without consent", "without permission", "landlord consent",
                         "alteration", "improvement", "minor change"),
    ...
)
```

"Garden" alone doesn't fire. "Garden" + "without consent" fires. This is the right level of expressiveness for the problem.

### 4. Design principle: routes are recall guarantees, not ranking

This is exactly the conclusion from the federated retrieval analysis. Routes ensure the right sections are in the candidate pool. The scorer decides order. This keeps responsibilities clean and means route bugs only affect recall (missing sections), not answer quality (wrong section ranked first).

### 5. `exclude_any` used more aggressively

The document's observation that `exclude_any` is underused is correct. Before building two-tier triggers, try aggressive exclusions first — they're simpler and solve many of the same collision problems:

```python
# property_change: exclude repair-context vocabulary
exclude_any=("not repaired", "not fixed", "won't fix", "broken",
             "not working", "healthy homes", "plumbing"),
```

This is cheaper than two-tier triggers for routes where the competing context has distinctive vocabulary.

---

## What I disagree with (or would defer)

### 1. `RouteStrength` adds cognitive overhead without current payoff

The HARD/MEDIUM/SOFT distinction answers one question: "which route's allow-list wins?" But today:
- Only `property_change` defines a `leg_allow_list`
- No two HARD routes compete for allow-list dominance yet
- The allow-list winner is trivially determined (it's the only one that has one)

RouteStrength is solving for a future where 5+ HARD routes compete. You have 1. The existing `priority` integer handles this case with less conceptual overhead.

**When to add it:** When you have 3+ routes with `leg_allow_list` and the integer priority feels arbitrary. That's probably at 15+ routes total.

**Risk of adding too early:** Every new route author now has to think "is this HARD, MEDIUM, or SOFT?" when the distinction only matters for allow-list propagation. This makes the authoring interface harder without adding recall value.

### 2. Specificity scoring is premature optimization

```python
def _route_specificity(route: StatuteRoute, q: str) -> int:
    score = 0
    for term in route.include_any:
        if term in q:
            score += 3 if " " in term else 1
    ...
```

This scoring exists to tiebreak two competing HARD routes with allow-lists. Currently you have ONE route with an allow-list. Specificity scoring has zero value until:
1. You add a second HARD route with an allow-list
2. Both fire on the same query
3. Their allow-lists conflict

That's a triple conjunction that hasn't happened yet. When it does, add specificity scoring. Until then, route list order or the existing `priority` integer handles it fine.

### 3. `retrieval_passes` couples routing to retrieval implementation

```python
retrieval_passes: tuple[tuple[str, tuple[str, ...]], ...]
# ^ (synthetic_query, forced_sections_for_this_route) per matched route
```

This field exists so `anchor.py` can run one vector search per matched route. But:
- It encodes HOW retrieval works inside the routing decision
- If retrieval changes (e.g., federated per-Act search replaces per-route search), this field becomes wrong
- The routing module shouldn't know about vector search passes

**Better alternative:** `RouteDecision` provides `synthetic_queries` (flat list). `anchor.py` decides how many vector searches to run and how to use them. The retrieval strategy is retrieval's concern, not routing's.

If `anchor.py` needs the per-route grouping, let it derive it from `matched_intents` + the route table. Don't bake retrieval implementation into the decision object.

### 4. SOFT routes may not need to exist as routes at all

A SOFT route has no forced sections, no allow-list, no injection. It only provides a `synthetic_query` to bias vector search. But that's what the query rewrite already does — it reformulates the user question into better retrieval language.

**Question:** If a SOFT route only provides a synthetic query, why isn't it just a better query rewrite? The rewrite prompt could say "if the question is about flatmate agreements, include the phrase 'sham flatmate agreement section X'."

The answer might be: SOFT routes are faster than LLM query rewrites (no inference cost). Fair. But then they're just a lookup table of search-biasing strings, not really "routes" in the same sense as HARD/MEDIUM. Consider naming them differently (e.g., `SearchHint`) to avoid conflating their role with actual recall-guarantee routes.

---

## My proposed alternative: incremental evolution

Instead of one big redesign, ship three independent changes that compound:

### Change 1: `RouteDecision` encapsulation (1-2 hours)

```python
# routing.py — new public interface

@dataclass(frozen=True)
class RouteDecision:
    triggered: bool
    matched_intents: tuple[str, ...]
    trigger_terms: tuple[str, ...]
    forced_sections: tuple[str, ...]
    leg_allow_list: tuple[str, ...]
    boosted_act_ids: frozenset[str]
    synthetic_queries: tuple[str, ...]
    suppressed_sections: tuple[str, ...]

def build_route_decision(original: str, rewritten: str) -> RouteDecision:
    """Single public entry point. Returns everything callers need."""
    q = normalize_query(original + " " + rewritten)
    matched = _match_routes(q)
    forced = _merge_forced_sections(matched)
    allow = _get_dominant_allow_list(matched)
    boosted = frozenset(s.rsplit("/", 1)[0] for s in forced)
    synth = tuple(dict.fromkeys(r.synthetic_query for r in matched))
    triggers = _extract_trigger_terms(matched, q)
    suppressed = _compute_suppressed(q)
    return RouteDecision(
        triggered=bool(matched),
        matched_intents=tuple(r.intent.value for r in matched),
        trigger_terms=triggers,
        forced_sections=forced,
        leg_allow_list=allow,
        boosted_act_ids=boosted,
        synthetic_queries=synth,
        suppressed_sections=suppressed,
    )
```

**Result:** Three call sites collapse to one. `anchor.py` and `api.py` receive a flat decision object. Zero behaviour change, pure refactor.

### Change 2: Negative fixtures (1-2 hours)

Add `expected_routes` and `forbidden_routes` to `SmokeFixture`. Write 8+ pure routing tests (no Qdrant needed):

```python
ROUTE_FIXTURES = [
    # Positive
    RouteFixture("planted trees in backyard without consent",
                 expected_routes=["property_change"],
                 forbidden_routes=["repairs_maintenance"]),
    # Negative
    RouteFixture("garden fence is broken and leaking",
                 expected_routes=["repairs_maintenance"],
                 forbidden_routes=["property_change"]),
    # Overlap test
    RouteFixture("carpet is worn out after 8 years",
                 expected_routes=["wear_and_tear"],
                 forbidden_routes=["property_change"]),
]
```

**Result:** Collision bugs become visible before they reach users. Every future route change runs against this suite.

### Change 3: Two-tier triggers for the 2-3 routes that need it (1 hour)

Only `property_change` and `repairs_maintenance` have demonstrated collision problems. Add `include_any_precise` / `include_any_broad` / `require_context_any` to those two routes. Leave the other 6 unchanged.

Alternatively, try aggressive `exclude_any` first — it might be enough:

```python
StatuteRoute(
    intent=RouteIntent.PROPERTY_CHANGE,
    include_any=(...),
    exclude_any=(
        "not repaired", "not fixed", "won't fix", "broken",
        "not working", "healthy homes", "plumbing", "leak",
        "mould", "mold", "damp", "landlord obligation",
    ),
    ...
)
```

If `exclude_any` handles the known collisions without needing two-tier triggers, that's simpler. Deploy two-tier only if exclusions aren't expressive enough.

---

## Answers to the open questions

**Q1: `retrieval_passes` shape**
Drop it from `RouteDecision`. Let `anchor.py` derive its own search plan from `synthetic_queries` + route metadata. Routing shouldn't encode retrieval implementation.

**Q2: Public surface of `routing.py`**
`build_route_decision` + `StatuteRoute` + `RouteDecision` + `ROUTES` list. That's it. `_match_routes` becomes private. For testing, test through `build_route_decision` — if you need to test matching in isolation, make a `_match_routes` a module-level function (underscore prefix) that tests can import but isn't part of the public contract.

**Q3: `allow_section` boundary**
Keep it in `anchor.py`. It operates on retrieved results, not routing decisions. Moving it into `RouteDecision` would mean the decision object needs to know about post-retrieval state, which violates the clean "routes decide recall, scorer decides order" principle.

**Q4: `RouteStrength` vs `priority`**
Keep `priority` only. Drop `RouteStrength` for now. When you have 3+ routes with `leg_allow_list` competing, introduce strength tiers. Until then, the integer is sufficient and simpler to author.

**Q5: Context term quality for broad triggers**
Yes, require context terms to be multi-word phrases (2+ words) or highly specific single words (e.g., "alteration", "fixture" — not "tenant", "landlord", "repair"). A lint rule in the test suite could enforce this:

```python
for route in ROUTES:
    for term in route.require_context_any:
        assert " " in term or term in ALLOWED_SINGLE_WORD_CONTEXT_TERMS, \
            f"Context term '{term}' is too broad - use a phrase"
```

**Q6: `include_any` retirement**
Keep it as an alias for "all precise." Most routes don't need the precise/broad split. Forcing every route to use two fields when one suffices creates noise. The migration path: routes that have collision problems get split into precise/broad. Routes that don't, keep `include_any`.

**Q7: SOFT route forced sections enforcement**
Enforce at the dataclass level with a `__post_init__` validator:

```python
def __post_init__(self):
    if self.strength == RouteStrength.SOFT and self.forced_sections:
        raise ValueError(f"SOFT route {self.intent} cannot have forced_sections")
```

Catch mistakes at definition time, not at runtime in production.

**Q8: Legal scorer interface**
The scorer should receive:
```python
def score_candidates(
    candidates: list[RetrievedChunk],
    route_decision: RouteDecision,
    query: str,
) -> list[ScoredChunk]:
```

It uses `RouteDecision.boosted_act_ids` as one signal among many. The scorer owns ranking; routes own recall. Don't let the scorer reach back into the route table — it operates on the decision object only.

**Q10: Synthetic query cache**
No change needed. The cache is keyed on the string content of the synthetic query. Whether those strings come from iterating raw routes or from `RouteDecision.synthetic_queries`, the cache key is the same. The refactor is transparent to caching.

---

## Risk assessment

| Change | Value | Risk | Ship? |
|--------|-------|------|-------|
| `RouteDecision` encapsulation | High — eliminates scattered derivation bugs | Very low — pure refactor | Now |
| Negative fixtures | Very high — catches collisions before users see them | Zero — additive tests | Now |
| Aggressive `exclude_any` | Medium — fixes known collisions with zero new concepts | Low — can cause under-matching if too aggressive | Now, carefully |
| Two-tier triggers | Medium — elegant solution for genuinely ambiguous terms | Low — new concept for route authors | After exclude_any proves insufficient |
| `RouteStrength` tiers | Low at current scale | Medium — adds conceptual overhead | Defer until 15+ routes |
| Specificity scoring | Zero at current scale | Medium — premature abstraction | Defer until collision observed |
| `retrieval_passes` in decision | Negative — couples routing to retrieval | Medium — wrong abstraction boundary | Don't ship |

---

## Bottom line

The design thinking is sound. The principles are correct. But **ship the refactors in order of immediate value, not as one monolithic redesign:**

1. `RouteDecision` — eliminates scattered logic, zero behaviour change
2. Negative fixtures — highest testing value per hour invested
3. `exclude_any` expansion — cheapest collision fix
4. Two-tier triggers — only where exclusions aren't enough
5. RouteStrength / specificity — only when the route table outgrows integer priority

The current 8-route system's main problem is not architectural — it's that routing logic leaks into `anchor.py`. Fix the encapsulation first. The matching expressiveness can evolve incrementally as new routes expose real collisions, with negative fixtures catching regressions along the way.
