"""Kaur Threads Boutique — AI Review Generator.

Minimal FastAPI backend exposing exactly one application route:
POST /generate-review.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.ai.groq_client import (
    GroqError,
    GroqRateLimitError,
    NotBoutiqueError,
    ReviewRejectedError,
    generate_review,
)
from app.config import settings
from app.google_review import get_google_review_url
from app.schemas import GenerateReviewRequest, GenerateReviewResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# The HTTP clients log every request at INFO; keep only their warnings.
for _noisy in ("httpx", "google_genai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Kaur Threads Boutique — AI Review Generator",
    version="1.0.0",
)

# CORS: ready for a future frontend to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not get_google_review_url():
    logger.warning(
        "GOOGLE_REVIEW_URL is not set. The frontend needs it so the customer "
        "can open Kaur Threads' Google review page and submit their review."
    )


@app.post("/generate-review", response_model=GenerateReviewResponse)
def generate_review_endpoint(
    payload: GenerateReviewRequest,
) -> GenerateReviewResponse:
    """Generate a natural review from a 1-5 rating and optional experience."""
    try:
        review = generate_review(payload.rating, payload.experience)
    except NotBoutiqueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReviewRejectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GroqRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GroqError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return GenerateReviewResponse(rating=payload.rating, review=review)
