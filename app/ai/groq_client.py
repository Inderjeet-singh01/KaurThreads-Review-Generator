"""Review generation: a boutique review from a rating + experience.

Each generation request asks for CANDIDATES alternative versions; the
first that passes every local check is returned. Groq is the primary
provider. A click makes at most MAX_PROVIDER_CALLS calls:

- Groq is busy (429) and asks for a short wait: Groq gets one more call
  after that wait.
- Groq fails transiently otherwise (longer wait, timeout, network, 5xx):
  Gemini gets one call with the same prompts.
- Groq answers but none of its versions pass the checks: Groq gets one more
  call with fresh style notes, so the customer isn't asked to retry.

There is no LLM-based checking. The flow is::

    domain check (local) -> Groq call [-> Gemini if Groq is down] -> per
    version: local clean-up and checks (hard facts, tone, uniqueness;
    coverage preferred) -> save the best that passes -> return
    [no version passed and a call is left -> one fresh Groq call]

Variation comes from a length band and style notes picked locally for that
one call. A review that fails the local checks is not regenerated; the API
returns a controlled error and the customer can press Regenerate themselves.
"""

from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from groq import APIConnectionError, APIError, BadRequestError, Groq, RateLimitError

from app.ai import review_rules as rules
from app.ai.review_history import ReviewHistory, input_key
from app.config import settings

logger = logging.getLogger(__name__)


class GroqError(Exception):
    """Review generation failed or a provider is not configured.

    ``reason`` is set for transient provider failures (see FALLBACK_REASONS);
    those, and only those, hand the request over to Gemini.
    """

    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason

    @property
    def fallback_eligible(self) -> bool:
        return self.reason in FALLBACK_REASONS


class GroqRateLimitError(GroqError):
    """A provider answered HTTP 429. ``retry_after`` is its suggested wait in
    seconds, when it gave one."""

    def __init__(self, message: str = "", reason: str | None = "rate_limited", retry_after: float | None = None):
        super().__init__(message or BUSY_MESSAGE, reason)
        self.retry_after = retry_after


class NotBoutiqueError(Exception):
    """The customer's experience is not about a fashion boutique."""


class ReviewRejectedError(Exception):
    """The one generated review failed a local check (grounding, tone,
    coverage or uniqueness). Not regenerated automatically."""


NOT_BOUTIQUE = "NOT_BOUTIQUE"
BUSY_MESSAGE = "Too many reviews are being generated right now. Please wait a moment and try again."
# Failure categories worth one Gemini call. Anything else (bad key, bad
# request, unknown model, our own bugs) fails fast without a fallback.
FALLBACK_REASONS = frozenset({"rate_limited", "transient", "service_unavailable", "empty_response"})

