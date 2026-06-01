"""JurisdictionBase - the single interface every jurisdiction module must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.routing import StatuteRoute

if TYPE_CHECKING:
    from fastapi import FastAPI


@dataclass
class CorpusConfig:
    """Pointers to the data stores for this jurisdiction."""
    qdrant_collection: str          # primary collection (cases + decisions)
    courts: list[str]               # Qdrant payload filter values, e.g. ["NZTT"]
    leg_collection: str | None = None  # separate collection for legislation chunks
    pg_database: str | None = None  # PostgreSQL database name, None = no SQL path


@dataclass
class LegislationConfig:
    """Live legislation extraction settings."""
    acts: dict[str, str]            # act_id -> URL, e.g. {"RTA": "https://..."}
    cache_ttl_seconds: int = 3600


@dataclass
class WebVerifyConfig:
    """Web search verification settings."""
    search_prefix: str              # e.g. "NZ residential tenancy law"
    max_results: int = 3
    cache_ttl_seconds: int = 604800  # 7 days


@dataclass
class SmokeFixture:
    """A single smoke test case for Tier 1 retrieval testing."""
    question: str
    expected_sections: list[str]    # section IDs that MUST appear in retrieval
    forbidden_sections: list[str] = field(default_factory=list)
    description: str = ""
    min_sources: int = 0            # if > 0, assert at least this many case sources returned


class JurisdictionBase(ABC):
    """Base class for a legal RAG jurisdiction.

    A jurisdiction module must implement 4 things:
        name            - short slug, used in logs and service names
        corpus          - which Qdrant collection and courts to search
        system_prompt   - the full LLM system prompt (jurisdiction owns this entirely)
        routes          - statute route table (may be empty list if no routing needed)

    Everything else has a working default. Start with just the 4 required properties
    and add optional overrides as you discover what your jurisdiction needs.
    """

    # -------------------------------------------------------------------------
    # Required (must implement)
    # -------------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short slug. e.g. 'nz-tenancy', 'nsw-tenancy'"""

    @property
    @abstractmethod
    def corpus(self) -> CorpusConfig: ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Full LLM system prompt. Jurisdiction owns this entirely - core does not modify it."""

    @property
    @abstractmethod
    def routes(self) -> list[StatuteRoute]:
        """Statute route table. Return [] if no routing is needed."""

    # -------------------------------------------------------------------------
    # Optional - override as needed
    # -------------------------------------------------------------------------

    @property
    def description(self) -> str:
        return f"{self.name} legal research tool"

    @property
    def legislation(self) -> LegislationConfig | None:
        """None = no live legislation anchor (falls back to vector store only)."""
        return None

    @property
    def web_verify(self) -> WebVerifyConfig | None:
        """None = no web search verification step."""
        return None

    @property
    def low_priority_sections(self) -> dict[str, tuple[str, ...]]:
        """Sections suppressed unless the query explicitly mentions listed terms."""
        return {}

    @property
    def rewrite_prompt(self) -> str | None:
        """Custom query rewrite prompt. None = use core default. Return '' = skip rewrite."""
        return None

    @property
    def max_question_chars(self) -> int:
        """Maximum allowed question length. Requests exceeding this get 400."""
        return 1200

    @property
    def forbidden_topics(self) -> tuple[str, ...]:
        """Topics outside this jurisdiction's scope, referenced in system prompt enforcement."""
        return ()

    @property
    def smoke_fixtures(self) -> list[SmokeFixture]:
        """Tier 1 retrieval smoke test fixtures. Core test suite runs these automatically."""
        return []

    def extract_section(self, act_id: str, section: str, full_text: str) -> str | None:
        """Extract a section excerpt from live Act text.

        Return None to use the core default heading-aware extractor.
        Override only if the legislation site has unusual formatting.
        """
        return None

    def format_source_label(self, source: dict) -> str:
        """How to render a source in the frontend. Override for jurisdiction-specific labels."""
        court = source.get("court_name") or source.get("court", "Unknown")
        date = source.get("date", "")
        return f"{court} - {date}" if date else court

    def register_routes(self, app: "FastAPI") -> None:
        """Optional: register jurisdiction-specific extra routes on the FastAPI app.

        Called at the end of create_app() after all core routes are registered.
        Route handlers can access pipeline and store via request.app.state.
        """

    def register_mcp_tools(self, mcp, service) -> None:
        """Optional: register jurisdiction-specific MCP tools on the server.

        Called by create_mcp_server() after the 4 core tools are registered.
        Use mcp.add_tool(fn, name=..., description=...) to add tools.
        The service parameter provides access to pipeline helpers.

        Args:
            mcp: FastMCP server instance.
            service: JurisdictionService with search/ask/get_source/get_legislation.
        """

    @abstractmethod
    def get_scraper(self):
        """Return a scraper instance for offline corpus ingestion.

        The scraper is not part of the API runtime - it runs offline to populate Qdrant.
        See schemas/qdrant_payload.schema.json for the required payload structure.
        """
