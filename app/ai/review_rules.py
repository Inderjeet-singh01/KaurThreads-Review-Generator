"""Local, deterministic rules for a generated boutique review.

Nothing here calls an LLM. The rules keep a review inside the fashion-boutique
domain, grounded in what the customer actually wrote, and in the tone of the
star rating. All matching runs on :func:`normalize`d text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split into sentences, ignoring empty fragments."""
    return [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if re.search(r"\w", s)]


def _words(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b")


# --- Boutique vocabulary ---------------------------------------------------
# These are DOMAIN CATEGORIES, not facts about the boutique: a review may only
# mention one when the customer's own text supports it.

# Named items that must each appear in the customer's text: a review may not
# turn "blouse" into "lehenga", "fabric" into "silk" or add a colour.
GARMENTS = {
    "dress": r"dress(?:es)?", "suit": r"suits?", "saree": r"sarees?|saris?",
    "lehenga": r"lehengas?|lehngas?", "kurti": r"kurt[ai]s?", "blouse": r"blouses?",
    "gown": r"gowns?", "dupatta": r"dupattas?", "salwar": r"salwars?|shalwars?",
    "anarkali": r"anarkalis?", "sharara": r"shararas?|ghararas?",
    "sherwani": r"sherwanis?", "skirt": r"skirts?", "jacket": r"jackets?",
}
FABRICS = {
    name: name + r"s?"
    for name in (
        "cotton", "silk", "linen", "chiffon", "georgette", "velvet", "rayon",
        "crepe", "organza", "satin", "net", "banarasi", "khadi",
    )
}
COLOURS = {
    name: name
    for name in (
        "red", "blue", "green", "pink", "maroon", "gold", "golden", "silver",
        "black", "white", "yellow", "orange", "purple", "peach", "beige",
        "cream", "navy", "mustard",
    )
}
_SPECIFIC_RES = {
    name: re.compile(r"\b(?:" + pattern + r")\b")
    for name, pattern in {**GARMENTS, **FABRICS, **COLOURS}.items()
}

# Topics a review may not bring up unless the customer did.
TOPICS: dict[str, tuple[str, ...]] = {
    # Product
    "clothing": (
        r"outfits?", r"clothes", r"clothing", r"garments?", r"pieces?", r"attire",
        r"(?:ethnic|party|bridal|festive|designer) wear",
    ),
    "collection": (r"collections?", r"stock", r"new arrivals?"),
    "variety": (r"selection", r"variety", r"range", r"options", r"choices"),
    "design": (r"designs?", r"designer", r"patterns?", r"prints?", r"styles?"),
    "colour": (r"colou?rs?", r"colou?rful", r"shades?"),
    "fabric": (r"fabrics?", r"materials?", r"cloth"),
    "quality": (
        r"quality", r"well made", r"durable", r"sturdy", r"finish(?:ing|ed)?",
        r"neat(?:ly)?", r"craftsmanship", r"workmanship", r"detailing",
        r"hand ?made", r"crafted",
    ),
    "comfort": (r"comfort\w*", r"soft", r"breathable", r"itchy"),
    "embroidery": (
        r"embroider\w*", r"hand ?work", r"zari", r"zardozi", r"sequins?",
        r"mirror work", r"thread work", r"bead ?work",
    ),
    "brand": (r"brands?", r"branded", r"labels?"),
    # Service
    "stitching": (r"stitch\w*", r"tailor\w*", r"sewing", r"sewn"),
    "fitting": (r"fit", r"fits", r"fitted", r"fitting", r"adjust\w*", r"loose", r"tight"),
    "alteration": (r"alter\w*", r"redone", r"redo"),
    "measurement": (r"measure\w*",),
    "customisation": (r"custom\w*", r"personali[sz]\w*", r"made to order", r"bespoke"),
    "trial": (r"trials?", r"tried", r"try(?:ing)? (?:it |them )?on"),
    "staff": (
        r"staff", r"employees?", r"team", r"sales ?(?:person|man|woman|girl|lady)s?",
        r"owners?", r"shopkeepers?", r"assistants?", r"stylists?", r"workers?",
        r"aunty", r"auntie", r"didi", r"bhaiya", r"people there", r"lady",
    ),
    "service": (
        r"service", r"served", r"attended", r"assist\w*", r"help\w*", r"guid\w*",
        r"suggest\w*", r"consult\w*",
    ),
    "styling": (r"styling", r"styled"),
    "appointment": (r"appointments?", r"booking", r"booked", r"slots?"),
    "order": (r"orders?", r"ordered", r"ordering"),
    "communication": (
        r"call(?:ed|s|ing)?", r"messag\w*", r"whatsapp", r"repl\w*", r"respon\w*",
        r"communicat\w*", r"updates?", r"informed",
    ),
    "delivery": (
        r"deliver\w*", r"shipping", r"shipped", r"courier", r"dispatch\w*",
        r"pick ?up", r"picked up", r"collected", r"ready", r"arriv\w*",
    ),
    "timing": (
        r"on time", r"in time", r"timely", r"late", r"delay\w*", r"quick\w*",
        r"fast", r"prompt\w*", r"same day", r"deadline", r"wait\w*", r"days",
        r"weeks", r"hours?",
    ),
    # Business facts
    "price": (
        r"pric\w*", r"costs?", r"costly", r"cheap\w*", r"expensive", r"afford\w*",
        r"discount\w*", r"offers?", r"on sale", r"budget", r"money", r"value",
        r"rupees?", r"rs", r"reasonabl[ey]", r"overpriced",
    ),
    "occasion": (
        r"weddings?", r"bridal", r"brides?", r"festiv\w*", r"part(?:y|ies)",
        r"occasions?", r"events?", r"functions?", r"diwali", r"eid",
        r"engagements?", r"reception", r"sangeet", r"meh[e]?ndi",
    ),
    "shop atmosphere": (
        r"ambien\w*", r"atmosphere", r"vibes?", r"decor", r"interiors?",
        r"spacious", r"cozy", r"cosy", r"welcoming", r"displays?", r"racks?",
        r"(?:shop|store|place|boutique) (?:is|was|looks|looked) (?:\w+ )?"
        r"(?:clean|nice|lovely|beautiful|pretty)",
    ),
    "location": (r"location", r"located", r"parking", r"nearby", r"easy to find"),
    "payment": (r"payments?", r"paid", r"pay", r"upi", r"cash", r"card", r"bill\w*"),
    "purchase": (r"bought", r"buy\w*", r"purchas\w*"),
    "recommendation": (
        r"recommend\w*", r"must (?:visit|try|go)", r"go for it",
        r"check (?:it|them|this place|the place) out",
    ),
    "return visit": (
        r"come back", r"coming back", r"came back", r"be back", r"go(?:ing)? back",
        r"went back", r"return\w*", r"visit\w* again", r"next time", r"again soon",
        r"(?:come|go|shop|be) (?:here |there )?again",
        r"check (?:back|in again)", r"stop by again", r"drop by again", r"visit (?:soon|more often)",
    ),
    # Outcomes models like to claim for the customer.
    "claimed outcome": (
        r"exactly what i\w*", r"what i (?:was|were) (?:looking|hoping) for",
        r"(?:all|just) what i (?:wanted|needed)", r"fit my style", r"place to shop",
        r"felt ignored",
    ),
}

# Customer words that also make a topic legitimate ("fitting was fixed" ->
# "the alteration came out well").
EXTRA_GROUNDING: dict[str, tuple[str, ...]] = {
    "clothing": TOPICS["collection"] + TOPICS["variety"] + TOPICS["design"] + tuple(GARMENTS.values()),
    "collection": TOPICS["variety"],
    "quality": TOPICS["fabric"],
    "fitting": TOPICS["alteration"],
    "alteration": TOPICS["fitting"] + (r"fix\w*",),
    "trial": TOPICS["fitting"],
    "staff": TOPICS["service"],
    "service": TOPICS["staff"],
    "styling": TOPICS["service"] + (r"choos\w*", r"chose", r"pick\w*"),
    "order": TOPICS["stitching"] + TOPICS["customisation"],
}

_TOPIC_RES = {topic: _words(p) for topic, p in TOPICS.items()}
_GROUNDING_RES = {
    topic: _words(p + EXTRA_GROUNDING.get(topic, ())) for topic, p in TOPICS.items()
}

# The customer's points a review must keep. A point counts as covered when
# the review mentions any topic (or named item) of its group.
COVERAGE_GROUPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "the garment": (("clothing",), tuple(GARMENTS)),
    "the collection": (("collection", "variety"), ()),
    "the design": (("design", "colour", "embroidery"), tuple(COLOURS)),
    "the quality": (("quality", "fabric", "comfort"), tuple(FABRICS)),
    "the fitting or tailoring": (
        ("fitting", "alteration", "stitching", "measurement", "customisation", "trial"), (),
    ),
    "the staff or service": (("staff", "service", "styling"), ()),
    "the timing or delivery": (("delivery", "timing", "order", "appointment"), ()),
    "the price": (("price",), ()),
    "the communication": (("communication",), ()),
}