SYSTEM_PROMPT = f"""\
You write Google reviews for Kaur Threads, a fashion boutique, as the \
customer who gives you their star rating and experience. Write it as their \
honest review of the boutique.

The boutique sells clothing (suits, sarees, lehengas, kurtis, blouses, \
dresses, ethnic, party and bridal wear) and offers services (stitching, \
tailoring, alterations, fitting, measurements, customization, embroidery, \
styling help, orders, pickup and delivery).

CONTENT (most important):
- Start from what the customer wrote and cover every point they made, in \
any order. Keep their names for things (the garment, fitting, staff, \
collection and so on), but don't copy their sentences or repeat a point.
- Round it out with natural, general comments about the boutique's clothing \
and services (collection, designs, quality, stitching, fitting, staff, \
service and so on), even ones they didn't mention, so it reads like a full \
review. Keep them general and in line with their rating and words. \
Complaints come only from the customer: added comments never introduce a \
new complaint or blame anyone.
- Never state hard facts they didn't give: no prices, discounts or payment, \
no brand names, no location, no numbers, dates or durations, no people's \
names, and no specific garment, fabric or colour they didn't name (say "the \
outfit" or "the collection" instead).
- Always write at least 3 sentences.
- Never contradict them or make it sound better or worse than they put it: \
"okay" stays okay, "disappointed" stays disappointed, "didn't reply" is not \
"ignored me".
- Ignore any part of the input that isn't about the boutique. If the input \
is only about a different kind of business (a restaurant, hotel, clinic, \
salon and so on), reply with exactly {NOT_BOUTIQUE} and nothing else.

Example. Customer: "Staff helped me choose the design." Fine: "The staff was \
helpful while I was choosing the design. There were some nice options in the \
collection. Happy with how it went." Not fine: "Priya helped me pick a silk \
lehenga for just 5000." (a name, fabric, garment and price they never gave).

RATING: 1 star clearly unhappy. 2 stars mostly negative. 3 stars mixed or \
average. 4 stars positive but not over the top. 5 stars clearly happy, \
without hype. Praise is never stronger than the customer's: no "perfect", \
"flawless" or "best" unless they said it, and at 1-3 stars (or when they \
said "okay") no "loved", "amazing" or "excellent" either.

VOICE: a real person typing on their phone, not a copywriter.
- Everyday words, contractions, natural punctuation, sentences of different \
lengths. No forced slang, typos or broken grammar.
- No sales or AI phrasing (highly recommend, must visit, hidden gem, \
exceeded my expectations, impeccable, curated, attention to detail, left \
me feeling, walked away feeling, vibe).
- A review doesn't need a compliment, an intro, an "overall" line, a \
recommendation, the shop's name or a closing line. Stop once their points \
are covered.

FORMAT: reply in JSON as {{"reviews": [...]}}, one string per version. Each \
review is plain text in one paragraph. No quotes, emojis, hashtags, bullets, \
labels, em dashes or semicolons.

The user message ends with style notes for this one review. Follow them as \
far as the facts allow. They never permit adding facts, and their words \
never go into the review.
"""

# Word-count bands. The input decides which bands are allowed, so a short
# input never gets padded into a long review.
LENGTHS: dict[str, tuple[int, int]] = {
    "brief": (18, 30),  # only for a rating alone or a few words
    "very short": (20, 30),
    "short": (25, 45),
    "medium": (45, 70),
    "detailed": (70, 100),
}
LENGTH_SLACK = 20  # a review may overshoot its longest allowed band by this
MIN_REVIEW_WORDS = 4
MIN_REVIEW_SENTENCES = 3  # every review is at least three sentences
MISSED_POINT = "it left out "  # the one soft problem (see _pick_review)

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
    "one longer sentence and two short ones",
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
# Versions requested per call. One invented sentence rejects a version, so
# several independent versions make it very likely that one passes.
CANDIDATES = 3
MAX_TOKENS = 1000  # three ~100-word versions plus low-effort reasoning
GEMINI_MAX_TOKENS = 1200  # Gemini counts its (low) thinking in this budget
# Groq + a Gemini call share one deadline (the frontend waits up to 30s per
# attempt): Groq gets at most CALL_TIMEOUT_SECONDS, Gemini what is left.
CALL_TIMEOUT_SECONDS = 8.0
REQUEST_BUDGET_SECONDS = 18.0
MIN_GEMINI_SECONDS = 4.0  # less than this left: skip Gemini, it can't finish
MAX_PROVIDER_CALLS = 2  # per click, whatever happens
# A 429 whose suggested wait is this short is waited out and Groq retried,
# instead of switching to Gemini (the free tier clears within seconds).
MAX_GROQ_WAIT_SECONDS = 4.0
_RETRY_IN_RE = re.compile(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)\b")
MAX_AVOID_IN_PROMPT = 6

