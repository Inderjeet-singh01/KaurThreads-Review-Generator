"""Offline tests for duplicate prevention in review generation (Groq mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai import groq_client
from app.ai.review_history import (
    ReviewHistory,
    count_sentences,
    history,
    input_key,
    normalize,
    ungrounded_topics,
)
from app.main import app

EXPERIENCE = "Good collection and nice quality"
A = "Loved browsing the collection here. The quality felt really nice as well."
B = "Such a lovely collection to look through! I was pleased with how good the quality was."
C = "Nice quality across everything I saw. Browsing the collection was a pleasure."


class FakeGroq:
    """Returns queued replies and records every prompt it receives."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *, messages, **_):
        self.prompts.append(messages[-1]["content"])
        text = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    history.clear()
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "test-key")
    yield
    history.clear()


def use_fake(monkeypatch, replies) -> FakeGroq:
    fake = FakeGroq(replies)
    monkeypatch.setattr(groq_client, "Groq", lambda **_: fake)
    return fake


def test_normalize():
    assert normalize("  Loved it!!  The   QUALITY, too. ") == "loved it the quality too"


def test_near_duplicates_are_rejected():
    h = ReviewHistory()
    key = input_key(5, EXPERIENCE)
    assert h.add_if_unique(key, A)
    assert h.too_similar(A) == "it was identical to a previous review"
    assert h.too_similar(A.upper().replace(".", "!")) is not None  # same after normalizing
    assert h.too_similar(A.replace("really ", "")) is not None  # near-duplicate
    assert h.too_similar(B) is None
    assert not h.add_if_unique(key, A)


def test_repeated_opening_is_flagged():
    h = ReviewHistory()
    key = input_key(5, EXPERIENCE)
    h.add_if_unique(key, A)
    assert "opening" in h.repeated_edges(key, "Loved browsing the racks. Quality was nice.")
    assert h.repeated_edges(key, B) is None


def test_ungrounded_topics():
    assert ungrounded_topics("The staff were kind and the fabric was soft.", EXPERIENCE) == [
        "staff",
        "fabric",
    ]
    assert ungrounded_topics("I would recommend it.", EXPERIENCE) == ["recommendation"]
    assert ungrounded_topics("The staff were kind.", "staff was helpful") == []
    assert ungrounded_topics("It suited what I was looking for.", EXPERIENCE) == []


def test_count_sentences():
    assert count_sentences(A) == 2
    assert count_sentences("One line only.") == 1


def test_duplicate_is_regenerated_with_previous_reviews_in_prompt(monkeypatch):
    fake = use_fake(monkeypatch, [A])
    assert groq_client.generate_review(5, EXPERIENCE) == A

    fake = use_fake(monkeypatch, [A, B])
    assert groq_client.generate_review(5, EXPERIENCE) == B
    assert "PREVIOUS_REVIEWS" in fake.prompts[0] and A in fake.prompts[0]
    assert "substantially different from every review" in fake.prompts[0]
    assert "rejected because it was identical" in fake.prompts[1]


def test_invalid_candidates_are_retried(monkeypatch):
    use_fake(
        monkeypatch,
        [
            "Too short.",  # 1 sentence
            "The staff were lovely. Quality was nice too.",  # invented staff
            C,
        ],
    )
    assert groq_client.generate_review(5, EXPERIENCE) == C


def test_never_returns_a_duplicate(monkeypatch):
    use_fake(monkeypatch, [A])
    groq_client.generate_review(5, EXPERIENCE)

    attempts = groq_client.NORMAL_ATTEMPTS + len(groq_client.RESCUE_INSTRUCTIONS)
    fake = use_fake(monkeypatch, [A] * attempts)
    with pytest.raises(groq_client.GroqError):
        groq_client.generate_review(5, EXPERIENCE)
    assert len(fake.prompts) == attempts
    assert any("different voice" in p for p in fake.prompts[groq_client.NORMAL_ATTEMPTS:])


def test_api_contract_unchanged(monkeypatch):
    use_fake(monkeypatch, [A])
    res = TestClient(app).post("/generate-review", json={"rating": 5, "experience": EXPERIENCE})
    assert res.status_code == 200
    assert res.json() == {"rating": 5, "review": A}


def test_new_grounding_topics_and_no_false_positives():
    assert ungrounded_topics("I'll definitely be back.", EXPERIENCE) == ["return visit"]
    assert ungrounded_topics("Happy with my purchase.", EXPERIENCE) == ["purchase"]
    assert ungrounded_topics("Every piece I tried was nice.", EXPERIENCE) == ["trying on"]
    assert ungrounded_topics("The boutique offers a lovely collection.", EXPERIENCE) == []
    assert ungrounded_topics("I won't return.", "bad quality, will not return") == []


def test_common_starter_not_repeated_back_to_back():
    h = ReviewHistory()
    key = input_key(5, EXPERIENCE)
    h.add_if_unique(key, "The collection was lovely. Quality felt nice.")
    assert "started with 'the'" in h.repeated_edges(key, "The quality stood out. Loved the range.")
    assert h.repeated_edges(key, "Loved the range here. Quality stood out too.") is None
