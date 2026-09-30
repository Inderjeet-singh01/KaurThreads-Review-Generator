"""Collapse repeats of one generation request into one LLM run.

The frontend sends an ``Idempotency-Key`` (one per Generate/Regenerate
click) and resends it when it retries after a timeout or dropped
connection. A repeat that arrives while the first run is still going waits
for that run instead of starting a second LLM call; a repeat after it
succeeded gets the same review back. Failures are not kept, so a retry
after a failure runs again.

In-memory and per process: enough for a single Render instance.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class StillRunningError(Exception):
    """The original run didn't finish within the repeat's wait."""


@dataclass
class _Run:
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    finished_at: float | None = None


class RequestDeduplicator:
    """Thread-safe single-flight with a short memory of successful results."""

    def __init__(self, ttl_seconds: float = 120.0, max_entries: int = 500, wait_seconds: float = 30.0):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._wait = wait_seconds
        self._runs: dict[Hashable, _Run] = {}
        self._lock = threading.Lock()

    def run(self, key: Hashable | None, fn: Callable[[], Any]) -> Any:
        """``fn()``, unless a run for ``key`` is in flight or recently
        succeeded; then that run's outcome. ``key=None`` always runs."""
        if key is None:
            return fn()
        with self._lock:
            self._evict()
            run = self._runs.get(key)
            owner = run is None
            if owner:
                run = self._runs[key] = _Run()
        if not owner:
            logger.info("Duplicate generation request joined the existing run (finished=%s)", run.done.is_set())
            if not run.done.wait(self._wait):
                raise StillRunningError()
            if run.error is not None:
                raise run.error
            return run.result
        try:
            run.result = fn()
        except BaseException as exc:
            run.error = exc
            with self._lock:  # forget failures: a later retry runs afresh
                self._runs.pop(key, None)
            raise
        finally:
            run.finished_at = time.monotonic()
            run.done.set()
        return run.result

    def _evict(self) -> None:
        # Caller holds self._lock.
        cutoff = time.monotonic() - self._ttl
        for key in [k for k, r in self._runs.items() if r.finished_at is not None and r.finished_at < cutoff]:
            del self._runs[key]
        while len(self._runs) >= self._max:
            finished = [k for k, r in self._runs.items() if r.finished_at is not None]
            if not finished:
                break
            del self._runs[finished[0]]  # dicts keep insertion order: oldest first
