# StatuteRoute Redesign

Status: brainstorm - not yet implemented

---

## Design Principle

**Routes are recall guarantees, not a ranking system.**

```
StatuteRoute  = recall guarantee   (right sections always present)
Federated retrieval = broad candidate discovery
Legal scorer  = final ordering
```

Not:

```
StatuteRoute  = everything
```

The canonical pipeline:

```
1. Rewrite query
2. Build RouteDecision
3. Add forced sections          <- route responsibility ends here
4. Run federated per-Act search
5. Apply dominant allow-list    <- HARD routes only
6. Suppress known false positives
7. Validate anchors
8. Rank using legal scorer      <- routes do NOT influence this
9. Build context
```

Routes keep the right sections in the candidate pool. The scorer decides order.
This keeps routes small, purposeful, and easy to audit.

Implications for the proposals below:

- **RouteStrength dominance** only needs to answer one narrow question: which
  HARD route's allow-list applies. It does not need to drive ranking.
- **Specificity score** is relevant for the allow-list decision only (tiebreak
  between two competing HARD routes). It is not a ranking signal.
- **SOFT routes** fit naturally: they bias federated retrieval via synthetic query
  without injecting anything, then the scorer orders the candidates.
- **priority integer** only matters for allow-list tiebreaking within HARD tier.
  Outside that, route order in the list is a sufficient tiebreaker.

---

## The Problem

`StatuteRoute` started as a targeted retrieval patch. It is becoming a rule engine.

`match_routes` returns a list of matched routes and every caller derives the actual
decision from that list themselves:

- `anchor.py` calls `match_routes` twice (injection pass, case retrieval pass)
- `anchor.py` manually computes `boosted_act_ids` from forced sections
- `anchor.py` iterates routes for per-route synthetic query embedding
- `anchor.py` calls `get_dominant_leg_allow_list` separately
- `api.py` calls `match_routes` a third time just for the debug event

The routing logic is not in `routing.py`. It is spread across every call site.

As the route table grows, three compounding problems emerge:

1. **Keyword collision** - broad terms fire routes they should not. "garden" in a
   fence repair question triggers PROPERTY_CHANGE.
2. **Dominance ambiguity** - when multiple routes match, forced sections from all
   routes are merged with no priority signal beyond a raw integer.
3. **Rule engine creep** - `include_all`, `exclude_any`, `leg_allow_list`, `priority`,
   `case_synthetic_query` are all route-level fields that callers have to interpret
   correctly at every call site. Adding a new field means updating all callers.

---

## Proposed Changes

### 1. `RouteDecision` - single structured decision object

`build_route_decision(original, rewritten, routes)` becomes the only public entry
point. It is the single place where all routing logic lives:

- which routes matched
- which route dominates
- which sections are forced
- which allow-list applies
- which sections are suppressed
- which synthetic queries should run

Callers receive a flat `RouteDecision` and never inspect matched routes directly.

```python
@dataclass(frozen=True)
class RouteDecision:
    triggered: bool
    matched_intents: tuple[str, ...]           # for debug/logging
    trigger_terms: tuple[str, ...]             # for debug/logging
    forced_sections: tuple[str, ...]           # merged union, order preserved
    leg_allow_list: tuple[str, ...]            # dominant (highest-strength, then priority)
    boosted_act_ids: frozenset[str]            # derived from forced_sections, for federated search
    case_synthetic_queries: tuple[str, ...]    # unique, non-empty, priority order
    retrieval_passes: tuple[tuple[str, tuple[str, ...]], ...]
    # ^ (synthetic_query, forced_sections_for_this_route) per matched route
    # Needed so anchor.py can run one targeted vector search per matched route
    # without re-deriving it from the raw route list.
```

What disappears:

- `get_dominant_leg_allow_list` - absorbed into `build_route_decision`
- `match_routes` - becomes private `_match_routes` internally
- Three separate `match_routes` call sites collapse to one `build_route_decision`
  call each, or better, computed once and passed through

What stays out:

- `allow_section` / `low_priority_sections` is a post-retrieval chunk filter that
  operates on individual retrieved results. It is not a routing decision - it depends
  on what Qdrant actually returned. It stays in `anchor.py`.

