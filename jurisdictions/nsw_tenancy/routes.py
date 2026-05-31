"""Statute routes for NSW Residential Tenancies Act 2010.

Section IDs use the pattern NSWLEG/RTA2010/s<N> - these must match the
chunk case_ids in the nsw_legal Qdrant collection once ingested.
"""

from core.routing import StatuteRoute

# Sections suppressed unless the query explicitly mentions the listed trigger terms.
# Prevents loose vector hits from injecting penalty or procedural sections into
# answers that don't need them.
LOW_PRIORITY_SECTIONS: dict[str, tuple[str, ...]] = {
    "NSWLEG/RTA2010/s9": ("fixed term", "break lease", "periodic"),
    "NSWLEG/RTA2010/s100": ("tribunal", "order", "application"),
}

ROUTES: list[StatuteRoute] = [
    StatuteRoute(
        intent="repairs_maintenance",
        include_any=(
            "repair", "fix", "fixing", "broken", "break", "leak", "leaking",
            "mould", "mold", "damp", "moisture", "water damage", "condensation",
            "pest", "vermin", "rodent", "cockroach",
            "maintain", "maintenance", "fault", "damage",
            "heating", "hot water", "plumbing", "electrical",
        ),
        forced_sections=("NSWLEG/RTA2010/s63", "NSWLEG/RTA2010/s64"),
        synthetic_query="landlord obligation repair maintain residential premises urgent non-urgent NSW",
        notes="s63 urgent repairs, s64 non-urgent repairs",
    ),
    StatuteRoute(
        intent="bond",
        include_any=(
            "bond", "deposit", "security deposit", "rental bond",
            "bond refund", "bond claim", "bond release", "bond dispute",
            "fair trading", "bond lodgement",
        ),
        forced_sections=("NSWLEG/RTA2010/s105", "NSWLEG/RTA2010/s113"),
        synthetic_query="rental bond payment lodgement refund claim NSW Fair Trading residential tenancy",
        notes="s105 bond lodgement, s113 bond claim and release",
    ),
    StatuteRoute(
        intent="rent",
        include_any=(
            "rent", "rental", "payment", "arrears", "increase", "raise rent",
            "rent hike", "overdue", "behind on rent", "withhold rent",
        ),
        forced_sections=("NSWLEG/RTA2010/s44", "NSWLEG/RTA2010/s51"),
        synthetic_query="rent increase notice period payment obligation residential tenancy NSW",
        notes="s44 rent increases, s51 rent payment obligations",
    ),
    StatuteRoute(
        intent="landlord_entry",
        include_any=(
            "entry", "enter", "access", "inspection", "landlord come in",
            "notice to enter", "privacy", "quiet enjoyment",
        ),
        forced_sections=("NSWLEG/RTA2010/s72", "NSWLEG/RTA2010/s73"),
        synthetic_query="landlord right of entry notice access residential premises NSW",
        notes="s72 permitted entry, s73 entry without consent",
    ),
    StatuteRoute(
        intent="termination",
        include_any=(
            "terminate", "termination", "evict", "eviction", "notice to vacate",
            "end tenancy", "break lease", "leave early", "vacate",
            "no grounds", "without reason", "landlord ending",
        ),
        forced_sections=("NSWLEG/RTA2010/s84", "NSWLEG/RTA2010/s85"),
        synthetic_query="termination notice residential tenancy landlord tenant grounds NSW",
        notes="s84 landlord termination, s85 tenant termination",
    ),
    StatuteRoute(
        intent="property_change",
        include_any=(
            "fixture", "install", "installed", "alteration", "renovate",
            "nail", "hook", "paint", "painted", "modification",
            "air conditioner", "dishwasher", "shelf", "shelving",
        ),
        forced_sections=("NSWLEG/RTA2010/s80", "NSWLEG/RTA2010/s81"),
        synthetic_query="tenant fixture alteration modification consent permission residential premises NSW",
        leg_allow_list=("NSWLEG/RTA2010/s80", "NSWLEG/RTA2010/s81"),
        priority=1,
        notes="s80 alterations, s81 fixtures",
    ),
    StatuteRoute(
        intent="wear_and_tear",
        include_any=(
            "wear", "worn", "tear", "deteriorated", "deterioration",
            "fair wear", "general wear", "aged", "old", "normal use",
            "carpet", "paint", "wall", "mark", "scuff",
        ),
        forced_sections=("NSWLEG/RTA2010/s19", "NSWLEG/RTA2010/s42"),
        synthetic_query="fair wear and tear tenant liability damage condition premises end of tenancy NSW",
        notes="s19 condition report (start), s42 end of tenancy obligations",
    ),
]