# Typography people don't type on a phone keyboard, swapped for what they do.
_PLAIN_TYPOGRAPHY = str.maketrans({"‐": "-", "‑": "-", "‘": "'", "’": "'", "“": "", "”": "", '"': ""})
_PREAMBLE_RE = re.compile(r"^\s*(?:here(?:'s| is)[^:\n]*:|review\s*:|sure[^:\n]*:)\s*", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)
# Backup split when a reply isn't JSON: ###/---/*** lines or blank lines.
_CANDIDATE_SPLIT_RE = re.compile(r"^\s*(?:#{3,}|-{3,}|\*{3,})\s*$|\n\s*\n", re.MULTILINE)
_JSON_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
# Both providers must answer {"reviews": [...]}, so versions never run together.
REVIEWS_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": {"type": "string"}}},
    "required": ["reviews"],
    "additionalProperties": False,
}
_LABEL_RE = re.compile(r"^\s*(?:(?:version|review|option)\s*\d*\s*[:.)-]|\d+[.)])\s+", re.IGNORECASE)
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


def generate_review(rating: int, experience: str | None, request_id: str | None = None) -> str:
    """Generate one review: one Groq call, plus one Gemini call only when
    Groq fails transiently.

    Raises :class:`NotBoutiqueError` for off-topic input,
    :class:`ReviewRejectedError` when the generated review fails a local
    check, :class:`GroqRateLimitError` on HTTP 429 and :class:`GroqError` on
    any other configuration/API failure. ``request_id`` ties these logs to
    the API request's.
    """
    if not settings.groq_api_key:
        logger.error("Review not generated: GROQ_API_KEY is not configured")
        raise GroqError(
            "GROQ_API_KEY is not configured. Set it in the .env file to "
            "enable review generation."
        )
    if not rules.is_boutique_input(experience):
        logger.info("Review not generated: off-topic input, no model called")
        raise NotBoutiqueError(
            "Please describe your experience with the boutique's clothes or services."
        )

    request_id = request_id or uuid.uuid4().hex[:12]
    key = input_key(rating, experience)
    started = time.monotonic()
    deadline = started + REQUEST_BUDGET_SECONDS

    calls = 0
    while True:
        plan = plan_review(experience)  # fresh style notes for every call
        avoid_openings, avoid_closings = _recent_edges(key)
        prompt = build_user_prompt(
            rating, experience, plan, avoid_openings=avoid_openings, avoid_closings=avoid_closings
        )
        if calls == 0:
            raw, model, used = _generate_raw(prompt, request_id, deadline)
        else:
            try:  # the retry is Groq only, and its failure is just a rejection
                raw, model, used = _generate_raw(prompt, request_id, deadline, allow_fallback=False)
            except GroqError:
                break
        calls += used
        review, problem = _pick_review(raw, model, request_id, rating, experience, plan.max_words, key)
        if problem is None:
            logger.info(
                "Review OK: model=%s time=%.1fs calls=%d rating=%s words=%d req=%s",
                model, time.monotonic() - started, calls, rating, len(review.split()), request_id,
            )
            return review
        if calls >= MAX_PROVIDER_CALLS or deadline - time.monotonic() < CALL_TIMEOUT_SECONDS / 2:
            break
        logger.warning("Versions failed checks (%s), trying once more req=%s", problem, request_id)

    logger.warning("Review rejected: model=%s calls=%d reason=%s req=%s", model, calls, problem, request_id)
    raise ReviewRejectedError(
        "We couldn't write a fresh review this time. Please tap Regenerate."
    )


def _pick_review(
    raw: str, model: str, request_id: str, rating: int, experience: str | None,
    max_words: int, key: tuple[int, str],
) -> tuple[str, str | None]:
    """Run each version through the local checks and save the first that
    passes. A version whose only problem is a missed customer point is kept
    as the fallback, so one request nearly always yields a review. Returns
    (review, None) or ("", the versions' problems)."""
    # Either provider's text goes through exactly the same checks.
    if NOT_BOUTIQUE in raw:
        logger.info("Review not generated: model=%s flagged off-topic input req=%s", model, request_id)
        raise NotBoutiqueError(
            "Please describe your experience with the boutique's clothes or services."
        )
    problem, problems, partial = "it returned no review", [], []
    for candidate in split_candidates(raw):
        review, problem = finalize_review(candidate, rating, experience, max_words)
        if problem is None:
            problem = _store(key, review)
            if problem is None:
                return review, None
        elif problem.startswith(MISSED_POINT):
            partial.append(review)
        problems.append(problem)
    for review in partial:  # passed every hard check, just not full coverage
        if _store(key, review) is None:
            return review, None
    return "", "; ".join(dict.fromkeys(problems)) or problem


