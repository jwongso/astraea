"""Request-scoped timing instrumentation.

Usage in any async function:
    from core.timing import get_timer
    t0 = time.perf_counter_ns()
    result = await do_something()
    if timer := get_timer():
        timer.record("step_name", (time.perf_counter_ns() - t0) // 1000)

Usage with context manager:
    if timer := get_timer():
        with timer.span("step_name"):
            result = do_something()
    else:
        result = do_something()

The timer is set per-request in api.py and propagated automatically via
contextvars (works correctly across asyncio.gather and task boundaries).
"""

from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from typing import Generator

_current_timer: contextvars.ContextVar[TimingCollector | None] = (
    contextvars.ContextVar("_current_timer", default=None)
)


class TimingCollector:
    """Collects named timing spans for one request. Thread-safe (immutable append)."""

    __slots__ = ("_t0", "_steps")

    def __init__(self) -> None:
        self._t0: int = time.perf_counter_ns()
        self._steps: list[dict] = []

    def record(self, name: str, duration_us: int, **meta) -> None:
        """Record a completed span by name (duration in microseconds)."""
        entry: dict = {"name": name, "us": duration_us, "ms": round(duration_us / 1000, 3)}
        if meta:
            entry.update(meta)
        self._steps.append(entry)

    @contextmanager
    def span(self, name: str, **meta) -> Generator[None, None, None]:
        """Context manager that records wall-clock duration of the block."""
        t = time.perf_counter_ns()
        try:
            yield
        finally:
            self.record(name, (time.perf_counter_ns() - t) // 1000, **meta)

    def elapsed_us(self) -> int:
        return (time.perf_counter_ns() - self._t0) // 1000

    def to_dict(self) -> dict:
        total_us = self.elapsed_us()
        return {
            "total_ms": round(total_us / 1000, 2),
            "total_us": total_us,
            "steps": list(self._steps),
        }


def get_timer() -> TimingCollector | None:
    """Return the active timer for the current request, or None."""
    return _current_timer.get()


def install_timer() -> tuple[TimingCollector, contextvars.Token]:
    """Create and install a new timer for the current async context.

    Returns (timer, token). Call token.var.reset(token) to restore previous state.
    """
    t = TimingCollector()
    tok = _current_timer.set(t)
    return t, tok
