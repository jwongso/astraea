"""Unit tests for refine-retrieve and session helpers in core/api.py.

These tests are stateless (no Qdrant, no LLM) and always run.
They verify the confidence classification thresholds and the
query deduplication logic used by _refine_retrieve.
"""

import pytest

from core.anchor import _dedupe_queries
from core.api import _confidence
from core.session import _format_session_context, _SESSION_ID_RE


# ---------------------------------------------------------------------------
# _confidence thresholds
# ---------------------------------------------------------------------------

class TestConfidence:

    def test_empty_scores_is_low(self):
        r = _confidence([])
        assert r["level"] == "low"
        assert r["chunks"] == 0

    def test_single_low_score_is_low(self):
        r = _confidence([0.70])
        assert r["level"] == "low"

    def test_single_high_score_insufficient_chunks_is_low(self):
        # top >= 0.82 but n < 4 -> not high; top >= 0.77 but n < 2 -> not medium
        r = _confidence([0.90])
        assert r["level"] == "low"

    def test_two_medium_scores_is_medium(self):
        r = _confidence([0.80, 0.78])
        assert r["level"] == "medium"

    def test_four_high_scores_is_high(self):
        r = _confidence([0.85, 0.83, 0.82, 0.82])
        assert r["level"] == "high"

    def test_four_scores_below_high_threshold_is_medium(self):
        r = _confidence([0.80, 0.79, 0.78, 0.77])
        assert r["level"] == "medium"

    def test_boundary_top_exactly_082_four_chunks(self):
        r = _confidence([0.82, 0.80, 0.79, 0.78])
        assert r["level"] == "high"

    def test_boundary_top_exactly_077_two_chunks(self):
        r = _confidence([0.77, 0.77])
        assert r["level"] == "medium"

    def test_refine_triggers_on_low_confidence(self):
        # The contract: refine fires iff level == "low"
        assert _confidence([])["level"] == "low"
        assert _confidence([0.70])["level"] == "low"
        assert _confidence([0.90])["level"] == "low"  # 1 chunk, below medium n threshold

    def test_refine_does_not_trigger_on_medium(self):
        assert _confidence([0.80, 0.78])["level"] == "medium"

    def test_message_present(self):
        for scores in ([], [0.70], [0.80, 0.78], [0.85, 0.83, 0.82, 0.82]):
            r = _confidence(scores)
            assert r["message"]


# ---------------------------------------------------------------------------
# _dedupe_queries
# ---------------------------------------------------------------------------

class TestDedupeQueries:

    def test_identical_queries_returns_one(self):
        result = _dedupe_queries("heating broken", "heating broken")
        assert result == ["heating broken"]

    def test_different_queries_returns_both(self):
        result = _dedupe_queries("heating is broken in my flat", "heating broken flat")
        assert len(result) == 2
        assert result[0] == "heating is broken in my flat"

    def test_case_insensitive_dedup(self):
        result = _dedupe_queries("Heating Broken", "heating broken")
        assert len(result) == 1

    def test_whitespace_normalised(self):
        result = _dedupe_queries("  heating  broken  ", "heating broken")
        assert len(result) == 1

    def test_original_is_first(self):
        result = _dedupe_queries("original question here", "rewritten version")
        assert result[0] == "original question here"


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

class TestSessionIdValidation:

    def test_valid_uuid4_accepted(self):
        import uuid
        uid = str(uuid.uuid4())
        assert _SESSION_ID_RE.match(uid)

    def test_non_hex_rejected(self):
        assert not _SESSION_ID_RE.match("test-session-12345")

    def test_too_short_rejected(self):
        assert not _SESSION_ID_RE.match("abc123")

    def test_empty_rejected(self):
        assert not _SESSION_ID_RE.match("")

    def test_uppercase_rejected(self):
        # crypto.randomUUID() always produces lowercase; uppercase would be anomalous
        assert not _SESSION_ID_RE.match("550E8400-E29B-41D4-A716-446655440000")


class TestFormatSessionContext:

    def test_empty_turns_returns_empty(self):
        assert _format_session_context([]) == ""

    def test_single_turn_formatted(self):
        turns = [{"q": "Can my landlord enter?", "a": "No, 24 hours notice is required.", "ts": 0}]
        result = _format_session_context(turns)
        assert "Can my landlord enter?" in result
        assert "24 hours notice" in result
        assert "Recent conversation" in result

    def test_answer_truncated_with_ellipsis(self):
        long_answer = "x" * 401
        # Simulate stored turn where answer was already capped at 400 chars
        turns = [{"q": "q", "a": long_answer[:400], "ts": 0}]
        result = _format_session_context(turns)
        assert result.endswith("...")

    def test_short_answer_no_ellipsis(self):
        turns = [{"q": "q", "a": "Short answer.", "ts": 0}]
        result = _format_session_context(turns)
        assert not result.endswith("...")

    def test_multiple_turns_all_present(self):
        turns = [
            {"q": "Question one", "a": "Answer one", "ts": 0},
            {"q": "Question two", "a": "Answer two", "ts": 1},
            {"q": "Question three", "a": "Answer three", "ts": 2},
        ]
        result = _format_session_context(turns)
        for t in turns:
            assert t["q"] in result
            assert t["a"] in result
