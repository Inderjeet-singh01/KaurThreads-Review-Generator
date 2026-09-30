"""POST /generate-review: one Groq call per request, grounded boutique
reviews, rating-true tone, variable length and uniqueness."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

from app.ai import groq_client, review_rules
from app.ai.review_history import ReviewHistory, input_key
from app.main import app

client = TestClient(app)


class FakeGroq:
    """Stands in for the Groq SDK client and records every call."""

    calls: list[dict] = []
    replies: list = []
    last = None

    def __init__(self, **kwargs):
        assert kwargs.get("max_retries") == 0  # the SDK must not retry either
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        FakeGroq.calls.append(kwargs)
        # Out of scripted replies: the model writes the same thing again.
        reply = FakeGroq.last = FakeGroq.replies.pop(0) if FakeGroq.replies else FakeGroq.last
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


class FakeGemini:
    """Stands in for google.genai.Client and records every call."""

    calls: list[dict] = []
    replies: list = []
    client_kwargs: dict = {}

    def __init__(self, **kwargs):
        FakeGemini.client_kwargs = kwargs
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        FakeGemini.calls.append(kwargs)
        reply = FakeGemini.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


@pytest.fixture(autouse=True)
def fake_groq(monkeypatch):
    FakeGroq.calls = []
    FakeGroq.replies = []
    FakeGroq.last = None
    FakeGemini.calls = []
    FakeGemini.replies = []
    monkeypatch.setattr(groq_client, "Groq", FakeGroq)
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "test-key")
    # Gemini is never reached for real; the fallback is off unless a test
    # turns it on with the `gemini` fixture.
    monkeypatch.setattr(groq_client.genai, "Client", FakeGemini)
    monkeypatch.setattr(groq_client.settings, "gemini_api_key", "")
    monkeypatch.setattr(groq_client, "history", ReviewHistory(":memory:"))
    return FakeGroq


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(groq_client.settings, "gemini_api_key", "test-gemini-key")
    return FakeGemini


def _post(rating=5, experience="Good collection and nice quality."):
    return client.post("/generate-review", json={"rating": rating, "experience": experience})


def _generate(fake, rating, experience, reply):
    fake.replies = [reply]
    response = _post(rating, experience)
    # One call when a version passes, one fresh retry when none does.
    assert len(fake.calls) == (groq_client.MAX_PROVIDER_CALLS if response.status_code == 409 else 1)
    return response


def _finalize(text, rating, experience):
    return groq_client.finalize_review(text, rating, experience, max_words=120)


def _groq_response(status):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return httpx.Response(status, request=request)


# --- API contract and one-call behaviour ------------------------------------


def test_api_contract_unchanged(fake_groq):
    response = _generate(fake_groq, 5, "Good collection and nice quality.", "Liked the collection. Quality was nice too. That's about it.")
    assert response.status_code == 200
    assert response.json() == {"rating": 5, "review": "Liked the collection. Quality was nice too. That's about it."}


def test_each_generation_makes_exactly_one_call(fake_groq):
    replies = [
        "Liked the collection. Quality was nice too. That's about it.",
        "Pretty good quality, and there was a decent collection to look through. Happy with it. Just sharing my experience.",
        "Nice collection here and the quality seemed good to me. It was fine. Nothing else to add really.",
    ]
    for expected_calls, reply in enumerate(replies, start=1):
        fake_groq.replies = [reply]
        assert _post().status_code == 200
        assert len(fake_groq.calls) == expected_calls


def test_rejected_review_gets_one_fresh_retry_then_a_controlled_error(fake_groq):
    # Only invented content, twice: 409 after exactly two calls.
    response = _generate(fake_groq, 5, "Good collection.", "The staff was helpful and prices were low.")
    assert response.status_code == 409
    assert len(fake_groq.calls) == 2


def test_retry_after_failed_checks_returns_the_fresh_review(fake_groq, gemini):
    fake_groq.replies = [V_INVENTED, V_GOOD]
    response = _post(5, "Good collection and nice quality.")
    assert response.json()["review"] == V_GOOD
    assert len(fake_groq.calls) == 2 and gemini.calls == []  # retry is Groq, never Gemini
    # the retry gets its own style notes, and the prompt otherwise matches
    assert fake_groq.calls[1]["messages"][0] == fake_groq.calls[0]["messages"][0]


def test_retry_that_hits_a_groq_outage_is_still_a_rejection(fake_groq, gemini):
    fake_groq.replies = [V_INVENTED, RateLimitError("rate limited", response=_groq_response(429), body=None)]
    assert _post(5, "Good collection and nice quality.").status_code == 409
    assert len(fake_groq.calls) == 2 and gemini.calls == []  # never a third call


def test_gemini_fallback_that_fails_checks_is_not_retried(fake_groq, gemini):
    groq_429 = RateLimitError("rate limited", response=_groq_response(429), body=None)
    assert _fallback(fake_groq, gemini, groq_429, V_INVENTED).status_code == 409
    assert len(fake_groq.calls) == 1 and len(gemini.calls) == 1  # two calls used up


def test_rate_limit_is_returned_not_retried(fake_groq):
    response = _generate(fake_groq, 5, "Nice.", RateLimitError("rate limited", response=_groq_response(429), body=None))
    assert response.status_code == 429


@pytest.mark.parametrize(
    "failure",
    [APITimeoutError(request=httpx.Request("POST", "https://api.groq.com")), RuntimeError("boom"), ""],
)
def test_other_failures_are_returned_not_retried(fake_groq, failure):
    assert _generate(fake_groq, 5, "Nice.", failure).status_code == 502


def test_missing_key_makes_no_call(fake_groq, monkeypatch):
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "")
    assert _post().status_code == 502
    assert fake_groq.calls == []


def test_model_settings_and_prompt(fake_groq):
    _generate(fake_groq, 4, "Staff helped me choose the design.", "The staff was helpful while I was choosing the design. Liked the options. Happy with it.")
    call = fake_groq.calls[0]
    assert call["model"] == groq_client.settings.groq_model
    assert 0.8 <= call["temperature"] <= 0.9
    assert call["reasoning_effort"] == "low"
    assert call["max_tokens"] <= 1000
    prompt = call["messages"][1]["content"]
    assert "Star rating: 4 out of 5" in prompt
    assert "<<<\nStaff helped me choose the design.\n>>>" in prompt
    assert "fashion boutique" in call["messages"][0]["content"]


# --- Boutique domain ---------------------------------------------------------


@pytest.mark.parametrize("experience", ["Pizza was excellent", "The dentist was helpful", "The hotel room was clean"])
def test_off_domain_input_is_rejected_without_a_call(fake_groq, experience):
    assert _post(5, experience).status_code == 400
    assert fake_groq.calls == []


@pytest.mark.parametrize(
    "experience",
    [
        "Loved the lehenga.",
        "The blouse fitting needed another alteration.",
        "The staff helped me choose a design.",
        "Good collection but not much variety.",
        "The stitching was neat.",
        "Staff was rude",
        None,
    ],
)
def test_boutique_and_vague_inputs_are_accepted(experience):
    assert review_rules.is_boutique_input(experience)


def test_model_can_flag_off_domain_input_in_its_one_call(fake_groq):
    assert _generate(fake_groq, 5, "The yoga class was relaxing.", "NOT_BOUTIQUE").status_code == 400


# --- Product / service / grounding ------------------------------------------


def test_product_experience(fake_groq):
    reply = "Really liked the quality of the suit. Happy with it. That's about it."
    response = _generate(fake_groq, 5, "Loved the suit quality.", reply)
    assert response.json()["review"] == reply


def test_service_experience(fake_groq):
    reply = "Got the fitting sorted here. It came out much better than before. That's about it."
    response = _generate(fake_groq, 4, "The fitting was fixed and came out much better.", reply)
    assert response.json()["review"] == reply


def test_product_and_service_are_both_kept(fake_groq):
    experience = "Loved the blouse and the fitting was much better after the alteration."
    reply = "Loved the blouse. The fitting was much better once the alteration was done. Happy with it."
    assert _generate(fake_groq, 5, experience, reply).json()["review"] == reply

    fake_groq.calls = []  # a version covering every point beats one that drops the service point
    partial = "The blouse was really pretty. Happy with it. That's about it."
    full = "Really liked my blouse. The fitting came out much better after the alteration. Glad I went."
    assert _generate(fake_groq, 5, experience, json.dumps({"reviews": [partial, full]})).json()["review"] == full


@pytest.mark.parametrize(
    "general",
    [
        "The staff was really helpful.",
        "They did the tailoring quickly.",
        "Delivery was on time.",
        "The embroidery was lovely.",
        "The fabric felt soft.",
        "There was a nice variety too.",
        "It was exactly what I was looking for.",
        "Will check back soon for more.",
    ],
)
def test_general_boutique_comments_are_kept(general):
    base = "The collection was really good. Liked a lot of it. That's about it."
    assert _finalize(f"{base} {general}", 5, "Good collection.") == (f"{base} {general}", None)


@pytest.mark.parametrize(
    "invented",
    [
        "Prices were reasonable too.",
        "They stock good brands.",
        "Paid by card, easy.",
        "The silk felt soft.",
        "The red one was lovely.",
        "It was ready in 2 days.",
    ],
)
def test_hard_facts_are_removed(fake_groq, invented):
    base = "The collection was really good. Liked a lot of it. That's about it."
    response = _generate(fake_groq, 5, "Good collection.", f"{base} {invented}")
    assert response.json()["review"] == base


def test_garment_cannot_be_swapped_but_fitting_can_be_reworded():
    review, problem = _finalize(
        "The blouse fitting was good. The adjustment came out well. Happy with it. The lehenga looked great too.",
        5, "The blouse fitting was good.",
    )
    assert problem is None  # an unnamed garment is made generic instead of dropped
    assert review == "The blouse fitting was good. The adjustment came out well. Happy with it. The outfit looked great too."


def test_no_experience_allows_general_comments_but_no_hard_facts():
    assert review_rules.invented_facts("Nice collection and helpful staff.", None) == []
    assert review_rules.invented_facts("Loved the silk lehenga for 5000.", None) == ["lehenga", "silk", "a number"]


# --- Rating ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rating", "experience", "review", "ok"),
    [
        (1, "Very disappointed with the alteration.", "Really disappointed with how the alteration came out. Not what I hoped for. That's about it.", True),
        (1, "Very disappointed with the alteration.", "The alteration was good and it looked nice on me.", False),
        (2, "The fitting was not great.", "The fitting wasn't great. I wasn't happy with it. That's about it.", True),
        (2, "The fitting was not great.", "Loved the fitting, it was great to see.", False),
        (3, "The fitting was okay.", "The fitting was okay. Nothing more than that really. Just sharing my experience.", True),
        (3, "The fitting was okay.", "The fitting was perfect and I was happy with it.", False),
        (4, "The fitting was okay.", "The fitting was amazing, I was so happy with it.", False),
        (4, "Good fitting.", "The fitting was good. Pretty happy with it overall. That's about it.", True),
        (5, "The fitting was good.", "Really happy with the fitting. It came out great. That's about it.", True),
        (5, "The fitting was good.", "Terrible fitting, would not go there for it.", False),
    ],
)
def test_tone_matches_rating_and_customer_words(rating, experience, review, ok):
    result, problem = _finalize(review, rating, experience)
    assert (problem is None and result == review) is ok


# --- Length -----------------------------------------------------------------


def test_length_varies_but_short_input_is_never_padded():
    long_input = (
        "Got my lehenga stitched here for my sister's wedding. The fitting was a bit loose "
        "at first, so they did an alteration and after that it was fine. The staff was "
        "patient and the embroidery on the blouse came out neat."
    )
    long_lengths = {groq_client.plan_review(long_input).length for _ in range(60)}
    assert len(long_lengths) >= 3
    assert {groq_client.plan_review("Good quality.").length for _ in range(30)} == {"brief"}
    assert "detailed" not in {groq_client.plan_review("Nice suit, good fitting.").length for _ in range(30)}


def test_back_to_back_plans_differ():
    plans = [groq_client.plan_review("Loved the blouse and the fitting was much better after the alteration.") for _ in range(20)]
    for a, b in zip(plans, plans[1:]):
        assert a.length != b.length and a.opening != b.opening and a.voice != b.voice


def test_prompt_carries_the_word_band(fake_groq):
    plan = groq_client.plan_review("Good quality.")
    prompt = groq_client.build_user_prompt(5, "Good quality.", plan)
    assert "at least 3 sentences, about 18-30 words" in prompt


def test_long_reviews_are_not_cut_to_a_fixed_sentence_count(fake_groq):
    experience = (
        "Got my lehenga stitched here for my sister's wedding. The fitting was a bit loose "
        "at first, so they did an alteration and after that it was fine. The staff was "
        "patient and the embroidery on the blouse came out neat."
    )
    reply = (
        "Got my lehenga stitched here for my sister's wedding. The fitting was a bit loose at first. "
        "They did an alteration and after that it sat fine. Staff was patient with me the whole time. "
        "The embroidery on the blouse came out neat, which I liked. Glad it worked out in the end."
    )
    response = _generate(fake_groq, 4, experience, reply)
    assert response.json()["review"] == reply
    assert len(review_rules.split_sentences(reply)) == 6


def test_review_has_at_least_three_sentences(fake_groq):
    assert _generate(fake_groq, 5, "Good collection.", "Liked the collection. It was good.").status_code == 409
    # Trimming an overlong review never takes it below three sentences.
    review, problem = groq_client.finalize_review(
        "Liked the collection. It was good. That's about it. Just sharing my experience.",
        5, "Good collection.", max_words=5,
    )
    assert len(review_rules.split_sentences(review)) == 3
    assert problem is not None  # still too long, so it is rejected rather than cut short


# --- Uniqueness -------------------------------------------------------------


def test_duplicate_is_rejected_with_one_call_each(fake_groq):
    reply = "Liked the collection. Quality was nice too. That's about it."
    fake_groq.replies = [reply, reply]
    assert _post().status_code == 200
    assert _post().status_code == 409
    assert len(fake_groq.calls) == 3  # 1, then a duplicate and its one retry


@pytest.mark.parametrize(
    "second",
    [
        "Liked the collection. The quality was nice too. That's about it.",  # near duplicate
        "Quality was nice too. That's about it. Liked the collection.",  # same sentences reordered
        "Pretty decent overall. The quality was good. That's about it.",  # same closing
        "Liked the collection a lot. The quality was good. Happy with it.",  # same opening
    ],
)
def test_near_duplicates_and_reused_edges_are_rejected(fake_groq, second):
    fake_groq.replies = ["Liked the collection. Quality was nice too. That's about it.", second]
    assert _post().status_code == 200
    assert _post().status_code == 409


def test_distinct_review_is_accepted_and_prompt_avoids_recent_edges(fake_groq):
    fake_groq.replies = [
        "Liked the collection. Quality was nice too. That's about it.",
        "Pretty good quality, and there was a decent collection to look through. Happy with it. Just sharing my experience.",
    ]
    assert _post().status_code == 200
    assert _post().status_code == 200
    prompt = fake_groq.calls[1]["messages"][1]["content"]
    assert "Don't start with: 'liked the collection'" in prompt
    assert "Liked the collection. Quality was nice too. That's about it." not in prompt  # no full reviews sent


def test_reused_sentence_is_rejected_across_inputs():
    history = ReviewHistory(":memory:")
    assert history.add_if_unique(input_key(5, "Loved the lehenga."), "Loved the lehenga. Really happy with how everything turned out.") is None
    assert history.add_if_unique(input_key(4, "Good fitting."), "Fitting was good. Really happy with how everything turned out.") is not None


def test_history_survives_restart(tmp_path):
    path = str(tmp_path / "history.sqlite3")
    key = input_key(5, "Good collection.")
    assert ReviewHistory(path).add_if_unique(key, "Liked the collection a lot here.") is None
    assert ReviewHistory(path).add_if_unique(key, "Liked the collection a lot here.") is not None


# --- Naturalness ------------------------------------------------------------


@pytest.mark.parametrize(
    "review",
    [
        "Really liked the quality. The fitting was pretty good too. That's about it.",
        "Quality was quite nice. Happy with the fitting as well. Just sharing my experience.",
        "Good experience overall. Liked the quality and the fitting wasn't bad either. That's about it.",
        "The fitting was better than I thought. The quality was good. That's about it.",
    ],
)
def test_normal_conversational_wording_is_kept(review):
    assert _finalize(review, 4, "Good quality, happy with the fitting.") == (review, None)


@pytest.mark.parametrize("phrase", ["Highly recommend it.", "A hidden gem.", "It exceeded my expectations."])
def test_promotional_phrases_are_removed(phrase):
    review, problem = _finalize(f"Liked the collection. It was good. That's about it. {phrase}", 5, "Good collection.")
    assert problem is None and review == "Liked the collection. It was good. That's about it."


def test_clean_review_is_local_and_plain():
    raw = 'Here\'s your review: "Honestly, got my blouse stitched — fitting was good; happy 😊 #boutique\n\nWould go again'
    assert groq_client.clean_review(raw) == "Got my blouse stitched, fitting was good, happy. Would go again."
    assert groq_client.clean_review("Rated it 4.5 in my head. Nice.") == "Rated it 4.5 in my head. Nice."


# --- Gemini fallback -----------------------------------------------------------

GOOD_REPLY = "Liked the collection. Quality was nice too. That's about it."
GEMINI_REPLY = "Nice collection to look through. The quality was good as well. Happy with my visit."


def _fallback(fake_groq, gemini, groq_reply, gemini_reply=GEMINI_REPLY, rating=5, experience="Good collection and nice quality."):
    fake_groq.replies = [groq_reply]
    gemini.replies = [gemini_reply]
    return _post(rating, experience)


def test_groq_success_never_calls_gemini(fake_groq, gemini):
    response = _fallback(fake_groq, gemini, GOOD_REPLY)
    assert response.json()["review"] == GOOD_REPLY
    assert len(fake_groq.calls) == 1 and gemini.calls == []


@pytest.mark.parametrize(
    "groq_failure",
    [
        RateLimitError("rate limited", response=_groq_response(429), body=None),
        APITimeoutError(request=httpx.Request("POST", "https://api.groq.com")),
        APIConnectionError(request=httpx.Request("POST", "https://api.groq.com")),
        InternalServerError("server error", response=_groq_response(500), body=None),
        InternalServerError("unavailable", response=_groq_response(503), body=None),
        "",  # empty completion
    ],
    ids=["429", "timeout", "connection", "500", "503", "empty"],
)
def test_transient_groq_failure_falls_back_to_gemini_once(fake_groq, gemini, groq_failure):
    response = _fallback(fake_groq, gemini, groq_failure)
    assert response.status_code == 200
    assert response.json() == {"rating": 5, "review": GEMINI_REPLY}  # response shape unchanged
    assert len(fake_groq.calls) == 1 and len(gemini.calls) == 1  # never more than two calls


@pytest.mark.parametrize(
    "groq_failure",
    [
        AuthenticationError("invalid api key", response=_groq_response(401), body=None),
        BadRequestError("malformed request", response=_groq_response(400), body=None),
        NotFoundError("unknown model", response=_groq_response(404), body=None),
        RuntimeError("bug in our code"),
    ],
    ids=["401", "400", "404", "bug"],
)
def test_permanent_groq_failure_does_not_call_gemini(fake_groq, gemini, groq_failure):
    assert _fallback(fake_groq, gemini, groq_failure).status_code == 502
    assert gemini.calls == []


def test_missing_groq_key_does_not_call_gemini(fake_groq, gemini, monkeypatch):
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "")
    assert _post().status_code == 502
    assert fake_groq.calls == [] and gemini.calls == []


@pytest.mark.parametrize(
    ("gemini_failure", "status"),
    [
        (genai_errors.ServerError(503, {"error": {"message": "unavailable"}}), 502),
        (genai_errors.ClientError(429, {"error": {"message": "quota"}}), 429),
        (TimeoutError("read timed out"), 502),
        ("", 502),
    ],
    ids=["503", "429", "timeout", "empty"],
)
def test_gemini_failure_is_a_controlled_error(fake_groq, gemini, gemini_failure, status):
    groq_429 = RateLimitError("rate limited", response=_groq_response(429), body=None)
    assert _fallback(fake_groq, gemini, groq_429, gemini_failure).status_code == status
    assert len(fake_groq.calls) == 1 and len(gemini.calls) == 1  # Groq is not tried again


def test_gemini_uses_the_same_prompts_and_one_low_effort_attempt(fake_groq, gemini):
    _fallback(fake_groq, gemini, RateLimitError("rate limited", response=_groq_response(429), body=None))
    groq_messages = fake_groq.calls[0]["messages"]
    call = gemini.calls[0]
    assert call["model"] == groq_client.settings.gemini_model
    assert call["config"].system_instruction == groq_messages[0]["content"]
    assert call["contents"] == groq_messages[1]["content"]
    assert call["config"].thinking_config.thinking_level == genai_types.ThinkingLevel.LOW
    assert call["config"].tools is None
    assert gemini.client_kwargs["http_options"].retry_options.attempts == 1


def test_gemini_review_goes_through_the_same_validators(fake_groq, gemini):
    groq_429 = RateLimitError("rate limited", response=_groq_response(429), body=None)
    base = "The collection was really good. Liked a lot of it. That's about it."
    response = _fallback(fake_groq, gemini, groq_429, f"{base} Prices were reasonable too.", experience="Good collection.")
    assert response.json()["review"] == base  # invented price sentence removed

    fake_groq.calls, gemini.calls = [], []  # rating consistency still applies
    response = _fallback(fake_groq, gemini, groq_429, "The alteration was lovely. It looked great. So happy with it.",
                         rating=1, experience="Very disappointed with the alteration.")
    assert response.status_code == 409
    assert len(fake_groq.calls) == 1 and len(gemini.calls) == 1

    fake_groq.calls, gemini.calls = [], []  # the model's off-domain flag still applies
    assert _fallback(fake_groq, gemini, groq_429, "NOT_BOUTIQUE", experience="The yoga class was relaxing.").status_code == 400


def test_gemini_cannot_return_a_duplicate_of_an_accepted_review(fake_groq, gemini):
    assert _fallback(fake_groq, gemini, GOOD_REPLY).status_code == 200
    groq_timeout = APITimeoutError(request=httpx.Request("POST", "https://api.groq.com"))
    assert _fallback(fake_groq, gemini, groq_timeout, GOOD_REPLY).status_code == 409


# --- Several versions per call ---------------------------------------------------

V_INVENTED = "The collection was really good. Prices were fair. They stock nice brands."
V_GOOD = "Nice collection here. Quality was good as well. Happy with my visit."


def test_first_version_that_passes_is_returned(fake_groq):
    reply = f"{V_INVENTED}\n###\n{V_GOOD}\n###\nLiked the collection. Quality was nice. That's about it."
    response = _generate(fake_groq, 5, "Good collection and nice quality.", reply)
    assert response.json()["review"] == V_GOOD


def test_versions_are_split_cleanly():
    raw = "Version 1: First one here. Two. Three.\n###\n\n2. Second one. Two. Three.\n ### \nThird. Two. Three.\n###\nFourth."
    assert groq_client.split_candidates(raw) == ["First one here. Two. Three.", "Second one. Two. Three.", "Third. Two. Three."]
    assert groq_client.split_candidates("Just one review. Two. Three.") == ["Just one review. Two. Three."]


def test_duplicate_version_is_skipped_for_a_fresh_one(fake_groq):
    assert _generate(fake_groq, 5, "Good collection and nice quality.", GOOD_REPLY).status_code == 200
    fake_groq.calls = []
    response = _generate(fake_groq, 5, "Good collection and nice quality.", f"{GOOD_REPLY}\n###\n{V_GOOD}")
    assert response.json()["review"] == V_GOOD


def test_prompt_asks_for_several_versions(fake_groq):
    _generate(fake_groq, 5, "Good collection.", V_GOOD)
    assert f"Write {groq_client.CANDIDATES} different versions" in fake_groq.calls[0]["messages"][1]["content"]



def test_failed_checks_never_go_to_gemini(fake_groq, gemini):
    response = _fallback(fake_groq, gemini, V_INVENTED, V_GOOD)
    assert response.status_code == 409
    assert len(fake_groq.calls) == 2 and gemini.calls == []


def test_version_missing_a_point_is_used_when_it_is_the_only_one_left(fake_groq):
    experience = "Loved the blouse and the fitting was much better after the alteration."
    partial = "The blouse was really pretty. Happy with it. That's about it."
    assert _generate(fake_groq, 5, experience, json.dumps({"reviews": [V_INVENTED, partial]})).json()["review"] == partial



def test_off_topic_flag_does_not_use_the_second_chance(fake_groq, gemini):
    assert _fallback(fake_groq, gemini, "NOT_BOUTIQUE", V_GOOD, experience="The yoga class was relaxing.").status_code == 400
    assert gemini.calls == []


def test_json_versions_are_parsed_and_both_providers_require_json(fake_groq, gemini):
    reply = json.dumps({"reviews": [V_INVENTED, V_GOOD, GOOD_REPLY]})
    assert _generate(fake_groq, 5, "Good collection and nice quality.", reply).json()["review"] == V_GOOD
    assert fake_groq.calls[0]["response_format"]["json_schema"]["strict"] is True

    fake_groq.calls = []
    _fallback(fake_groq, gemini, RateLimitError("rate limited", response=_groq_response(429), body=None), json.dumps({"reviews": [GOOD_REPLY]}))
    assert gemini.calls[0]["config"].response_mime_type == "application/json"
    assert gemini.calls[0]["config"].response_json_schema == groq_client.REVIEWS_SCHEMA


def test_cut_off_json_keeps_its_complete_versions():
    raw = '{"reviews": ["First one. Two. Three.", "Second \\"quoted\\" one. Two. Three.", "Third one that got cu'
    assert groq_client.split_candidates(raw) == ["First one. Two. Three.", 'Second "quoted" one. Two. Three.']


def test_versions_run_together_are_rejected_not_returned():
    merged = ("Nice! The quality was nice, which was reassuring. I left satisfied. Great! I was impressed by "
              "the nice quality. The collection was good. Cool! The quality was nice.")
    review, problem = _finalize(merged, 5, "Good collection and nice quality.")
    assert problem is not None and "repeated" in problem





def test_rejection_reason_names_the_dropped_facts_not_customer_text():
    _, problem = _finalize("The fitting was good. Prices were fair. They stock nice brands.", 4, "The fitting was good.")
    assert problem.startswith("too little was left") and "price" in problem and "brand" in problem
    assert "fair" not in problem


def test_gemini_call_has_automatic_function_calling_off(fake_groq, gemini):
    _fallback(fake_groq, gemini, RateLimitError("rate limited", response=_groq_response(429), body=None), GOOD_REPLY)
    assert gemini.calls[0]["config"].automatic_function_calling.disable is True


@pytest.mark.parametrize(
    ("sentence", "experience"),
    [
        ("Service was slow and disappointing.", None),
        ("The collection felt limited.", None),
        ("The staff seemed busy but did not give any updates.", "Alteration took too long."),
        ("Service was slow.", None),
        ("The atmosphere was uninviting and the service seemed indifferent.", None),
    ],
)
def test_added_complaints_are_removed(sentence, experience):
    assert "complaint" in review_rules.sentence_problem(sentence, 2, experience)


@pytest.mark.parametrize(
    ("sentence", "experience"),
    [
        ("The experience was disappointing.", None),
        ("The alteration took far too long and I was left waiting.", "Alteration took too long."),
        ("The stitching was bad.", "The stitching was bad."),
        ("The service just didn't meet my expectations.", None),
        ("Probably won't go back.", None),
    ],
)
def test_customer_complaints_and_plain_disappointment_stay(sentence, experience):
    assert review_rules.sentence_problem(sentence, 2, experience) is None


def test_groq_json_validation_error_is_read_without_another_call(fake_groq, gemini):
    failed = BadRequestError(
        "Failed to validate JSON",
        response=_groq_response(400),
        body={"error": {"code": "json_validate_failed", "failed_generation": f"{V_GOOD}\n###\n{GOOD_REPLY}"}},
    )
    response = _fallback(fake_groq, gemini, failed)
    assert response.json()["review"] == V_GOOD
    assert len(fake_groq.calls) == 1 and gemini.calls == []


def test_offer_as_a_verb_is_not_a_price():
    assert review_rules.sentence_problem("I like the range of outfits they offer.", 4, None) is None
    assert "price" in review_rules.sentence_problem("They had great offers.", 4, None)


@pytest.mark.parametrize(
    ("text", "rating", "experience", "expected"),
    [
        ("I got a dress altered here. Dresses looked nice.", 2, None, "I got an outfit altered here. Outfits looked nice."),
        ("A lehenga caught my eye.", 4, None, "An outfit caught my eye."),
        ("The suit fit perfectly. Perfect stitching.", 5, "Loved the suit.", "The suit fit really well. Great stitching."),
        ("The dress was perfect.", 5, "Perfect dress!", "The dress was perfect."),  # their own words stay
    ],
)
def test_unnamed_garments_and_hype_are_repaired_locally(text, rating, experience, expected):
    assert review_rules.generalize_review(text, rating, experience) == expected


def test_delay_wording_counts_as_the_customer_raising_timing():
    assert review_rules.sentence_problem("The wait was really long.", 2, "Alteration took too long.") is None
    assert "complaint" in review_rules.sentence_problem("The staff seemed uninterested.", 2, None)


# --- Groq busy: short wait, then Groq again ----------------------------------------


def _groq_busy(retry_after=None, message="rate limited"):
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return RateLimitError(message, response=httpx.Response(429, headers=headers, request=request), body=None)


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(groq_client.time, "sleep", waited.append)
    return waited


@pytest.mark.parametrize(
    "busy",
    [_groq_busy(retry_after="2"), _groq_busy(message="Rate limit reached. Please try again in 3.07s. Need more tokens?")],
    ids=["header", "message"],
)
def test_short_groq_wait_is_waited_out_instead_of_gemini(fake_groq, gemini, sleeps, busy):
    fake_groq.replies = [busy, GOOD_REPLY]
    response = _post()
    assert response.json()["review"] == GOOD_REPLY
    assert len(fake_groq.calls) == 2 and gemini.calls == []
    assert sleeps and sleeps[0] <= groq_client.MAX_GROQ_WAIT_SECONDS


def test_long_or_unknown_groq_wait_goes_to_gemini(fake_groq, gemini, sleeps):
    for busy in (_groq_busy(retry_after="30"), _groq_busy()):
        fake_groq.calls, gemini.calls = [], []
        gemini.replies = [GEMINI_REPLY if not fake_groq.calls else GOOD_REPLY]
        fake_groq.replies = [busy]
        assert _post().status_code in (200, 409)
        assert len(fake_groq.calls) == 1 and len(gemini.calls) == 1
    assert sleeps == []


def test_groq_still_busy_after_the_wait_is_a_busy_error_with_two_calls(fake_groq, gemini, sleeps):
    fake_groq.replies = [_groq_busy(retry_after="1"), _groq_busy(retry_after="1")]
    assert _post().status_code == 429
    assert len(fake_groq.calls) == 2 and gemini.calls == []  # never a third call


def test_groq_wait_that_would_break_the_deadline_goes_to_gemini(fake_groq, gemini, sleeps, monkeypatch):
    monkeypatch.setattr(groq_client, "REQUEST_BUDGET_SECONDS", groq_client.MIN_GEMINI_SECONDS + 1)
    fake_groq.replies = [_groq_busy(retry_after="3")]
    gemini.replies = [GEMINI_REPLY]
    assert _post().json()["review"] == GEMINI_REPLY
    assert sleeps == []


@pytest.mark.parametrize(
    "sentence",
    ["The collection was not bad.", "No complaints about the staff.", "The staff were average.",
     "The selection was decent but nothing special."],
)
def test_mild_three_star_wording_is_not_an_invented_complaint(sentence):
    assert review_rules.sentence_problem(sentence, 3, None) is None