def split_candidates(raw: str) -> list[str]:
    """The model's alternative versions from its JSON reply. A reply cut off
    mid-JSON keeps its complete versions; a plain-text reply is split on
    separator or blank lines."""
    text = raw.strip()
    if text.startswith("{"):
        try:
            parts = json.loads(text).get("reviews", [])
        except (ValueError, AttributeError):
            # Truncated JSON: keep every fully closed string after "reviews".
            body = text.split('"reviews"', 1)[-1]
            parts = [json.loads(f'"{m}"') for m in _JSON_STRING_RE.findall(body)]
        parts = [p for p in parts if isinstance(p, str)]
    else:
        parts = _CANDIDATE_SPLIT_RE.split(text)
    parts = (_LABEL_RE.sub("", part).strip() for part in parts)
    return [part for part in parts if part][:CANDIDATES]


def _generate_raw(
    prompt: str, request_id: str, deadline: float, allow_fallback: bool = True
) -> tuple[str, str, int]:
    """Groq once; on a fallback-eligible failure (when allowed), Gemini once.
    Returns (raw text, "provider/model" label, provider calls made).

    A Groq timeout may still have run on Groq's side; falling back anyway is
    deliberate, and the uniqueness check still guards the returned review.
    """
    groq_model = f"groq/{settings.groq_model}"
    try:
        # max_retries=0: the SDK would otherwise retry 429s and timeouts itself.
        timeout = min(CALL_TIMEOUT_SECONDS, max(1.0, deadline - time.monotonic()))
        raw = _complete(Groq(api_key=settings.groq_api_key, max_retries=0), prompt, request_id, timeout)
    except GroqRateLimitError as exc:
        wait = exc.retry_after
        if not allow_fallback or wait is None or wait > MAX_GROQ_WAIT_SECONDS \
                or deadline - time.monotonic() - wait < CALL_TIMEOUT_SECONDS / 2:
            raw = _fall_back(exc, prompt, request_id, deadline, allow_fallback)
            return raw, f"gemini/{settings.gemini_model}", 2
        logger.warning("Groq busy, retrying Groq in %.1fs req=%s", wait, request_id)
        time.sleep(wait)
        try:
            timeout = min(CALL_TIMEOUT_SECONDS, max(1.0, deadline - time.monotonic()))
            raw = _complete(Groq(api_key=settings.groq_api_key, max_retries=0), prompt, request_id, timeout)
        except GroqError as retry_exc:  # two calls used: no Gemini after this
            logger.error("Review failed: model=%s reason=%s after retry req=%s", groq_model, retry_exc.reason, request_id)
            raise
        return raw, groq_model, 2
    except GroqError as exc:
        raw = _fall_back(exc, prompt, request_id, deadline, allow_fallback)
        return raw, f"gemini/{settings.gemini_model}", 2
    return raw, groq_model, 1


def _fall_back(exc: GroqError, prompt: str, request_id: str, deadline: float, allow_fallback: bool) -> str:
    """Gemini's one call after a failed Groq call, or re-raise when the
    failure isn't transient, the fallback isn't allowed or not configured."""
    groq_model = f"groq/{settings.groq_model}"
    if not exc.fallback_eligible or not allow_fallback:
        logger.error("Review failed: model=%s error=%s req=%s", groq_model, _short(exc.__cause__ or exc), request_id)
        raise exc
    if not settings.gemini_api_key:
        logger.error("Review failed: model=%s reason=%s (no Gemini fallback configured) req=%s", groq_model, exc.reason, request_id)
        raise exc
    gemini_model = f"gemini/{settings.gemini_model}"
    logger.warning("Groq failed (%s), falling back to model=%s req=%s", exc.reason, gemini_model, request_id)
    return _complete_gemini(prompt, request_id, gemini_model, deadline)


