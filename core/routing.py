"""Statute routing primitives shared across all jurisdictions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StatuteRoute:
    """Maps a class of user question to the legislation sections that embeddings frequently miss.

    Required:
        intent          - machine-readable label for this route
        include_any     - any of these terms in the combined query triggers the route
        forced_sections - legislation chunk IDs to prepend to vector results
        synthetic_query - embedded to locate forced_sections in the leg collection

    Optional:
        include_all     - ALL of these must also match
        exclude_any     - if any match, skip this route entirely
        leg_allow_list  - when set, only these sections are allowed as legislation anchors
        priority        - highest priority wins when multiple routes define leg_allow_list
        notes           - human-readable explanation
    """
    intent: str
    include_any: tuple[str, ...]
    forced_sections: tuple[str, ...]
    synthetic_query: str
    include_all: tuple[str, ...] = ()
    exclude_any: tuple[str, ...] = ()
    leg_allow_list: tuple[str, ...] = ()
    priority: int = 0
    notes: str = ""
    case_synthetic_query: str = ""  # if set, a supplementary case retrieval pass runs with this query


@dataclass(frozen=True)
class RouteDecision:
    """Fully computed routing decision. Callers never inspect raw routes directly.

    Build with build_route_decision(). All fields are derived in one place so
    anchor.py and api.py receive a flat, consistent object.
    """
    triggered: bool
    matched_intents: tuple[str, ...]           # intents of matched routes, for debug/logging
    trigger_terms: tuple[str, ...]             # terms that actually matched in the query
    forced_sections: tuple[str, ...]           # union of all forced sections, order preserved
    leg_allow_list: tuple[str, ...]            # dominant allow-list (highest-priority route that defines one)
    boosted_act_ids: frozenset[str]            # act IDs derived from forced_sections, for federated search
    leg_synthetic_queries: tuple[str, ...]     # for legislation injection pass in anchor.py
    case_synthetic_queries: tuple[str, ...]    # for supplementary case retrieval in anchor.py
    dominant_route: str                        # intent of route that owns leg_allow_list; "" if none
    dominance_reason: str                      # human-readable explanation for debug output
    ignored_routes: tuple[tuple[str, str], ...] # ((intent, reason), ...) for debug output


def normalize_query(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def _match_routes(q: str, routes: list[StatuteRoute]) -> list[StatuteRoute]:
    """Match a normalized combined query string against the route table."""
    matches: list[StatuteRoute] = []
    for route in routes:
        if route.exclude_any and any(term in q for term in route.exclude_any):
            continue
        any_ok = any(term in q for term in route.include_any)
        all_ok = (not route.include_all) or all(term in q for term in route.include_all)
        if any_ok and all_ok:
            matches.append(route)
    return matches


def build_route_decision(
    original: str,
    rewritten: str,
    routes: list[StatuteRoute],
) -> RouteDecision:
    """Single public entry point for all routing logic.

    Computes every derived field in one place. anchor.py and api.py call this
    once and use the returned RouteDecision - they never inspect raw routes.
    """
    q = normalize_query(original + " " + rewritten)
    matched = _match_routes(q, routes)

    # Forced sections: union, order preserved (first route wins on duplicates)
    seen_sections: set[str] = set()
    forced: list[str] = []
    for r in matched:
        for s in r.forced_sections:
            if s not in seen_sections:
                forced.append(s)
                seen_sections.add(s)

    # Act IDs for federated search boost
    boosted: set[str] = set()
    for s in forced:
        parts = s.split("/")
        if len(parts) >= 2:
            boosted.add(parts[1])

    # Allow-list: highest-priority route that defines one
    allow_candidates = [r for r in matched if r.leg_allow_list]
    if allow_candidates:
        dominant = max(allow_candidates, key=lambda r: r.priority)
        leg_allow_list = dominant.leg_allow_list
    else:
        dominant = max(matched, key=lambda r: r.priority) if matched else None
        leg_allow_list = ()

    # Synthetic queries: deduplicated, order preserved
    leg_synths = list(dict.fromkeys(r.synthetic_query for r in matched if r.synthetic_query))
    case_synths = list(dict.fromkeys(r.case_synthetic_query for r in matched if r.case_synthetic_query))

    # Trigger terms: only the terms that actually appeared in the query
    trigger_terms = sorted({t for r in matched for t in r.include_any if t in q})

    # Dominance audit fields
    dominant_route = ""
    dominance_reason = ""
    ignored: list[tuple[str, str]] = []
    if matched and dominant is not None:
        dominant_route = dominant.intent
        if allow_candidates:
            parts_d = ["has leg_allow_list"]
            if dominant.priority > 0:
                parts_d.append(f"priority {dominant.priority}")
            dominance_reason = ", ".join(parts_d)
            for r in matched:
                if r is dominant:
                    continue
                why = (
                    f"lower priority ({r.priority} < {dominant.priority}); "
                    "allow-list not used, forced sections still merged"
                    if r.leg_allow_list
                    else "no allow-list; forced sections still merged"
                )
                ignored.append((r.intent, why))
        else:
            dominance_reason = (
                f"highest priority ({dominant.priority}); "
                "no matched routes define leg_allow_list"
            )
            ignored = [
                (r.intent, "lower priority; forced sections still merged")
                for r in matched if r is not dominant
            ]

    return RouteDecision(
        triggered=bool(matched),
        matched_intents=tuple(r.intent for r in matched),
        trigger_terms=tuple(trigger_terms),
        forced_sections=tuple(forced),
        leg_allow_list=leg_allow_list,
        boosted_act_ids=frozenset(boosted),
        leg_synthetic_queries=tuple(leg_synths),
        case_synthetic_queries=tuple(case_synths),
        dominant_route=dominant_route,
        dominance_reason=dominance_reason,
        ignored_routes=tuple(ignored),
    )


def allow_section(
    case_id: str,
    combined_query: str,
    low_priority_sections: dict[str, tuple[str, ...]],
) -> bool:
    """Return False to suppress sections that are almost-never relevant for this query."""
    rule = low_priority_sections.get(case_id)
    if not rule:
        return True
    return any(term in combined_query for term in rule)
