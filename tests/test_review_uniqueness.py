"""Offline tests for duplicate prevention in review generation (Groq mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai import groq_client
from app.ai.review_history import (
    ReviewHistory,
    count_sentences,
    format_problems,
    history,
    input_key,
    normalize,
    promotional_phrases,
    sentiment_problem,
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
    assert "started with 'loved'" in h.repeated_edges(key, "Loved browsing the racks. Quality was nice.")
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
    assert "rejected as too similar to a previous review" in fake.prompts[1]
    assert "substantially different structure and wording" in fake.prompts[1]


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

    attempts = groq_client.MAX_ATTEMPTS
    fake = use_fake(monkeypatch, [A] * attempts)
    with pytest.raises(groq_client.GroqError):
        groq_client.generate_review(5, EXPERIENCE)
    assert len(fake.prompts) == attempts
    rescues = len(groq_client.RESCUE_INSTRUCTIONS)
    assert all("different voice" in p for p in fake.prompts[-rescues:])
    assert not any("different voice" in p for p in fake.prompts[:-rescues])


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


def test_reused_sentence_is_rejected_even_when_review_differs():
    h = ReviewHistory()
    key = input_key(5, EXPERIENCE)
    h.add_if_unique(
        key,
        "When I first came in, it caught my eye. The collection felt fresh and "
        "the quality was clearly well made. It left a strong impression.",
    )
    candidate = (
        "My reaction was pure delight. The collection felt fresh and the quality "
        "was clearly solid. Walked away truly satisfied."
    )
    assert h.too_similar(candidate) is None  # whole-review check alone misses it
    assert "sentence" in h.reused_sentence(key, candidate)
    assert h.reused_sentence(key, B) is None


def test_similar_inputs_share_history():
    h = ReviewHistory()
    h.add_if_unique(input_key(5, EXPERIENCE), A)
    assert h.recent_for(input_key(5, "Nice quality and a good collection!"), 5) == [A]
    assert h.recent_for(input_key(4, "good collection, nice quality"), 5) == [A]
    assert h.recent_for(input_key(5, "Staff helped me choose a design"), 5) == []
    assert h.recent_for(input_key(5, None), 5) == []


def test_templated_closing_sentence_is_flagged():
    h = ReviewHistory()
    key = input_key(5, EXPERIENCE)
    h.add_if_unique(key, "Such a nice collection. I left feeling completely satisfied.")
    assert "closing sentence" in h.repeated_edges(
        key, "Quality was lovely here. I walked out feeling truly satisfied."
    )


def test_invented_shop_details_are_ungrounded():
    assert ungrounded_topics("Checked out the new arrivals. Quality was solid.", EXPERIENCE) == [
        "shop details"
    ]
    assert ungrounded_topics("When I walked in, the display caught my eye.", EXPERIENCE) == [
        "shop details"
    ]
    assert ungrounded_topics("You can see the care put into each piece.", EXPERIENCE) == [
        "craftsmanship"
    ]
    assert ungrounded_topics("A wide range to choose from.", EXPERIENCE) == ["large selection"]
    assert ungrounded_topics("A wide range to choose from.", "lots of variety") == []
    assert ungrounded_topics("Their stylists were kind.", "staff helped") == []


def test_promotional_phrases():
    assert promotional_phrases("Top-notch quality. Worth a must visit!", EXPERIENCE) == [
        "must visit",
        "a must",
        "top notch",
    ]
    assert promotional_phrases("Best boutique in town, honestly.", "best boutique ever") == []


def test_sentiment_must_match_rating():
    assert sentiment_problem("Loved the collection, it was amazing.", 3, "collection was okay")
    assert sentiment_problem("Wasn't impressed with the fitting at all.", 2, "fitting was bad") is None
    assert sentiment_problem("It was disappointing.", 5, EXPERIENCE)
    assert sentiment_problem("The quality didn't disappoint.", 5, EXPERIENCE) is None
    assert sentiment_problem("The delivery was slow.", 4, "delivery took long") is None


def test_format_rejects_preamble_and_long_sentences():
    assert format_problems("Here is your review: Nice collection. Good quality.")
    assert format_problems("- Nice collection.\n- Good quality.")
    assert format_problems(("word " * 35).strip() + ". Short one.")
    assert format_problems(A) == []


def test_rejected_invented_text_is_not_shown_back(monkeypatch):
    invented = "The staff were lovely. Quality was nice too."
    fake = use_fake(monkeypatch, [invented, C])
    assert groq_client.generate_review(5, EXPERIENCE) == C
    assert invented not in fake.prompts[1]
    assert "which the customer did not mention" in fake.prompts[1]
