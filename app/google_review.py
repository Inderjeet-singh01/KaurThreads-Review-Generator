"""Google review page configuration — kept separate from the LLM logic.

The customer submits their review themselves on Google's own interface. This
module only holds/validates the boutique's public "write a review" URL; it
NEVER posts anything to Google and requires no OAuth. It is the single source
of truth for that URL, which the frontend (added later) opens in a new tab.
"""

from __future__ import annotations

from app.config import settings


def get_google_review_url() -> str | None:
    """Return the configured Google review URL, or ``None`` when unset."""
    url = settings.google_review_url.strip()
    return url or None
