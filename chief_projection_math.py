"""Bounded arithmetic for explicitly hypothetical annual/monthly target explanations.

These are calculations on owner-supplied inputs, never evidence of earned
revenue or current subscribers. No model, database, or business mutation.
"""
from decimal import Decimal, ROUND_HALF_UP
import re

_AMOUNT = r"(?:\$?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|thousand|billion|[km]))?|(?:a|one)\s+(?:million|thousand|billion))(?:\s+dollars)?"
_SCALES = {'thousand': 1000, 'k': 1000, 'million': 1000000, 'm': 1000000, 'billion': 1000000000}
_AMOUNT_RE = re.compile(r"(?<![\w])(" + _AMOUNT + r")(?![\w])", re.I)
_CONVERSION = re.compile(
    r"(?:to (?:reach|hit)\s+)?(?P<annual>" + _AMOUNT + r")\s+(?:a|per) year"
    r"(?:\s+in (?:annual )?revenue)?\s+(?:is|means|requires|would mean|would require)\s+"
    r"(?P<approx>about|roughly|approximately)?\s*(?P<monthly>" + _AMOUNT + r")\s+"
    r"(?:a|per) month(?:\s+in (?:monthly |recurring )?revenue)?[.!]?", re.I)
_RATE = re.compile(
    r"at\s+(?P<rate>" + _AMOUNT + r")(?:\s+(?:a month|per month|monthly))?\s*,?\s+"
    r"(?:(?:you(?:'d| would)?|we(?:'d| would)?)\s+need\s+)?"
    r"(?P<approx>about|roughly|approximately)\s+(?P<count>\d[\d,]*)"
    r"(?:\s+(?:paying )?(?:users|subscribers|customers|members|clients))?[.!]?", re.I)


def amount(text):
    value = re.sub(r"[,$]|\bdollars\b", "", text.lower()).strip()
    match = re.fullmatch(r"(a|one|\d+(?:\.\d+)?)\s*(thousand|million|billion|k|m)?", value)
    if not match:
        return None
    number = Decimal(1) if match[1] in ('a', 'one') else Decimal(match[1])
    return number * _SCALES.get(match[2], 1)


def owner_amounts(sources):
    return {amount(m[1]) for s in sources.values()
            if s.get('kind') == 'conversation' and s.get('role') == 'user'
            for m in _AMOUNT_RE.finditer(s.get('text') or '')} - {None}


def _matches(actual, expected, approximate):
    if actual == expected:
        return True
    if not approximate or expected <= 0:
        return False
    # Explicit rounding to units/tens/hundreds, within one percent. This
    # accepts 83,300 for 1,000,000/12 and 280 for 1,000,000/12/299;
    # an unrelated or materially wrong projection still fails.
    return abs(actual - expected) / expected <= Decimal('0.01') and any(
        actual == expected.quantize(Decimal(q), rounding=ROUND_HALF_UP)
        for q in ('1', '1E1', '1E2'))


def verified_figures(text, reply, sources):
    """Return figures only for a whole recognized, verified calculation sentence."""
    owned = owner_amounts(sources)
    sentence = text.strip()
    conversion = _CONVERSION.fullmatch(sentence)
    if conversion:
        annual, monthly = amount(conversion['annual']), amount(conversion['monthly'])
        if annual in owned and _matches(monthly, annual / 12, conversion['approx']):
            return {annual, monthly}
        return set()
    rate = _RATE.fullmatch(sentence)
    if not rate or amount(rate['rate']) not in owned:
        return set()
    price, count = amount(rate['rate']), Decimal(rate['count'].replace(',', ''))
    if price <= 0:
        return set()
    # The draft must state the annual-to-monthly assumption and that
    # conversion must itself check out. Assistant history is not input.
    for part in re.split(r'(?<=[.!?])\s+|\n+', reply):
        basis = _CONVERSION.fullmatch(part.strip())
        if basis and verified_figures(part, '', sources):
            monthly = amount(basis['annual']) / 12
            if _matches(count, monthly / price, rate['approx']):
                return {price, count}
    return set()
