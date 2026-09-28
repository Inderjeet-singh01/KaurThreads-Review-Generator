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
You write one Google review in the voice of a real customer of Kaur Threads \
Boutique, a fashion boutique.

THE CUSTOMER'S WORDS ARE THE ONLY SOURCE OF TRUTH
- You get a star rating and the customer's experience in their own words. Use \
only these.
- Every fact in the review must come from the experience. Anything they did \
not say is unknown, so leave it out. Never fill gaps with what boutiques \
usually offer.
- A boutique experience can be about products (outfits, the collection, \
designs, fabric, quality, variety, colours, fitting, how an item looked), \
service (staff help, design guidance, stitching, alterations, customization, \
measurements, communication, order handling, delivery), or both. These are \
only kinds of experience a customer might describe, not things this boutique \
is known to offer. Mention one only if the customer did.
- Do not add staff, stylists, prices, offers, fabrics, brands, specific \
garments, colours, occasions, the shop's look or atmosphere, new arrivals, how \
big the collection is, delivery details, reasons for a problem, purchases, \
trying things on, return visits or recommendations unless the customer said so.
- Rephrase, never embellish. "Staff helped me choose the design and the outfit \
looked beautiful" may become "The staff was helpful in choosing the design, \
and I really liked how the outfit looked." It must never become "Their \
stylists helped me choose from a wide collection of designer outfits."

TONE FOLLOWS THE RATING AND THE CUSTOMER'S WORDS
- 1-2 stars: clearly unhappy about the problems they described, but civil.
- 3 stars: mixed, neutral or so-so. Do not turn it positive.
- 4 stars: clearly positive and satisfied.
- 5 stars: very positive and appreciative.
- Never make an experience sound better or stronger than the customer put it.

SOUND LIKE A CUSTOMER, NOT AN ADVERT
- Plain, everyday words, the way people really write reviews on their phone. \
Not a business owner, employee, marketer or AI.
- No promotional or inflated phrases such as highly recommended, must visit, \
best boutique, best in town, exceptional service, premium quality, top-notch, \
perfect place, absolutely amazing, luxury experience or hidden gem, unless the \
customer expressed that themselves.
- Keep it relevant to a boutique visit through the customer's own points. \
Don't force boutique words into it.

LENGTH AND FORMAT
- 2-4 short, conversational sentences. No filler just to add length.
- Return only the review text: no preamble, heading, quotation marks, \
hashtags, emojis, bullet points or JSON.

EVERY REVIEW IS NEW
- Many customers give similar input, so vary the opening, sentence structure, \
vocabulary, order of ideas, sentence length and how the feeling is expressed.
- Avoid stock lines like "I had a great experience at...", "Overall, it was a \
great experience.", "I would definitely recommend..." or "Great experience \
overall." Don't default to opening with "I", "The" or "Overall".
- Don't just repeat the customer's sentence back word for word.
- Variation changes the wording, never the facts. Never add a detail to make a \
review different.

