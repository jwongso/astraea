"""NZ Tenancy jurisdiction - tenancy.localrun.ai

Covers NZ residential tenancy law: Tenancy Tribunal decisions (NZTT) +
live RTA 1986 section extraction from legislation.govt.nz.
"""

from core.jurisdiction import (
    CorpusConfig,
    JurisdictionBase,
    LegislationConfig,
    LegislationSource,
    RouteFixture,
    SmokeFixture,
    WebVerifyConfig,
)
from core.routing import StatuteRoute
from jurisdictions.nz_tenancy.prompt import SYSTEM_PROMPT
from jurisdictions.nz_tenancy.routes import LOW_PRIORITY_SECTIONS, ROUTES


class NZTenancyJurisdiction(JurisdictionBase):

    @property
    def name(self) -> str:
        return "nz-tenancy"

    @property
    def description(self) -> str:
        return "Free NZ residential tenancy law Q&A - tenancy.localrun.ai"

    @property
    def corpus(self) -> CorpusConfig:
        return CorpusConfig(
            qdrant_collection="nztt_moj",
            courts=["NZTT"],
            leg_collection="nz_legal_v2",
            pg_database="nz_legal",
        )

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @property
    def routes(self) -> list[StatuteRoute]:
        return ROUTES

    @property
    def leg_sources(self) -> list[LegislationSource]:
        return [
            LegislationSource(
                act_id="RTA",
                court_name="Residential Tenancies Act 1986",
                default_top_k=6,
                boost_top_k=10,
            ),
            LegislationSource(
                act_id="HHS2019",
                court_name="Residential Tenancies (Healthy Homes Standards) Regulations 2019",
                default_top_k=4,
                boost_top_k=8,
            ),
        ]

    @property
    def low_priority_sections(self) -> dict[str, tuple[str, ...]]:
        return LOW_PRIORITY_SECTIONS

    @property
    def legislation(self) -> LegislationConfig:
        return LegislationConfig(
            acts={"RTA": "https://www.legislation.govt.nz/act/public/1986/120/en/latest/"},
            cache_ttl_seconds=3600,
        )

    @property
    def web_verify(self) -> WebVerifyConfig:
        return WebVerifyConfig(
            search_prefix="NZ residential tenancy law",
            max_results=3,
            cache_ttl_seconds=604800,
        )

    @property
    def leg_ce_min_score(self) -> float:
        return 0.50

    @property
    def log_route_decisions(self) -> bool:
        return True

    @property
    def max_question_chars(self) -> int:
        return 1200

    @property
    def smoke_fixtures(self) -> list[SmokeFixture]:
        return [
            SmokeFixture(
                question="I live in a rental and planted several trees in the backyard. Does this break any rules?",
                expected_sections=["NZLEG/RTA/s40", "NZLEG/RTA/s42A", "NZLEG/RTA/s42B"],
                forbidden_sections=["NZLEG/RTA/s19"],
                description="property_change route - trees in backyard",
            ),
            SmokeFixture(
                question="The carpet is worn after living here for 6 years. Can the landlord take money from my bond?",
                expected_sections=["NZLEG/RTA/s49A", "NZLEG/RTA/s49B"],
                description="wear_and_tear route - worn carpet",
            ),
            SmokeFixture(
                question="There is mould in my rental. Is the landlord responsible?",
                expected_sections=["NZLEG/RTA/s45"],
                description="repairs_maintenance route - mould",
            ),
            SmokeFixture(
                question="Can my landlord enter without giving me notice?",
                expected_sections=["NZLEG/RTA/s48"],
                description="landlord_entry route",
            ),
            SmokeFixture(
                question="My landlord wants to increase my rent. How much notice do they need to give?",
                expected_sections=["NZLEG/RTA/s28"],
                expected_guidance_sources=["MANUAL/rent-increases-and-reductions"],
                description="rent_increase route - notice requirements + official guidance injection",
            ),
            SmokeFixture(
                question="My landlord did not fix a leaking ceiling for 5 months. What compensation can I apply for?",
                expected_sections=["NZLEG/RTA/s45"],
                description="repairs_maintenance route - ceiling leak compensation",
            ),
            SmokeFixture(
                question="My landlord never gave me a copy of the tenancy agreement after I signed it. Are they required to?",
                expected_sections=["NZLEG/RTA/s13A", "NZLEG/RTA/s13B"],
                description="agreement_form route - landlord must provide copy of signed agreement",
            ),
            SmokeFixture(
                question="My landlord asked me to pay 6 weeks rent as a bond. I thought there was a maximum. They also haven't lodged the bond yet.",
                expected_sections=["NZLEG/RTA/s18"],
                description="bond route - maximum bond amount and lodgement obligation",
            ),
            SmokeFixture(
                question="My landlord gave me a 90 day eviction notice but I am on a periodic tenancy and have done nothing wrong. Is this legal?",
                expected_sections=["NZLEG/RTA/s51"],
                description="termination_notice route - 90 day no-cause notice on periodic tenancy",
            ),
            SmokeFixture(
                question="My landlord put us on a flatmate agreement but they lived in another house. We are meant to be tenants. They forced us to leave with 3 weeks notice.",
                expected_sections=[],
                min_sources=6,
                description="sham_flatmate_agreement route - case_synthetic_query augmentation",
            ),
            SmokeFixture(
                question="My landlord is withholding my $2,000 bond claiming carpet damage. I paid $160 for a professional clean and the carpet was already 8 years old when I moved in. What are my rights and draft a letter disputing this?",
                expected_sections=["NZLEG/RTA/s49A", "NZLEG/RTA/s49B"],
                description="draft_letter route - combined analysis+draft, wear_and_tear sections in context",
            ),
            SmokeFixture(
                question="My rental has no ceiling insulation and the heating does not meet the healthy homes standards. What is my landlord required to provide?",
                expected_sections=["NZLEG/RTA/s138B", "NZLEG/HHS2019/s8", "NZLEG/HHS2019/s14"],
                description="healthy_homes route - HHS2019 heating and insulation requirements surface alongside RTA s138B",
            ),
            SmokeFixture(
                question="Am I allowed a security camera while staying in a rental?",
                expected_sections=[],
                forbidden_sections=["NZLEG/RTA/s18", "NZLEG/RTA/s18A", "NZLEG/RTA/s18B"],
                description="low_priority suppression - security camera must not surface bond sections (s18*)",
            ),
            SmokeFixture(
                question="We have been offered a new fixed term tenancy with a rent review in 6 months. What happens if they increase the rent beyond what we can afford?",
                expected_sections=["NZLEG/RTA/s13A", "NZLEG/RTA/s28"],
                description="fixed_term_rent_review - s13A (review clause must be specified) and s28 (notice rules) both in context",
            ),
            SmokeFixture(
                question="I am on a fixed-term tenancy for a year and my partner has been offered a job with free housing. Can I leave the tenancy early?",
                expected_sections=["NZLEG/RTA/s50", "NZLEG/RTA/s66"],
                description="tenant_early_exit route - tenant wants to leave fixed-term early, mutual termination and assignment",
            ),
            SmokeFixture(
                question="My rent includes 2 carparks and my landlord is asking me to vacate one. Can I get a rent reduction?",
                expected_sections=["NZLEG/RTA/s45", "NZLEG/RTA/s13A"],
                description="carpark_dispute route - landlord removing agreed carpark, s45 landlord obligations and s13A tenancy agreement contents",
            ),
            # --- guidance injection smoke tests ---
            SmokeFixture(
                question="How do I get my bond back after moving out?",
                expected_sections=["NZLEG/RTA/s18"],
                expected_guidance_sources=["MANUAL/how-to-apply-for-a-bond-refund", "MANUAL/bonds"],
                description="bond route - guidance injection: bond refund page",
            ),
            SmokeFixture(
                question="I want to give notice to end my periodic tenancy and move out in 3 weeks.",
                expected_sections=["NZLEG/RTA/s51"],
                expected_guidance_sources=["MANUAL/giving-notice-to-end-a-tenancy", "MANUAL/ending-a-tenancy"],
                description="termination_notice route - guidance injection: giving notice page",
            ),
            SmokeFixture(
                question="Can my landlord refuse to let me have a cat at my rental?",
                expected_sections=["NZLEG/RTA/s42E"],
                expected_guidance_sources=["MANUAL/requesting-pet-consent", "MANUAL/rules-about-pets"],
                description="agreement_form route (pets) - guidance injection via vector threshold",
            ),
            SmokeFixture(
                question="I am behind on rent by 3 weeks and cannot pay. What will happen?",
                expected_sections=["NZLEG/RTA/s55", "NZLEG/RTA/s27"],
                expected_guidance_sources=["MANUAL/rent-arrears-and-overdue-rent"],
                description="rent_arrears route - guidance injection: rent arrears page",
            ),
        ]

    @property
    def route_fixtures(self) -> list[RouteFixture]:
        return [
            # --- wear_and_tear ---
            RouteFixture(
                question="The carpet has worn out after 8 years. Can the landlord charge me for replacement?",
                expected_routes=["wear_and_tear"],
                forbidden_routes=["property_change"],
                description="wear_and_tear positive - worn carpet after 8 years",
            ),
            RouteFixture(
                question="I installed new shelving in the bedroom as a minor improvement without asking the landlord.",
                expected_routes=["property_change"],
                forbidden_routes=["wear_and_tear"],
                description="wear_and_tear negative - shelving install is property_change, not wear_and_tear",
            ),
            # --- property_change ---
            RouteFixture(
                question="I planted several trees in the backyard without getting landlord consent. Is that allowed?",
                expected_routes=["property_change"],
                forbidden_routes=["repairs_maintenance"],
                description="property_change positive - trees in backyard without consent",
            ),
            RouteFixture(
                question="The garden fence is broken and leaking water. My landlord won't fix it.",
                expected_routes=["repairs_maintenance"],
                forbidden_routes=["property_change"],
                description="property_change negative - broken fence is repairs, not alteration",
            ),
            # --- repairs_maintenance ---
            RouteFixture(
                question="There is mould on the bedroom ceiling and my landlord refuses to fix it.",
                expected_routes=["repairs_maintenance"],
                forbidden_routes=["property_change"],
                description="repairs_maintenance positive - mould",
            ),
            RouteFixture(
                question="I want to install a new fixture in the bathroom without landlord consent. Is that an alteration?",
                expected_routes=["property_change"],
                forbidden_routes=["repairs_maintenance"],
                description="repairs_maintenance negative - install fixture is property_change",
            ),
            # --- landlord_entry ---
            RouteFixture(
                question="My landlord came in without giving me 24 hours notice. What are my rights?",
                expected_routes=["landlord_entry"],
                forbidden_routes=["repairs_maintenance"],
                description="landlord_entry positive - entry without notice",
            ),
            RouteFixture(
                question="My landlord is not maintaining the property and will not fix the broken stove.",
                expected_routes=["repairs_maintenance"],
                forbidden_routes=["landlord_entry"],
                description="landlord_entry negative - maintenance failure is repairs, not entry",
            ),
            # --- agreement_form ---
            RouteFixture(
                question="My landlord never gave me a copy of the tenancy agreement after I signed it.",
                expected_routes=["agreement_form"],
                forbidden_routes=["bond"],
                description="agreement_form positive - copy of signed tenancy agreement",
            ),
            RouteFixture(
                question="My landlord asked me to sign a bond form but I have not received a receipt.",
                expected_routes=["bond"],
                forbidden_routes=["agreement_form"],
                description="agreement_form negative - bond receipt, not tenancy agreement",
            ),
            # --- bond ---
            RouteFixture(
                question="My landlord still has not lodged my bond with Tenancy Services after 3 weeks.",
                expected_routes=["bond"],
                forbidden_routes=["rent_increase"],
                description="bond positive - bond not lodged",
            ),
            RouteFixture(
                question="My landlord increased the rent last month. What is the maximum allowed?",
                expected_routes=["rent_increase"],
                forbidden_routes=["bond"],
                description="bond negative - rent increase question, not bond",
            ),
            # --- rent_increase ---
            RouteFixture(
                question="My landlord wants to increase my rent by $200 per week. How much notice do they need to give?",
                expected_routes=["rent_increase"],
                forbidden_routes=["wear_and_tear"],
                description="rent_increase positive - rent increase notice",
            ),
            RouteFixture(
                question="My landlord is withholding my bond claiming carpet wear.",
                expected_routes=["wear_and_tear"],
                forbidden_routes=["rent_increase"],
                description="rent_increase negative - bond and wear, not rent increase",
            ),
            # --- termination_notice ---
            RouteFixture(
                question="My landlord gave me a 90 day eviction notice even though I have done nothing wrong.",
                expected_routes=["termination_notice"],
                forbidden_routes=["tenant_early_exit"],
                description="termination_notice positive - 90 day no-cause notice",
            ),
            RouteFixture(
                question="I want to leave my fixed term tenancy early because I got a job offer in another city.",
                expected_routes=["tenant_early_exit"],
                forbidden_routes=["termination_notice"],
                description="termination_notice negative - tenant leaving early is tenant_early_exit",
            ),
            # --- fixed_term_sell ---
            RouteFixture(
                question="My landlord wants to sell the house and needs us to vacate before listing it. We are on a fixed term.",
                expected_routes=["fixed_term_sell"],
                forbidden_routes=["termination_notice"],
                description="fixed_term_sell positive - landlord selling during fixed term",
            ),
            RouteFixture(
                question="My landlord increased the rent while I am still on a fixed term tenancy.",
                expected_routes=["rent_increase"],
                forbidden_routes=["fixed_term_sell"],
                description="fixed_term_sell negative - rent increase during fixed term",
            ),
            # --- tenant_early_exit ---
            RouteFixture(
                question="My partner has been offered a farm job with free housing. Can I leave the fixed term tenancy early?",
                expected_routes=["tenant_early_exit"],
                forbidden_routes=["termination_notice"],
                description="tenant_early_exit positive - partner job offer, fixed term",
            ),
            RouteFixture(
                question="I want to end the tenancy because my landlord has not maintained the property.",
                expected_routes=["termination_notice", "repairs_maintenance"],
                forbidden_routes=["tenant_early_exit"],
                description="tenant_early_exit negative - ending tenancy for landlord breach",
            ),
            # --- sham_flatmate_agreement ---
            RouteFixture(
                question="We are on a flatmate agreement but our landlord does not live at the property at all.",
                expected_routes=["sham_flatmate_agreement"],
                forbidden_routes=["agreement_form"],
                description="sham_flatmate_agreement positive - landlord not resident",
            ),
            RouteFixture(
                question="I have a dispute with my landlord about the tenancy agreement terms.",
                expected_routes=["agreement_form"],
                forbidden_routes=["sham_flatmate_agreement"],
                description="sham_flatmate_agreement negative - tenancy agreement dispute, not sham",
            ),
            # --- carpark_dispute ---
            RouteFixture(
                question="My landlord is asking me to vacate one of my two carparks that came with the tenancy.",
                expected_routes=["carpark_dispute"],
                forbidden_routes=["repairs_maintenance"],
                description="carpark_dispute positive - landlord removing agreed carpark",
            ),
            RouteFixture(
                question="The garage door is broken and my landlord will not repair it.",
                expected_routes=["repairs_maintenance"],
                forbidden_routes=["carpark_dispute"],
                description="carpark_dispute negative - broken garage door is repairs, not carpark dispute",
            ),
            # --- healthy_homes ---
            RouteFixture(
                question="My rental has no ceiling insulation and the heating does not meet the healthy homes standards.",
                expected_routes=["healthy_homes"],
                forbidden_routes=["repairs_maintenance"],
                description="healthy_homes positive - insulation and healthy homes standards",
            ),
            RouteFixture(
                question="The hot water cylinder is not working and my landlord has not fixed it in two weeks.",
                expected_routes=["repairs_maintenance"],
                forbidden_routes=["healthy_homes"],
                description="healthy_homes negative - broken hot water is repairs, not healthy homes",
            ),
            # --- fixed_term_rent_review ---
            RouteFixture(
                question="We are on a fixed term tenancy and there is a rent review in 6 months. What can the landlord increase it by?",
                expected_routes=["fixed_term_rent_review", "rent_increase"],
                forbidden_routes=["tenant_early_exit"],
                description="fixed_term_rent_review positive - fixed term + rent review fires both routes",
            ),
            RouteFixture(
                question="My landlord wants to increase my rent by $50 per week. How much notice do they need to give?",
                expected_routes=["rent_increase"],
                forbidden_routes=["fixed_term_rent_review"],
                description="fixed_term_rent_review negative - rent increase with no fixed term must not fire fixed_term_rent_review",
            ),
            # --- two-tier trigger tests for property_change ---
            RouteFixture(
                question="The landlord has been mowing the lawn and trimming trees at the property.",
                expected_routes=[],
                forbidden_routes=["property_change"],
                description="two-tier: bare broad terms (lawn, trees) without consent context must NOT fire property_change",
            ),
            RouteFixture(
                question="I planted a tree in the garden without getting the landlord's consent. Am I in breach?",
                expected_routes=["property_change"],
                forbidden_routes=["repairs_maintenance", "wear_and_tear"],
                description="two-tier: broad term (tree, garden) + consent context fires property_change; repairs must not co-fire",
            ),
            RouteFixture(
                question="I made an alteration to the bathroom without telling my landlord.",
                expected_routes=["property_change"],
                forbidden_routes=["repairs_maintenance"],
                description="two-tier: precise term (alteration) fires property_change unconditionally",
            ),
            RouteFixture(
                question="I made an alteration to the bathroom but the plumbing is now broken and not working.",
                expected_routes=[],
                forbidden_routes=["property_change"],
                description="two-tier: exclude_any (broken, not working, plumbing) overrides precise term (alteration) - property_change must NOT fire",
            ),
        ]

    def format_source_label(self, source: dict) -> str:
        court = source.get("court_name", "Tenancy Tribunal")
        date = source.get("date", "")
        return f"{court} - {date}" if date else court

    def get_scraper(self):
        from jurisdictions.nz_tenancy.scraper import NZTenancyScraper
        return NZTenancyScraper()
