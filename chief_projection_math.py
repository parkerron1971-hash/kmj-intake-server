"""Bounded arithmetic for explicitly hypothetical annual/monthly target explanations.

These are calculations on owner-supplied inputs, never evidence of earned
revenue or current subscribers. No model, database, or business mutation.
"""
from decimal import Decimal, ROUND_HALF_UP
import re

_AMOUNT = r"(?:\$?\d(?:[\d,]*\d)?(?:\.\d+)?(?:\s*(?:million|thousand|billion|[km]))?|(?:a|one)\s+(?:million|thousand|billion))(?:\s+dollars)?"
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


# Keep the units attached to the inputs. A traffic target or annual price
# must never become a revenue target or monthly subscription assumption.
_YEAR = r"(?:(?:a|per|each) year|(?:in|over) (?:one|1|the next) year|annually)"
_TARGET = r"(?:make|earn|collect|generate|reach|(?:(?:revenue|income|sales) )?(?:goal|target)(?: is)?)[ :]*"
_ANNUAL_TARGET = re.compile(
    r"\b" + _TARGET + r"(?P<amount>" + _AMOUNT + r")\s+"
    r"(?:(?:in )?(?:revenue|income|sales)\s+)?" + _YEAR + r"\b", re.I)
_ANNUAL_PREFIX = re.compile(
    r"\b(?:annual|yearly) (?:(?:revenue|income|sales) )?(?:goal|target)(?: is)?[ :]*"
    r"(?P<amount>" + _AMOUNT + r")", re.I)
_MONTHLY_RATE = re.compile(
    r"(?P<amount>" + _AMOUNT + r")\s+(?:(?:a|per|each) month|monthly)\b", re.I)
_MONTHLY_LIST = re.compile(
    r"\bmonthly (?:prices|tiers|plans|rates)(?: are| cost| at| of)?[ :]*"
    r"(?P<amounts>" + _AMOUNT + r"(?:(?:\s*,\s*|\s+and\s+)" + _AMOUNT + r")*)", re.I)
_NEGATED = re.compile(r"\b(?:not|never|instead)\b|n['\u2019]t\b", re.I)


def owner_inputs(sources):
    annual, monthly = set(), set()
    for source in sources.values():
        if source.get('kind') != 'conversation' or source.get('role') != 'user':
            continue
        for clause in re.split(r'(?<=[.!?;])\s+|\n+', source.get('text') or ''):
            if _NEGATED.search(clause):
                continue
            for pattern in (_ANNUAL_TARGET, _ANNUAL_PREFIX):
                for match in pattern.finditer(clause):
                    raw = match['amount']
                    if '$' in raw or 'dollars' in raw.lower():
                        annual.add(amount(raw))
            for match in _MONTHLY_RATE.finditer(clause):
                raw = match['amount']
                if '$' in raw or 'dollars' in raw.lower():
                    monthly.add(amount(raw))
            for match in _MONTHLY_LIST.finditer(clause):
                monthly.update(amount(m[1]) for m in _AMOUNT_RE.finditer(match['amounts'])
                               if '$' in m[1] or 'dollars' in m[1].lower())
    return annual - {None}, monthly - {None}


# The model may identify a semantic contradiction as well as missing numeric
# proof. Only its explicit arithmetic-only gap can use this narrow exception.
_ARITHMETIC_GAPS = frozenset({'arithmetic', 'calculation', 'arithmetic calculation',
                             'calculation not in source', 'arithmetic not in source'})


def arithmetic_only_gap(gap):
    return isinstance(gap, str) and gap.strip().lower().rstrip('.') in _ARITHMETIC_GAPS


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
    annual_targets, monthly_rates = owner_inputs(sources)
    sentence = text.strip()
    conversion = _CONVERSION.fullmatch(sentence)
    if conversion:
        annual, monthly = amount(conversion['annual']), amount(conversion['monthly'])
        if annual in annual_targets and _matches(monthly, annual / 12, conversion['approx']):
            return {annual, monthly}
        return set()
    rate = _RATE.fullmatch(sentence)
    if not rate or amount(rate['rate']) not in monthly_rates:
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
