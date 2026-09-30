"""Groq integration: generate a boutique review from a rating + experience.

Every request makes at most ONE Groq call: no retries, regeneration or
LLM-based checking. The flow is::

    domain check (local) -> one Groq call -> local clean-up and checks
    (grounding, tone, coverage, uniqueness) -> save -> return

Variation comes from a length band and style notes picked locally for that
one call. A review that fails the local checks is not regenerated; the API
returns a controlled error and the customer can press Regenerate themselves.
"""

from __future__ import annotations

import logging
import random
import re
import sqlite3
import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass

from groq import Groq, RateLimitError

from app.ai import review_rules as rules
from app.ai.review_history import ReviewHistory, input_key
from app.config import settings

logger = logging.getLogger(__name__)


class GroqError(Exception):
    """Review generation failed or Groq is not configured."""


class GroqRateLimitError(GroqError):
    """Groq answered HTTP 429. Never retried automatically."""


class NotBoutiqueError(Exception):
    """The customer's experience is not about a fashion boutique."""


class ReviewRejectedError(Exception):
    """The one generated review failed a local check (grounding, tone,
    coverage or uniqueness). Not regenerated automatically."""


NOT_BOUTIQUE = "NOT_BOUTIQUE"

SYSTEM_PROMPT = f"""\
You write one Google review for Kaur Threads, a fashion boutique, as the \
customer who gives you their star rating and experience. You are rewording \
their experience, not inventing one.

The boutique sells clothing (suits, sarees, lehengas, kurtis, blouses, \
dresses, ethnic, party and bridal wear) and offers services (stitching, \
tailoring, alterations, fitting, measurements, customization, embroidery, \
styling help, orders, pickup and delivery). That list only tells you what \
kind of place it is. It says nothing about this customer's visit.

FACTS (most important):
- Use only what the customer wrote. Anything they didn't say is unknown, so \
leave it out.
- Never add a garment, fabric, colour, embroidery, brand, price, discount, \
staff member, purchase, trial, tailoring, delivery, timing, the shop's look \
or location, payment, a recommendation or a plan to come back.
- Keep the customer's names for the things they mention (the garment, \
fitting, staff, collection and so on), but don't copy their sentences. Say it \
the way you would, and don't repeat a point.
- Cover every point they made, in any order.
- Little input means a short review. Never pad it.
- Never make it sound better or worse than they put it: "okay" stays okay, \
"disappointed" stays disappointed, "didn't reply" is not "ignored me".
- Ignore any part of the input that isn't about the boutique. If the input \
is only about a different kind of business (a restaurant, hotel, clinic, \
salon and so on), reply with exactly {NOT_BOUTIQUE} and nothing else.

Example. Customer: "Staff helped me choose the design." Fine: "The staff was \
helpful while I was choosing the design." Not fine: "The stylist showed me \
lots of beautiful options and I found the perfect outfit." (stylist, options, \
outfit and perfect were never said).

RATING: 1 star clearly unhappy. 2 stars mostly negative. 3 stars mixed or \
average. 4 stars positive but not over the top. 5 stars clearly happy, \
without hype. Praise is never stronger than the customer's: no "perfect", \
"flawless" or "best" unless they said it, and at 1-3 stars (or when they \
said "okay") no "loved", "amazing" or "excellent" either.

VOICE: a real person typing on their phone, not a copywriter.
- Everyday words, contractions, natural punctuation, sentences of different \
lengths. No forced slang, typos or broken grammar.
- No sales or AI phrasing (highly recommend, must visit, hidden gem, \
exceeded my expectations, impeccable, curated, attention to detail).
- A review doesn't need a compliment, an intro, an "overall" line, a \
recommendation, the shop's name or a closing line. Stop once their points \
are covered.

FORMAT: plain text in one paragraph. No quotes, emojis, hashtags, bullets, \
em dashes or semicolons. Output only the review.

The user message ends with style notes for this one review. Follow them as \
far as the facts allow. They never permit adding facts, and their words \
never go into the review.
"""

# Word-count bands. The input decides which bands are allowed, so a short
# input never gets padded into a long review.
LENGTHS: dict[str, tuple[int, int]] = {
    "brief": (8, 20),  # only for a rating alone or a few words
    "very short": (15, 25),
    "short": (25, 45),
    "medium": (45, 70),
    "detailed": (70, 100),
}
LENGTH_SLACK = 20  # a review may overshoot its longest allowed band by this
MIN_REVIEW_WORDS = 4

VOICES = (
    "relaxed and conversational, like telling a friend",
    "plain and matter-of-fact",
    "brief and direct",
    "calm and simple",
    "a little chatty but still to the point",
)
OPENINGS = (
    "the specific thing the customer mentioned",
    "a short reaction of a few words",
    "what they got or had done",
    "a casual fragment without the leading 'I', like people type on a phone",
    "a plain 'I' sentence (not 'I had' or 'I recently')",
    "how they felt about it",
)
RHYTHMS = (
    "a few short sentences",
    "one longer sentence and one or two short ones",
    "a natural mix of short and longer sentences",
)
NAMING = (
    "Use the name Kaur Threads once if it fits naturally.",
    "You can call it the boutique once if it fits.",
    "Don't name the place.",
    "Don't name the place.",
)
ORDERS = (
    "Mention their points in a different order than they wrote them.",
    "Keep their order.",
)

