"""NSW Tenancy jurisdiction - Milestone 1 skeleton.

Covers NSW residential tenancy law: NCAT decisions (Consumer and Commercial
Division) + live RTA 2010 section extraction from legislation.nsw.gov.au.

No real corpus yet - this skeleton proves the interface works for a second
jurisdiction and can be wired to a real NCAT corpus when ingested.
"""

from core.jurisdiction import (
    CorpusConfig,
    JurisdictionBase,
    LegislationConfig,
    SmokeFixture,
    WebVerifyConfig,
)
from core.routing import StatuteRoute
from jurisdictions.nsw_tenancy.prompt import SYSTEM_PROMPT
from jurisdictions.nsw_tenancy.routes import LOW_PRIORITY_SECTIONS, ROUTES


class NSWTenancyJurisdiction(JurisdictionBase):

    @property
    def name(self) -> str:
        return "nsw-tenancy"

    @property
    def description(self) -> str:
        return "Free NSW residential tenancy law Q&A"

    @property
    def corpus(self) -> CorpusConfig:
        return CorpusConfig(
            qdrant_collection="nsw_tenancy_ncat",
            courts=["NSWCATCD"],
            leg_collection="nsw_legal",
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
            acts={"RTA2010": "https://legislation.nsw.gov.au/view/whole/html/inforce/current/act-2010-042"},
            cache_ttl_seconds=3600,
        )

    @property
    def web_verify(self) -> WebVerifyConfig:
        return WebVerifyConfig(
            search_prefix="NSW residential tenancy law",
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
                question="My landlord wants to enter the property without giving me notice. Is that allowed?",
                expected_sections=["NSWLEG/RTA2010/s72", "NSWLEG/RTA2010/s73"],
                description="landlord_entry route",
            ),
            SmokeFixture(
                question="The hot water system is broken. Whose responsibility is it to fix it?",
                expected_sections=["NSWLEG/RTA2010/s63"],
                description="repairs_maintenance - urgent repair",
            ),
            SmokeFixture(
                question="My landlord is trying to keep my bond. What are my rights?",
                expected_sections=["NSWLEG/RTA2010/s113"],
                description="bond route - bond claim",
            ),
            SmokeFixture(
                question="The carpet is old and worn. Can my landlord charge me for it at the end of tenancy?",
                expected_sections=["NSWLEG/RTA2010/s19", "NSWLEG/RTA2010/s42"],
                description="wear_and_tear route",
            ),
            SmokeFixture(
                question="My landlord wants to raise the rent. How much notice do I need to get?",
                expected_sections=["NSWLEG/RTA2010/s44"],
                description="rent route - rent increase",
            ),
        ]

    def format_source_label(self, source: dict) -> str:
        court = source.get("court_name", "NCAT")
        date = source.get("date", "")
        return f"{court} - {date}" if date else court

    def get_scraper(self):
        raise NotImplementedError(
            "NSW NCAT scraper not yet implemented. "
            "See ingest/base.py ScraperBase for the interface. "
            "Source: https://www.austlii.edu.au/cgi-bin/viewdb/au/cases/nsw/NSWCATCD/"
        )
