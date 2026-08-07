"""Currency and symbol normalization for text on its way to a TTS provider.

Why this lives on the server
────────────────────────────
TTS engines disagree about symbols. "$1,234.56" is read correctly by some
voices and mangled by others — the thousands comma is honoured as a pause
("one, two three four"), the cents come out as a bare integer — and
"$1.5M" is read as a letter M by all of them. Whichever provider speaks,
the practitioner should hear the same number.

The frontend already normalizes for its own local browser-speech path
(which never reaches this server). Doing it ONLY there would make the
guarantee a property of one client: /ai/tts/speak is also reachable by
the KAI agent, the packaged mobile app, and anything added later, and
those would silently get the mangled reading. This module is the wire,
so it holds for every caller.

Not an ElevenLabs setting
─────────────────────────
ElevenLabs exposes `apply_text_normalization`, which would let us send
the short form and have them expand it (cheaper — they meter characters).
It is Enterprise-only on the v2.5 models, and ELEVENLABS_MODEL here is
`eleven_turbo_v2_5`. ElevenLabs' own guidance for everyone else is to
normalize the text before sending it, which is what this does. If the
account ever moves to Enterprise, the parameter becomes the cheaper path
and this module can step aside for that provider.

The transform is idempotent — normalizing already-normalized text is a
no-op — so it is safe for a client to have normalized first.
"""

import re
from typing import Optional

_MAGNITUDE_WORDS = {"k": "thousand", "m": "million", "b": "billion", "t": "trillion"}
_RATE_UNITS = {"mo": "month", "yr": "year", "wk": "week", "hr": "hour"}

# One dollar amount. The comma counts only as a REAL thousands group: a
# permissive [\d,]+ swallows the separator in "$79, $199" and the list
# silently collapses to "79 dollars 199 dollars".
_MONEY = r"\$\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"

_MAGNITUDE_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?([KkMmBbTt])\b")
_RANGE_RE = re.compile(rf"({_MONEY})\s?[-–—]\s?(?=\$)")
_RATE_RE = re.compile(
    rf"({_MONEY})\s?/\s?(mo|month|yr|year|wk|week|hr|hour|day|seat|user|session)\b",
    re.IGNORECASE,
)
_LIST_RE = re.compile(rf"({_MONEY})\s?/\s?(?=\$)")
_NEGATIVE_RE = re.compile(r"(^|[\s(])[-–—]\s?(?=\$)")
_ANY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?!\d)")
_CENTS_RE = re.compile(r"(\d+)\s?¢")
_PERCENT_RE = re.compile(r"(\d)\s?%")
_WS_RE = re.compile(r"\s+")


def _spell_amount(whole: str, cents: Optional[str]) -> str:
    """"$1,234.56" -> "1234 dollars and 56 cents", with the plural, the
    zero-cents and the under-a-dollar cases said the way a person says
    them. The thousands comma is dropped deliberately: some voices honour
    it as a pause."""
    w = whole.replace(",", "")
    dollar_word = "dollar" if w == "1" else "dollars"
    # ".5" is fifty cents, not five — pad before reading it as a number.
    cn = int(cents.ljust(2, "0")) if cents else 0
    if not cn:
        return f"{w} {dollar_word}"
    cent_word = "cent" if cn == 1 else "cents"
    # "$0.99" is ninety-nine cents, not "zero dollars and ninety-nine".
    if int(w) == 0:
        return f"{cn} {cent_word}"
    return f"{w} {dollar_word} and {cn} {cent_word}"


def _magnitude_sub(m: "re.Match[str]") -> str:
    return f"{m.group(1)} {_MAGNITUDE_WORDS[m.group(2).lower()]} dollars"


def _rate_sub(m: "re.Match[str]") -> str:
    unit = m.group(2).lower()
    return f"{m.group(1)} per {_RATE_UNITS.get(unit, unit)}"


def _cents_sub(m: "re.Match[str]") -> str:
    n = m.group(1)
    return f"{n} {'cent' if n == '1' else 'cents'}"


def normalize_for_speech(text: str) -> str:
    """Turn currency and symbols into words so every provider reads them
    the same way. Order matters: the shaped cases claim their text before
    the general dollar rule runs, which would otherwise consume "$1" out
    of "$1.5M" and strand the suffix."""
    if not text:
        return ""
    out = text
    # "$1.5M" -> "1.5 million dollars"
    out = _MAGNITUDE_RE.sub(_magnitude_sub, out)
    # "$79-$199" -> "$79 to $199"; a bare dash is read as "minus".
    out = _RANGE_RE.sub(r"\1 to ", out)
    # "$149/mo" -> "$149 per month" (the slash is silent otherwise).
    out = _RATE_RE.sub(_rate_sub, out)
    # "$79/$199/$399" -> "$79, $199, $399" (the pricing ladder).
    out = _LIST_RE.sub(r"\1, ", out)
    # "-$50" -> "negative $50" — bookkeeping deltas run negative.
    out = _NEGATIVE_RE.sub(r"\1negative ", out)
    # The general case, last.
    out = _ANY_RE.sub(lambda m: _spell_amount(m.group(1), m.group(2)), out)
    out = _CENTS_RE.sub(_cents_sub, out)
    out = _PERCENT_RE.sub(r"\1 percent", out)
    return _WS_RE.sub(" ", out).strip()
