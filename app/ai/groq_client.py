"""Groq integration: generate a customer review from a rating + experience.

This module's only job is: "Generate one review." It is deliberately isolated
so the model, prompt, or provider can be swapped later without touching the
API layer. It reuses the same Groq credentials/model as the Review Reply AI
project.
"""

from __future__ import annotations

import logging
import random
import time
import uuid

from groq import Groq

from app.ai.review_history import (
    ai_style_problem,
    closing,
    format_problems,
    history,
    input_key,
    normalize,
    promotional_phrases,
    sentiment_problem,
    ungrounded_topics,
)
from app.config import settings

logger = logging.getLogger(__name__)


class GroqError(Exception):
    """Review generation failed or Groq is not configured."""


SYSTEM_PROMPT = """\
You write one Google review as a real customer of Kaur Threads Boutique, a \
fashion boutique.

FACTS: use only the customer's rating and experience.
- Every fact must come from the experience. Anything not said is unknown: \
leave it out. Never fill gaps with what boutiques usually offer.
- A customer may talk about products (outfits, collection, designs, fabric, \
quality, variety, colours, fitting) and/or service (staff help, stitching, \
alterations, customization, measurements, communication, orders, delivery). \
These are possible topics, not facts about this boutique. Mention one only if \
the customer did.
- Never add staff, stylists, prices, offers, fabrics, brands, garments, \
occasions, the shop's look, new arrivals, a "wide" range, delivery details, \
reasons for a problem, purchases, trying on, coming back or recommending.
- Rephrase, never embellish. "Staff helped me choose the design" can become \
"The staff was helpful when I was choosing a design", never "Their stylists \
guided me through a wide range of designer outfits".

TONE: 1-2 stars unhappy but civil; 3 stars mixed or so-so, not positive; \
4 stars clearly satisfied; 5 stars very positive. Never make it sound better \
or stronger than the customer put it.

VOICE: write like an ordinary customer typing on their phone. Simple, direct, \
a little informal, short common words. Not polished, literary, promotional or \
AI-like. No "highly recommended", "must visit", "best in town", "top-notch", \
"premium", "exceptional", "absolutely amazing", "truly", "delightful", \
"curated", "impeccable", "spot-on", "vibe", "caught my eye", "left me \
feeling" and the like. No filler openers ("Honestly,", "So,", "Well,", "You \
know,") and no neat wrap-up line at the end.

Examples of the right voice (never reuse these sentences):
- 5 stars, "Beautiful collection and really good quality." -> The collection \
was lovely and the quality was really good. Very happy with what I found.
- 3 stars, "The collection was okay but I didn't find much variety." -> \
Collection was okay but there wasn't much variety. Pretty average for me.
- 2 stars, "The fitting was not right and I had to get it changed." -> The \
fitting wasn't right so I had to get it changed. Bit disappointing.

VARIETY: many customers write similar things, so vary the opening, sentence \
structure, word choice, order of ideas and length. Avoid stock lines like "I \
had a great experience", "Overall, it was a great experience" or "I would \
definitely recommend". Don't just echo the customer's sentence. Variation \
changes wording, never facts.

FORMAT: 2-4 short sentences. Plain punctuation: no em dashes, semicolons, \
quotation marks, hashtags, emojis, bullets or headings. Output only the review.
"""


# One is used per attempt (shuffled per request) so reviews don't share a
# skeleton. Each only reorders or restyles what the customer said.
ANGLES = (
    "Start with the first thing the customer mentioned.",
    "Start with the last thing the customer mentioned, then the rest.",
    "Start with how the customer felt, then say why in simple words.",
    "Fit the customer's points into one sentence, then add a short personal reaction.",
    "Keep it very plain and brief, like a quick review typed on a phone.",
)

# Picked per request so reviews are tied to the boutique without every one
# naming it.
NAMING = (
    "Mention Kaur Threads by name once, where it fits naturally.",
    "Refer to the place as the boutique once, where it fits naturally.",
    "Do not name the place.",
    "Do not name the place.",
)

