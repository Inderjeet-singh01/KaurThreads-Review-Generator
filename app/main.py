"""Kaur Threads Boutique — AI Review Generator.

Minimal FastAPI backend exposing one application route, POST
/generate-review, plus GET /health for health checks and cold-start wake-up.
"""

from __future__ import annotations

import time

# Taken before the heavy imports below, so the "Backend ready" log shows
# the real boot time of a cold start.
_import_started = time.monotonic()

import logging  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Header  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.ai.groq_client import (  # noqa: E402
    GroqError,
    GroqRateLimitError,
    NotBoutiqueError,
    ReviewRejectedError,
    generate_review,
)
from app.config import settings  # noqa: E402
from app.google_review import get_google_review_url  # noqa: E402
from app.idempotency import RequestDeduplicator, StillRunningError  # noqa: E402
from app.schemas import GenerateReviewRequest, GenerateReviewResponse  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# The HTTP clients log every request at INFO; keep only their warnings.
for _noisy in ("httpx", "google_genai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Customer-safe messages. Internal error text only ever goes to the logs.
BUSY_DETAIL = "The AI service is temporarily busy. Please wait a few seconds and try again."
UNAVAILABLE_DETAIL = "The AI service is temporarily unavailable. Please try again in a few seconds."
FAILED_DETAIL = "Review generation is not available right now."
INTERNAL_DETAIL = "Something went wrong while generating your review."
DEFAULT_BUSY_RETRY_AFTER = 10  # seconds, when the provider gave no wait
UNAVAILABLE_RETRY_AFTER = 3
MAX_RETRY_AFTER = 60
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

# One LLM run per click, even when the frontend retries after a timeout.
_dedupe = RequestDeduplicator()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Shows in the Render logs how long this instance took to become ready
    # after a cold start (module import + app setup).
    logger.info("Backend ready: startup took %.2fs", time.monotonic() - _import_started)
    yield


app = FastAPI(
    title="Kaur Threads Boutique — AI Review Generator",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: lets the frontend call this API from the browser. Retry-After is
# exposed so the frontend can read the suggested wait on 429/503.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

if not get_google_review_url():
    logger.warning(
        "GOOGLE_REVIEW_URL is not set. The frontend needs it so the customer "
        "can open Kaur Threads' Google review page and submit their review."
    )


@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
async def health() -> dict[str, str]:
    """Liveness check: no LLM, database or other I/O, so it answers
    instantly once the process is up."""
    return {"status": "ok"}


def _error(status: int, code: str, detail: str, *, retryable: bool, retry_after: int | None = None) -> JSONResponse:
    """Error response. ``detail`` stays a plain string (the documented
    contract); ``code``/``retryable`` tell the frontend whether to retry."""
    body: dict = {"detail": detail, "code": code, "retryable": retryable}
    headers = {}
    if retry_after is not None:
        body["retry_after"] = retry_after
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(status_code=status, content=body, headers=headers)


def _retry_after_seconds(value: float | None) -> int:
    if value is None:
        return DEFAULT_BUSY_RETRY_AFTER
    return max(1, min(MAX_RETRY_AFTER, math.ceil(value)))


@app.post("/generate-review", response_model=GenerateReviewResponse)
def generate_review_endpoint(
    payload: GenerateReviewRequest,
    idempotency_key: str | None = Header(default=None),
):
    """Generate a natural review from a 1-5 rating and optional experience."""
    request_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    key = idempotency_key if idempotency_key and _IDEMPOTENCY_KEY_RE.match(idempotency_key) else None
    # Never log the customer's text: only its size.
    logger.info(
        "Review generation request started req=%s rating=%s experience_chars=%d key=%s",
        request_id, payload.rating, len(payload.experience or ""), key[:8] if key else "-",
    )

    def failed(status: int, code: str, level: int = logging.WARNING) -> None:
        logger.log(
            level, "Review generation failed req=%s status=%d code=%s took=%.1fs",
            request_id, status, code, time.monotonic() - started,
        )

    try:
        review = _dedupe.run(
            (key, payload.rating, payload.experience) if key else None,
            lambda: generate_review(payload.rating, payload.experience, request_id=request_id),
        )
    except NotBoutiqueError as exc:
        failed(400, "not_boutique", logging.INFO)
        return _error(400, "not_boutique", str(exc), retryable=False)
    except ReviewRejectedError as exc:
        failed(409, "review_rejected")
        return _error(409, "review_rejected", str(exc), retryable=False)
    except GroqRateLimitError as exc:
        # Groq/Gemini said 429 and the backend's own short wait didn't help.
        # Not retried here: the frontend waits Retry-After before allowing
        # another click, so there is no request storm.
        wait = _retry_after_seconds(exc.retry_after)
        logger.warning("Groq rate limit reached the customer req=%s retry_after=%ds", request_id, wait)
        failed(429, "ai_busy")
        return _error(429, "ai_busy", BUSY_DETAIL, retryable=False, retry_after=wait)
    except StillRunningError:
        failed(503, "still_running")
        return _error(503, "ai_unavailable", UNAVAILABLE_DETAIL, retryable=True, retry_after=UNAVAILABLE_RETRY_AFTER)
    except GroqError as exc:
        if exc.fallback_eligible:  # timeout, network, 5xx, empty reply
            failed(503, f"ai_unavailable:{exc.reason}")
            return _error(503, "ai_unavailable", UNAVAILABLE_DETAIL, retryable=True, retry_after=UNAVAILABLE_RETRY_AFTER)
        # Missing/invalid key, bad request, unknown model: retrying won't help.
        logger.error("Review generation cannot succeed req=%s error=%s", request_id, _short(exc))
        failed(502, "ai_error", logging.ERROR)
        return _error(502, "ai_error", FAILED_DETAIL, retryable=False)
    except Exception:
        # A bug. Log the full traceback for Render's logs and answer from
        # inside the app, so the response still carries CORS headers (an
        # unhandled exception would reach the browser as a network error).
        logger.exception("Review generation crashed req=%s", request_id)
        failed(500, "internal_error", logging.ERROR)
        return _error(500, "internal_error", INTERNAL_DETAIL, retryable=False)

    logger.info(
        "Review generation completed req=%s status=200 took=%.1fs",
        request_id, time.monotonic() - started,
    )
    return GenerateReviewResponse(rating=payload.rating, review=review)


def _short(exc: BaseException) -> str:
    """One-line, length-capped error text for logs."""
    return " ".join(str(exc).split())[:200] or type(exc).__name__
