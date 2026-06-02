"""Feedback log writer with file rotation.

Writes thumbs-up/down feedback to JSONL files. Rotates at configurable size
limits to prevent disk fill. Non-overridable rotation logic is a framework
security guarantee.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from cachetools import TTLCache
from fastapi import HTTPException, Request

from core.queue import get_client_ip

_FEEDBACK_LOG = Path("data/feedback.jsonl")
_FEEDBACK_FULL_LOG = Path("data/feedback_full.jsonl")
_FEEDBACK_DEBUG_LOG = Path("data/feedback_debug.jsonl")
_FEEDBACK_MAX_BYTES = 20 * 1024 * 1024       # 20 MB per file before rotation
_FEEDBACK_FULL_MAX_BYTES = 50 * 1024 * 1024  # 50 MB per file before rotation
_FEEDBACK_ROTATE_KEEP = 5
_FEEDBACK_COOLDOWN_S = 30

_feedback_last: TTLCache = TTLCache(maxsize=2000, ttl=_FEEDBACK_COOLDOWN_S)
_feedback_full_last: TTLCache = TTLCache(maxsize=4000, ttl=1)


def _rotate_log(path: Path, max_bytes: int) -> None:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return
    for i in range(_FEEDBACK_ROTATE_KEEP - 1, 0, -1):
        old = path.parent / f"{path.stem}.{i}{path.suffix}"
        new = path.parent / f"{path.stem}.{i + 1}{path.suffix}"
        if old.exists():
            old.rename(new)
    path.rename(path.parent / f"{path.stem}.1{path.suffix}")


def write_feedback(request: Request, question: str, rating: int, comment: str = "") -> None:
    if rating not in (1, -1):
        raise HTTPException(status_code=400, detail="Rating must be 1 or -1.")
    ip = get_client_ip(request)
    if ip in _feedback_last:
        raise HTTPException(status_code=429, detail="Please wait before submitting more feedback.")
    _feedback_last[ip] = 1
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": question[:2000],
        "rating": rating,
        "comment": comment[:500],
    }
    _FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log(_FEEDBACK_LOG, _FEEDBACK_MAX_BYTES)
    with _FEEDBACK_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def write_feedback_full(request: Request, entry: dict) -> None:
    ip = get_client_ip(request)
    if ip in _feedback_full_last:
        raise HTTPException(status_code=429, detail="Duplicate submission.")
    _feedback_full_last[ip] = 1
    _FEEDBACK_FULL_LOG.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log(_FEEDBACK_FULL_LOG, _FEEDBACK_FULL_MAX_BYTES)
    with _FEEDBACK_FULL_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def write_feedback_debug(request: Request, entry: dict) -> None:
    _FEEDBACK_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log(_FEEDBACK_DEBUG_LOG, _FEEDBACK_FULL_MAX_BYTES)
    with _FEEDBACK_DEBUG_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