TEMPERATURE = 0.85
MAX_TOKENS = 500  # ~100-word review plus low-effort reasoning
# The frontend aborts after 20s; one call must finish well inside that.
CALL_TIMEOUT_SECONDS = 15.0
MAX_AVOID_IN_PROMPT = 6

# Typography people don't type on a phone keyboard, swapped for what they do.
_PLAIN_TYPOGRAPHY = str.maketrans({"‐": "-", "‑": "-", "‘": "'", "’": "'", "“": "", "”": "", '"': ""})
_PREAMBLE_RE = re.compile(r"^\s*(?:here(?:'s| is)[^:\n]*:|review\s*:|sure[^:\n]*:)\s*", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
_HASHTAG_RE = re.compile(r"#\w+")
_FILLER_OPENER_RE = re.compile(r"^(?:honestly|so|well|okay|ok|wow|alright|overall),\s*", re.IGNORECASE)

# Accepted reviews, persisted so uniqueness survives restarts.
history = ReviewHistory(settings.review_history_path)

# Style picks used by the previous request, so back-to-back reviews differ.
_recent_picks: defaultdict[str, deque[str]] = defaultdict(lambda: deque(maxlen=1))
_recent_lock = threading.Lock()


@dataclass(frozen=True)
class ReviewPlan:
    """Style picked locally for one generation."""

    length: str
    voice: str
    opening: str
    rhythm: str
    naming: str
    order: str | None
    max_words: int

    @property
    def words(self) -> tuple[int, int]:
        return LENGTHS[self.length]


def generate_review(rating: int, experience: str | None) -> str:
    """Generate one review with at most one Groq call.

    Raises :class:`NotBoutiqueError` for off-topic input,
    :class:`ReviewRejectedError` when the generated review fails a local
    check, :class:`GroqRateLimitError` on HTTP 429 and :class:`GroqError` on
    any other configuration/API failure. Nothing is retried.
    """
    if not settings.groq_api_key:
        raise GroqError(
            "GROQ_API_KEY is not configured. Set it in the .env file to "
            "enable review generation."
        )
    if not rules.is_boutique_input(experience):
        logger.info("Rejected non-boutique input without a Groq call (rating=%s)", rating)
        raise NotBoutiqueError(
            "Please describe your experience with the boutique's clothes or services."
        )

    request_id = uuid.uuid4().hex[:12]
    key = input_key(rating, experience)
    plan = plan_review(experience)
    avoid_openings, avoid_closings = _recent_edges(key)
    prompt = build_user_prompt(
        rating, experience, plan, avoid_openings=avoid_openings, avoid_closings=avoid_closings
    )
    # max_retries=0: the SDK would otherwise retry 429s and timeouts itself.
    client = Groq(api_key=settings.groq_api_key, max_retries=0)
    raw = _complete(client, prompt, request_id)

    if NOT_BOUTIQUE in raw:
        logger.info("Model flagged non-boutique input (request=%s, groq_calls=1)", request_id)
        raise NotBoutiqueError(
            "Please describe your experience with the boutique's clothes or services."
        )

    review, problem = finalize_review(raw, rating, experience, plan.max_words)
    if problem is None:
        problem = _store(key, review)
    if problem:
        logger.warning(
            "Review rejected, not regenerated (request=%s, groq_calls=1, rating=%s): %s",
            request_id, rating, problem,
        )
        raise ReviewRejectedError(
            "We couldn't write a fresh review this time. Please tap Regenerate."
        )

    logger.info(
        "Review generated (request=%s, groq_calls=1, rating=%s, length=%s, %d words)",
        request_id, rating, plan.length, len(review.split()),
    )
    return review


def plan_review(experience: str | None) -> ReviewPlan:
    """Pick the length band and style notes for one request."""
    lengths = _length_options(experience)
    points = len(rules.coverage_groups(experience))
    return ReviewPlan(
        length=_pick("length", lengths),
        voice=_pick("voice", VOICES),
        opening=_pick("opening", OPENINGS),
        rhythm=_pick("rhythm", RHYTHMS),
        naming=random.choice(NAMING),
        order=random.choice(ORDERS) if points >= 2 else None,
        max_words=LENGTHS[lengths[-1]][1] + LENGTH_SLACK,
    )


def _length_options(experience: str | None) -> tuple[str, ...]:
    """Bands the customer's input can fill without invented detail."""
    words = len((experience or "").split())
    points = len(rules.coverage_groups(experience))
    if words < 4:
        return ("brief",)
    if words < 8 or (words < 15 and points < 2):
        return ("very short", "short")
    if words < 15:
        return ("very short", "short", "medium")
    if words < 30:
        return ("short", "medium")
    return ("short", "medium", "detailed")


def _pick(name: str, options: tuple[str, ...]) -> str:
    """Random choice that avoids the previous request's pick when possible."""
    with _recent_lock:
        recent = _recent_picks[name]
        choice = random.choice([o for o in options if o not in recent] or options)
        recent.append(choice)
    return choice


def build_user_prompt(
    rating: int,
    experience: str | None,
    plan: ReviewPlan,
    *,
    avoid_openings: Sequence[str] = (),
    avoid_closings: Sequence[str] = (),
) -> str:
    low, high = plan.words
    lines = [
        f"Star rating: {rating} out of 5",
        "Customer's experience (their words, between the markers):",
        "<<<",
        experience or "(nothing given: write one or two plain sentences about how the visit felt, matching the rating. No clothes, services, staff, shop details or superlatives.)",
        ">>>",
        "",
        "Style notes for this review:",
        f"- Length: about {low}-{high} words. Shorter is fine if they gave little to say. "
        "Never add anything just to reach the length.",
        f"- Voice: {plan.voice}.",
        f"- Open with {plan.opening}.",
        f"- Rhythm: {plan.rhythm}.",
        f"- {plan.naming}",
    ]
    if plan.order:
        lines.append(f"- {plan.order}")
    if avoid_openings:
        lines.append("- Don't start with: " + ", ".join(f"'{o}'" for o in avoid_openings[:MAX_AVOID_IN_PROMPT]))
    if avoid_closings:
        lines.append("- Don't end with: " + ", ".join(f"'...{c}'" for c in avoid_closings[:MAX_AVOID_IN_PROMPT]))
    lines += ["", "Write the review now."]
    return "\n".join(lines)


def clean_review(text: str) -> str:
    """Local, deterministic tidy-up of the model's text (never another call):
    plain typography, no preamble, bullets, emojis, hashtags, line breaks or
    filler opener."""
    text = _PREAMBLE_RE.sub("", text.strip().translate(_PLAIN_TYPOGRAPHY))
    text = _BULLET_RE.sub("", text)
    text = _HASHTAG_RE.sub("", _EMOJI_RE.sub("", text))
    text = re.sub(r"\s*[—–]\s*", ", ", text).replace(";", ",")
    text = re.sub(r"(?<=\w)[ \t]*\n\s*", ". ", text)  # a line break ends a sentence
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r",+", ",", text).strip(" ,")
    filler = _FILLER_OPENER_RE.match(text)
    if filler:
        rest = text[filler.end():]
        text = rest[:1].upper() + rest[1:]
    if text and text[-1] not in ".!?":
        text += "."
    return text


