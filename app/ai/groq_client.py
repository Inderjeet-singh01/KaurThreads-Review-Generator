"""Groq integration: generate a customer review from a rating + experience.

This module's only job is: "Generate one review." It is deliberately isolated
so the model, prompt, or provider can be swapped later without touching the
API layer. It reuses the same Groq credentials/model as the Review Reply AI
project.
"""

from __future__ import annotations

import logging

from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)


class GroqError(Exception):
    """Review generation failed or Groq is not configured."""


SYSTEM_PROMPT = """\
You write a single Google review as the CUSTOMER of Kaur Threads Boutique, a
small fashion clothing store. You write in the first person ("I", "we").

Absolute rules:
1. Use ONLY the rating and the customer's own words provided. If details are
   sparse, keep the review short and general.
2. NEVER invent products, employees, names, prices, discounts, promotions,
   services, events, policies, or any fact the customer did not state.
3. Sound like a real person: natural, plain, specific to what was given. Not
   marketing copy, not a slogan, no hashtags, no headings, no quotes, no emoji.
4. Match the star rating:
   - 1-2 stars: dissatisfied and negative, but respectful and civil.
   - 3 stars: balanced and neutral, mentioning it was just okay.
   - 4-5 stars: positive and appreciative.
5. Keep it concise: 1 to 3 short sentences.
6. Return ONLY the review text, with no preamble or explanation.
"""


def generate_review(rating: int, experience: str | None) -> str:
    """Generate one natural-sounding review for the given rating/experience.

    ``experience`` may be ``None`` when the customer provided no words. Returns
    the review text. Raises :class:`GroqError` on any configuration or API
    failure so the API layer can translate it into a clean HTTP error.
    """
    if not settings.groq_api_key:
        raise GroqError(
            "GROQ_API_KEY is not configured. Set it in the .env file to "
            "enable review generation."
        )

    experience_text = experience or "(No specific details provided.)"
    user_prompt = (
        f"Star rating: {rating} out of 5\n"
        f"Customer's experience in their own words: {experience_text}\n\n"
        "Write the review now. Return only the review text."
    )

    client = Groq(api_key=settings.groq_api_key)
    try:
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
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

    logger.info("Review generated (rating=%s, %d characters)", rating, len(review))
    return review