# Words that make an input clearly about a boutique (weak words such as
# "staff", "helpful" or "quality" fit any business, so they don't count).
_BOUTIQUE_RE = _words(
    [p for t in (
        "clothing", "collection", "variety", "design", "fabric", "embroidery", "stitching",
        "fitting", "alteration", "measurement", "customisation", "trial", "styling",
    ) for p in TOPICS[t]]
    + list(GARMENTS.values()) + list(FABRICS.values())
    + [r"boutique", r"kaur threads?"]
)
# Businesses that are clearly not a fashion boutique.
_OFF_DOMAIN_RE = _words((
    r"food", r"pizzas?", r"burgers?", r"pasta", r"biryani", r"meals?", r"dish(?:es)?",
    r"restaurants?", r"cafe", r"menu", r"waiters?", r"chef", r"tasty", r"delicious",
    r"bakery", r"dentists?", r"doctors?", r"clinic", r"hospital", r"pharmacy",
    r"hotels?", r"resort", r"(?<!trial )(?<!changing )rooms?", r"pool", r"mechanic",
    r"garage", r"salon", r"haircut", r"facial", r"massage", r"spa", r"gym",
    r"movie", r"cinema", r"flights?", r"airline", r"plumber", r"electrician",
))


def is_boutique_input(experience: str | None) -> bool:
    """False only when the input is clearly about another kind of business.
    Vague input ("Nice", "Staff was rude") is fine."""
    text = normalize(experience or "")
    return bool(_BOUTIQUE_RE.search(text)) or not _OFF_DOMAIN_RE.search(text)