# Openings/closings the requirements single out as templates.
STOCK_OPENINGS = ("I had a", "I really", "Overall", "Great experience")
STOCK_CLOSINGS = (
    "Overall, a great experience.",
    "Great experience overall.",
    "I was very happy.",
    "Highly recommended.",
    "I would definitely recommend.",
)

# Used for the last attempts, to push for a new shape.
RESCUE_INSTRUCTIONS = (
    "Use a noticeably different voice from every earlier review: plainer and "
    "shorter, with a different first word and a different last sentence.",
    "Use a noticeably different voice from every earlier review: "
    "matter-of-fact, mentioning the customer's points in reverse order.",
)

# The prompt's tone-reference outputs; a review must not copy one of them.
EXAMPLE_REVIEWS = (
    "The collection was lovely and the quality was really good. Very happy with what I found.",
    "Collection was okay but there wasn't much variety. Pretty average for me.",
    "The fitting wasn't right so I had to get it changed. Bit disappointing.",
)

# Typography people don't type on a phone keyboard, swapped for what they do.
_PLAIN_TYPOGRAPHY = str.maketrans({"‐": "-", "‑": "-", "‘": "'", "’": "'"})

MAX_ATTEMPTS = 4  # the first try plus up to 3 regenerations
MAX_PREVIOUS_IN_PROMPT = 4
BASE_TEMPERATURE = 0.8

# Timing. The frontend aborts after 20s, so every request finishes by
# DEADLINE_SECONDS: each call's timeout is clipped to the time left, and no
# new attempt starts without MIN_CALL_SECONDS to spare. Once a usable
# fallback exists, no retry starts after SETTLE_SECONDS, to keep it quick.
DEADLINE_SECONDS = 15.0
CALL_TIMEOUT_SECONDS = 7.0
MIN_CALL_SECONDS = 3.0
SETTLE_SECONDS = 6.0

# Rejection kinds, in the order a candidate is preferred as a fallback when
# no attempt passes every check. UNGROUNDED (invented facts) and DUPLICATE
# (identical to a past review) candidates are never returned. Only
# EDGE/SIMILAR candidates are shown back to the model as contrast; the others
# contain content it should not see again (or already sees).
EDGE, SIMILAR, STYLE = "edge", "similar", "style"
UNGROUNDED, DUPLICATE = "ungrounded", "duplicate"
_FALLBACK_RANK = {EDGE: 0, SIMILAR: 1, STYLE: 2}