def _short(exc: BaseException) -> str:
    """One-line, length-capped error text for logs."""
    return " ".join(str(exc).split())[:160] or type(exc).__name__


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
        experience or "(nothing given: write a general review of the boutique that matches the rating. At 4-5 stars, general comments on the collection, quality, service or staff are fine. At 1-3 stars, only say how you feel overall, without naming any specific problem. Never hard facts.)",
        ">>>",
        "",
        "Style notes for this review:",
        f"- Length: at least {MIN_REVIEW_SENTENCES} sentences, about {low}-{high} words.",
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
    lines += [
        "",
        f"Write {CANDIDATES} different versions of this review now, as JSON. Each one follows "
        "every rule and style note above, with its own wording.",
    ]
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
    kept, dropped = [], []
    for sentence in rules.split_sentences(rules.generalize_review(clean_review(raw), rating, experience)):
        problem = rules.sentence_problem(sentence, rating, experience)
        if problem:
            dropped.append(problem.rsplit(": ", 1)[-1])  # topic/phrase only, never customer text
        else:
            kept.append(sentence)
    while len(kept) > MIN_REVIEW_SENTENCES and len(" ".join(kept).split()) > max_words:
        kept.pop()
    review = " ".join(kept)

    if len(review.split()) < MIN_REVIEW_WORDS or len(kept) < MIN_REVIEW_SENTENCES:
        detail = f" (dropped: {', '.join(dict.fromkeys(dropped))})" if dropped else ""
        return review, "too little was left after removing unsupported sentences" + detail
    repeated = _repeated_word(review)
    if repeated:
        return review, f"it repeated '{repeated}' too often"
    if len(review.split()) > max_words:
        return review, f"it was longer than {max_words} words"
    floor = rules.rating_floor_problem(review, rating)
    if floor:
        return review, floor
    missing = rules.missing_points(review, experience)  # checked last: a soft problem
    if missing:
        return review, MISSED_POINT + ", ".join(missing)
    return review, None


# Common words that may appear often; any other word 3+ times reads as a
# review repeating itself (or several versions run together).
_REPEAT_OK = frozenset(
    "the a an and but so or to of in on at for with was were is it its it's i i'm "
    "me my we our they them this that there had have has be been very really just "
    "too also all it's".split()
)
MAX_WORD_REPEATS = 2


def _repeated_word(review: str) -> str | None:
    counts: defaultdict[str, int] = defaultdict(int)
    for word in re.findall(r"[a-z']+", review.lower()):
        if word not in _REPEAT_OK and len(word) > 2:
            counts[word] += 1
            if counts[word] > MAX_WORD_REPEATS:
                return word
    return None


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


