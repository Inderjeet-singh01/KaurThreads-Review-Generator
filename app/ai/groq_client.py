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
12. Keep the review to 1-3 natural sentences.
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

18. Never add new information merely to create variation.

19. Avoid repeatedly using the same phrases such as:
    "I had a great experience"
    "I was very happy"
    "Highly recommended"
    "Overall, a great experience"

20. If the customer's input is extremely short, keep the factual content
    limited but still vary the natural phrasing.

IMPORTANT:
Variation means different wording and structure, NOT different facts.

If the customer says:
"Good collection and nice quality"

possible generations could be different in wording, for example:
"Really liked the collection and was happy with the quality."

or:
"I liked the collection a lot, and the quality was good too."

or:
"The collection was nice and the quality met my expectations."

Do NOT add facts such as specific clothing, fabric, staff, stitching,
price, service, or recommendations unless the customer mentioned them.

Return ONLY the final review text.
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
