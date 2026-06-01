"""Unit tests for core MCP factory (core/mcp.py) and JurisdictionService (core/service.py).

All tests are stateless (no Qdrant, no LLM). They verify:
  - ServiceError attributes
  - JurisdictionService._validate() enforcement
  - create_mcp_server() tool registration (names, count, leg-conditional)
  - Tool call handlers always return valid JSON (never raise)
  - register_mcp_tools() hook is called and extra tools are reachable
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.jurisdiction import CorpusConfig, JurisdictionBase
from core.service import JurisdictionService, ServiceError


# ---------------------------------------------------------------------------
# Minimal fake jurisdiction (no live services required)
# ---------------------------------------------------------------------------

class _Jx(JurisdictionBase):
    @property
    def name(self): return "test-jx"
    @property
    def corpus(self):
        return CorpusConfig(
            qdrant_collection="test_col",
            courts=["TEST"],
            leg_collection="test_leg_col",
        )
    @property
    def system_prompt(self): return "You are a concise legal assistant."
    @property
    def routes(self): return []
    def get_scraper(self): return None
    @property
    def description(self): return "Test Legal Jurisdiction"


class _JxNoLeg(_Jx):
    """Same as _Jx but without leg_collection - legal_get_legislation must be absent."""
    @property
    def corpus(self):
        return CorpusConfig(
            qdrant_collection="test_col",
            courts=["TEST"],
            leg_collection=None,
        )


def _mock_service(jx=None):
    """Return a fully-mocked JurisdictionService with canned async responses."""
    if jx is None:
        jx = _Jx()
    svc = MagicMock(spec=JurisdictionService)
    svc.jurisdiction = jx
    svc.pipeline = MagicMock()
    svc.leg_store = MagicMock()
    svc.search = AsyncMock(return_value=[
        {
            "case_id": "TEST/2025/001",
            "title": "Smith v Landlord",
            "court_name": "TEST",
            "date": "2025-03-01",
            "url": "https://example.com/001",
            "_score": 0.88,
        }
    ])
    svc.ask = AsyncMock(return_value={
        "answer": "A landlord must give 24 hours notice before entry.",
        "sources": [{"case_id": "TEST/2025/001", "title": "Smith v Landlord"}],
    })
    svc.get_source = AsyncMock(return_value={
        "source_id": "TEST/2025/001",
        "title": "Smith v Landlord",
        "court_name": "TEST",
        "date": "2025-03-01",
        "url": "https://example.com/001",
        "text": "The landlord failed to give the required notice...",
    })
    svc.get_legislation = AsyncMock(return_value={
        "section_id": "TESTLEG/ACT/s42",
        "title": "Section 42 - Entry",
        "text": "A landlord must give notice of at least 24 hours...",
        "url": "https://example.com/act/s42",
    })
    return svc


def _build(jx=None, svc=None):
    """Build a FastMCP server with mocked pipeline and service."""
    if jx is None:
        jx = _Jx()
    if svc is None:
        svc = _mock_service(jx)
    with patch("core.mcp.RAGPipeline"), \
         patch("core.mcp.VectorStore"), \
         patch("core.mcp.JurisdictionService", return_value=svc):
        from core.mcp import create_mcp_server
        return create_mcp_server(jx), svc


def _tools(server) -> dict:
    return {t.name: t for t in asyncio.run(server.list_tools())}


def _call(server, name, args=None) -> dict:
    content, _ = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(content[0].text)


# ---------------------------------------------------------------------------
# ServiceError
# ---------------------------------------------------------------------------

class TestServiceError:

    def test_is_exception(self):
        assert isinstance(ServiceError("fail"), Exception)

    def test_default_code_is_400(self):
        assert ServiceError("bad").code == 400

    def test_custom_code(self):
        assert ServiceError("not found", code=404).code == 404

    def test_message_preserved(self):
        assert str(ServiceError("specific message")) == "specific message"


# ---------------------------------------------------------------------------
# JurisdictionService._validate
# ---------------------------------------------------------------------------

class TestServiceValidation:

    def _svc(self, max_chars=200):
        jx = MagicMock(spec=JurisdictionBase)
        jx.max_question_chars = max_chars
        return JurisdictionService(jx, MagicMock())

    def test_empty_string_raises(self):
        with pytest.raises(ServiceError, match="empty"):
            self._svc()._validate("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ServiceError, match="empty"):
            self._svc()._validate("   ")

    def test_exceeds_max_chars_raises(self):
        svc = self._svc(max_chars=10)
        with pytest.raises(ServiceError, match="10 characters"):
            svc._validate("a" * 11)

    def test_valid_question_returned(self):
        result = self._svc()._validate("Can my landlord enter without notice?")
        assert "landlord" in result

    def test_leading_trailing_whitespace_stripped(self):
        result = self._svc()._validate("  what are my rights?  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_at_exact_limit_accepted(self):
        svc = self._svc(max_chars=20)
        result = svc._validate("a" * 20)
        assert result  # should not raise


# ---------------------------------------------------------------------------
# create_mcp_server - tool registration
# ---------------------------------------------------------------------------

class TestToolRegistration:

    def test_server_name_contains_jurisdiction_name(self):
        server, _ = _build()
        assert "test-jx" in server.name

    def test_server_name_prefix_astraea(self):
        server, _ = _build()
        assert server.name.startswith("astraea-")

    def test_core_tools_always_registered(self):
        server, _ = _build()
        names = set(_tools(server))
        assert {"legal_search", "legal_ask", "legal_get_source"} <= names

    def test_legislation_tool_present_with_leg_collection(self):
        server, _ = _build(jx=_Jx())
        assert "legal_get_legislation" in _tools(server)

    def test_legislation_tool_absent_without_leg_collection(self):
        jx = _JxNoLeg()
        svc = _mock_service(jx)
        with patch("core.mcp.RAGPipeline"), \
             patch("core.mcp.JurisdictionService", return_value=svc):
            from core.mcp import create_mcp_server
            server = create_mcp_server(jx)
        assert "legal_get_legislation" not in _tools(server)

    def test_exactly_four_tools_with_leg_collection(self):
        server, _ = _build(jx=_Jx())
        assert len(_tools(server)) == 4

    def test_exactly_three_tools_without_leg_collection(self):
        jx = _JxNoLeg()
        svc = _mock_service(jx)
        with patch("core.mcp.RAGPipeline"), \
             patch("core.mcp.JurisdictionService", return_value=svc):
            from core.mcp import create_mcp_server
            server = create_mcp_server(jx)
        assert len(_tools(server)) == 3

    def test_tool_descriptions_are_non_empty(self):
        server, _ = _build()
        for name, tool in _tools(server).items():
            assert tool.description, f"Tool {name!r} has empty description"

    def test_search_description_mentions_jurisdiction(self):
        server, _ = _build()
        desc = _tools(server)["legal_search"].description
        assert "Test Legal Jurisdiction" in desc

    def test_register_mcp_tools_hook_is_called(self):
        jx = _Jx()
        jx.register_mcp_tools = MagicMock()
        svc = _mock_service(jx)
        _build(jx=jx, svc=svc)
        jx.register_mcp_tools.assert_called_once()

    def test_register_mcp_tools_receives_mcp_and_service(self):
        captured = {}
        class _HookJx(_Jx):
            def register_mcp_tools(self, mcp, service):
                captured["mcp"] = mcp
                captured["service"] = service
        jx = _HookJx()
        svc = _mock_service(jx)
        _build(jx=jx, svc=svc)
        assert "mcp" in captured
        assert "service" in captured


# ---------------------------------------------------------------------------
# Tool call behavior - always returns valid JSON, never raises
# ---------------------------------------------------------------------------

class TestToolCallBehavior:

    # -- legal_search --

    def test_search_returns_sources_list(self):
        server, _ = _build()
        result = _call(server, "legal_search", {"query": "entry notice"})
        assert "sources" in result
        assert isinstance(result["sources"], list)

    def test_search_count_equals_sources_length(self):
        server, _ = _build()
        result = _call(server, "legal_search", {"query": "bond deduction"})
        assert result["count"] == len(result["sources"])

    def test_search_service_error_returns_json_error_not_exception(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.search = AsyncMock(side_effect=ServiceError("Question too long."))
        server, _ = _build(jx, svc)
        result = _call(server, "legal_search", {"query": "x"})
        assert "error" in result
        assert "Question too long" in result["error"]

    def test_search_unexpected_exception_returns_json_error_not_exception(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.search = AsyncMock(side_effect=RuntimeError("qdrant down"))
        server, _ = _build(jx, svc)
        result = _call(server, "legal_search", {"query": "x"})
        assert "error" in result

    def test_search_passes_top_k_to_service(self):
        jx = _Jx()
        svc = _mock_service(jx)
        server, _ = _build(jx, svc)
        _call(server, "legal_search", {"query": "bond", "top_k": 3})
        svc.search.assert_awaited_once_with("bond", top_k=3)

    # -- legal_ask --

    def test_ask_returns_answer_and_sources(self):
        server, _ = _build()
        result = _call(server, "legal_ask", {"question": "Can my landlord enter?"})
        assert "answer" in result
        assert "sources" in result
        assert isinstance(result["answer"], str) and result["answer"]

    def test_ask_service_error_returns_json_error_not_exception(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.ask = AsyncMock(side_effect=ServiceError("Empty question."))
        server, _ = _build(jx, svc)
        result = _call(server, "legal_ask", {"question": "x"})
        assert "error" in result

    def test_ask_unexpected_exception_returns_json_error_not_exception(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.ask = AsyncMock(side_effect=OSError("llm unreachable"))
        server, _ = _build(jx, svc)
        result = _call(server, "legal_ask", {"question": "x"})
        assert "error" in result

    # -- legal_get_source --

    def test_get_source_found_returns_full_record(self):
        server, _ = _build()
        result = _call(server, "legal_get_source", {"source_id": "TEST/2025/001"})
        assert result["source_id"] == "TEST/2025/001"
        assert "title" in result
        assert "text" in result
        assert "url" in result

    def test_get_source_not_found_returns_json_error(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.get_source = AsyncMock(return_value=None)
        server, _ = _build(jx, svc)
        result = _call(server, "legal_get_source", {"source_id": "MISSING/999"})
        assert "error" in result
        assert "MISSING/999" in result["error"]

    def test_get_source_unexpected_exception_returns_json_error(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.get_source = AsyncMock(side_effect=RuntimeError("timeout"))
        server, _ = _build(jx, svc)
        result = _call(server, "legal_get_source", {"source_id": "TEST/001"})
        assert "error" in result

    # -- legal_get_legislation --

    def test_get_legislation_found_returns_full_record(self):
        server, _ = _build()
        result = _call(server, "legal_get_legislation", {"section_id": "TESTLEG/ACT/s42"})
        assert result["section_id"] == "TESTLEG/ACT/s42"
        assert "title" in result
        assert "text" in result

    def test_get_legislation_not_found_returns_json_error(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.get_legislation = AsyncMock(return_value=None)
        server, _ = _build(jx, svc)
        result = _call(server, "legal_get_legislation", {"section_id": "NZLEG/RTA/s9999"})
        assert "error" in result
        assert "NZLEG/RTA/s9999" in result["error"]

    def test_get_legislation_unexpected_exception_returns_json_error(self):
        jx = _Jx()
        svc = _mock_service(jx)
        svc.get_legislation = AsyncMock(side_effect=RuntimeError("qdrant timeout"))
        server, _ = _build(jx, svc)
        result = _call(server, "legal_get_legislation", {"section_id": "TESTLEG/ACT/s42"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Jurisdiction-specific tools via register_mcp_tools hook
# ---------------------------------------------------------------------------

class TestJurisdictionExtraTools:

    def _build_with_extra(self, extra_fn_name="custom_tool"):
        class _ExtJx(_Jx):
            def register_mcp_tools(self, mcp, service):
                async def custom_tool() -> str:
                    return json.dumps({"result": "jurisdiction-specific"})
                mcp.add_tool(custom_tool, name=extra_fn_name,
                             description="A jurisdiction-specific tool.")
        jx = _ExtJx()
        return _build(jx=jx)

    def test_extra_tool_appears_in_tool_list(self):
        server, _ = self._build_with_extra("nz_tenancy_check_rta_section")
        assert "nz_tenancy_check_rta_section" in _tools(server)

    def test_extra_tool_is_callable_and_returns_json(self):
        server, _ = self._build_with_extra("nz_get_bond_threshold")
        result = _call(server, "nz_get_bond_threshold", {})
        assert "result" in result

    def test_extra_tool_does_not_shadow_core_tools(self):
        server, _ = self._build_with_extra("nz_extra")
        names = set(_tools(server))
        assert {"legal_search", "legal_ask", "legal_get_source", "legal_get_legislation"} <= names

    def test_jurisdiction_with_no_extras_has_exactly_four_tools(self):
        server, _ = _build(jx=_Jx())
        assert len(_tools(server)) == 4

    def test_jurisdiction_with_two_extras_has_six_tools(self):
        class _TwoExtraJx(_Jx):
            def register_mcp_tools(self, mcp, service):
                async def tool_a() -> str: return "{}"
                async def tool_b() -> str: return "{}"
                mcp.add_tool(tool_a, name="jx_tool_a", description="A")
                mcp.add_tool(tool_b, name="jx_tool_b", description="B")
        jx = _TwoExtraJx()
        server, _ = _build(jx=jx)
        assert len(_tools(server)) == 6
