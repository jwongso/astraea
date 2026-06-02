"""Cross-encoder re-ranker for federated legislation retrieval.

Phase 1 - LOG ONLY: scores are computed and returned alongside candidates
but must NOT be used to reorder production results. The log lets us measure
how often the cross-encoder agrees with route-based ranking before we promote
it to influence output order.

Phase 2 (future): once benchmark data shows the cross-encoder matches or
exceeds route-based quality on the smoke regression set, flip
CrossEncoderReranker.log_only = False and the caller can use rerank() to order.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Wraps BAAI/bge-reranker-v2-m3 for (query, passage) relevance scoring.

    Loaded lazily at first call; warmed up immediately after load to amortise
    JIT overhead across subsequent queries.
    """

    def __init__(
        self,
        model: str = "BAAI/bge-reranker-v2-m3",
        max_length: int = 512,
        log_only: bool = True,
    ) -> None:
        self._model_name = model
        self._max_length = max_length
        self.log_only = log_only
        self._model: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder
        # Always run on CPU - GPU is reserved for the generation model.
        self._model = CrossEncoder(self._model_name, max_length=self._max_length, device="cpu")
        try:
            self._model.predict([("warmup", "warmup")])
        except Exception:
            pass

    def score(
        self,
        query: str,
        candidates: list,
    ) -> list[tuple[Any, float]]:
        """Score each candidate without changing their order.

        Returns list of (candidate, ce_score) in original input order.
        Scores are in [0, 1] (sigmoid-normalised by bge-reranker-v2-m3).
        """
        if not candidates:
            return []
        try:
            self._ensure_loaded()
            pairs = [(query, c.text) for c in candidates]
            scores = self._model.predict(pairs)
            raw = scores.tolist() if hasattr(scores, "tolist") else list(scores)
            return list(zip(candidates, raw))
        except Exception as exc:
            logger.warning("CrossEncoderReranker.score error: %s", exc)
            return [(c, 0.0) for c in candidates]

    def rerank(
        self,
        query: str,
        candidates: list,
        top_k: int | None = None,
    ) -> list:
        """Re-order candidates by cross-encoder score (highest first).

        Only call this when log_only is False and benchmark data supports it.
        """
        if not candidates:
            return candidates
        scored = self.score(query, candidates)
        scored.sort(key=lambda x: x[1], reverse=True)
        result = [c for c, _ in scored]
        return result[:top_k] if top_k is not None else result
