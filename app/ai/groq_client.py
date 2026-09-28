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
    ungrounded_topics,
)
from app.config import settings

logger = logging.getLogger(__name__)


class GroqError(Exception):
    """Review generation failed or Groq is not configured."""


SYSTEM_PROMPT = """\
You write ONE authentic Google review as the CUSTOMER of Kaur Threads Boutique.

Kaur Threads Boutique is a fashion boutique where a customer's experience may involve
PRODUCTS, SERVICES, or BOTH.

Possible product-related topics include:
- clothing/outfit collection
- designs/styles
- fabric/material quality
- variety/selection
- fitting
- overall product quality

Possible service-related topics include:
- stitching/tailoring
- alterations
- customization
- fitting assistance
- design guidance
- staff/customer service
- communication
- delivery/timeliness
- attention to customer requirements

These are ONLY possible topics, NOT business facts.
Mention something ONLY when the customer explicitly provides it.

INPUT:
- Rating: customer's selected rating
- Experience: customer's own words

ABSOLUTE RULES:

1. Use ONLY the customer's rating and experience.
2. Never invent products, services, staff, names, prices, offers, fabrics,
   designs, policies, delivery details, or any other business fact.
3. If a fact is not explicitly present in the customer's Experience,
   treat it as UNKNOWN and do not mention it.
4. Preserve the customer's actual meaning and sentiment.
5. Do not artificially make the review positive.
6. 1-2 stars: dissatisfied/critical but respectful.
7. 3 stars: balanced or mixed.
8. 4 stars: positive and satisfied.
9. 5 stars: very positive and appreciative.
10. Write naturally as a real customer.
11. Do not use marketing language, slogans, hashtags, emojis, headings,
    or quotation marks.
12. Keep the review to 2-4 short, natural sentences.
13. Return ONLY the review text.

VARIATION REQUIREMENTS:

14. Every generation is a NEW review request.
    Do NOT intentionally reproduce a previous review.

15. When the same or similar customer input is received multiple times,
    generate a meaningfully different version while preserving exactly
    the same facts and sentiment.

16. Vary the natural writing style between generations.
    You may vary:
    - sentence structure
    - opening phrase
    - word choice
    - order of the customer's mentioned points
    - sentence length
    - how the experience is naturally expressed

17. Do NOT change the factual meaning just to make the review different.

18. Never add new information merely to create variation. That includes
    claims the customer did not make about buying something, trying items
    on, planning to return or visit again, recommending the boutique, or
    what the boutique does, cares about, or pays attention to.

19. Phrases must never become templates. Avoid opening with:
    "I had...", "I really...", "I am...", "Overall...", "The...",
    "Great...", "Really..."
    and avoid closing with:
    "Overall, a great experience.", "I was very happy.",
    "Highly recommended.", "I would definitely recommend.",
    "Great experience."

20. If the customer's input is extremely short, keep the factual content
    limited but still vary the natural phrasing.

21. The request may include PREVIOUS_REVIEWS. Generate a review that is
    substantially different from every review in PREVIOUS_REVIEWS. Do not
    reuse their sentence structure, opening phrase, closing phrase, or
    distinctive wording. Never copy any detail from them — use only this
    customer's rating and experience.

22. Follow the WRITING STRUCTURE given in the request, but never mention it.

IMPORTANT:
Variation means different wording and structure, NOT different facts.

If the customer says:
"Good collection and nice quality"

one possible wording (an illustration only — never copy it) is:
The collection was really nice, and I was happy with the quality.
Everything I saw felt good and suited what I was looking for.

Do NOT add facts such as specific clothing, fabric, staff, stitching,
price, service, or recommendations unless the customer mentioned them.

Return ONLY the final review text.
"""


# One is picked at random per attempt so reviews don't share a skeleton.
WRITING_STRUCTURES = (
    "Direct experience, then a specific point, then an overall feeling.",
    "Overall reaction, then a specific point, then a closing thought.",
    "A specific point, then a personal reaction, then the overall experience.",
    "A personal reaction, then the customer's described detail, then a conclusion.",
    "A short conversational observation, then a second observation, then a reaction.",
)

# One is picked at random per request to spread out how reviews begin.
OPENING_STYLES = (
    "Open with the customer's own point itself, e.g. naming what they liked or disliked.",
    "Open with a short phrase describing how the visit felt.",
    "Open with a brief phrase about the moment of noticing something.",
    "Open with a casual, conversational remark, as if talking to a friend.",
    "Open with a word such as My, So, Such, What, Honestly, Pleased, or Loved, "
    "whichever fits the rating naturally.",
)

# Openings the requirements single out; never used as the first words.
AVOID_OPENINGS = ("I had", "I really", "I am", "Overall", "The", "Great", "Really")
AVOID_CLOSINGS = (
    "Overall, a great experience.",
    "I was very happy.",
    "Highly recommended.",
    "I would definitely recommend.",
    "Great experience.",
)

# Used once the normal attempts are exhausted, to push for a new shape.
RESCUE_INSTRUCTIONS = (
    "Use a noticeably different voice: short, casual sentences, as if telling a friend.",
    "Use a noticeably different voice: calm and reflective, with one longer sentence.",
    "Begin with how the visit felt, and mention the customer's points in reverse order.",
)

NORMAL_ATTEMPTS = 4
MAX_PREVIOUS_IN_PROMPT = 8
# No new attempt starts after this, so a response arrives well within the
# frontend's 20s request timeout.
GENERATION_BUDGET_SECONDS = 8.0


