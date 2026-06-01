"""Qdrant payload-filter scroll queries for nz_legal structured data.

These are specific to the nz_legal payload schema (penalty, sentencing, pg, counsel
fields). They do not belong in Astraea core - only nz_legal uses this schema.
"""

from __future__ import annotations

from core.retriever import SearchResult, VectorStore
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range


def _penalty_weight(r: SearchResult) -> float:
    p = r.payload.get("penalty", {})
    osi = p.get("outcome_osi") or 0.0
    awarded = p.get("awarded_amount") or 0.0
    return osi * 1000 + awarded / 1_000_000


def scroll_notable(
    store: VectorStore,
    flags: list[str] | None = None,
    min_outcome_osi: float | None = None,
    max_outcome_osi: float | None = None,
    min_recovery_rate: float | None = None,
    max_recovery_rate: float | None = None,
    min_awarded: float | None = None,
    max_awarded: float | None = None,
    counsel_surname: str | None = None,
    crown_counsel: str | None = None,
    courts: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 30,
) -> list[SearchResult]:
    must: list = []
    should: list = []

    if courts:
        must.append(FieldCondition(key="court", match=MatchAny(any=courts)))
    if year_from is not None or year_to is not None:
        must.append(FieldCondition(
            key="year",
            range=Range(
                gte=year_from if year_from is not None else 1900,
                lte=year_to if year_to is not None else 2100,
            ),
        ))
    if min_outcome_osi is not None or max_outcome_osi is not None:
        must.append(FieldCondition(
            key="penalty.outcome_osi",
            range=Range(
                gte=min_outcome_osi if min_outcome_osi is not None else 0.0,
                lte=max_outcome_osi if max_outcome_osi is not None else 1.0,
            ),
        ))
    if min_recovery_rate is not None or max_recovery_rate is not None:
        must.append(FieldCondition(
            key="penalty.recovery_rate",
            range=Range(
                gte=min_recovery_rate if min_recovery_rate is not None else 0.0,
                lte=max_recovery_rate if max_recovery_rate is not None else 99999.0,
            ),
        ))
    if min_awarded is not None or max_awarded is not None:
        must.append(FieldCondition(
            key="penalty.awarded_amount",
            range=Range(
                gte=min_awarded if min_awarded is not None else 0.0,
                lte=max_awarded if max_awarded is not None else 999_999_999.0,
            ),
        ))
    if flags:
        for f in flags:
            should.append(FieldCondition(key="flags", match=MatchValue(value=f)))
    if counsel_surname:
        must.append(FieldCondition(key="counsel.all_surnames", match=MatchValue(value=counsel_surname)))
    if crown_counsel:
        must.append(FieldCondition(key="counsel.crown", match=MatchValue(value=crown_counsel)))

    query_filter = (
        Filter(must=must or None, should=should or None)
        if (must or should)
        else None
    )

    raw = store.scroll_filtered(query_filter, limit=limit * 4)

    seen: dict[str, SearchResult] = {}
    for r in raw:
        cid = r.case_id
        if cid not in seen or _penalty_weight(r) > _penalty_weight(seen[cid]):
            seen[cid] = r

    return sorted(seen.values(), key=_penalty_weight, reverse=True)[:limit]


def scroll_sentencing(
    store: VectorStore,
    flags: list[str] | None = None,
    courts: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    sentence_type: str | None = None,
    min_starting_point: float | None = None,
    max_starting_point: float | None = None,
    min_final_sentence: float | None = None,
    max_final_sentence: float | None = None,
    has_guilty_plea: bool | None = None,
    limit: int = 30,
) -> list[SearchResult]:
    must: list = [FieldCondition(key="sentencing.has_data", match=MatchValue(value=True))]
    should: list = []

    if courts:
        must.append(FieldCondition(key="court", match=MatchAny(any=courts)))
    if year_from is not None or year_to is not None:
        must.append(FieldCondition(
            key="year",
            range=Range(
                gte=year_from if year_from is not None else 1900,
                lte=year_to if year_to is not None else 2100,
            ),
        ))
    if sentence_type:
        must.append(FieldCondition(key="sentencing.sentence_type", match=MatchValue(value=sentence_type)))
    if min_starting_point is not None or max_starting_point is not None:
        must.append(FieldCondition(
            key="sentencing.starting_point_months",
            range=Range(
                gte=min_starting_point if min_starting_point is not None else 0.0,
                lte=max_starting_point if max_starting_point is not None else 9999.0,
            ),
        ))
    if min_final_sentence is not None or max_final_sentence is not None:
        must.append(FieldCondition(
            key="sentencing.final_sentence_months",
            range=Range(
                gte=min_final_sentence if min_final_sentence is not None else 0.0,
                lte=max_final_sentence if max_final_sentence is not None else 9999.0,
            ),
        ))
    if has_guilty_plea is not None:
        must.append(FieldCondition(key="sentencing.has_guilty_plea", match=MatchValue(value=has_guilty_plea)))
    if flags:
        for f in flags:
            should.append(FieldCondition(key="flags", match=MatchValue(value=f)))

    raw = store.scroll_filtered(Filter(must=must, should=should or None), limit=limit * 6)

    _key_fields = [
        "starting_point_months", "final_sentence_months",
        "home_detention_months", "community_work_hours", "guilty_plea_discount_pct",
    ]

    def _completeness(r: SearchResult) -> int:
        s = r.payload.get("sentencing", {})
        return sum(1 for k in _key_fields if s.get(k) is not None)

    case_best: dict[str, SearchResult] = {}
    case_merged: dict[str, dict] = {}

    for r in raw:
        cid = r.case_id
        s = r.payload.get("sentencing", {})
        if cid not in case_best:
            case_best[cid] = r
            case_merged[cid] = {k: v for k, v in s.items() if k != "has_data"}
        else:
            if _completeness(r) > _completeness(case_best[cid]):
                case_best[cid] = r
            for k, v in s.items():
                if k != "has_data" and case_merged[cid].get(k) is None and v is not None:
                    case_merged[cid][k] = v

    merged: list[SearchResult] = []
    for cid, best in case_best.items():
        merged_payload = {**best.payload, "sentencing": {**case_merged[cid], "has_data": True}}
        merged.append(SearchResult(merged_payload, 1.0))

    def _sort_key(r: SearchResult) -> float:
        s = r.payload.get("sentencing", {})
        return s.get("starting_point_months") or s.get("final_sentence_months") or 0.0

    return sorted(merged, key=_sort_key, reverse=True)[:limit]