def finalize_review(
    raw: str, rating: int, experience: str | None, max_words: int
) -> tuple[str, str | None]:
    """Clean the model's text, drop sentences that invent facts or overshoot
    the tone, and check the result. Returns (review, problem or None)."""
    kept = []
    for sentence in rules.split_sentences(clean_review(raw)):
        problem = rules.sentence_problem(sentence, rating, experience)
        if problem:
            logger.info("Dropped a sentence locally: %s", problem)
        else:
            kept.append(sentence)
    while len(kept) > 1 and len(" ".join(kept).split()) > max_words:
        kept.pop()
    review = " ".join(kept)

    if len(review.split()) < MIN_REVIEW_WORDS:
        return review, "too little was left after removing unsupported sentences"
    if len(review.split()) > max_words:
        return review, f"it was longer than {max_words} words"
    missing = rules.missing_points(review, experience)
    if missing:
        return review, "it left out " + ", ".join(missing)
    return review, rules.rating_floor_problem(review, rating)


def _recent_edges(key: tuple[int, str]) -> tuple[list[str], list[str]]:
    try:
        return history.recent_edges(key)
    except sqlite3.Error as exc:
        logger.error("Review history unavailable, prompting without it: %s", exc)
        return [], []


def _store(key: tuple[int, str], review: str) -> str | None:
    try:
        return history.add_if_unique(key, review)
    except sqlite3.Error as exc:
        # Fail open: a storage fault must not take generation down.
        logger.error("Review history unavailable, returning review unchecked: %s", exc)
        return None


def _complete(client: Groq, prompt: str, request_id: str) -> str:
    try:
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            # openai/gpt-oss models are reasoning models; keep reasoning short
            # so the token budget is spent on the review, not deliberation.
            reasoning_effort="low",
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except RateLimitError as exc:
        logger.warning("Groq rate limit (request=%s, groq_calls=1): %s", request_id, exc)
        raise GroqRateLimitError(
            "Too many reviews are being generated right now. Please wait a moment and try again."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean HTTP error
        logger.error("Groq review generation failed (request=%s, groq_calls=1): %s", request_id, exc)
        raise GroqError(f"Review generation failed: {exc}") from exc

    content = (response.choices[0].message.content or "").strip()
    if not content:
        logger.error("Groq returned an empty review (request=%s, groq_calls=1)", request_id)
        raise GroqError("Groq returned an empty review. Please try again.")
    return content