---

### 2. `RouteStrength` - semantic dominance tier

Right now `priority` is an integer tiebreaker. It does not express the *nature* of
the match. A HARD route and a SOFT route can fire simultaneously with no way to
suppress the weaker one's contributions.

```python
class RouteStrength(str, Enum):
    HARD   = "hard"    # precise match - allow-list may apply, dominates softer routes
    MEDIUM = "medium"  # force sections, no strict allow-list
    SOFT   = "soft"    # synthetic query / boost only, no forced sections
```

Dominance rule in `build_route_decision`:

Dominance only matters for one decision: **which HARD route's allow-list applies**.
It does not affect ranking (that is the scorer's job).

Ordering for the allow-list decision:

1. **RouteStrength** - only HARD routes may contribute an allow-list
2. **Specificity score** - query-relative tiebreaker between competing HARD routes
3. **Priority integer** - static tiebreaker within same specificity score
4. **Route list order** - deterministic final tiebreaker

```python
def _route_specificity(route: StatuteRoute, q: str) -> int:
    score = 0
    for term in route.include_any:
        if term in q:
            score += 3 if " " in term else 1  # multi-word phrase > single token
    for term in route.include_all:
        if term in q:
            score += 2  # conjunctive constraint, higher signal
    return score
```

Specificity is only computed when two HARD routes both define a leg_allow_list and
need a tiebreaker. In all other cases the allow-list decision is trivial (zero or
one HARD route with an allow-list).

Additional rules:
- MEDIUM/SOFT routes never contribute a leg_allow_list even if one is defined
- If a HARD route matches, SOFT routes are excluded from the forced-sections merge
- All matched routes (HARD + MEDIUM) still contribute forced_sections regardless of
  which route dominates the allow-list decision

Known limitation: section references like `s48` score 1 (single token, no space).
Multi-word matches like "landlord entry" score 3. In practice these co-occur on the
same route, so the net score is still dominant over other routes. A section-ref
bonus could be added later if a real collision appears.

Route assignments (tentative):

| Route | Strength |
|---|---|
| property_change | HARD |
| landlord_entry | HARD |
| wear_and_tear | HARD |
| fixed_term_sell | HARD |
| carpark_dispute | HARD |
| tenant_early_exit | MEDIUM |
| repairs_maintenance | MEDIUM |
| agreement_form | MEDIUM |
| bond | MEDIUM |
| rent_increase | MEDIUM |
| healthy_homes | MEDIUM |
| sham_flatmate_agreement | SOFT |

SOFT routes do not force sections and do not set allow-lists. They only provide a
better `synthetic_query` to steer vector search. This is a genuinely different
behaviour - currently there is no way to express "bias retrieval without injecting
anything." SOFT fills that gap.

---

### 3. Two-tier trigger matching - precise vs broad

Some trigger terms are too broad. "garden", "fence", "lawn" appear in repairs and
premises disputes that are not tenant-alteration questions. A flat `include_any` list
cannot distinguish.

Split into three fields:

```python
include_any_precise: tuple[str, ...] = ()
# Fires unconditionally. Use for terms that are unambiguous in context.
# Example: "fixture", "alteration", "written consent", "plant trees"

include_any_broad: tuple[str, ...] = ()
# Only fires when at least one context term is also present.
# Example: "garden", "fence", "tree", "backyard"

require_context_any: tuple[str, ...] = ()
# Context gate for broad terms. Any one of these must co-occur.
# Example: "without consent", "without permission", "landlord consent",
#          "written permission", "alteration", "improvement"
```

Matching logic:

```python
def _route_matches(route, q):
    if any(t in q for t in route.include_any_precise):
        return True
    if any(t in q for t in route.include_any_broad):
        return any(t in q for t in route.require_context_any)
    return False
```

Precise term alone can trigger. Broad term requires at least one context term.
`require_context_any` is only evaluated when a broad term matched - it is not
required when a precise term matched.

Backward compatibility: the existing `include_any` field is kept as a fallback
for routes where all terms are already precise. Routes can migrate incrementally.

---

## Open Questions

**Q1: `retrieval_passes` shape**
Should it stay as a flat tuple of `(str, tuple[str, ...])` pairs, or should it be a
proper `RetrievalPass` dataclass with named fields? Named fields are more readable
when the number of per-pass attributes grows.

**Q2: Public surface of `routing.py`**
Should `build_route_decision` be the only public symbol alongside `StatuteRoute` and
`RouteDecision`? Or should `_match_routes` stay public for testing purposes?
`StatuteRoute` = authoring interface. `RouteDecision` = runtime interface.

**Q3: `allow_section` boundary**
Is there a case for moving it into `RouteDecision` as a method that closes over
`low_priority_sections`, so callers pass `(case_id, query)` and never touch the
dict directly? Or does that blur the retrieval/routing boundary?

**Q4: `RouteStrength` vs `priority` - are both needed?**
With the design principle that routes are recall guarantees and ranking belongs to the
scorer, dominance only affects the allow-list decision. Specificity score now handles
the primary tiebreak between two competing HARD routes with allow-lists. `priority`
becomes a static fallback for identical specificity scores, which will be rare.

Specific question: can `priority` be dropped entirely, using route list order as the
final tiebreaker instead? This simplifies the authoring surface (one fewer field to
think about). Against: route list order is implicit and fragile - reordering the list
for readability would silently change dominance behaviour. Recommendation: keep
`priority` but document that it only matters for HARD routes with leg_allow_list.

**Q5: context term quality for broad triggers**
"tenant" appears in almost every tenancy query and would make a weak context gate.
Consent/permission language ("without consent", "written permission") is strong.
How do we prevent `require_context_any` terms from themselves becoming too broad?
Should context terms be required to be multi-word phrases only?

**Q6: `include_any` retirement**
Should `include_any` be deprecated once all routes are migrated to
`include_any_precise` / `include_any_broad`? Or kept permanently as a convenience
alias for "all precise"?

**Q7: SOFT route forced sections**
SOFT routes currently have no forced sections by definition. Should that be enforced
at the dataclass level (forced_sections must be empty for SOFT routes), or left to
the route author?

**Q8: legal scorer - what does it look like?**
The pipeline names a "legal scorer" at step 8 that handles final ranking. This does
not exist yet. Candidates:

- Simple: BM25 over retrieved chunks against the rewritten query
- Medium: cross-encoder reranker (BGE-reranker, ms-marco) fine-tuned or zero-shot
- Legal-specific: feature vector combining vector score + BM25 + section freshness
  + act boost from RouteDecision.boosted_act_ids

The choice affects whether `boosted_act_ids` needs to stay in RouteDecision at all
(if the scorer handles act-level boosting) or whether federated retrieval still
controls that. Open: define the scorer interface before finalizing RouteDecision shape.

**Q10: synthetic query cache**
`_synth_vector_cache` in `anchor.py` is keyed on `synthetic_query` strings.
Does the refactor change anything about that caching behaviour when `retrieval_passes`
replaces direct route iteration?

---

## Testing Discipline

**The key rule:** routes should guarantee critical legal recall. They should not
become an untested pile of regex-like magic.

Every route must have:

1. **Positive fixture** - a question that SHOULD trigger the route, with
   `expected_sections` containing every section that route forces.
2. **Negative fixture** - a question that MUST NOT trigger the route, proving
   that broad trigger terms do not fire in an adjacent context.

A route without a negative fixture is a route that could be silently causing
retrieval pollution on every similar question, with no test to catch it.

### `SmokeFixture` extension needed

Currently `SmokeFixture` tests retrieval outcomes (sections present/absent).
It cannot assert which routes fired or which routes must NOT have fired.

Proposed addition to `SmokeFixture`:

```python
@dataclass
class SmokeFixture:
    question: str
    expected_sections: list[str]
    forbidden_sections: list[str] = field(default_factory=list)
    description: str = ""
    min_sources: int = 0
    expected_routes: list[str] = field(default_factory=list)   # NEW: routes that MUST fire
    forbidden_routes: list[str] = field(default_factory=list)  # NEW: routes that MUST NOT fire
```

The smoke test runner would call `match_routes(question, question, jur.routes)`
directly (no HTTP, no retrieval) and assert:
- all `expected_routes` are in matched intents
- no `forbidden_routes` are in matched intents

This is a pure routing unit test, fast, no Qdrant dependency.

### Current coverage gaps

Routes that have a positive fixture but no negative fixture:

| Route | Positive | Negative needed |
|---|---|---|
| property_change | "planted several trees in backyard" | repairs question containing "garden", "fence", or "lawn" |
| repairs_maintenance | "mould in rental" | alteration question containing "broken" or "not working" |
| tenant_early_exit | "partner offered farm job, fixed term" | termination_notice question containing "end the tenancy" |
| carpark_dispute | "landlord asking me to vacate one carpark" | repairs question containing "garage" |
| wear_and_tear | "carpet worn after 6 years" | property_change question containing "carpet damage" |
| healthy_homes | "no ceiling insulation" | repairs question overlapping on "not working" heating |
| sham_flatmate_agreement | "flatmate agreement, landlord not living there" | genuine flatmate dispute |
| termination_notice | "90 day eviction notice" | tenant_early_exit question containing "end the tenancy" |
| fixed_term_sell | "landlord wants to sell, fixed term" | rent increase question |

Routes with only broad trigger terms and NO negative fixture are the highest risk.
`property_change` and `repairs_maintenance` are the first priority.

### Dominance explainability

`route_dominance_info()` in `routing.py` is already wired into the `context_debug`
SSE event. Every request in debug mode now emits:

```json
{
  "dominant_route": "carpark_dispute",
  "dominance_reason": "has leg_allow_list",
  "ignored_routes": [
    { "route": "repairs_maintenance", "reason": "no allow-list; forced sections still merged" }
  ]
}
```

This makes routing auditable without reading source code.

---

## Route-Specific Negative Terms (already available, use aggressively)

`exclude_any` already exists and short-circuits the route before any matching.
Use it proactively to prevent cross-domain firing, not just as a last resort.

Pattern: if a route fires on terms that also appear in a clearly different context,
add the distinguishing terms of that other context to `exclude_any`.

Examples applied:

- `property_change` fires on "install", "renovation", "broken" - but a question about
  a broken appliance or a landlord failing to maintain is NOT a tenant-alteration
  question. Exclusions added: "not repaired", "not fixed", "won't fix", "broken",
  "not working", "healthy homes", "building code", "plumbing".

- `repairs_maintenance` fires on "alteration", "minor change", "plant trees" via
  overlap with property_change terms. Exclusions added: "install fixture",
  "minor change", "alteration", "renovation without consent".

This is cheaper than two-tier triggers for routes where the contexts are cleanly
separable by vocabulary. Two-tier triggers handle the case where the SAME term is
ambiguous (e.g., "garden" in repairs vs alterations). Negative terms handle the case
where the OTHER context has a distinctive vocabulary that can be blocked outright.

---

## What Does Not Change

- `StatuteRoute` remains the authoring interface - jurisdiction authors write routes
  the same way
- The smoke test suite is unaffected - fixtures test retrieval outcomes, not routing
  internals
- `allow_section` / `low_priority_sections` stays in `anchor.py` (structural suppressions only)
- The Qdrant schema and corpus are unaffected

---

## Two-Layer Retrieval Precision Architecture

### The four-tool stack

Legal RAG uses four different AI tools, each solving a different problem. Understanding
what each one does - and cannot do - is what makes the two-layer architecture necessary.

```
Tool             What it does                          Weakness
----             ------------                          --------
Embedder         Converts text to a vector.            Each text encoded independently.
                 Fast. Captures semantic similarity.   Cannot compare two texts together.

Qdrant           Finds vectors closest to the query.   "Close" = similar tokens, not same
                 Returns top-k candidates with scores. meaning. "Security camera" and
                 The recall layer.                     "security bond" are close.

Cross-encoder    Reads (query, passage) TOGETHER.      Slower than bi-encoder.
(bge-reranker)   Attends to full context of both.      Must run on every candidate.
                 The precision layer.

LLM              Generates the answer.                 Easily distracted by irrelevant
                 Sees the final filtered context.      context it was given. Cannot tell
                 Most expensive per token.             you a section is wrong - it uses it.
```

### Plain-language analogies

**Embedder - the librarian who sorts books by topic**

Imagine a librarian who reads every book in the library once and puts a label on the
spine: a number that represents what the book is about. Books about "dogs" get labels
close to books about "cats". Books about "security guards" happen to get labels close
to books about "security deposits" because both use the word "security" a lot.

The embedder works the same way. It reads a piece of text once and produces a number
(a vector). It never compares two texts against each other - it just labels each one.

**Qdrant - the warehouse that finds the nearest labels**

Qdrant is the warehouse storing all those spine labels. When you ask a question, the
embedder labels your question too. Qdrant then finds the books whose labels are
numerically closest to your question's label. Very fast - millions of books in
milliseconds.

The problem: "Am I allowed a security camera?" and "Bond lodgement - landlord must
provide security deposit receipt" both have the word "security". Their labels end up
close. Qdrant dutifully returns the bond section as a candidate. It did its job
correctly - but it has no way to know the two "security" words mean completely different
things.

**Cross-encoder - the expert who reads both at once**

The cross-encoder is the expert you bring in for a second opinion. You hand them both
texts - the question AND the candidate passage - and they read both together. They can
see that "security camera" in the question is about CCTV surveillance, and "security
deposit" in the passage is about bond money. The answer: not relevant. Score: 0.03.

They can also see that "Am I allowed a security camera?" and "Tenant's responsibilities
regarding fixtures and alterations" ARE related - a camera requires drilling, which is
a fixture change. Score: 0.81. Keep it.

The cost: they can only read a small pile of candidates. You cannot ask them to read
all million books - it would take hours. This is why you use Qdrant first (fast,
finds the pile) and the cross-encoder second (slow, filters the pile).

**LLM - the lawyer who writes the answer**

The LLM is the lawyer who reads the pile the expert approved and writes the actual
answer. They are good at reasoning, citing sections, and giving practical advice.

But here is the trap: if you hand them a pile that still contains the bond section,
they will try to work it into the answer. They might say "while the RTA also sets out
bond lodgement obligations under s18A...". They are not hallucinating - they are
faithfully using the context you gave them. The garbage was in your input.

The rule: never ask the LLM to filter. Filter before it sees anything.

**The full analogy in one paragraph**

A user asks about a security camera. The librarian (embedder) labels the question.
The warehouse (Qdrant) finds the ten closest books - mostly about tenant obligations
and fixtures, but accidentally also the bond book because "security" matched. The
expert (cross-encoder) reads each book against the question and scores them: fixtures
0.81, tenant responsibilities 0.68, bond 0.03. The librarian's assistant drops anything
below 0.15. The lawyer (LLM) gets a clean pile of three books and writes a precise
answer about fixtures and CCTV installation rights. Nobody mentions bonds.

### Why two encoders?

The embedder (bi-encoder) encodes query and passage **independently** and then
compares the resulting vectors. This is fast - Qdrant can search millions of vectors
in milliseconds. But it has a fundamental limitation: it never sees the two texts
together. It matches tokens and concepts that appear in both, regardless of whether
the contexts make sense together.

A cross-encoder reads (query, passage) as a **single input**. The attention mechanism
can relate every word in the query to every word in the passage. This is how it catches:

> "Am I allowed a security camera?" + "Bond lodgement - landlord must lodge bond
> (security deposit) within 23 working days" -> score: 0.03

The cross-encoder sees "security camera" and "security deposit" in context and knows
they are unrelated uses of the same word. The bi-encoder sees "security" in both and
returns a moderate similarity score.

### The word-sense problem in practice

Real examples from user questions that triggered false positives before this fix:

| User question           | False-positive section    | Reason bi-encoder matched    |
|-------------------------|---------------------------|------------------------------|
| "security camera"       | s18A bond lodgement       | "security" in security deposit |
| "security gate"         | s18A bond lodgement       | same                         |
| "biosecurity"           | s18A bond lodgement       | same                         |
| "garden fence broken"   | property_change (RTA s42) | "fence", "garden" overlap    |
| "school term ends"      | fixed-term tenancy (s66)  | "term" overlap               |

The naive fix - adding keyword rules - is a whack-a-mole game. For every new
unrelated use of "security", "term", "bond", "notice", "deposit", "change" you need
a new rule. The ruleset grows without bound and has no systematic coverage guarantee.

The cross-encoder gate eliminates all of these with one threshold.

### The retrieval pipeline after this change

```
1. User question: "Am I allowed a security camera while staying in a rental?"

2. Embedder -> query vector

3. Qdrant federated search (recall)
   Returns: [s42A, s42B, s40, s18A, s28, ...]  <- s18A included (bi-encoder sees "security")

4. Route injection (recall guarantee)
   No routes fired for this question.
   Forced sections: (none)

5. Structural filters
   allow_section: s16A suppressed (no overseas context). Others pass.
   leg_allow_list: not active.

6. Cross-encoder gate (precision)
   Scores each (query, section) pair together:
     s42A "Consent for tenant's fixtures"  -> 0.81  KEPT
     s42B "Minor changes"                  -> 0.73  KEPT
     s40  "Tenant's responsibilities"      -> 0.68  KEPT
     s18A "Bond lodgement"                 -> 0.03  DROPPED (< 0.15 threshold)
     s28  "Rent increase notice"           -> 0.09  DROPPED
   Threshold: 0.15 (jurisdiction.leg_ce_min_score)

7. LLM context
   Sees: [s42A, s42B, s40]  <- zero false positives
   Answers about fixtures and tenant obligations. No bond sections cited.
```

### Forced section guarantee

Route-forced sections always pass the CE gate regardless of score. This is
intentional: the route table is a recall guarantee - when a route fires, the LLM
**must** see those sections. The CE gate narrows precision for un-forced candidates
only. Forced + high-CE sections go into context; forced + low-CE sections still go
in but the low score is logged as a signal that the route may need review.

### What replaces the keyword rules

`low_priority_sections` is now reserved for **structural suppressions** only: sections
that are almost never relevant to any question and have distinctive trigger vocabulary.
s16A (overseas landlord obligations) is the only current entry. It requires the query
to mention overseas/21-days/agent-if-landlord before surfacing.

Word-sense disambiguation (security camera vs security bond, garden vs alteration,
term vs fixed-term) is now handled entirely by the CE gate. No keyword rules needed.

### Threshold tuning

The default threshold is `0.15` (configurable per-jurisdiction via `leg_ce_min_score`).

- Too low (e.g. 0.05): almost nothing filtered, same noise as before
- Too high (e.g. 0.50): legitimate borderline sections dropped (e.g. a tangentially
  relevant section the LLM should see to give a complete answer)
- 0.15 is conservative: only clearly irrelevant sections (score < 0.15) are dropped

If legitimate sections are disappearing, lower the threshold. If noise persists,
raise it. The `ce_gate` field in every `route_debug.jsonl` entry shows the exact
score for every candidate so you can read the data and decide.

### Reading the ce_gate log

Every `route_debug.jsonl` entry now includes a `ce_gate` array:

```json
"ce_gate": [
  {"case_id": "NZLEG/RTA/s42A", "ce_score": 0.8134, "forced": false, "kept": true},
  {"case_id": "NZLEG/RTA/s42B", "ce_score": 0.7281, "forced": false, "kept": true},
  {"case_id": "NZLEG/RTA/s40",  "ce_score": 0.6812, "forced": false, "kept": true},
  {"case_id": "NZLEG/RTA/s18A", "ce_score": 0.0312, "forced": false, "kept": false},
  {"case_id": "NZLEG/RTA/s28",  "ce_score": 0.0891, "forced": false, "kept": false}
]
```

`kept: false` entries are the false positives the gate caught. Monitoring these
shows you exactly what would have reached the LLM before the gate existed.

### When to add a StatuteRoute vs relying on CE

- **Add a route** when a critical section is systematically missed by Qdrant - i.e.
  the Qdrant score for a genuinely relevant section is consistently below the retrieval
  threshold. Routes inject sections as a floor guarantee regardless of embedding score.
- **Raise leg_ce_min_score** when too many irrelevant sections are reaching the LLM
  despite the current threshold.
- **Lower leg_ce_min_score** when the LLM is missing sections it should see.
- **Add to low_priority_sections** only when a section is structurally almost never
  relevant (property of the section, not the query) AND the vocabulary gap is large
  enough that the keyword gate is reliable.
