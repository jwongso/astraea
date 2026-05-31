"""NZ Employment jurisdiction.

Covers NZ employment law: Employment Relations Authority (NZERA) and
Employment Court (NZEmpC) decisions, with live ERA 2000 section extraction.

Primary use case: employees understanding their rights around dismissal,
personal grievances, good faith, redundancy, and minimum entitlements.
"""

from core.jurisdiction import (
    CorpusConfig,
    JurisdictionBase,
    LegislationConfig,
    SmokeFixture,
    WebVerifyConfig,
)
from core.routing import StatuteRoute
from jurisdictions.nz_employment.prompt import SYSTEM_PROMPT
from jurisdictions.nz_employment.routes import LOW_PRIORITY_SECTIONS, ROUTES


class NZEmploymentJurisdiction(JurisdictionBase):

    @property
    def name(self) -> str:
        return "nz-employment"

    @property
    def description(self) -> str:
        return "Free NZ employment law Q&A - ERA and Employment Court decisions"

    @property
    def corpus(self) -> CorpusConfig:
        return CorpusConfig(
            qdrant_collection="nz_legal",
            courts=["NZERA", "NZEmpC"],
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
            acts={
                "ERA2000": "https://www.legislation.govt.nz/act/public/2000/0024/latest/whole.html",
                "HOLIDAYS": "https://www.legislation.govt.nz/act/public/2003/0129/latest/whole.html",
            },
            cache_ttl_seconds=3600,
        )

    @property
    def web_verify(self) -> WebVerifyConfig:
        return WebVerifyConfig(
            search_prefix="NZ employment law ERA 2000",
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
                question="My employer fired me without any warning or process. Do I have a case?",
                expected_sections=["NZLEG/ERA2000/s103A", "NZLEG/ERA2000/s104"],
                description="unjustified_dismissal - no process",
            ),
            SmokeFixture(
                question="How long do I have to raise a personal grievance after being dismissed?",
                expected_sections=["NZLEG/ERA2000/s114"],
                description="personal_grievance - 90 day time limit",
            ),
            SmokeFixture(
                question="My employer made my role redundant but I think it was just to get rid of me. What are my rights?",
                expected_sections=["NZLEG/ERA2000/s103A", "NZLEG/ERA2000/s4"],
                description="redundancy - sham restructure",
            ),
            SmokeFixture(
                question="What does good faith mean in an employment relationship?",
                expected_sections=["NZLEG/ERA2000/s4"],
                description="good_faith - s4 definition",
            ),
            SmokeFixture(
                question="Can I get my job back after being unfairly dismissed?",
                expected_sections=["NZLEG/ERA2000/s123", "NZLEG/ERA2000/s125"],
                description="remedies - reinstatement",
            ),
        ]

    def format_source_label(self, source: dict) -> str:
        court = source.get("court_name", "")
        if not court:
            c = source.get("court", "")
            court = "Employment Relations Authority" if c == "NZERA" else \
                    "Employment Court" if c == "NZEmpC" else c
        date = source.get("date", "")
        return f"{court} - {date}" if date else court

    def get_scraper(self):
        raise NotImplementedError(
            "NZ employment scraper not yet implemented. "
            "Source: https://www.nzlii.org/nz/cases/NZEmpC/ and "
            "https://www.nzlii.org/nz/cases/NZERA/"
        )
