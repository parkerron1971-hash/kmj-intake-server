"""
test_speech_text.py — guards how spoken money is pronounced.

`normalize_for_speech` turns currency and symbols into words before text
reaches a TTS provider. It exists because the providers disagree: some
voices honour a thousands comma as a pause ("one, two three four"), read
cents as a bare integer, and every one of them reads "$1.5M" as a letter
M. ElevenLabs' own `apply_text_normalization` would do this upstream but
is Enterprise-only on the v2.5 models, and ELEVENLABS_MODEL here is
`eleven_turbo_v2_5`.

This is a class of bug that is INVISIBLE in every other check: the text on
screen is perfect, the request succeeds, the mp3 plays. It is only wrong
in the audio, which no test can hear. So the tests assert the property
that stands in for hearing it — no raw currency symbol survives, and each
shape reads the way a person would say it.

Two of these cases are regressions, not hypotheticals. The ladder case
caught a greedy `[\\d,]+` that swallowed the SEPARATOR in "$79, $199" and
silently collapsed the list. The one-decimal case pins "$1,234.5" as
fifty cents, not five.
"""
import pytest

import speech_text
from speech_text import normalize_for_speech as n


# ── the shapes ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    # ── Kevin, 2026-08-14: "$2,345 sounds like two three forty five
    # dollars". A bare four-digit number is read as a YEAR by every
    # engine. Dropping the thousands comma (which some voices honour as
    # a pause, "one, two three four") swapped one misreading for
    # another. Words are the only form with a single pronunciation.
    ("You are owed $2,345.", "You are owed two thousand three hundred forty-five dollars."),
    # dollars and cents
    ("You collected $1,234.56 this month.",
     "You collected one thousand two hundred thirty-four dollars and fifty-six cents this month."),
    # a round amount should not say "and zero cents"
    ("The invoice is $79.00 flat.", "The invoice is seventy-nine dollars flat."),
    # singular
    ("That is $1.00 exactly.", "That is one dollar exactly."),
    ("Off by $0.01.", "Off by one cent."),
    # under a dollar is cents, not "zero dollars and..."
    ("Rounding left $0.99 behind.", "Rounding left ninety-nine cents behind."),
    ("You have $0 outstanding.", "You have zero dollars outstanding."),
    ("Revenue was $1,200 this week.", "Revenue was one thousand two hundred dollars this week."),
    # the teens, which have their own words
    ("Cash on hand is $10.77.", "Cash on hand is ten dollars and seventy-seven cents."),
    ("You have $1,865 in receivables.",
     "You have one thousand eight hundred sixty-five dollars in receivables."),
    # magnitude suffixes — read as a letter by every engine otherwise
    ("Valuation is $1.5M and change.", "Valuation is 1.5 million dollars and change."),
    ("Budget of $2.3k per campaign.", "Budget of 2.3 thousand dollars per campaign."),
    # bookkeeping deltas run negative
    ("-$50 was the adjustment.", "negative fifty dollars was the adjustment."),
    ("The delta was -$1,250.40 for June.",
     "The delta was negative one thousand two hundred fifty dollars and forty cents for June."),
    # a bare dash between prices is read as "minus"
    ("Plans run $79-$199 a month.",
     "Plans run seventy-nine dollars to one hundred ninety-nine dollars a month."),
    # REGRESSION: a greedy [\d,]+ ate the comma separator here
    ("Pricing is $79/$199/$399.",
     "Pricing is seventy-nine dollars, one hundred ninety-nine dollars, three hundred ninety-nine dollars."),
    # the slash is silent unless it becomes a word
    ("Founder pricing is $149/mo for 50 seats.",
     "Founder pricing is one hundred forty-nine dollars per month for 50 seats."),
    ("It is $1,999/year billed up front.",
     "It is one thousand nine hundred ninety-nine dollars per year billed up front."),
    ("Revenue is up 12.5% over last month.",
     "Revenue is up 12.5 percent over last month."),
    ("It costs 50¢ per unit.", "It costs 50 cents per unit."),
    # REGRESSION: ".5" is fifty cents, not five
    ("You are owed $1,234.5 total.",
     "You are owed one thousand two hundred thirty-four dollars and fifty cents total."),
    ("Total is $1,240,300.10 across all clients.",
     "Total is one million two hundred forty thousand three hundred dollars and ten cents across all clients."),
    # a YEAR outside a dollar amount is left alone — it is not money and
    # "twenty twenty-six" is the correct reading.
    ("Renewal lands in 2026.", "Renewal lands in 2026."),
    # text with nothing to normalize must come back untouched
    ("Nothing urgent right now.", "Nothing urgent right now."),
])
def test_reads_the_way_a_person_would_say_it(raw, expected):
    assert n(raw) == expected


