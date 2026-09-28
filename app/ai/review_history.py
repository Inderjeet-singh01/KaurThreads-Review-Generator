"""In-memory history of generated reviews and the checks used to keep every
review unique and grounded.

The history lives only in this process (it resets on restart) and is never
returned to customers — it is only shown to the model as "do not repeat"
context and used to reject duplicates.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher

# How many past reviews are remembered for duplicate checks.
MAX_HISTORY = 500

# A candidate is "too similar" (hard reject) at or above either threshold.
MAX_SEQUENCE_SIMILARITY = 0.75  # character-level, SequenceMatcher ratio
MAX_TOKEN_SIMILARITY = 0.80  # word-set Jaccard overlap

# Openings/closings are compared over this many words, against this many of
# the most recent reviews for the same input.
EDGE_WORDS = 3
RECENT_EDGE_WINDOW = 5

# Generic first words ("The ...", "I ...") may not open two reviews in a row
# for the same input.
COMMON_STARTERS = frozenset({"the", "i", "great", "really", "overall"})
RECENT_STARTER_WINDOW = 1

MIN_SENTENCES = 2
MAX_SENTENCES = 4

# Topics the model must not introduce unless the customer mentioned them.
# A topic is allowed when ANY of its patterns appears in the experience text.
UNGROUNDED_TOPICS: dict[str, tuple[str, ...]] = {
    "staff": (
        r"staff", r"employees?", r"team", r"sales ?(?:person|man|woman|girl)s?",
        r"owners?", r"shopkeepers?", r"assistants?", r"helpers?", r"aunty",
        r"didi", r"bhaiya", r"people there",
    ),
    "service": (r"service", r"served", r"serving", r"attended", r"assisted"),
    "stitching": (
        r"stitch\w*", r"tailor\w*", r"alter\w*", r"custom\w*", r"measure\w*",
    ),
    "fitting": (r"fit", r"fits", r"fitted", r"fitting"),
    "fabric": (
        r"fabrics?", r"materials?", r"cotton", r"silk", r"linen", r"chiffon",
        r"georgette", r"velvet", r"rayon", r"crepe", r"net",
    ),
    "design": (r"designs?", r"designer", r"embroider\w*", r"patterns?", r"prints?"),
    "clothing": (
        r"outfits?", r"dress(?:es)?", r"suits?", r"sarees?", r"saris?",
        r"lehengas?", r"kurtis?", r"kurtas?", r"dupattas?", r"salwars?",
        r"anarkalis?", r"blouses?", r"gowns?", r"clothes", r"clothing",
        r"garments?", r"wear",
    ),
    "price": (
        r"pric\w*", r"costs?", r"costly", r"cheap\w*", r"expensive",
        r"afford\w*", r"discount\w*", r"special offers?", r"on sale",
        r"budget", r"money", r"rupees?", r"rs",
    ),
    "delivery": (
        r"deliver\w*", r"shipping", r"shipped", r"courier", r"dispatch\w*",
        r"on time", r"timely",
    ),
    "recommendation": (r"recommend\w*",),
    "purchase": (r"bought", r"buy\w*", r"purchas\w*", r"order\w*"),
    "trying on": (r"tried", r"try\w*", r"trial"),
    "return visit": (
        r"come back", r"coming back", r"came back", r"be back", r"return\w*",
        r"visit\w* again", r"shop\w* (?:here |there )?again", r"next time",
    ),
}

_TOPIC_RES = {
    topic: re.compile(r"\b(?:" + "|".join(patterns) + r")\b")
    for topic, patterns in UNGROUNDED_TOPICS.items()
}

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿]")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def sequence_similarity(a: str, b: str) -> float:
    """Character-level similarity of two normalized strings (0-1)."""
    return SequenceMatcher(None, a, b).ratio()


def token_similarity(a: str, b: str) -> float:
    """Jaccard overlap of the word sets of two normalized strings (0-1)."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def count_sentences(text: str) -> int:
    """Count sentences/lines, ignoring empty fragments."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return sum(1 for p in parts if re.search(r"\w", p))


def opening(normalized: str) -> str:
    return " ".join(normalized.split()[:EDGE_WORDS])


def closing(normalized: str) -> str:
    return " ".join(normalized.split()[-EDGE_WORDS:])


def ungrounded_topics(review: str, experience: str | None) -> list[str]:
    """Topics mentioned in the review that the customer never mentioned."""
    review_n = normalize(review)
    experience_n = normalize(experience or "")
    return [
        topic
        for topic, pattern in _TOPIC_RES.items()
        if pattern.search(review_n) and not pattern.search(experience_n)
    ]


def format_problems(review: str) -> list[str]:
    """Formatting rules from the prompt that are cheap to verify."""
    problems = []
    sentences = count_sentences(review)
    if not MIN_SENTENCES <= sentences <= MAX_SENTENCES:
        problems.append(
            f"it had {sentences} sentences; write {MIN_SENTENCES}-{MAX_SENTENCES}"
        )
    if "#" in review or _EMOJI_RE.search(review):
        problems.append("it contained a hashtag or emoji")
    if re.search(r"[\"“”]", review):
        problems.append("it contained quotation marks")
    return problems


def input_key(rating: int, experience: str | None) -> tuple[int, str]:
    """Reviews for the same rating + experience are grouped under this key."""
    return rating, normalize(experience or "")


@dataclass(frozen=True)
class _Entry:
    key: tuple[int, str]
    text: str
    normalized: str


class ReviewHistory:
    """Thread-safe, bounded record of reviews already returned to customers."""

    def __init__(self, max_size: int = MAX_HISTORY) -> None:
        self._entries: deque[_Entry] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def recent_for(self, key: tuple[int, str], limit: int) -> list[str]:
        """Most recent reviews for the same input, newest first."""
        with self._lock:
            matches = [e.text for e in reversed(self._entries) if e.key == key]
        return matches[:limit]

    def too_similar(self, text: str, extra: list[str] = ()) -> str | None:
        """Reason the text is a duplicate/near-duplicate of any past review
        (or of ``extra`` candidates), else ``None``."""
        with self._lock:
            past = [e.normalized for e in self._entries]
        return _too_similar(normalize(text), past + [normalize(t) for t in extra])

    def repeated_edges(self, key: tuple[int, str], text: str) -> str | None:
        """Reason the opening/closing repeats a recent review for the same
        input, else ``None``."""
        n = normalize(text)
        recent = [normalize(t) for t in self.recent_for(key, RECENT_EDGE_WINDOW)]
        first = n.split()[0] if n else ""
        if first in COMMON_STARTERS and any(
            r.split()[:1] == [first] for r in recent[:RECENT_STARTER_WINDOW]
        ):
            return f"it started with '{first}' like a recent review"
        if any(opening(n) == opening(r) for r in recent):
            return f"it reused the opening '{opening(n)}'"
        if any(closing(n) == closing(r) for r in recent):
            return f"it reused the closing '{closing(n)}'"
        return None

    def add_if_unique(self, key: tuple[int, str], text: str) -> bool:
        """Atomically re-check and record ``text``. Returns ``False`` if a
        concurrent request stored a too-similar review first."""
        n = normalize(text)
        with self._lock:
            if _too_similar(n, [e.normalized for e in self._entries]):
                return False
            self._entries.append(_Entry(key=key, text=text, normalized=n))
        return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _too_similar(candidate: str, others: list[str]) -> str | None:
    for other in others:
        if candidate == other:
            return "it was identical to a previous review"
        if sequence_similarity(candidate, other) >= MAX_SEQUENCE_SIMILARITY:
            return "its wording was too close to a previous review"
        if token_similarity(candidate, other) >= MAX_TOKEN_SIMILARITY:
            return "it reused almost the same words as a previous review"
    return None


history = ReviewHistory()
