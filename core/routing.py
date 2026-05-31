"""Statute routing primitives shared across all jurisdictions."""

from __future__ import annotations

from dataclasses import dataclass


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


def normalize_query(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def match_routes(
    original_query: str,
    rewritten_query: str,
    routes: list[StatuteRoute],
) -> list[StatuteRoute]:
    """Match both original and rewritten query against the route table."""
    q = normalize_query(original_query + " " + rewritten_query)
    matches: list[StatuteRoute] = []
    for route in routes:
        if route.exclude_any and any(term in q for term in route.exclude_any):
            continue
        any_ok = any(term in q for term in route.include_any)
        all_ok = (not route.include_all) or all(term in q for term in route.include_all)
        if any_ok and all_ok:
            matches.append(route)
    return matches


def get_dominant_leg_allow_list(matched: list[StatuteRoute]) -> tuple[str, ...]:
    """Return the leg_allow_list from the highest-priority matched route that defines one."""
    candidates = [r for r in matched if r.leg_allow_list]
    if not candidates:
        return ()
    return max(candidates, key=lambda r: r.priority).leg_allow_list


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
