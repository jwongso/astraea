"""NZ Tenancy jurisdiction - tenancy.localrun.ai

Covers NZ residential tenancy law: Tenancy Tribunal decisions (NZTT) +
live RTA 1986 section extraction from legislation.govt.nz.
"""

from core.jurisdiction import (
    CorpusConfig,
    JurisdictionBase,
    LegislationConfig,
    LegislationSource,
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
            leg_collection="nz_legal",
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
                description="rent_payment route",
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
        ]

    def format_source_label(self, source: dict) -> str:
        court = source.get("court_name", "Tenancy Tribunal")
        date = source.get("date", "")
        return f"{court} - {date}" if date else court

    def get_scraper(self):
        from jurisdictions.nz_tenancy.scraper import NZTenancyScraper
        return NZTenancyScraper()
