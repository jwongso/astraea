"""Statute routes for NZ Employment Relations Act 2000.

Section IDs use the pattern NZLEG/ERA2000/s<N> - these must match the
chunk case_ids in the nz_legal legislation collection.
"""

from core.routing import StatuteRoute

LOW_PRIORITY_SECTIONS: dict[str, tuple[str, ...]] = {
    "NZLEG/ERA2000/s19": ("union", "collective", "bargaining"),
    "NZLEG/ERA2000/s238": ("strike", "lockout", "industrial action"),
}

ROUTES: list[StatuteRoute] = [
    StatuteRoute(
        intent="unjustified_dismissal",
        include_any=(
            "fired", "dismissed", "termination", "terminated", "sacked", "let go",
            "lost job", "lost my job", "end of employment", "dismissal",
            "unjustified", "unfair dismissal", "without cause", "without warning",
        ),
        forced_sections=("NZLEG/ERA2000/s103A", "NZLEG/ERA2000/s104"),
        synthetic_query="unjustified dismissal test substantive procedural justification employer ERA 2000",
        notes="s103A justification test (substantive + procedural), s104 unjustified dismissal",
    ),
    StatuteRoute(
        intent="personal_grievance",
        include_any=(
            "personal grievance", "grievance", "raise a grievance", "pg",
            "90 days", "ninety days", "time limit", "raise within",
            "how to raise", "notify employer",
        ),
        forced_sections=("NZLEG/ERA2000/s103", "NZLEG/ERA2000/s114"),
        synthetic_query="personal grievance raise notify employer 90 day time limit ERA 2000",
        notes="s103 types of personal grievance, s114 how to raise (90-day limit)",
    ),
    StatuteRoute(
        intent="good_faith",
        include_any=(
            "good faith", "honest", "open", "transparent", "deceive", "mislead",
            "not told", "withheld information", "duty of good faith",
        ),
        forced_sections=("NZLEG/ERA2000/s4",),
        synthetic_query="good faith duty employer employee active and constructive ERA 2000",
        notes="s4 good faith - the foundation of employment relationships in NZ",
    ),
    StatuteRoute(
        intent="redundancy",
        include_any=(
            "redundan", "restructur", "position disestablished", "role gone",
            "position gone", "made redundant", "redeployment", "reorganis",
            "reorganiz", "downsiz",
        ),
        forced_sections=("NZLEG/ERA2000/s103A", "NZLEG/ERA2000/s4"),
        synthetic_query="redundancy genuine restructure good faith consultation redeployment ERA 2000",
        notes="redundancy must meet s103A justification + s4 good faith consultation",
    ),
    StatuteRoute(
        intent="unjustified_disadvantage",
        include_any=(
            "disadvantage", "bullying", "harass", "hostile", "unfair treatment",
            "demoted", "demotion", "hours reduced", "pay cut", "duties changed",
            "working conditions", "constructive dismissal",
        ),
        forced_sections=("NZLEG/ERA2000/s103", "NZLEG/ERA2000/s105"),
        synthetic_query="unjustified disadvantage action employer working conditions ERA 2000",
        notes="s103(b) unjustified disadvantage, s105 constructive dismissal",
    ),
    StatuteRoute(
        intent="remedies",
        include_any=(
            "compensation", "reinstate", "reinstatement", "remedy", "remedies",
            "payout", "settlement", "award", "how much", "what can I get",
            "lost wages", "lost income",
        ),
        forced_sections=("NZLEG/ERA2000/s123", "NZLEG/ERA2000/s125"),
        synthetic_query="remedies reinstatement compensation lost wages ERA 2000 personal grievance",
        notes="s123 remedies available, s125 reinstatement as primary remedy",
    ),
    StatuteRoute(
        intent="leave_holidays",
        include_any=(
            "annual leave", "sick leave", "holiday", "holidays act",
            "leave entitlement", "public holiday", "bereavement",
            "alternative holiday", "leave pay",
        ),
        forced_sections=("NZLEG/HOLIDAYS/s16", "NZLEG/HOLIDAYS/s65"),
        synthetic_query="annual leave sick leave entitlement Holidays Act 2003 employee NZ",
        notes="Holidays Act 2003 - s16 annual leave, s65 sick leave",
    ),
    StatuteRoute(
        intent="minimum_rights",
        include_any=(
            "minimum wage", "minimum pay", "underpaid", "wage theft",
            "trial period", "90 day trial", "fixed term", "casual",
            "zero hours", "rest break", "meal break",
        ),
        forced_sections=("NZLEG/ERA2000/s67A", "NZLEG/ERA2000/s67B"),
        synthetic_query="trial period 90 days minimum rights zero hours rest breaks ERA 2000",
        notes="s67A/s67B trial period, minimum employment standards",
    ),
]
