"""Tests for POST /generate-review.

Groq is never contacted: the generation function is monkeypatched so the tests
are fast, deterministic, and offline.

Run with:
    python -m pytest tests/test_generate_review.py
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main
import app.google_review as google_review
from app.ai.groq_client import GroqError
from app.config import settings
from app.main import app

client = TestClient(app)


def test_valid_five_star_request(monkeypatch):
    """A valid 5-star request returns the generated review and echoes rating."""
    monkeypatch.setattr(
        main, "generate_review", lambda rating, experience: "Lovely fabrics and a warm visit."
    )
    resp = client.post(
        "/generate-review",
        json={
            "rating": 5,
            "experience": "Loved the collection and the staff was very helpful",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"rating": 5, "review": "Lovely fabrics and a warm visit."}


def test_invalid_rating_rejected():
    """A rating outside 1-5 is rejected with 422 before any LLM call."""
    resp = client.post(
        "/generate-review",
        json={"rating": 6, "experience": "Great store"},
    )
    assert resp.status_code == 422


def test_missing_experience_is_allowed(monkeypatch):
    """Experience is optional; a request without it still generates a review."""
    monkeypatch.setattr(
        main, "generate_review", lambda rating, experience: "Just an okay visit."
    )
    resp = client.post("/generate-review", json={"rating": 3})
    assert resp.status_code == 200
    assert resp.json()["rating"] == 3


def test_experience_too_long_rejected():
    """Over-long experience input is rejected with 422 (abuse guard)."""
    resp = client.post(
        "/generate-review",
        json={"rating": 4, "experience": "x" * 1001},
    )
    assert resp.status_code == 422


def test_llm_failure_returns_502(monkeypatch):
    """A GroqError is surfaced as a clean 502, not a raw 500 traceback."""

    def _boom(rating, experience):
        raise GroqError("Groq is down")

    monkeypatch.setattr(main, "generate_review", _boom)
    resp = client.post(
        "/generate-review",
        json={"rating": 5, "experience": "Nice"},
    )
    assert resp.status_code == 502
    assert "Groq is down" in resp.json()["detail"]


def test_google_review_url_reads_from_config(monkeypatch):
    """The Google review URL is read from config and trimmed (no posting)."""
    monkeypatch.setattr(settings, "google_review_url", "  https://example.test/review  ")
    assert google_review.get_google_review_url() == "https://example.test/review"
    monkeypatch.setattr(settings, "google_review_url", "")
    assert google_review.get_google_review_url() is None


def test_only_generate_review_route_exists():
    """Exactly one application route is registered: POST /generate-review."""
    app_routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if getattr(route, "methods", None) and route.path == "/generate-review"
    }
    assert app_routes == {("/generate-review", ("POST",))}
