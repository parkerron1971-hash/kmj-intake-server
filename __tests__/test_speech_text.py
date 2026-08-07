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

from speech_text import normalize_for_speech as n


# ── the shapes ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    # dollars and cents, the case Kevin reported
    ("You collected $1,234.56 this month.",
     "You collected 1234 dollars and 56 cents this month."),
    # a round amount should not say "and zero cents"
    ("The invoice is $79.00 flat.", "The invoice is 79 dollars flat."),
    # singular
    ("That is $1.00 exactly.", "That is 1 dollar exactly."),
    ("Off by $0.01.", "Off by 1 cent."),
    # under a dollar is cents, not "zero dollars and..."
    ("Rounding left $0.99 behind.", "Rounding left 99 cents behind."),
    ("You have $0 outstanding.", "You have 0 dollars outstanding."),
    ("Revenue was $1,200 this week.", "Revenue was 1200 dollars this week."),
    # magnitude suffixes — read as a letter by every engine otherwise
    ("Valuation is $1.5M and change.", "Valuation is 1.5 million dollars and change."),
    ("Budget of $2.3k per campaign.", "Budget of 2.3 thousand dollars per campaign."),
    # bookkeeping deltas run negative
    ("-$50 was the adjustment.", "negative 50 dollars was the adjustment."),
    ("The delta was -$1,250.40 for June.",
     "The delta was negative 1250 dollars and 40 cents for June."),
    # a bare dash between prices is read as "minus"
    ("Plans run $79-$199 a month.", "Plans run 79 dollars to 199 dollars a month."),
    # REGRESSION: a greedy [\d,]+ ate the comma separator here
    ("Pricing is $79/$199/$399.", "Pricing is 79 dollars, 199 dollars, 399 dollars."),
    # the slash is silent unless it becomes a word
    ("Founder pricing is $149/mo for 50 seats.",
     "Founder pricing is 149 dollars per month for 50 seats."),
    ("It is $1,999/year billed up front.",
     "It is 1999 dollars per year billed up front."),
    ("Revenue is up 12.5% over last month.",
     "Revenue is up 12.5 percent over last month."),
    ("It costs 50¢ per unit.", "It costs 50 cents per unit."),
    # REGRESSION: ".5" is fifty cents, not five
    ("You are owed $1,234.5 total.", "You are owed 1234 dollars and 50 cents total."),
    ("Total is $1,240,300.10 across all clients.",
     "Total is 1240300 dollars and 10 cents across all clients."),
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
