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

# A candidate is "too similar" (hard reject) to ANY past review at or above
# either threshold.
MAX_SEQUENCE_SIMILARITY = 0.72  # character-level, SequenceMatcher ratio
MAX_TOKEN_SIMILARITY = 0.70  # word-set Jaccard overlap

# Two whole reviews can differ while sharing one templated sentence, so each
# sentence is also compared with the sentences of recent reviews written for
# a similar input. Very short sentences are only rejected on an exact match.
MAX_SENTENCE_SIMILARITY = 0.80
MIN_SENTENCE_WORDS = 4
RELATED_SENTENCE_WINDOW = 20

# Closing sentences templatize easily ("I left feeling truly satisfied"), so
# they are compared more strictly against the most recent related reviews.
MAX_CLOSING_SIMILARITY = 0.70

# Inputs whose experience texts are this similar share one history "family",
# so "good collection, nice quality" and "nice quality and good collection"
# are checked against each other.
RELATED_INPUT_SEQUENCE = 0.75
RELATED_INPUT_TOKENS = 0.50

# Openings/closings are compared over this many words, against this many of
# the most recent related reviews.
EDGE_WORDS = 3
RECENT_EDGE_WINDOW = 5

# Two related reviews in a row may not start with the same word. A wider
# window pushes the model toward odd, unnatural openers.
RECENT_STARTER_WINDOW = 1

MIN_SENTENCES = 2
MAX_SENTENCES = 4
MAX_SENTENCE_WORDS = 30
MAX_REVIEW_WORDS = 90

