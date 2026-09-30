"""Persistent history of accepted reviews and the local checks that keep each
new review unique.

Accepted reviews are stored in a small SQLite file (Python standard library,
no extra service or dependency), so uniqueness survives restarts. Nothing here
calls an LLM. Only the first and last few words of recent reviews are ever
sent to the model (as "don't start/end like this"), never whole reviews.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from app.ai.review_rules import normalize, split_sentences

# Rows kept on disk, and how many of the newest are compared per request.
MAX_HISTORY = 1000
CHECK_WINDOW = 500

# Whole-review near-duplicates, against every review in the window.
MAX_SEQUENCE_SIMILARITY = 0.72  # character-level, SequenceMatcher ratio
MAX_TOKEN_SIMILARITY = 0.70  # word-set Jaccard overlap

# Sentences of MIN_SENTENCE_WORDS+ words may not closely repeat any past
# sentence; shorter ones only count on an exact repeat for a related input.
MAX_SENTENCE_SIMILARITY = 0.85
MIN_SENTENCE_WORDS = 5
RELATED_SENTENCE_WINDOW = 8

# Openings/closings (first/last EDGE_WORDS words, and the closing sentence)
# may not repeat the RECENT_WINDOW newest reviews or newest related ones.
EDGE_WORDS = 3
RECENT_WINDOW = 5
MAX_CLOSING_SIMILARITY = 0.70

# Inputs this similar share a "family" ("good collection, nice quality" vs
# "nice quality and good collection"). The rating is ignored.
RELATED_INPUT_SEQUENCE = 0.75
RELATED_INPUT_TOKENS = 0.50


def token_similarity(a: str, b: str) -> float:
    """Jaccard overlap of the word sets of two normalized strings (0-1)."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def any_similar(text: str, others: Iterable[str], threshold: float) -> bool:
    """Whether ``text`` is at least ``threshold`` similar (SequenceMatcher
    ratio) to any of ``others``. Cheap upper bounds are checked first."""
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(text)
    for other in others:
        matcher.set_seq1(other)
        if (
            matcher.real_quick_ratio() >= threshold
            and matcher.quick_ratio() >= threshold
            and matcher.ratio() >= threshold
        ):
            return True
    return False


def opening(normalized: str) -> str:
    return " ".join(normalized.split()[:EDGE_WORDS])


def closing(normalized: str) -> str:
    return " ".join(normalized.split()[-EDGE_WORDS:])


def input_key(rating: int, experience: str | None) -> tuple[int, str]:
    """Identifies the request a review was written for."""
    return rating, normalize(experience or "")


def related_inputs(a: tuple[int, str], b: tuple[int, str]) -> bool:
    ea, eb = a[1], b[1]
    if ea == eb:
        return True
    if not ea or not eb:
        return False
    return (
        token_similarity(ea, eb) >= RELATED_INPUT_TOKENS
        or any_similar(ea, [eb], RELATED_INPUT_SEQUENCE)
    )


@dataclass(frozen=True)
class _Entry:
    key: tuple[int, str]
    normalized: str
    sentences: tuple[str, ...]  # normalized


def _entry(rating: int, input_text: str, review: str) -> _Entry:
    return _Entry(
        key=(rating, input_text),
        normalized=normalize(review),
        sentences=tuple(normalize(s) for s in split_sentences(review)),
    )


def _edge_pool(entries: list[_Entry], key: tuple[int, str]) -> list[_Entry]:
    """Newest reviews overall plus newest reviews for a related input."""
    related = [e for e in entries if related_inputs(e.key, key)]
    return entries[:RECENT_WINDOW] + related[:RECENT_WINDOW]


def uniqueness_problem(entries: list[_Entry], key: tuple[int, str], text: str) -> str | None:
    """Reason ``text`` repeats past reviews (``entries``, newest first), else None."""
    n = normalize(text)
    if not n:
        return "it was empty"
    for e in entries:
        if n == e.normalized:
            return "it was identical to a previous review"
        if token_similarity(n, e.normalized) >= MAX_TOKEN_SIMILARITY:
            return "it reused almost the same words as a previous review"
    if any_similar(n, (e.normalized for e in entries), MAX_SEQUENCE_SIMILARITY):
        return "its wording was too close to a previous review"

    pool = _edge_pool(entries, key)
    if any(opening(n) == opening(e.normalized) for e in pool):
        return f"it reused the opening '{opening(n)}'"
    if any(closing(n) == closing(e.normalized) for e in pool):
        return f"it reused the closing '{closing(n)}'"

    sentences = [normalize(s) for s in split_sentences(text)]
    if sentences and any_similar(
        sentences[-1], (e.sentences[-1] for e in pool if e.sentences), MAX_CLOSING_SIMILARITY
    ):
        return "its closing sentence followed the same pattern as a recent review"

    related_short = {
        s
        for e in [e for e in entries if related_inputs(e.key, key)][:RELATED_SENTENCE_WINDOW]
        for s in e.sentences
    }
    long_sentences = [
        s for e in entries for s in e.sentences if len(s.split()) >= MIN_SENTENCE_WORDS
    ]
    for sentence in sentences:
        if len(sentence.split()) >= MIN_SENTENCE_WORDS:
            if any_similar(sentence, long_sentences, MAX_SENTENCE_SIMILARITY):
                return "one of its sentences was almost the same as a sentence in a previous review"
        elif sentence in related_short:
            return "one of its sentences repeated a recent review"
    return None


class ReviewHistory:
    """Thread-safe, bounded, SQLite-backed record of accepted reviews.

    ``path`` may be ``":memory:"`` (tests, or no writable disk). The file is
    opened on first use, so importing this module never touches the disk.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        # Caller holds self._lock.
        if self._conn is None:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._path, timeout=5.0, isolation_level=None, check_same_thread=False
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS reviews ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " rating INTEGER NOT NULL,"
                " input TEXT NOT NULL,"
                " review TEXT NOT NULL,"
                " created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            self._conn = conn
        return self._conn

    def _entries(self, conn: sqlite3.Connection) -> list[_Entry]:
        rows = conn.execute(
            "SELECT rating, input, review FROM reviews ORDER BY id DESC LIMIT ?",
            (CHECK_WINDOW,),
        ).fetchall()
        return [_entry(*row) for row in rows]

    def recent_edges(self, key: tuple[int, str]) -> tuple[list[str], list[str]]:
        """Openings and closings a new review for ``key`` must not reuse."""
        with self._lock:
            pool = _edge_pool(self._entries(self._connect()), key)
        openings = list(dict.fromkeys(opening(e.normalized) for e in pool))
        closings = list(dict.fromkeys(closing(e.normalized) for e in pool))
        return openings, closings

    def add_if_unique(self, key: tuple[int, str], text: str) -> str | None:
        """Atomically check ``text`` against the history and store it.
        Returns the rejection reason, or ``None`` once stored."""
        with self._lock:
            conn = self._connect()
            # IMMEDIATE also serialises check+insert across worker processes.
            conn.execute("BEGIN IMMEDIATE")
            try:
                reason = uniqueness_problem(self._entries(conn), key, text)
                if reason is None:
                    conn.execute(
                        "INSERT INTO reviews (rating, input, review) VALUES (?, ?, ?)",
                        (key[0], key[1], text),
                    )
                    conn.execute(
                        "DELETE FROM reviews WHERE id <= (SELECT MAX(id) FROM reviews) - ?",
                        (MAX_HISTORY,),
                    )
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return reason