# ── the properties that stand in for listening ───────────────────────

CURRENCY_SHAPES = [
    "$1,234.56", "$79.00", "$0.99", "$1.5M", "-$50", "$79-$199",
    "$79/$199/$399", "$149/mo", "12.5%", "50¢", "$1,240,300.10",
]


@pytest.mark.parametrize("shape", CURRENCY_SHAPES)
def test_no_raw_symbol_reaches_the_provider(shape):
    """The whole point: a provider must never receive $, ¢ or % — that is
    where the pronunciation stops being ours and starts being the
    voice's."""
    out = n(f"The number is {shape} today.")
    assert "$" not in out
    assert "¢" not in out
    assert "%" not in out


@pytest.mark.parametrize("shape", CURRENCY_SHAPES)
def test_idempotent(shape):
    """A client may have normalized already (the web app does, for its own
    local speech path). Applying this twice must not corrupt the text, or
    the frontend and the wire could not both hold the guarantee."""
    once = n(f"It came to {shape} in the end.")
    assert n(once) == once


def test_empty_and_none_are_safe():
    assert n("") == ""
    assert n(None) == ""


def test_digits_that_are_not_money_are_left_alone():
    """Normalization must not reach past currency into ordinary numbers —
    invoice ids, dates and counts are read fine as-is."""
    assert n("Invoice 1042 is 3 days late.") == "Invoice 1042 is 3 days late."
    assert n("Version 2.0 shipped on 7/31.") == "Version 2.0 shipped on 7/31."


def test_a_decimal_is_never_split():
    """Guards the sibling bug fixed on the frontend (FE#402): a decimal
    point must survive as a decimal point, never become a sentence end."""
    assert "1234.56" not in n("$1,234.56")   # it became words
    assert n("The ratio was 3.5 to one.") == "The ratio was 3.5 to one."


# ── number_words: the reading itself ─────────────────────────────────
#
# Kevin's report was not "the amount is wrong", it was "the amount is
# said wrong". Every case below is a shape that a TTS engine reads
# ambiguously when handed digits, and unambiguously when handed words.

@pytest.mark.parametrize("n,words", [
    (0, "zero"),
    (1, "one"),
    (9, "nine"),
    # the teens have their own words; "thirteen" is not "three-teen"
    (13, "thirteen"),
    (19, "nineteen"),
    (20, "twenty"),
    (21, "twenty-one"),
    (45, "forty-five"),
    (99, "ninety-nine"),
    (100, "one hundred"),
    (101, "one hundred one"),
    (110, "one hundred ten"),
    (999, "nine hundred ninety-nine"),
    (1000, "one thousand"),
    # THE reported case
    (2345, "two thousand three hundred forty-five"),
    # a four-digit number an engine would otherwise read as a year
    (1999, "one thousand nine hundred ninety-nine"),
    (2026, "two thousand twenty-six"),
    # no "zero hundred" filler in the middle
    (1005, "one thousand five"),
    (10000, "ten thousand"),
    (100000, "one hundred thousand"),
    (123456, "one hundred twenty-three thousand four hundred fifty-six"),
    (1000000, "one million"),
    (1240300, "one million two hundred forty thousand three hundred"),
    (1000000000, "one billion"),
])
def test_number_words(n, words):
    assert speech_text.number_words(n) == words


def test_absurd_numbers_fall_back_to_digits():
    """Past a quadrillion the words stop helping and nobody's books have
    one anyway. Falling back beats a wrong or unbounded expansion."""
    assert speech_text.number_words(10 ** 15) == str(10 ** 15)


def test_negative_numbers_say_negative():
    assert speech_text.number_words(-45) == "negative forty-five"


def test_every_amount_up_to_ten_thousand_is_speakable():
    """No amount may come back with a digit in it — a single leaked
    digit is a number some engine will read as a year."""
    for i in range(0, 10001):
        w = speech_text.number_words(i)
        assert not any(c.isdigit() for c in w), f"{i} -> {w}"