# Topics the model must not introduce unless the customer mentioned them.
# A topic is allowed when ANY of its patterns (or its extra allow patterns
# below) appears in the experience text.
UNGROUNDED_TOPICS: dict[str, tuple[str, ...]] = {
    "staff": (
        r"staff", r"employees?", r"team", r"sales ?(?:person|man|woman|girl)s?",
        r"owners?", r"shopkeepers?", r"assistants?", r"helpers?", r"stylists?",
        r"aunty", r"didi", r"bhaiya", r"people there",
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
    "colours": (r"colou?rs?", r"colou?rful", r"shades?", r"hues?"),
    "brands": (r"brands?", r"branded", r"labels?"),
    "craftsmanship": (
        r"craftsmanship", r"crafted", r"hand ?made", r"workmanship",
        r"detailing", r"finishing", r"care (?:put|that went) into",
    ),
    "occasion": (
        r"weddings?", r"festiv\w*", r"part(?:y|ies)", r"occasions?", r"events?",
        r"functions?", r"diwali", r"eid", r"engagements?", r"reception",
    ),
    "shop details": (
        r"walk(?:ed|ing) (?:in|into|out)", r"stepp(?:ed|ing) (?:in|into)",
        r"displays?", r"new arrivals?", r"new stock", r"ambien\w*",
        r"atmosphere", r"vibes?", r"decor", r"interiors?", r"racks?",
        r"shelves", r"window", r"layout",
    ),
    "large selection": (
        r"(?:wide|huge|vast|big|large|great|endless) "
        r"(?:range|variety|selection|collection|choice)s?",
        r"(?:lots|plenty|tons) of (?:options|choices|variety)",
        r"so many (?:options|choices)",
    ),
    "price": (
        r"pric\w*", r"costs?", r"costly", r"cheap\w*", r"expensive",
        r"afford\w*", r"discount\w*", r"special offers?", r"on sale",
        r"budget", r"money", r"value", r"rupees?", r"rs",
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

# Customer words that make a topic's paraphrases legitimate.
EXTRA_GROUNDING: dict[str, tuple[str, ...]] = {
    "large selection": (
        r"variety", r"range", r"options?", r"choices?", r"selection", r"wide",
        r"lots?", r"many",
    ),
    "colours": (r"red", r"blue", r"green", r"pink", r"black", r"white"),
}

# Advert-style phrases, rejected unless the customer used them.
PROMOTIONAL_PHRASES = (
    r"highly recommend\w*", r"must visit", r"a must", r"best boutique",
    r"best in (?:town|the city)", r"best place", r"exceptional", r"premium",
    r"top notch", r"perfect place", r"absolutely amazing", r"luxur\w*",
    r"hidden gem", r"one stop", r"look no further", r"second to none",
    r"world class", r"go to place", r"(?:five|5) stars?", r"10 10",
    r"exceeded (?:all )?(?:my )?expectations", r"beyond expectations",
    r"unmatched", r"unbeatable", r"like no other",
)

# Wording that makes a review read as AI-written, rejected unless the
# customer used it.
AI_STYLE_PHRASES = (
    r"truly", r"delight\w*", r"impeccabl\w*", r"curated", r"elevat\w*",
    r"seamless\w*", r"testament", r"exquisite", r"meticulous\w*", r"spot on",
    r"caught my eye", r"(?:strong|lasting) impression", r"attention to detail",
    r"nothing short of", r"well crafted", r"effortless\w*", r"showcas\w*",
    r"boasts?", r"a (?:real )?treat", r"gem", r"journey", r"thoughtful\w*",
    r"genuinely", r"undeniabl\w*", r"remarkabl\w*", r"left (?:me )?feeling",
    r"walked away", r"lineup", r"top tier", r"in every way", r"wholeheartedly",
    r"a cut above", r"sheer", r"stellar", r"whether you", r"if you re looking",
    r"can t wait", r"experience was nothing", r"felt instantly",
)
# Filler openings real customers rarely type but models love.
FILLER_OPENERS = (
    r"honestly", r"so", r"well", r"you know", r"wow", r"okay so", r"ok so",
    r"let me", r"as someone", r"what a", r"if you", r"my reaction",
)

# Words that push a review's tone past its rating, unless the customer used
# them. Keyed by the ratings they are checked for.
TOO_POSITIVE_LOW = (
    r"loved?", r"amazing", r"fantastic", r"wonderful", r"excellent", r"perfect",
    r"delighted", r"impressed", r"thrilled", r"great experience", r"beautiful",
)
TOO_POSITIVE_MID = (
    r"loved?", r"amazing", r"fantastic", r"wonderful", r"excellent", r"perfect",
    r"delighted", r"thrilled",
)
# "not impressed", "didn't disappoint", "would have loved" don't count.
NEGATORS = frozenset({"not", "never", "no", "t", "hardly", "have", "without"})
NEGATION_WINDOW = 3
TOO_NEGATIVE_HIGH = (
    r"disappoint\w*", r"terrible", r"awful", r"horrible", r"worst", r"poor\w*",
    r"frustrat\w*", r"unhappy",
)

_PREAMBLE_RE = re.compile(r"^\s*(?:here(?:'s| is)|review\s*:|sure\b)", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s", re.MULTILINE)
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _alternation(patterns: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b")


_TOPIC_RES = {topic: _alternation(p) for topic, p in UNGROUNDED_TOPICS.items()}
_EXTRA_RES = {topic: _alternation(p) for topic, p in EXTRA_GROUNDING.items()}
_PROMO_RES = [re.compile(r"\b" + p + r"\b") for p in PROMOTIONAL_PHRASES]
_AI_STYLE_RES = [re.compile(r"\b" + p + r"\b") for p in AI_STYLE_PHRASES]
_FILLER_OPENER_RE = re.compile(r"^(?:" + "|".join(FILLER_OPENERS) + r")\b")
_TOO_POSITIVE_LOW_RE = _alternation(TOO_POSITIVE_LOW)
_TOO_POSITIVE_MID_RE = _alternation(TOO_POSITIVE_MID)
_TOO_NEGATIVE_HIGH_RE = _alternation(TOO_NEGATIVE_HIGH)


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


def split_sentences(text: str) -> list[str]:
    """Split into sentences/lines, ignoring empty fragments."""
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [p for p in parts if re.search(r"\w", p)]


def count_sentences(text: str) -> int:
    return len(split_sentences(text))


def opening(normalized: str) -> str:
    return " ".join(normalized.split()[:EDGE_WORDS])


def closing(normalized: str) -> str:
    return " ".join(normalized.split()[-EDGE_WORDS:])


def ungrounded_topics(review: str, experience: str | None) -> list[str]:
    """Topics mentioned in the review that the customer never mentioned."""
    review_n = normalize(review)
    experience_n = normalize(experience or "")
    found = []
    for topic, pattern in _TOPIC_RES.items():
        if not pattern.search(review_n) or pattern.search(experience_n):
            continue
        extra = _EXTRA_RES.get(topic)
        if extra and extra.search(experience_n):
            continue
        found.append(topic)
    return found


def promotional_phrases(review: str, experience: str | None) -> list[str]:
    """Advert-style phrases in the review that the customer never used."""
    review_n = normalize(review)
    experience_n = normalize(experience or "")
    found = []
    for pattern in _PROMO_RES:
        match = pattern.search(review_n)
        if match and not pattern.search(experience_n):
            found.append(match.group(0))
    return found


def ai_style_problem(review: str, experience: str | None) -> str | None:
    """Reason the review reads as AI-written rather than typed by a customer,
    else ``None``."""
    review_n = normalize(review)
    experience_n = normalize(experience or "")
    if "\u2014" in review or ";" in review:
        return "it used an em dash or semicolon, which reads as AI-written"
    opener = _FILLER_OPENER_RE.match(review_n)
    if opener:
        return f"it opened with the filler '{opener.group(0)}'"
    for pattern in _AI_STYLE_RES:
        match = pattern.search(review_n)
        if match and not pattern.search(experience_n):
            return (
                f"it used '{match.group(0)}', which sounds AI-written; use "
                "plain everyday words"
            )
    return None


def sentiment_problem(review: str, rating: int, experience: str | None) -> str | None:
    """Reason the tone clearly overshoots the rating, else ``None``."""
    review_n = normalize(review)
    experience_n = normalize(experience or "")
    if rating <= 2:
        pattern, direction = _TOO_POSITIVE_LOW_RE, "positive"
    elif rating == 3:
        pattern, direction = _TOO_POSITIVE_MID_RE, "positive"
    else:
        pattern, direction = _TOO_NEGATIVE_HIGH_RE, "negative"
    if pattern.search(experience_n):
        return None
    for match in pattern.finditer(review_n):
        before = review_n[: match.start()].split()[-NEGATION_WINDOW:]
        if not NEGATORS.intersection(before):
            return (
                f"'{match.group(0)}' sounded too {direction} for a {rating}-star "
                "rating and the customer's words"
            )
    return None


def format_problems(review: str) -> list[str]:
    """Formatting rules from the prompt that are cheap to verify."""
    problems = []
    sentences = split_sentences(review)
    if not MIN_SENTENCES <= len(sentences) <= MAX_SENTENCES:
        problems.append(
            f"it had {len(sentences)} sentences; write {MIN_SENTENCES}-{MAX_SENTENCES}"
        )
    if len(review.split()) > MAX_REVIEW_WORDS or any(
        len(s.split()) > MAX_SENTENCE_WORDS for s in sentences
    ):
        problems.append("its sentences were too long; keep them short")
    if "#" in review or _EMOJI_RE.search(review):
        problems.append("it contained a hashtag or emoji")
    if re.search(r"[\"“”]", review):
        problems.append("it contained quotation marks")
    if _PREAMBLE_RE.search(review) or _BULLET_RE.search(review):
        problems.append("it included a preamble or bullet points")
    return problems


def input_key(rating: int, experience: str | None) -> tuple[int, str]:
    """Identifies the request a review was written for."""
    return rating, normalize(experience or "")


def related_inputs(a: tuple[int, str], b: tuple[int, str]) -> bool:
    """Whether two inputs are similar enough to share a history family.
    The rating is ignored: a 4 and a 5 for the same words read alike."""
    ea, eb = a[1], b[1]
    if ea == eb:
        return True
    if not ea or not eb:
        return False
    return (
        sequence_similarity(ea, eb) >= RELATED_INPUT_SEQUENCE
        or token_similarity(ea, eb) >= RELATED_INPUT_TOKENS
    )


@dataclass(frozen=True)
class _Entry:
    key: tuple[int, str]
    text: str
    normalized: str
    sentences: tuple[str, ...]  # normalized


def _entry(key: tuple[int, str], text: str) -> _Entry:
    return _Entry(
        key=key,
        text=text,
        normalized=normalize(text),
        sentences=tuple(normalize(s) for s in split_sentences(text)),
    )


class ReviewHistory:
    """Thread-safe, bounded record of reviews already returned to customers."""

    def __init__(self, max_size: int = MAX_HISTORY) -> None:
        self._entries: deque[_Entry] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def _related(self, key: tuple[int, str], limit: int) -> list[_Entry]:
        """Most recent entries for a related input, newest first."""
        with self._lock:
            entries = list(reversed(self._entries))
        return [e for e in entries if related_inputs(e.key, key)][:limit]

    def recent_for(self, key: tuple[int, str], limit: int) -> list[str]:
        """Most recent reviews for the same or a related input, newest first."""
        return [e.text for e in self._related(key, limit)]

    def too_similar(self, text: str, extra: list[str] = ()) -> str | None:
        """Reason the text is a duplicate/near-duplicate of any past review
        (or of ``extra`` candidates), else ``None``."""
        with self._lock:
            past = [e.normalized for e in self._entries]
        return _too_similar(normalize(text), past + [normalize(t) for t in extra])

    def reused_sentence(self, key: tuple[int, str], text: str) -> str | None:
        """Reason a sentence of ``text`` repeats a sentence of a recent related
        review, else ``None``."""
        past = [s for e in self._related(key, RELATED_SENTENCE_WINDOW) for s in e.sentences]
        for sentence in (normalize(s) for s in split_sentences(text)):
            short = len(sentence.split()) < MIN_SENTENCE_WORDS
            for other in past:
                if sentence == other or (
                    not short and sequence_similarity(sentence, other) >= MAX_SENTENCE_SIMILARITY
                ):
                    return "one of its sentences was almost the same as a sentence in a previous review"
        return None

    def repeated_edges(self, key: tuple[int, str], text: str) -> str | None:
        """Reason the opening/closing repeats a recent related review, else
        ``None``."""
        n = normalize(text)
        recent = self._related(key, RECENT_EDGE_WINDOW)
        first = n.split()[0] if n else ""
        if first and any(
            e.normalized.split()[:1] == [first] for e in recent[:RECENT_STARTER_WINDOW]
        ):
            return f"it started with '{first}' like a recent review"
        if any(opening(n) == opening(e.normalized) for e in recent):
            return f"it reused the opening '{opening(n)}'"
        if any(closing(n) == closing(e.normalized) for e in recent):
            return f"it reused the closing '{closing(n)}'"
        sentences = split_sentences(text)
        last = normalize(sentences[-1]) if sentences else ""
        if last and any(
            e.sentences
            and sequence_similarity(last, e.sentences[-1]) >= MAX_CLOSING_SIMILARITY
            for e in recent
        ):
            return "its closing sentence followed the same pattern as a recent review"
        return None

    def add_if_unique(self, key: tuple[int, str], text: str) -> bool:
        """Atomically re-check and record ``text``. Returns ``False`` if a
        concurrent request stored a too-similar review first."""
        entry = _entry(key, text)
        with self._lock:
            if _too_similar(entry.normalized, [e.normalized for e in self._entries]):
                return False
            self._entries.append(entry)
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
