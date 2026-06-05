"""Statute routing table for NZ residential tenancy law (RTA 1986).

Maps common tenant/landlord question types to the RTA sections that vector
search frequently misses. Sections are prepended to vector results so the LLM
always sees the correct legislative grounding.
"""

from core.routing import StatuteRoute

ROUTES: list[StatuteRoute] = [
    StatuteRoute(
        intent="wear_and_tear",
        include_any=(
            "fair wear and tear", "wear and tear", "normal wear",
            "tenant damage", "damage claim", "repair cost",
            "landlord charge", "liable for damage", "damage to the",
            "worn", "deteriorated", "deterioration",
            "carpet damage", "carpet replacement", "carpet clean", "carpet wear",
            "bond deduction", "deducting from", "deduct from bond",
            "withholding my bond", "withheld my bond", "withhold my bond",
            "s49a", "s49b",
        ),
        forced_sections=("NZLEG/RTA/s49A", "NZLEG/RTA/s49B", "NZLEG/RTA/s40"),
        synthetic_query=(
            "tenant not liable fair wear tear exception section 49A damage "
            "landlord cannot charge deterioration reasonable use natural forces "
            "residential tenancies act"
        ),
        notes="Tenant damage liability and fair wear and tear exception.",
    ),
    StatuteRoute(
        intent="property_change",
        include_any=(),  # unused - two-tier mode active
        include_any_precise=(
            "alteration", "alter", "altered",
            "minor change",
            "renovate", "renovation",
            "without consent", "without permission",
            "landlord consent", "written consent", "written permission",
            "landlord permission",
            "planted trees", "planted a tree", "planted several",
            "plant trees", "plant a tree",
        ),
        include_any_broad=(
            "plant", "planted", "tree", "trees", "shrub", "hedge",
            "garden", "backyard", "back yard", "lawn",
            "fence",
            "fixture",
            "install", "installed",
            "improvement",
        ),
        require_context_any=(
            "consent", "permission",
            "without consent", "without permission",
            "landlord consent", "landlord's consent",
            "written consent", "written permission",
            "landlord permission", "landlord's permission",
            "alteration", "minor change", "improvement",
        ),
        exclude_any=(
            "healthy homes", "building code", "building act",
            "resource management act",
            "plumbing", "sewage", "shower drain",
            "landlord failed to maintain", "landlord hasn't maintained",
            "landlord has not maintained",
            "not repaired", "not fixed", "won't fix", "wont fix",
            "hasn't fixed", "hasnt fixed",
            "broken", "not working",
        ),
        forced_sections=("NZLEG/RTA/s40", "NZLEG/RTA/s42A", "NZLEG/RTA/s42B"),
        synthetic_query=(
            "tenant obligations alter improve add fixtures to land garden "
            "written consent landlord section 40 42A 42B residential tenancies act"
        ),
        leg_allow_list=("NZLEG/RTA/s40", "NZLEG/RTA/s42A", "NZLEG/RTA/s42B"),
        priority=10,
        notes="Tenant changes to premises, garden, land, fixtures.",
    ),
    StatuteRoute(
        intent="repairs_maintenance",
        include_any=(
            "not working", "broken", "won't fix", "wont fix",
            "hasn't fixed", "hasnt fixed", "not fixed", "not repaired",
            "not maintained", "hasn't maintained", "has not maintained",
            "repair request", "maintenance",
            "hot water", "no hot water", "heating", "no heating",
            "mould", "mold", "damp", "dampness", "moisture", "mildew",
            "condensation", "water damage", "humid", "fungal",
            "leak", "leaking", "dripping",
            "weathertight", "habitable", "uninhabitable",
            "appliance", "oven", "stove", "fridge",
            "landlord obligation", "landlord's obligation",
            "s45",
        ),
        exclude_any=(
            "fair wear and tear", "wear and tear",
            "install fixture", "installed fixture",
            "minor change", "minor improvement",
            "plant trees", "planted trees", "planting trees",
            "alteration", "altered",
            "renovation without consent", "renovate without",
            "healthy homes",
        ),
        forced_sections=("NZLEG/RTA/s45",),
        synthetic_query=(
            "landlord responsibility maintain premises reasonable state repair "
            "section 45 habitable condition heating hot water weathertight "
            "residential tenancies act tenant remedies maintenance obligations"
        ),
        notes="Landlord maintenance and repair obligations (s45).",
    ),
    StatuteRoute(
        intent="agreement_form",
        include_any=(
            "tenancy agreement", "written agreement", "copy of agreement",
            "sign agreement", "signing agreement", "before signing",
            "provide agreement", "give the agreement", "before getting the agreement",
            "form of agreement", "written tenancy", "contents of agreement",
        ),
        forced_sections=("NZLEG/RTA/s13A", "NZLEG/RTA/s13B"),
        synthetic_query=(
            "contents of tenancy agreement landlord obligations provide copy "
            "section 13A written tenancy agreement residential tenancies act"
        ),
        notes="Contents and copy obligations for tenancy agreements (s13A, s13B).",
    ),
    StatuteRoute(
        intent="bond",
        include_any=(
            "bond lodgement", "bond lodged", "lodge the bond", "lodge bond",
            "bond receipt", "proof of bond", "bond proof",
            "bond before", "bond form", "bond help",
            "work and income", "winz", "bond guarantee",
            "can pay the bond", "pay the bond",
            "lodged my bond", "lodged the bond",
            "not lodged", "hasn't lodged", "has not lodged",
            "s18",
        ),
        forced_sections=("NZLEG/RTA/s18",),
        synthetic_query=(
            "general bond landlord maximum bond amount four weeks rent section 18 "
            "residential tenancies act bond obligations receipt"
        ),
        notes="General bond requirements - amount limits and receipt (s18).",
    ),
    StatuteRoute(
        intent="landlord_entry",
        include_any=(
            "landlord entry", "landlord enter", "right of entry",
            "inspection notice", "24 hour notice", "24 hours notice",
            "landlord came in", "landlord access",
            "notice before entering", "notice to enter",
            "s48",
        ),
        forced_sections=("NZLEG/RTA/s48",),
        synthetic_query=(
            "landlord right of entry inspection notice 24 hours section 48 "
            "residential tenancies act access premises"
        ),
        notes="Landlord entry and inspection rules (s48).",
    ),
    StatuteRoute(
        intent="sham_flatmate_agreement",
        include_any=(
            "flatmate agreement", "flatmate arrangement",
            "boarder agreement", "boarder arrangement",
            "licence agreement", "licensee",
            "not a tenant", "not tenants", "are we tenants",
            "meant to be tenants", "should be tenants",
            "landlord not living", "landlord lives elsewhere",
            "landlord doesn't live", "landlord does not live",
            "landlord not resident", "landlord not there",
            "s5",
        ),
        forced_sections=("NZLEG/RTA/s5",),
        synthetic_query=(
            "flatmate boarder licensee agreement landlord not resident sham tenancy "
            "RTA applies despite flatmate agreement section 5 definition residential "
            "tenancy landlord not living premises tenant rights wrongful agreement"
        ),
        case_synthetic_query=(
            "flatmate agreement landlord not living property sham tenancy RTA applies "
            "boarder licensee residential tenancy act tenant rights eviction notice "
            "invalid agreement landlord not resident"
        ),
        notes="Sham flatmate/boarder agreements where landlord is not resident (s5).",
    ),
    StatuteRoute(
        intent="termination_notice",
        include_any=(
            "evict", "eviction",
            "notice to leave", "notice to vacate",
            "end the tenancy", "end my tenancy", "terminate tenancy",
            "90 day notice", "90 days notice", "90-day notice",
            "42 day notice", "42 days notice", "42-day notice",
            "21 day notice", "21 days notice",
            "periodic tenancy end", "asked to leave",
            "termination notice", "s51", "s56",
        ),
        forced_sections=("NZLEG/RTA/s51",),
        synthetic_query=(
            "landlord terminate periodic tenancy notice 90 days 42 days "
            "section 51 residential tenancies act tenant notice 21 days "
            "lawful grounds termination"
        ),
        notes="Termination of periodic tenancy, notice periods (s51).",
    ),
    StatuteRoute(
        intent="fixed_term_sell",
        include_any=(
            "fixed term tenancy sell", "fixed-term tenancy sell",
            "sell the house", "sell the property", "want to sell",
            "selling the house", "selling the property",
            "list the property", "list the house", "before listing",
            "vacant possession", "empty before", "vacant before",
            "fixed term end early", "break fixed term",
        ),
        forced_sections=("NZLEG/RTA/s60A", "NZLEG/RTA/s50"),
        synthetic_query=(
            "landlord fixed term tenancy sell house vacant possession terminate early "
            "mutual agreement section 50 section 60A periodic tenancy notice "
            "residential tenancies act tenant rights fixed term expiry"
        ),
        notes="Landlord wants to sell with vacant possession during fixed-term (s60A, s50).",
    ),
    StatuteRoute(
        intent="healthy_homes",
        include_any=(
            "healthy homes", "healthy home", "hhs",
            "heating standard", "heating requirement", "minimum heating",
            "insulation standard", "ceiling insulation", "underfloor insulation",
            "ventilation standard", "extractor fan", "extraction fan",
            "moisture barrier", "ground moisture", "draught stopping",
            "draught standard", "draughts", "no insulation",
            "s138b", "s45b", "s66i",
        ),
        forced_sections=(
            "NZLEG/RTA/s138B",
            "NZLEG/HHS2019/s8",   # heating: main living room qualifying heater
            "NZLEG/HHS2019/s14",  # insulation: qualifying ceiling insulation
            "NZLEG/HHS2019/s21",  # ventilation: openable windows/doors
            "NZLEG/HHS2019/s23",  # ventilation: extraction fans in kitchens and bathrooms
            "NZLEG/HHS2019/s26",  # draught: gaps and holes
            "NZLEG/HHS2019/s28",  # moisture: ground moisture barrier
        ),
        synthetic_query=(
            "healthy homes standards heating insulation ventilation moisture draught "
            "residential tenancies act section 138B landlord obligations "
            "extractor fan ceiling underfloor insulation draught stopping ground moisture barrier"
        ),
        notes="Healthy Homes Standards - heating, insulation, ventilation, moisture, draught (HHS2019).",
    ),
    StatuteRoute(
        intent="healthy_homes_facilities",
        include_any=(
            "carport light", "laundry light", "no light", "lighting in",
            "lights in", "lights at", "adequate lighting", "working lights",
            "smoke alarm", "carbon monoxide",
        ),
        forced_sections=(
            "NZLEG/HHS2019/s21",  # ventilation: openable windows/doors
            "NZLEG/HHS2019/s23",  # ventilation: extraction fans in kitchens and bathrooms
            "NZLEG/HHS2019/s24",  # exemption from mechanical ventilation standard
        ),
        synthetic_query=(
            "landlord obligations lighting smoke alarm carport laundry "
            "healthy homes standards ventilation extraction fan requirements "
            "habitable space facilities residential tenancy"
        ),
        notes="HHS facilities: lighting, smoke alarms - forces ventilation sections as grounding context.",
    ),
    StatuteRoute(
        intent="rent_increase",
        include_any=(
            "rent increase", "increase the rent", "raise the rent", "raised the rent",
            "increased the rent", "increased my rent",
            "increase my rent", "increase rent", "increasing rent", "increasing my rent",
            "rent rise", "rent review", "maximum rent", "rent in advance",
            "weeks rent in advance", "how much rent", "notice to increase",
            "s28", "s28a",
        ),
        forced_sections=("NZLEG/RTA/s28", "NZLEG/RTA/s28A"),
        synthetic_query=(
            "notice to increase rent landlord section 28 28A residential tenancies act "
            "rent increase order unforeseen expenses 90 days"
        ),
        notes="Rent increases by notice or order (s28, s28A).",
    ),
    StatuteRoute(
        intent="fixed_term_rent_review",
        include_any=(
            "rent review", "rent increase", "increase the rent", "raise the rent",
            "review clause", "rent review clause", "rent will increase",
            "rent going up", "review in", "increase at review",
        ),
        include_all=("fixed term",),
        forced_sections=("NZLEG/RTA/s13A", "NZLEG/RTA/s50"),
        synthetic_query=(
            "fixed term tenancy rent review clause agreement contents section 13A "
            "landlord must specify review method limit mutual termination section 50 "
            "tenant options fixed term unable to pay increased rent"
        ),
        notes=(
            "Fixed-term tenancy with a rent review clause. "
            "s13A=agreement must clearly specify review terms (if silent, increase is invalid); "
            "s50=early exit options if tenant cannot afford the increase."
        ),
    ),
    StatuteRoute(
        intent="tenant_early_exit",
        include_any=(
            "leave early", "leave the tenancy early", "end the tenancy early",
            "move out before", "moving out before", "get out of the tenancy",
            "exit the lease", "exit the tenancy", "break the lease",
            "job offer", "new job", "job opportunity", "farm job",
            "relocating", "moving city", "moving town", "moving region",
            "partner got a job", "offered a job", "offered housing",
            "how do i get out", "how to get out", "how can i leave",
            "want to leave", "want to move out", "need to move out",
            "early termination tenant", "tenant terminate early",
        ),
        forced_sections=("NZLEG/RTA/s50", "NZLEG/RTA/s66"),
        synthetic_query=(
            "tenant fixed term tenancy leave early mutual agreement landlord consent "
            "section 50 termination agreement section 66 assignment subletting "
            "replacement tenant liability rent fixed term break lease early exit"
        ),
        notes="Tenant wants to leave a fixed-term early (job, relocation, hardship). s50=mutual termination, s66=assignment.",
    ),
    StatuteRoute(
        intent="carpark_dispute",
        include_any=(
            "carpark", "car park", "car parks", "carparks",
            "parking space", "parking spaces", "parking bay",
            "parking included", "park my car", "use the garage",
            "garage included", "remove carpark", "lose carpark",
            "take away carpark", "vacate carpark", "vacate the carpark",
        ),
        forced_sections=("NZLEG/RTA/s45", "NZLEG/RTA/s13A"),
        synthetic_query=(
            "landlord remove carpark parking space included tenancy agreement "
            "tenant facilities services agreed quiet enjoyment obligation "
            "section 45 landlord obligation section 13A tenancy agreement contents "
            "rent reduction loss of amenity agreed services"
        ),
        leg_allow_list=("NZLEG/RTA/s45", "NZLEG/RTA/s13A"),
        notes="Carpark/parking dispute - landlord removing agreed facility. s45=landlord obligations, s13A=tenancy agreement contents.",
    ),
]

LOW_PRIORITY_SECTIONS: dict[str, tuple[str, ...]] = {
    # Structural suppression: s16A is almost never relevant. Overseas landlord
    # queries are rare and have distinctive vocabulary, so keyword gate is reliable.
    # Word-sense false positives (e.g. "security camera" pulling bond sections) are
    # handled by the cross-encoder gate in anchor.py, not here.
    "NZLEG/RTA/s16A": (
        "landlord overseas", "landlord out of new zealand",
        "agent if landlord", "21 consecutive days",
        "out of new zealand", "overseas landlord",
    ),
    # s55AA: termination by notice for physical assault by tenant.
    # CE scores ~0.58 on relationship-breakdown and repeated-breach questions
    # because "termination" semantics overlap. Suppress unless the question
    # actually involves violence or physical harm.
    "NZLEG/RTA/s55AA": (
        "assault", "physical assault", "attacked", "attack",
        "violence", "violent", "threatened", "threat",
        "hit", "punched", "kicked", "hurt", "injured", "harm",
    ),
}