def _topics_in(text_n: str) -> set[str]:
    return {topic for topic, pattern in _TOPIC_RES.items() if pattern.search(text_n)}


def coverage_groups(text: str | None) -> list[str]:
    """The customer points (see COVERAGE_GROUPS) that ``text`` mentions."""
    text_n = normalize(text or "")
    topics = _topics_in(text_n)
    return [
        group
        for group, (group_topics, items) in COVERAGE_GROUPS.items()
        if topics.intersection(group_topics)
        or any(_SPECIFIC_RES[item].search(text_n) for item in items)
    ]


def missing_points(review: str, experience: str | None) -> list[str]:
    """Customer points that the review dropped."""
    covered = set(coverage_groups(review))
    return [g for g in coverage_groups(experience) if g not in covered]


def ungrounded_topics(review: str, experience: str | None) -> list[str]:
    """Topics or named items in the review that the customer never mentioned."""
    review_n, experience_n = normalize(review), normalize(experience or "")
    found = [
        topic
        for topic, pattern in _TOPIC_RES.items()
        if pattern.search(review_n) and not _GROUNDING_RES[topic].search(experience_n)
    ]
    found += [
        item
        for item, pattern in _SPECIFIC_RES.items()
        if pattern.search(review_n) and not pattern.search(experience_n)
    ]
    return found


# --- Style -----------------------------------------------------------------
# Only clearly promotional or machine-sounding wording. Ordinary phrases
# ("really liked it", "pretty good", "good experience") are left alone.
_ARTIFICIAL_RE = _words((
    r"highly recommend\w*", r"must visit", r"a must", r"hidden gem", r"one stop",
    r"look no further", r"second to none", r"world class", r"top notch",
    r"best (?:boutique|place|shop|store)\w*", r"best in (?:town|the city)",
    r"go to (?:place|boutique|shop)", r"exceeded (?:all )?(?:my )?expectations",
    r"beyond expectations", r"unmatched", r"unbeatable", r"like no other",
    r"(?:five|5) stars?", r"premium", r"luxur\w*", r"exceptional\w*",
    r"truly", r"impeccabl\w*", r"exquisite", r"curated", r"elevat\w*",
    r"seamless\w*", r"testament", r"meticulous\w*", r"attention to detail",
    r"nothing short of", r"a cut above", r"whether you re", r"if you re looking",
    r"left me feeling", r"walked away (?:feeling|with)", r"caught my eye",
    r"in every way", r"wholeheartedly", r"top tier", r"stellar", r"delightful",
))


def artificial_phrase(text: str, experience: str | None) -> str | None:
    """A promotional/AI-sounding phrase the customer didn't use, else None."""
    match = _ARTIFICIAL_RE.search(normalize(text))
    if match and match.group(0) not in normalize(experience or ""):
        return match.group(0)
    return None


