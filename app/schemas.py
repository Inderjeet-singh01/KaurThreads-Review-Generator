"""Pydantic models for the /generate-review API contract."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# Cap the free-text experience to keep prompts bounded and prevent abuse.
MAX_EXPERIENCE_CHARS = 1000


class GenerateReviewRequest(BaseModel):
    """Input for POST /generate-review."""

    rating: int = Field(
        ge=1,
        le=5,
        description="Star rating from 1 to 5. Controls the tone of the review.",
    )
    experience: str | None = Field(
        default=None,
        max_length=MAX_EXPERIENCE_CHARS,
        description="Optional customer experience in their own words.",
    )

    @field_validator("experience")
    @classmethod
    def _normalize_experience(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class GenerateReviewResponse(BaseModel):
    """Result of POST /generate-review."""

    rating: int = Field(description="The rating the review was written for.")
    review: str = Field(description="The generated review text.")