def generate_review(rating: int, experience: str | None) -> str:
    """Generate one new review for the given rating/experience.

    Every call makes a fresh generation. The result is checked against the
    in-memory history and regenerated (with stronger instructions) if it is
    identical or too similar to a previous review, repeats a recent opening or
    closing, breaks the format rules, or mentions topics the customer never
    mentioned. ``experience`` may be ``None``. Raises :class:`GroqError` on
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
    last_reason: str | None = None
    fallback: str | None = None  # unique, but reused an opening/closing
    structures = random.sample(WRITING_STRUCTURES, len(WRITING_STRUCTURES))
    opening_style = random.choice(OPENING_STYLES)
    attempts = NORMAL_ATTEMPTS + len(RESCUE_INSTRUCTIONS)

    for attempt in range(attempts):
        if attempt and time.monotonic() - started > GENERATION_BUDGET_SECONDS:
            logger.warning("Time budget reached (request=%s)", request_id)
            break
        rescue = (
            RESCUE_INSTRUCTIONS[attempt - NORMAL_ATTEMPTS]
            if attempt >= NORMAL_ATTEMPTS
            else None
        )
        prompt = _build_user_prompt(
            rating,
            experience,
            structure=structures[attempt % len(structures)],
            opening_style=opening_style,
            previous=previous + contrast,
            last_reason=last_reason,
            rescue=rescue,
        )
        review = _complete(client, prompt, temperature=min(0.7 + 0.1 * attempt, 1.0))

        ungrounded = _ungrounded_reason(review, experience)
        reason = ungrounded or _hard_rejection(review, rejected)
        if reason is None:
            soft = history.repeated_edges(key, review)
            if soft is None:
                if history.add_if_unique(key, review):
                    _log_success(request_id, rating, attempt, review)
                    return review
                reason = "a matching review was just generated for someone else"
            else:
                reason = soft
                fallback = fallback or review

        logger.info(
            "Review rejected (request=%s, attempt=%d): %s",
            request_id, attempt + 1, reason,
        )
        logger.debug("Rejected text (request=%s): %s", request_id, review)
        rejected.append(review)
        if not ungrounded:  # never feed invented facts back to the model
            contrast.append(review)
        last_reason = reason

    # Every attempt reused an opening/closing at best: return one that is
    # still unique rather than a duplicate.
    if fallback and history.add_if_unique(key, fallback):
        _log_success(request_id, rating, attempt, fallback)
        return fallback

    logger.error("No unique review after %d attempts (request=%s)", attempt + 1, request_id)
    raise GroqError("Could not generate a unique review. Please try again.")


def _build_user_prompt(
    rating: int,
    experience: str | None,
    *,
    structure: str,
    opening_style: str,
    previous: list[str],
    last_reason: str | None,
    rescue: str | None,
) -> str:
    experience_text = experience or "(No specific details provided.)"
    lines = [
        f"Star rating: {rating} out of 5",
        f"Customer's experience in their own words: {experience_text}",
        "",
        f"WRITING STRUCTURE: {structure}",
        f"OPENING: {opening_style}",
        "Do not begin with: " + ", ".join(_avoid_openings(previous)),
        "Do not end with: " + ", ".join(_avoid_closings(previous)),
    ]
    if previous:
        lines += ["", "PREVIOUS_REVIEWS (for contrast only, never copy details):"]
        lines += [f"{i}. {text}" for i, text in enumerate(previous, 1)]
        lines += [
            "",
            "Generate a review that is substantially different from every review "
            "in PREVIOUS_REVIEWS. Do not reuse their sentence structure, opening "
            "phrase, closing phrase, or distinctive wording.",
        ]
    if last_reason:
        lines += [
            "",
            f"Your last attempt was rejected because {last_reason}. Use a clearly "
            "different sentence structure, a different opening, and a different "
            "closing, while keeping exactly the same facts and sentiment.",
        ]
    if rescue:
        lines += ["", rescue]
    lines += ["", "Write 2-4 short sentences now. Return only the review text."]
    return "\n".join(lines)


def _avoid_openings(previous: list[str]) -> list[str]:
    """Always-avoided openings plus the first two words of recent reviews."""
    recent = []
    for text in previous[:5]:
        words = text.split()[:2]
        if words:
            recent.append(" ".join(words).strip(",.!"))
    return list(dict.fromkeys([*AVOID_OPENINGS, *recent]))


def _avoid_closings(previous: list[str]) -> list[str]:
    """Always-avoided closings plus the last few words of recent reviews."""
    recent = [f"...{closing(normalize(t))}" for t in previous[:5] if t.strip()]
    return list(dict.fromkeys([*AVOID_CLOSINGS, *recent]))


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


def _ungrounded_reason(review: str, experience: str | None) -> str | None:
    """Reason the review mentions topics the customer never did, else ``None``."""
    topics = ungrounded_topics(review, experience)
    if not topics:
        return None
    return "it mentioned " + ", ".join(topics) + ", which the customer did not mention"


def _hard_rejection(review: str, rejected: list[str]) -> str | None:
    """Reason a (grounded) candidate can never be returned, else ``None``."""
    problems = format_problems(review)
    if problems:
        return problems[0]
    return history.too_similar(review, extra=rejected)


def _log_success(request_id: str, rating: int, attempt: int, review: str) -> None:
    logger.info(
        "Review generated (request=%s, rating=%s, attempts=%d, %d characters)",
        request_id, rating, attempt + 1, len(review),
    )