def _complete(client: Groq, prompt: str, request_id: str, timeout: float = CALL_TIMEOUT_SECONDS) -> str:
    model = f"groq/{settings.groq_model}"
    logger.info("LLM request sent model=%s timeout=%.1fs req=%s", model, timeout, request_id)
    started = time.monotonic()
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
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "reviews", "strict": True, "schema": REVIEWS_SCHEMA},
            },
            timeout=timeout,
        )
    except RateLimitError as exc:
        retry_after = _retry_after(exc)
        logger.warning("Groq rate limit detected (429) retry_after=%s req=%s", retry_after, request_id)
        raise GroqRateLimitError(retry_after=retry_after) from exc
    except BadRequestError as exc:
        # The model's text failed Groq's JSON check: Groq returns that text,
        # and the local parser can still read its versions. No extra call.
        salvaged = _failed_generation(exc)
        if salvaged:
            return salvaged
        raise GroqError(f"Review generation failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean HTTP error
        reason = _groq_failure_reason(exc)
        if isinstance(exc, APIError):
            logger.warning(
                "LLM request failed model=%s reason=%s took=%.1fs error=%s req=%s",
                model, reason, time.monotonic() - started, _short(exc), request_id,
            )
        else:  # not an API answer: a bug, so keep the traceback
            logger.exception("LLM request raised unexpectedly model=%s req=%s", model, request_id)
        raise GroqError(f"Review generation failed: {exc}", reason) from exc

    logger.info("LLM request completed model=%s took=%.1fs req=%s", model, time.monotonic() - started, request_id)
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise GroqError("Groq returned an empty review. Please try again.", "empty_response")
    return content


def _retry_after(exc: RateLimitError) -> float | None:
    """Groq's suggested wait: the retry-after header, else the "try again in
    3.07s" of its message. None when it gave neither."""
    header = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        if header is not None:
            return float(header)
    except ValueError:
        pass
    match = _RETRY_IN_RE.search(str(exc))
    if not match:
        return None
    minutes, amount, unit = match.groups()
    seconds = float(amount) / (1000 if unit == "ms" else 1)
    return seconds + 60 * int(minutes or 0)


def _failed_generation(exc: BadRequestError) -> str:
    """The generated text Groq attaches to a json_validate_failed error."""
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", body)
    if isinstance(error, dict) and error.get("code") == "json_validate_failed":
        return str(error.get("failed_generation") or "").strip()
    return ""


def _groq_failure_reason(exc: Exception) -> str | None:
    """Fallback category for a failed Groq call, or None for errors Gemini
    can't fix (bad key or request, unknown model, bugs in our code)."""
    if isinstance(exc, APIConnectionError):  # includes APITimeoutError, DNS
        return "transient"
    status = getattr(exc, "status_code", None)  # groq.APIStatusError
    if status == 408:
        return "transient"
    if isinstance(status, int) and status >= 500:
        return "service_unavailable"
    return None


def _complete_gemini(prompt: str, request_id: str, model: str, deadline: float) -> str:
    """The one Gemini call, with the same system and user prompts, limited to
    the time left before the request deadline."""
    seconds_left = deadline - time.monotonic()
    if seconds_left < MIN_GEMINI_SECONDS:
        logger.error("Review failed: model=%s skipped, only %.1fs left req=%s", model, seconds_left, request_id)
        raise GroqError("Review generation took too long. Please try again.", "transient")
    logger.info("LLM request sent model=%s timeout=%.1fs req=%s", model, seconds_left, request_id)
    started = time.monotonic()
    try:
        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=genai_types.HttpOptions(
                timeout=int(seconds_left * 1000),
                retry_options=genai_types.HttpRetryOptions(attempts=1),  # no SDK retries
            ),
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                # Temperature left at the Gemini default: Google advises
                # against lowering it on thinking models.
                max_output_tokens=GEMINI_MAX_TOKENS,
                # No tools are sent; AFC off also skips the SDK's AFC warning.
                automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
                response_mime_type="application/json",
                response_json_schema=REVIEWS_SCHEMA,
                thinking_config=genai_types.ThinkingConfig(thinking_level=genai_types.ThinkingLevel.LOW),
            ),
        )
        content = (response.text or "").strip()
    except genai_errors.APIError as exc:
        logger.error("Review failed: model=%s status=%s error=%s req=%s", model, exc.code, _short(exc.message or exc), request_id)
        if exc.code == 429:
            logger.warning("Gemini rate limit detected (429) req=%s", request_id)
            raise GroqRateLimitError(reason=None) from exc
        transient = exc.code == 408 or (isinstance(exc.code, int) and exc.code >= 500)
        raise GroqError(f"Review generation failed: {exc}", "service_unavailable" if transient else None) from exc
    except (TimeoutError, ConnectionError, httpx.TransportError) as exc:
        logger.error("Review failed: model=%s error=%s req=%s", model, _short(exc), request_id)
        raise GroqError(f"Review generation failed: {exc}", "transient") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean HTTP error
        logger.exception("Review failed: model=%s raised unexpectedly req=%s", model, request_id)
        raise GroqError(f"Review generation failed: {exc}") from exc

    logger.info("LLM request completed model=%s took=%.1fs req=%s", model, time.monotonic() - started, request_id)
    if not content:
        logger.error("Review failed: model=%s error=empty response req=%s", model, request_id)
        raise GroqError("Review generation returned an empty review. Please try again.", "empty_response")
    return content