def scroll_pg(
    store: VectorStore,
    grievance_types: list[str] | None = None,
    reinstatement: bool | None = None,
    min_contributory: float | None = None,
    max_contributory: float | None = None,
    min_compensation: float | None = None,
    max_compensation: float | None = None,
    courts: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 30,
) -> list[SearchResult]:
    must: list = [FieldCondition(key="pg.has_data", match=MatchValue(value=True))]
    should: list = []

    if courts:
        must.append(FieldCondition(key="court", match=MatchAny(any=courts)))
    if year_from is not None or year_to is not None:
        must.append(FieldCondition(
            key="year",
            range=Range(
                gte=year_from if year_from is not None else 1900,
                lte=year_to if year_to is not None else 2100,
            ),
        ))
    if reinstatement is not None:
        must.append(FieldCondition(key="pg.reinstatement_ordered", match=MatchValue(value=reinstatement)))
    if min_contributory is not None or max_contributory is not None:
        must.append(FieldCondition(
            key="pg.contributory_conduct_pct",
            range=Range(
                gte=min_contributory if min_contributory is not None else 0.0,
                lte=max_contributory if max_contributory is not None else 100.0,
            ),
        ))
    if min_compensation is not None or max_compensation is not None:
        must.append(FieldCondition(
            key="penalty.awarded_amount",
            range=Range(
                gte=min_compensation if min_compensation is not None else 0.0,
                lte=max_compensation if max_compensation is not None else 999_999_999.0,
            ),
        ))
    if grievance_types:
        for gt in grievance_types:
            should.append(FieldCondition(key="pg.grievance_types", match=MatchValue(value=gt)))

    raw = store.scroll_filtered(Filter(must=must, should=should or None), limit=limit * 4)

    def _pg_completeness(r: SearchResult) -> int:
        pg = r.payload.get("pg", {})
        score = len(pg.get("grievance_types") or [])
        if pg.get("reinstatement_ordered") is not None:
            score += 2
        if pg.get("contributory_conduct_pct") is not None:
            score += 1
        return score

    case_best: dict[str, SearchResult] = {}
    case_merged_pg: dict[str, dict] = {}

    for r in raw:
        cid = r.case_id
        pg = r.payload.get("pg", {})
        if cid not in case_best:
            case_best[cid] = r
            case_merged_pg[cid] = {k: v for k, v in pg.items() if k != "has_data"}
        else:
            if _pg_completeness(r) > _pg_completeness(case_best[cid]):
                case_best[cid] = r
            for k, v in pg.items():
                if k == "grievance_types":
                    existing = case_merged_pg[cid].get("grievance_types") or []
                    for gt in (v or []):
                        if gt not in existing:
                            existing.append(gt)
                    case_merged_pg[cid]["grievance_types"] = existing
                elif k != "has_data" and case_merged_pg[cid].get(k) is None and v is not None:
                    case_merged_pg[cid][k] = v

    merged: list[SearchResult] = []
    for cid, best in case_best.items():
        merged_payload = {**best.payload, "pg": {**case_merged_pg[cid], "has_data": True}}
        merged.append(SearchResult(merged_payload, 1.0))

    def _comp_key(r: SearchResult) -> float:
        return r.payload.get("penalty", {}).get("awarded_amount") or 0.0

    return sorted(merged, key=_comp_key, reverse=True)[:limit]