def generate_review(rating: int, experience: str | None) -> str:
    """Generate one new review for the given rating/experience.

    Every call makes a fresh generation; nothing is cached. Each candidate is
    checked and regenerated (with feedback) if it mentions things the customer
    never did, sounds promotional or AI-written, overshoots the rating, breaks
    the format rules, or is too similar to a previous review (as a whole or
    sentence by sentence), including reviews written for similar inputs.

    If no attempt passes every check before the deadline, or Groq fails on a
    retry, the best grounded candidate that is not an exact duplicate is
    returned instead of an error. ``experience`` may be ``None``. Raises
    :class:`GroqError` on configuration/API failure or if no usable review
    could be produced.
    """
    if not settings.groq_api_key:
        raise GroqError(
            "GROQ_API_KEY is not configured. Set it in the .env file to "
            "enable review generation."
        )

    request_id = uuid.uuid4().hex[:12]
    key = input_key(rating, experience)
    previous = history.recent_for(key, MAX_PREVIOUS_IN_PROMPT)
    # Retries are handled here, within the deadline, not by the SDK.
    client = Groq(api_key=settings.groq_api_key, max_retries=0)
    started = time.monotonic()

    rejected: list[str] = []  # this request's rejected candidates
    contrast: list[str] = []  # rejected candidates safe to show the model
    fallbacks: list[tuple[int, int, str]] = []  # (rank, attempt, text)
    last_rejection: tuple[str, str] | None = None  # (kind, reason)
    last_error: GroqError | None = None
    angles = random.sample(ANGLES, len(ANGLES))
    naming = random.choice(NAMING)
    sentences = _sentence_target(experience)
    first_rescue = MAX_ATTEMPTS - len(RESCUE_INSTRUCTIONS)

    for attempt in range(MAX_ATTEMPTS):
        elapsed = time.monotonic() - started
        remaining = DEADLINE_SECONDS - elapsed
        if attempt and (remaining < MIN_CALL_SECONDS or (fallbacks and elapsed > SETTLE_SECONDS)):
            logger.warning("Time budget reached (request=%s)", request_id)
            break
        prompt = _build_user_prompt(
            rating,
            experience,
            nonce=f"{request_id}-{attempt + 1}",
            angle=angles[attempt % len(angles)],
            naming=naming,
            sentences=sentences,
            previous=previous + contrast,
            last_rejection=last_rejection,
            rescue=RESCUE_INSTRUCTIONS[attempt - first_rescue] if attempt >= first_rescue else None,
        )
        temperature = min(BASE_TEMPERATURE + 0.05 * attempt, 1.0)
        try:
            review = _complete(
                client,
                prompt,
                temperature=temperature,
                timeout=min(CALL_TIMEOUT_SECONDS, remaining),
            )
        except GroqError as exc:
            # A rate limit or timeout on a retry shouldn't fail the customer
            # when a usable candidate already exists.
            last_error = exc
            if fallbacks:
                break
            continue

        kind, reason = _rejection(review, rating, experience, key, rejected)
        if reason is None:
            if history.add_if_unique(key, review):
                _log_success(request_id, rating, attempt, review)
                return review
            kind, reason = SIMILAR, "it matched a review that was just generated"

        logger.info(
            "Review rejected (request=%s, attempt=%d): %s",
            request_id, attempt + 1, reason,
        )
        logger.debug("Rejected text (request=%s): %s", request_id, review)
        rejected.append(review)
        if kind in _FALLBACK_RANK:
            fallbacks.append((_FALLBACK_RANK[kind], attempt, review))
        if kind in (EDGE, SIMILAR):  # never feed invented or off-tone text back
            contrast.append(review)
        last_rejection = (kind, reason)

    # Nothing passed every check: return the best grounded candidate that is
    # not an exact duplicate, rather than failing the customer.
    for _, attempt, review in sorted(fallbacks):
        if history.add_if_unique(key, review, allow_similar=True):
            logger.warning("Returning best fallback candidate (request=%s)", request_id)
            _log_success(request_id, rating, attempt, review)
            return review

    logger.error("No usable review (request=%s)", request_id)
    if last_error and not fallbacks:
        raise last_error
    raise GroqError("Could not generate a unique review. Please try again.")


def _rejection(
    review: str,
    rating: int,
    experience: str | None,
    key: tuple[int, str],
    rejected: list[str],
) -> tuple[str, str | None]:
    """(kind, reason) the candidate was rejected, or (kind, None) if it passes."""
    topics = ungrounded_topics(review, experience)
    if topics:
        return UNGROUNDED, (
            "it mentioned " + ", ".join(topics) + ", which the customer did not mention"
        )
    if history.is_duplicate(review):
        return DUPLICATE, "it was identical to a previous review"
    promo = promotional_phrases(review, experience)
    if promo:
        return STYLE, f"it used promotional wording ('{promo[0]}') the customer never used"
    style = ai_style_problem(review, experience)
    if style:
        return STYLE, style
    tone = sentiment_problem(review, rating, experience)
    if tone:
        return STYLE, tone
    problems = format_problems(review)
    if problems:
        return STYLE, problems[0]
    similar = (
        history.too_similar(review, extra=[*rejected, *EXAMPLE_REVIEWS])
        or history.reused_sentence(key, review)
    )
    if similar:
        return SIMILAR, similar
    return EDGE, history.repeated_edges(key, review)


