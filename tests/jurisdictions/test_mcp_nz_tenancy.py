"""MCP server tests for the NZ Tenancy jurisdiction.

Tier 0 (always-run): structural checks - no Qdrant or LLM required.
Tier 1 (skip_no_qdrant): live retrieval calls against real corpus.
Tier 2 (skip_no_qdrant + skip_no_llm): end-to-end ask with LLM generation.

Run all tiers:
    pytest tests/jurisdictions/test_mcp_nz_tenancy.py -v

Structural only:
    pytest tests/jurisdictions/test_mcp_nz_tenancy.py -v -m "not retrieval"

Retrieval + generation:
    pytest tests/jurisdictions/test_mcp_nz_tenancy.py -v -m retrieval
"""

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import skip_no_qdrant, skip_no_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tools(server):
    return {t.name: t for t in asyncio.run(server.list_tools())}


def _call(server, name, args=None):
    content, _ = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(content[0].text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def nz_tenancy_server():
    """Import the nz_tenancy MCP server once per module.

    The server is created at import time (module-level singleton in mcp_server.py).
    VectorStore/RAGPipeline connect to Qdrant lazily, so this works even when
    Qdrant is not running - structural tests never make a network call.
    """
    from jurisdictions.nz_tenancy.mcp_server import server
    return server


# ---------------------------------------------------------------------------
# Tier 0: structural (always-run, no Qdrant)
# ---------------------------------------------------------------------------

class TestNZTenancyMcpStructure:

    def test_server_is_fastmcp_instance(self, nz_tenancy_server):
        assert isinstance(nz_tenancy_server, FastMCP)

    def test_server_name(self, nz_tenancy_server):
        assert nz_tenancy_server.name == "astraea-nz-tenancy"

    def test_exactly_four_tools_registered(self, nz_tenancy_server):
        assert len(_tools(nz_tenancy_server)) == 4

    def test_all_four_tool_names_present(self, nz_tenancy_server):
        names = set(_tools(nz_tenancy_server))
        assert names == {
            "legal_search",
            "legal_ask",
            "legal_get_source",
            "legal_get_legislation",
        }

    def test_tools_all_have_descriptions(self, nz_tenancy_server):
        for name, tool in _tools(nz_tenancy_server).items():
            assert tool.description, f"Tool {name!r} has no description"

    def test_legal_search_description_mentions_tenancy(self, nz_tenancy_server):
        desc = _tools(nz_tenancy_server)["legal_search"].description.lower()
        assert "tenancy" in desc or "tribunal" in desc or "nz" in desc

    def test_legal_get_legislation_description_mentions_section_format(self, nz_tenancy_server):
        desc = _tools(nz_tenancy_server)["legal_get_legislation"].description
        assert "NZLEG" in desc

    def test_server_has_instructions(self, nz_tenancy_server):
        assert nz_tenancy_server.instructions

    def test_instructions_mention_not_legal_advice(self, nz_tenancy_server):
        instructions = nz_tenancy_server.instructions.lower()
        assert "lawyer" in instructions or "legal advice" in instructions

    def test_mcp_server_module_exports_server(self):
        from jurisdictions.nz_tenancy import mcp_server
        assert hasattr(mcp_server, "server")
        assert isinstance(mcp_server.server, FastMCP)


# ---------------------------------------------------------------------------
# Tier 1: live retrieval (skip when Qdrant unavailable)
# ---------------------------------------------------------------------------

@skip_no_qdrant
@pytest.mark.retrieval
class TestNZTenancyMcpSearch:
    """legal_search against the real NZ Tenancy corpus."""

    def test_search_returns_sources_for_landlord_entry(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "landlord entry without notice"})
        assert "sources" in result
        assert result["count"] >= 1

    def test_search_returns_sources_for_bond_dispute(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "bond deduction carpet damage"})
        assert result.get("count", 0) >= 1

    def test_search_count_matches_sources_length(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "wear and tear"})
        assert result["count"] == len(result["sources"])

    def test_search_sources_have_required_fields(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "repair obligation landlord"})
        for src in result.get("sources", []):
            assert "case_id" in src, f"Missing case_id: {src}"
            assert "url" in src, f"Missing url: {src}"
            assert "_score" in src, f"Missing _score: {src}"

    def test_search_scores_between_zero_and_one(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "landlord obligations heating repair"})
        for src in result.get("sources", []):
            score = src.get("_score", -1)
            assert 0.0 <= score <= 1.0, f"Score out of range: {score}"

    def test_search_top_k_one_returns_at_most_one(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "bond return", "top_k": 1})
        assert len(result.get("sources", [])) <= 1

    def test_search_top_k_five_returns_at_most_five(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "landlord entry", "top_k": 5})
        assert len(result.get("sources", [])) <= 5

    def test_search_sources_court_is_nztt_or_nzleg(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "bond deduction damage"})
        for src in result.get("sources", []):
            cid = src.get("case_id", "")
            court = cid.split("/")[0] if "/" in cid else ""
            assert court in {"NZTT", "NZLEG", ""}, f"Unexpected court prefix: {cid!r}"

    def test_search_empty_query_returns_json_error(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search", {"query": ""})
        assert "error" in result

    def test_search_overlong_query_returns_json_error(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_search",
                       {"query": "x" * 1300})
        assert "error" in result


@skip_no_qdrant
@pytest.mark.retrieval
class TestNZTenancyMcpGetSource:
    """legal_get_source against real corpus - uses a search first to get a real ID."""

    def _find_source_id(self, server, query="bond deduction"):
        result = _call(server, "legal_search", {"query": query, "top_k": 1})
        sources = result.get("sources", [])
        if not sources:
            pytest.skip(f"No sources found for query: {query!r}")
        return sources[0]["case_id"]

    def test_get_source_found_returns_required_fields(self, nz_tenancy_server):
        source_id = self._find_source_id(nz_tenancy_server)
        result = _call(nz_tenancy_server, "legal_get_source", {"source_id": source_id})
        assert "source_id" in result
        assert "title" in result
        assert "text" in result
        assert "url" in result

    def test_get_source_text_is_non_empty(self, nz_tenancy_server):
        source_id = self._find_source_id(nz_tenancy_server, "landlord entry notice")
        result = _call(nz_tenancy_server, "legal_get_source", {"source_id": source_id})
        if "error" not in result:
            assert len(result.get("text", "")) > 10

    def test_get_source_id_matches_requested(self, nz_tenancy_server):
        source_id = self._find_source_id(nz_tenancy_server)
        result = _call(nz_tenancy_server, "legal_get_source", {"source_id": source_id})
        if "error" not in result:
            assert result["source_id"] == source_id

    def test_get_source_not_found_returns_json_error(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_get_source",
                       {"source_id": "NZTT/TOTALLY-FAKE/9999"})
        assert "error" in result


@skip_no_qdrant
@pytest.mark.retrieval
class TestNZTenancyMcpGetLegislation:
    """legal_get_legislation against real legislation corpus."""

    # Common RTA sections that should be in the corpus
    _COMMON_SECTIONS = [
        "NZLEG/RTA/s42",
        "NZLEG/RTA/s40",
        "NZLEG/RTA/s45",
        "NZLEG/RTA/s55",
    ]

    def test_nonexistent_section_returns_json_error(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_get_legislation",
                       {"section_id": "NZLEG/RTA/s9999"})
        assert "error" in result

    def test_found_section_has_required_fields(self, nz_tenancy_server):
        for section_id in self._COMMON_SECTIONS:
            result = _call(nz_tenancy_server, "legal_get_legislation",
                           {"section_id": section_id})
            if "section_id" in result:
                assert "title" in result
                assert "text" in result
                assert "url" in result
                return
        pytest.skip("None of the probed RTA sections found in corpus")

    def test_found_section_text_non_empty(self, nz_tenancy_server):
        for section_id in self._COMMON_SECTIONS:
            result = _call(nz_tenancy_server, "legal_get_legislation",
                           {"section_id": section_id})
            if "section_id" in result:
                assert len(result.get("text", "")) > 20
                return
        pytest.skip("None of the probed RTA sections found in corpus")

    def test_response_is_always_valid_json(self, nz_tenancy_server):
        for section_id in ["NZLEG/RTA/s42", "NZLEG/RTA/s9999", "GARBAGE"]:
            result = _call(nz_tenancy_server, "legal_get_legislation",
                           {"section_id": section_id})
            assert isinstance(result, dict), \
                f"Response for {section_id!r} is not a dict: {result!r}"


# ---------------------------------------------------------------------------
# Tier 2: end-to-end ask with LLM generation
# ---------------------------------------------------------------------------

@skip_no_qdrant
@skip_no_llm
@pytest.mark.retrieval
class TestNZTenancyMcpAsk:
    """legal_ask end-to-end: retrieval + LLM generation against real services."""

    def test_ask_returns_answer_string(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_ask",
                       {"question": "What notice must a landlord give before entering?"})
        assert "answer" in result
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 50

    def test_ask_returns_sources_list(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_ask",
                       {"question": "Can a landlord deduct for fair wear and tear?"})
        assert "sources" in result
        assert isinstance(result["sources"], list)

    def test_ask_sources_have_case_id(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_ask",
                       {"question": "What is the maximum bond amount?"})
        for src in result.get("sources", []):
            assert "case_id" in src

    def test_ask_answer_is_human_readable_not_raw_json(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_ask",
                       {"question": "Can a landlord increase rent during a fixed term?"})
        if "answer" in result:
            assert not result["answer"].strip().startswith("{"), \
                "Answer looks like raw JSON - generator may have malfunctioned"

    def test_ask_empty_question_returns_json_error(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_ask", {"question": ""})
        assert "error" in result

    def test_ask_overlong_question_returns_json_error(self, nz_tenancy_server):
        result = _call(nz_tenancy_server, "legal_ask",
                       {"question": "x" * 1300})
        assert "error" in result
