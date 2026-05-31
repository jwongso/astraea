"""NZ Tenancy jurisdiction - tenancy.localrun.ai

Covers NZ residential tenancy law: Tenancy Tribunal decisions (NZTT) +
live RTA 1986 section extraction from legislation.govt.nz.
"""

from core.jurisdiction import (
    CorpusConfig,
    JurisdictionBase,
    LegislationConfig,
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
        ]

    def format_source_label(self, source: dict) -> str:
        court = source.get("court_name", "Tenancy Tribunal")
        date = source.get("date", "")
        return f"{court} - {date}" if date else court

    def get_scraper(self):
        from jurisdictions.nz_tenancy.scraper import NZTenancyScraper
        return NZTenancyScraper()