def _sentence_target(experience: str | None) -> str:
    """A per-request sentence count, so lengths vary without padding short input."""
    words = len((experience or "").split())
    if words < 8:
        return random.choice(("2", "2", "3"))
    return random.choice(("2", "3", "4") if words >= 15 else ("2", "3"))


def _build_user_prompt(
    rating: int,
    experience: str | None,
    *,
    nonce: str,
    angle: str,
    naming: str,
    sentences: str,
    previous: list[str],
    last_rejection: tuple[str, str] | None,
    rescue: str | None,
) -> str:
    experience_text = experience or (
        "(No details given. Reflect only the rating in general terms and do "
        "not invent any specifics.)"
    )
    lines = [
        f"Request: {nonce}",
        f"Star rating: {rating} out of 5",
        f"Customer's experience in their own words: {experience_text}",
        "",
        f"Approach: {angle}",
        f"Naming: {naming}",
        f"Length: about {sentences} sentences.",
        "Do not begin with: " + ", ".join(_avoid_openings(previous)),
        "Do not end with: " + ", ".join(_avoid_closings(previous)),
    ]
    if previous:
        lines += ["", "PREVIOUS_REVIEWS (for contrast only, never copy details):"]
        lines += [f"{i}. {text}" for i, text in enumerate(previous, 1)]
        lines += [
            "",
            "Your review must be substantially different from every review in "
            "PREVIOUS_REVIEWS: a different opening, sentence structure, "
            "wording and closing.",
        ]
    if last_rejection:
        kind, reason = last_rejection
        if kind in (EDGE, SIMILAR, DUPLICATE):
            lines += [
                "",
                f"Your last attempt was rejected as too similar to a previous "
                f"review ({reason}). Write it again with a substantially "
                "different structure and wording: new opening, new sentence "
                "shapes, new closing. Keep exactly the same facts and tone.",
            ]
        else:
            lines += [
                "",
                f"Your last attempt was rejected because {reason}. Use only "
                "what the customer said, in their tone.",
            ]
    if rescue:
        lines += ["", rescue]
    lines += ["", "Write the review now. Return only the review text."]
    return "\n".join(lines)


def _avoid_openings(previous: list[str]) -> list[str]:
    """Stock openings plus the first words of recent related reviews."""
    recent = []
    for text in previous[:MAX_PREVIOUS_IN_PROMPT]:
        words = text.split()[:2]
        if words:
            recent.append(" ".join(words).strip(",.!"))
    return list(dict.fromkeys([*STOCK_OPENINGS, *recent]))


def _avoid_closings(previous: list[str]) -> list[str]:
    """Stock closings plus the last few words of recent related reviews."""
    recent = [f"...{closing(normalize(t))}" for t in previous[:MAX_PREVIOUS_IN_PROMPT] if t.strip()]
    return list(dict.fromkeys([*STOCK_CLOSINGS, *recent]))


def _complete(client: Groq, prompt: str, *, temperature: float, timeout: float) -> str:
    try:
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=400,
            # openai/gpt-oss models are reasoning models; keep reasoning short
            # so the token budget is spent on the review, not deliberation.
            reasoning_effort="low",
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean HTTP error
        logger.error("Groq review generation failed: %s", exc)
        raise GroqError(f"Review generation failed: {exc}") from exc

    review = (response.choices[0].message.content or "").strip().translate(_PLAIN_TYPOGRAPHY)
    if not review:
        logger.error("Groq returned an empty review")
        raise GroqError("Groq returned an empty review. Please try again.")
    return review


def _log_success(request_id: str, rating: int, attempt: int, review: str) -> None:
    logger.info(
        "Review generated (request=%s, rating=%s, attempts=%d, %d characters)",
        request_id, rating, attempt + 1, len(review),
    )