# --- Tone vs. rating ---------------------------------------------------------
_WARM_RE = _words((
    r"lov(?:e|ed|es|ing)", r"amazing(?:ly)?", r"fantastic", r"wonderful(?:ly)?",
    r"excellent", r"awesome", r"beautiful(?:ly)?", r"superb", r"brilliant",
    r"gorgeous", r"stunning", r"thrilled", r"delighted",
))
_EXTREME_RE = _words((
    r"perfect(?:ly|ion)?", r"flawless(?:ly)?", r"best", r"incredibl[ey]",
    r"outstanding", r"mind ?blowing",
))
_LUKEWARM_RE = _words((
    r"ok(?:ay)?", r"fine", r"average", r"decent", r"alright", r"not bad",
    r"so so", r"nothing special", r"mediocre",
))
_STRONG_NEGATIVE_RE = _words((
    r"disappoint\w*", r"terrible", r"awful", r"horrible", r"worst", r"poor(?:ly)?",
    r"frustrat\w*", r"unhappy", r"rude", r"pathetic", r"useless", r"waste\w*",
    r"never again", r"disgusting",
))
_EXTREME_NEGATIVE_RE = _words((
    r"terrible", r"awful", r"horrible", r"worst", r"pathetic", r"useless",
    r"waste\w*", r"never again", r"disgusting",
))
# A 1-2 star review has to carry at least one of these.
_NEGATIVE_CUE_RE = _words((
    r"not", r"no", r"never", r"t", r"disappoint\w*", r"bad", r"poor\w*", r"wrong",
    r"unhappy", r"issues?", r"problems?", r"late", r"delay\w*", r"rude",
    r"terrible", r"awful", r"horrible", r"worst", r"waste\w*", r"mediocre",
    r"average", r"meh", r"expected (?:more|better)", r"could (?:have been|be) better",
    r"sadly", r"unfortunately", r"upset", r"annoy\w*", r"frustrat\w*", r"careless",
    r"loose", r"tight", r"messed", r"lacking", r"lacked", r"only okay",
))
# "not perfect", "wasn't the best", "would have loved" don't overshoot.
_NEGATORS = frozenset({"not", "never", "no", "t", "hardly", "without", "nothing", "have"})
_NEGATION_WINDOW = 3


def _used_by_customer(word: str, experience_n: str) -> bool:
    stem = word.split()[0][:4]
    return bool(re.search(r"\b" + re.escape(stem), experience_n))


def _negated(text_n: str, start: int) -> bool:
    return bool(_NEGATORS.intersection(text_n[:start].split()[-_NEGATION_WINDOW:]))


def _positive_ceiling(rating: int, experience_n: str) -> int:
    """How strong praise may get: 0 plain, 1 warm ("loved"), 2 extreme
    ("perfect"). Never above what the rating and the customer's words allow."""
    used = 2 if _EXTREME_RE.search(experience_n) else 1 if _WARM_RE.search(experience_n) else 0
    if rating <= 3 or (used == 0 and _LUKEWARM_RE.search(experience_n)):
        return 0
    return used if rating == 4 else max(1, used)


def tone_problem(text: str, rating: int, experience: str | None) -> str | None:
    """Reason a sentence is stronger than the rating/customer allow, else None."""
    text_n, experience_n = normalize(text), normalize(experience or "")
    ceiling = _positive_ceiling(rating, experience_n)
    checks = [(tier, pattern, "positive") for tier, pattern in ((1, _WARM_RE), (2, _EXTREME_RE)) if tier > ceiling]
    if rating >= 4:
        checks.append((0, _STRONG_NEGATIVE_RE, "negative"))
    elif rating == 3:
        checks.append((0, _EXTREME_NEGATIVE_RE, "negative"))
    for _, pattern, direction in checks:
        for match in pattern.finditer(text_n):
            word = match.group(0)
            if not _used_by_customer(word, experience_n) and not _negated(text_n, match.start()):
                return f"'{word}' is too {direction} for {rating} stars and the customer's words"
    return None


def rating_floor_problem(review: str, rating: int) -> str | None:
    """A 1-2 star review must actually sound unhappy."""
    if rating <= 2 and not _NEGATIVE_CUE_RE.search(normalize(review)):
        return f"it didn't sound unhappy enough for {rating} stars"
    return None


def sentence_problem(sentence: str, rating: int, experience: str | None) -> str | None:
    """Reason one sentence can't stay in the review, else None. Such a
    sentence is dropped locally; nothing is regenerated."""
    if _OFF_DOMAIN_RE.search(normalize(sentence)):
        return "it talked about something other than the boutique"
    invented = ungrounded_topics(sentence, experience)
    if invented:
        return "it added details the customer never mentioned: " + ", ".join(invented)
    phrase = artificial_phrase(sentence, experience)
    if phrase:
        return f"it used the promotional/AI phrase '{phrase}'"
    return tone_problem(sentence, rating, experience)