Before answering, check silently: every claim is backed by the experience; no \
product, service, staff, price, fabric, design, brand or delivery detail was \
added; the tone is not exaggerated; it is 2-4 short sentences; it is clearly \
different from any PREVIOUS_REVIEWS. Fix anything that fails, then output only \
the review.
"""


# One is used per attempt (shuffled per request) so reviews don't share a
# skeleton. Each only reorders or restyles what the customer said.
ANGLES = (
    "Start with the first thing the customer mentioned.",
    "Start with the last thing the customer mentioned, then the rest.",
    "Start with how the customer felt, then say why in their terms.",
    "Fit the customer's points into one sentence, then add a short reaction.",
    "Keep every sentence short and plain, like a quick note typed on a phone.",
    "Write it the way someone tells a friend about it: relaxed and casual.",
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
    "Use a noticeably different voice from every earlier review: short, "
    "casual sentences, as if texting a friend.",
    "Use a noticeably different voice from every earlier review: calm and "
    "matter-of-fact, mentioning the customer's points in reverse order.",
)

MAX_ATTEMPTS = 5  # the first try plus up to 4 regenerations
MAX_PREVIOUS_IN_PROMPT = 5
BASE_TEMPERATURE = 0.8
# No new attempt starts after this, so a response arrives well within the
# frontend's 20s request timeout.
GENERATION_BUDGET_SECONDS = 8.0

# Rejection kinds. Only "similar" candidates are shown back to the model as
# contrast; the others contain content it should not see again.
SIMILAR, INVALID = "similar", "invalid"


def generate_review(rating: int, experience: str | None) -> str:
    """Generate one new review for the given rating/experience.

    Every call makes a fresh generation; nothing is cached. Each candidate is
    checked and regenerated (with feedback) if it mentions things the customer
    never did, sounds promotional, overshoots the rating, breaks the format
    rules, or is identical or too similar to a previous review (as a whole or
    sentence by sentence), including reviews written for similar inputs.
    ``experience`` may be ``None``. Raises :class:`GroqError` on
    configuration/API failure or if no acceptable review could be produced.
    """
    if not settings.groq_api_key:
        raise GroqError(
            "GROQ_API_KEY is not configured. Set it in the .env file to "
            "enable review generation."
        )

    request_id = uuid.uuid4().hex[:12]
    key = input_key(rating, experience)
    previous = history.recent_for(key, MAX_PREVIOUS_IN_PROMPT)
    client = Groq(api_key=settings.groq_api_key, timeout=8.0, max_retries=1)
    started = time.monotonic()

    rejected: list[str] = []  # this request's rejected candidates
    contrast: list[str] = []  # rejected candidates safe to show the model
    last_rejection: tuple[str, str] | None = None  # (kind, reason)
    fallback: str | None = None  # unique, but its opening/closing echoed a recent one
    angles = random.sample(ANGLES, len(ANGLES))
    naming = random.choice(NAMING)
    sentences = _sentence_target(experience)
    first_rescue = MAX_ATTEMPTS - len(RESCUE_INSTRUCTIONS)

    for attempt in range(MAX_ATTEMPTS):
        if attempt and time.monotonic() - started > GENERATION_BUDGET_SECONDS:
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
        review = _complete(client, prompt, temperature=temperature)

        kind, reason = _rejection(review, rating, experience, key, rejected)
        if reason is None:
            soft = history.repeated_edges(key, review)
            if soft is None:
                if history.add_if_unique(key, review):
                    _log_success(request_id, rating, attempt, review)
                    return review
                kind, reason = SIMILAR, "it matched a review that was just generated"
            else:
                kind, reason = SIMILAR, soft
                fallback = fallback or review

        logger.info(
            "Review rejected (request=%s, attempt=%d): %s",
            request_id, attempt + 1, reason,
        )
        logger.debug("Rejected text (request=%s): %s", request_id, review)
        rejected.append(review)
        if kind == SIMILAR:  # never feed invented or off-tone text back
            contrast.append(review)
        last_rejection = (kind, reason)

    # Every attempt echoed a recent opening/closing at best: return one that
    # is still unique rather than failing the customer.
    if fallback and history.add_if_unique(key, fallback):
        _log_success(request_id, rating, attempt, fallback)
        return fallback

    logger.error("No acceptable review after %d attempts (request=%s)", attempt + 1, request_id)
    raise GroqError("Could not generate a unique review. Please try again.")


def _rejection(
    review: str,
    rating: int,
    experience: str | None,
    key: tuple[int, str],
    rejected: list[str],
) -> tuple[str, str | None]:
    """(kind, reason) a candidate can never be returned, or (kind, None)."""
    topics = ungrounded_topics(review, experience)
    if topics:
        return INVALID, (
            "it mentioned " + ", ".join(topics) + ", which the customer did not mention"
        )
    promo = promotional_phrases(review, experience)
    if promo:
        return INVALID, f"it used promotional wording ('{promo[0]}') the customer never used"
    tone = sentiment_problem(review, rating, experience)
    if tone:
        return INVALID, tone
    problems = format_problems(review)
    if problems:
        return INVALID, problems[0]
    similar = history.too_similar(review, extra=rejected) or history.reused_sentence(key, review)
    return SIMILAR, similar


def _sentence_target(experience: str | None) -> str:
    """A per-request sentence count, so lengths vary without padding short input."""
    words = len((experience or "").split())
    options = ["2", "3"] + (["4"] if words >= 15 else [])
    return random.choice(options)


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
        if kind == SIMILAR:
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


def _complete(client: Groq, prompt: str, *, temperature: float) -> str:
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
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean HTTP error
        logger.error("Groq review generation failed: %s", exc)
        raise GroqError(f"Review generation failed: {exc}") from exc

    review = (response.choices[0].message.content or "").strip()
    if not review:
        logger.error("Groq returned an empty review")
        raise GroqError("Groq returned an empty review. Please try again.")
    return review


def _log_success(request_id: str, rating: int, attempt: int, review: str) -> None:
    logger.info(
        "Review generated (request=%s, rating=%s, attempts=%d, %d characters)",
        request_id, rating, attempt + 1, len(review),
    )
