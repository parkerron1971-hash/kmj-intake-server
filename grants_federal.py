"""
grants_federal.py — THE FEDERAL LANE (2026-08-28).

Grants.gov is the only comprehensive, free, structured source of federal
funding opportunities, and its search API needs no key and no account:

    POST https://api.grants.gov/v1/api/search2      list opportunities
    POST https://api.grants.gov/v1/api/fetchOpportunity   one, in full

That it costs nothing changes the product, not just the bill. A lane
with no per-call price can run on a schedule and PUSH — "three new
opportunities matched you this week" — instead of waiting to be asked,
and it must not be metered, because metering a free search teaches a
practitioner that looking is expensive.

FOUR THINGS THE LIVE API DOES THAT THE DOCS DO NOT MENTION, each of
which is a bug if you assume otherwise (all four verified by calling it,
2026-08-28):

  1. FAILURE ARRIVES INSIDE A 200. Every response carries `errorcode`
     and `msg`; a failed search is `HTTP 200` with a non-zero errorcode
     and an EMPTY `oppHits`. Trusting the status code turns "the search
     broke" into "there are no grants for you", which is the empty-state
     lie in its most expensive form — a practitioner concludes their
     organisation does not qualify for anything.

  2. TEXT IS HTML-ESCAPED, TWICE OVER. Titles come back with `&rsquo;`
     and `&ndash;` in them, and `synopsisDesc` is a block of raw HTML.
     Unescaped, a card reads "Bosnia and Herzegovina&rsquo;s".

  3. THE TWO ENDPOINTS DATE DIFFERENTLY. search2 gives `"09/28/2026"`;
     fetchOpportunity gives `"Sep 28, 2026 12:00:00 AM EDT"`. A single
     parser that only knows one of them silently drops every deadline
     from the other, and a grant with no deadline sorts as if it had all
     the time in the world.

  4. THERE IS NO URL IN THE PAYLOAD. The opportunity's public page is
     built from its id. We link to grants.gov's own detail page and
     never to a page of ours describing it, because the funder's words
     are the authority and a practitioner has to be able to check us.

HOW THE RULED-OUT TRAY IS BUILT WITHOUT AN N+1

  search2's hit rows carry no applicant-eligibility codes — only
  fetchOpportunity does, one opportunity per HTTP call. Annotating
  twenty-five hits that way is twenty-five round trips.

  So the eligibility question is asked of the SEARCH instead, twice: one
  call filtered to the codes this organisation actually is, one call
  unfiltered. The filtered ids are the matches; everything in the
  unfiltered set that is missing from the filtered one is ruled out, and
  the reason is known without asking — this funder did not list your
  applicant type. Two calls, whatever the page size.

  Ruled out is RETURNED, never dropped. A count of what was hidden is
  the thing that makes a search trustworthy, and "you are ineligible for
  six of these, here is which" is worth more than four hopeful cards.

WHAT THIS MODULE WILL NOT DO

  It does not rank, score or recommend. It reports what the funder said
  and what this organisation is, and it lets the difference between them
  speak. There is no percentage, because a percentage would be a number
  we cannot defend line by line.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

logger = logging.getLogger("grants_federal")

SEARCH_URL = "https://api.grants.gov/v1/api/search2"
FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
# The opportunity's own page on grants.gov. Verified 200 for a live id.
DETAIL_URL = "https://grants.gov/search-results-detail/{id}"

HTTP_TIMEOUT = 20.0
MAX_ROWS = 50
DEFAULT_ROWS = 25

# ─── Applicant eligibility codes ─────────────────────────────────────
#
# The complete list, read off a live unfiltered search rather than a doc
# page, so it cannot drift from what the API will actually accept.

ELIGIBILITY_LABELS: Dict[str, str] = {
    "00": "State governments",
    "01": "County governments",
    "02": "City or township governments",
    "04": "Special district governments",
    "05": "Independent school districts",
    "06": "Public and State controlled institutions of higher education",
    "07": "Native American tribal governments (Federally recognized)",
    "08": "Public housing authorities/Indian housing authorities",
    "11": "Native American tribal organizations (other than Federally recognized)",
    "12": "Nonprofits having a 501(c)(3) status with the IRS",
    "13": "Nonprofits without a 501(c)(3) status with the IRS",
    "20": "Private institutions of higher education",
    "21": "Individuals",
    "22": "For profit organizations other than small businesses",
    "23": "Small businesses",
    "25": "Others (see the notice's eligibility text)",
    "99": "Unrestricted — open to any type of entity",
}

# "99" means the funder placed no entity-type restriction at all, so it
# is eligible for EVERYONE. It is added to every filter rather than being
# something a practitioner has to know to ask for; leaving it out would
# rule an organisation out of the least restrictive grants on the board.
UNRESTRICTED = "99"

# Our profile's applicant_type → the codes that entitle them to apply.
# Keys mirror funderProfile.APPLICANT_TYPES on the frontend.
APPLICANT_TYPE_CODES: Dict[str, Tuple[str, ...]] = {
    "nonprofit_501c3": ("12",),
    "nonprofit_other": ("13",),
    # A fiscally sponsored project is not itself the applicant — its
    # sponsor is, and the sponsor holds the 501(c)(3). So both codes
    # apply, and the caller is told WHY rather than being quietly given a
    # wider net than it asked for: an award here is made to the sponsor.
    "fiscally_sponsored": ("12", "13"),
    "government_local": ("01", "02", "04"),
    "government_state": ("00",),
    "tribal": ("07", "11"),
    "education": ("05", "06", "20"),
    "for_profit": ("22", "23"),
    "individual": ("21",),
}

# Said on the card when the wider net is used, so nobody discovers it in
# a rejection letter.
APPLICANT_TYPE_NOTES: Dict[str, str] = {
    "fiscally_sponsored": (
        "Searched as both a 501(c)(3) and a non-501(c)(3) nonprofit. Your "
        "fiscal sponsor is the applicant of record and the award is made "
        "to them — check that they are willing before you build a budget."
    ),
}


class GrantsUnavailable(RuntimeError):
    """The lane could not answer. Deliberately distinct from an empty
    result: the caller must be able to say "the search broke" rather
    than "you match nothing"."""


# ─── Text and dates ──────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
# Every whitespace character EXCEPT a newline, which paragraphs need.
# Written as a negated class rather than a literal list because agency
# text is full of `&nbsp;` — which decodes to U+00A0, is invisible, does
# not wrap, and would survive a `[ \t]+` collapse to sit inside a title
# looking exactly like a space that behaves wrongly.
_WS = re.compile(r"[^\S\n]+")


def clean_text(value: Any, limit: int = 4000) -> str:
    """Entity-decode, strip tags, collapse runs of spaces.

    Unescaped TWICE on purpose: agency-authored fields arrive
    double-encoded often enough (`&amp;rsquo;`) that one pass leaves a
    visible `&rsquo;` on the card. A third pass buys nothing, and going
    further would start decoding text that legitimately contains an
    ampersand-word."""
    if value is None:
        return ""
    text = html.unescape(html.unescape(str(value)))
    text = _TAG.sub(" ", text)
    text = _WS.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


# search2: "09/28/2026". fetchOpportunity: "Sep 28, 2026 12:00:00 AM EDT".
_DATE_FORMATS = ("%m/%d/%Y", "%b %d, %Y %I:%M:%S %p", "%b %d, %Y", "%Y-%m-%d")


def parse_date(value: Any) -> Optional[str]:
    """Any of the API's date shapes → ISO `yyyy-mm-dd`, or None.

    None is a real answer and must stay distinguishable from a date: a
    forecast frequently has no close date at all, and inventing one
    would be the worst thing this module could do."""
    if not value:
        return None
    raw = str(value).strip()
    # The trailing timezone abbreviation is not parseable by %Z across
    # platforms, so it comes off before the formats are tried.
    raw = re.sub(r"\s+[A-Z]{2,4}$", "", raw)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def days_until(iso_date: Optional[str], today: Optional[datetime] = None) -> Optional[int]:
    if not iso_date:
        return None
    try:
        when = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    now = (today or datetime.now(timezone.utc)).date()
    return (when - now).days


# ─── The cache ───────────────────────────────────────────────────────
#
# Federal opportunities change on a daily cadence at best, so a search
# repeated within the hour should not become a request. Keyed on the
# exact query, bounded, and in-process: this is a courtesy to a public
# API and a latency win, NOT a correctness mechanism, so a cold worker
# simply asks again.

_CACHE_TTL = 3600.0
_CACHE_MAX = 256
_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_key(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        when, value = hit
        if time.time() - when > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        return value


def _cache_put(key: str, value: Any) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            # Oldest first. A plain dict is insertion-ordered, and this
            # runs a few times a day.
            for old in list(_cache.keys())[: max(1, _CACHE_MAX // 4)]:
                _cache.pop(old, None)
        _cache[key] = (time.time(), value)


def clear_cache() -> None:
    """Tests, and anything that needs a cold read."""
    with _cache_lock:
        _cache.clear()


# ─── The wire ────────────────────────────────────────────────────────


def _post(url: str, payload: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
    """One call, with the errorcode check that a status code does not do."""
    key = _cache_key({"url": url, **payload})
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            res = client.post(url, json=payload,
                              headers={"Content-Type": "application/json"})
    except Exception as e:  # network, DNS, timeout
        logger.warning("[grants] %s unreachable: %s", url, e)
        raise GrantsUnavailable("Grants.gov did not answer") from e

    if res.status_code != 200:
        logger.warning("[grants] %s returned HTTP %s", url, res.status_code)
        raise GrantsUnavailable(f"Grants.gov returned HTTP {res.status_code}")

    try:
        body = res.json()
    except Exception as e:
        raise GrantsUnavailable("Grants.gov sent something that was not JSON") from e

    # THE CHECK THAT MATTERS. A 200 with errorcode 1 and no hits is a
    # broken search, not an empty one.
    code = body.get("errorcode")
    if code not in (0, "0", None):
        msg = clean_text(body.get("msg")) or "no reason given"
        logger.warning("[grants] errorcode=%s msg=%s", code, msg)
        raise GrantsUnavailable(f"Grants.gov refused the search: {msg}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise GrantsUnavailable("Grants.gov sent no data block")

    if use_cache:
        _cache_put(key, data)
    return data


# ─── Normalising one opportunity ─────────────────────────────────────


def normalize_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    """One search2 row → the shape the grants board stores.

    Every field is either present and true or absent. Nothing is filled
    with a placeholder, because a placeholder in a deadline field is a
    month of work planned against a date nobody promised."""
    opp_id = str(hit.get("id") or "").strip()
    close_iso = parse_date(hit.get("closeDate"))
    status = clean_text(hit.get("oppStatus")).lower() or "posted"
    out: Dict[str, Any] = {
        "opportunity_id": opp_id,
        "number": clean_text(hit.get("number"), 120),
        "title": clean_text(hit.get("title"), 400),
        "agency": clean_text(hit.get("agency"), 200),
        "agency_code": clean_text(hit.get("agencyCode"), 60),
        "open_date": parse_date(hit.get("openDate")),
        "close_date": close_iso,
        "days_to_close": days_until(close_iso),
        "status": status,
        # A forecast is an INTENTION, not an opportunity. It gets its own
        # flag so a card can say so — planning a submission against a
        # forecast date as though it were firm is the mistake this
        # prevents, and it is a common one.
        "is_forecast": status == "forecasted",
        "aln": [clean_text(c, 20) for c in (hit.get("cfdaList") or []) if c],
        "source_lane": "federal",
        "source_url": DETAIL_URL.format(id=opp_id) if opp_id else None,
    }
    return out


def enrich(opp_id: str, use_cache: bool = True) -> Dict[str, Any]:
    """fetchOpportunity → the fields a search row does not carry.

    Called for ONE opportunity at a time, when a practitioner opens it —
    never in a loop over a result page."""
    data = _post(FETCH_URL, {"opportunityId": int(opp_id)}, use_cache=use_cache)
    syn = data.get("synopsis") or {}
    types = [
        {"code": str(t.get("id") or "").zfill(2),
         "label": clean_text(t.get("description"), 200)}
        for t in (syn.get("applicantTypes") or [])
        if t.get("id") is not None
    ]
    close_iso = parse_date(syn.get("responseDate"))
    return {
        "opportunity_id": str(data.get("id") or opp_id),
        "title": clean_text(data.get("opportunityTitle"), 400),
        "number": clean_text(data.get("opportunityNumber"), 120),
        "agency": clean_text(syn.get("agencyName"), 200),
        "description": clean_text(syn.get("synopsisDesc"), 6000),
        "close_date": close_iso,
        "days_to_close": days_until(close_iso),
        "open_date": parse_date(syn.get("postingDate")),
        "award_ceiling": syn.get("awardCeiling"),
        "award_floor": syn.get("awardFloor"),
        "estimated_funding": syn.get("estimatedFunding"),
        "number_of_awards": syn.get("numberOfAwards"),
        # The API answers this as a boolean, which is exactly the field
        # the award desk needs to know a cost-share obligation exists.
        "match_required": bool(syn.get("costSharing")),
        "applicant_types": types,
        # Often empty. When it is not, it is the prose gate — the thing
        # no code can decide and a person must read.
        "eligibility_note": clean_text(syn.get("applicantEligibilityDesc"), 4000),
        "agency_contact_email": clean_text(syn.get("agencyContactEmail"), 200),
        "source_lane": "federal",
        "source_url": DETAIL_URL.format(id=data.get("id") or opp_id),
    }


# ─── The search ──────────────────────────────────────────────────────


def codes_for_applicant_type(applicant_type: Optional[str]) -> List[str]:
    """The eligibility codes to filter on, always including the
    unrestricted one. Empty when we do not know what they are — and an
    empty filter must mean "do not filter", never "match nothing"."""
    if not applicant_type:
        return []
    codes = APPLICANT_TYPE_CODES.get(applicant_type)
    if not codes:
        return []
    return sorted({*codes, UNRESTRICTED})


def _search_once(keyword: str, statuses: str, rows: int,
                 eligibilities: Optional[List[str]] = None,
                 agencies: Optional[str] = None,
                 use_cache: bool = True) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "keyword": keyword,
        "oppStatuses": statuses,
        "rows": rows,
    }
    if eligibilities:
        payload["eligibilities"] = "|".join(eligibilities)
    if agencies:
        payload["agencies"] = agencies
    return _post(SEARCH_URL, payload, use_cache=use_cache)


def search(keyword: str,
           applicant_type: Optional[str] = None,
           include_forecasts: bool = True,
           rows: int = DEFAULT_ROWS,
           agencies: Optional[str] = None,
           use_cache: bool = True) -> Dict[str, Any]:
    """The federal lane.

    Returns matches, the ruled-out tray with its reason, and a coverage
    note. Raises GrantsUnavailable if the lane could not answer — the
    caller must not turn that into an empty list.
    """
    keyword = (keyword or "").strip()
    rows = max(1, min(int(rows or DEFAULT_ROWS), MAX_ROWS))
    statuses = "posted|forecasted" if include_forecasts else "posted"
    codes = codes_for_applicant_type(applicant_type)

    # The unfiltered set is asked for first, because it is the one that
    # must exist for the answer to mean anything: without it there is no
    # denominator and no ruled-out tray.
    everything = _search_once(keyword, statuses, rows, agencies=agencies,
                              use_cache=use_cache)
    all_hits = [h for h in (everything.get("oppHits") or []) if isinstance(h, dict)]

    matches: List[Dict[str, Any]]
    ruled_out: List[Dict[str, Any]]
    gates_decided = bool(codes)

    if not gates_decided:
        # We do not know what they are, so nothing is ruled out — and the
        # caller is told the gates are UNDECIDED rather than passed.
        matches = [normalize_hit(h) for h in all_hits]
        ruled_out = []
    else:
        eligible = _search_once(keyword, statuses, rows, eligibilities=codes,
                                agencies=agencies, use_cache=use_cache)
        eligible_ids = {
            str(h.get("id")) for h in (eligible.get("oppHits") or [])
            if isinstance(h, dict)
        }
        matches, ruled_out = [], []
        for hit in all_hits:
            row = normalize_hit(hit)
            if str(hit.get("id")) in eligible_ids:
                matches.append(row)
            else:
                row["ruled_out_because"] = (
                    "This funder did not list your applicant type "
                    f"({_applicant_label(applicant_type)}) as eligible."
                )
                ruled_out.append(row)

    # Deadline first. A grant is a date with money attached, and the one
    # closing on Friday is the only one that matters on Thursday. Rows
    # with no close date sort last rather than first — an unknown
    # deadline is not an urgent one.
    matches.sort(key=lambda r: (r["close_date"] is None, r["close_date"] or ""))
    ruled_out.sort(key=lambda r: (r["close_date"] is None, r["close_date"] or ""))

    return {
        "matches": matches,
        "ruled_out": ruled_out,
        "total_available": int(everything.get("hitCount") or 0),
        "returned": len(all_hits),
        "gates_decided": gates_decided,
        "applicant_type": applicant_type,
        "applicant_type_note": APPLICANT_TYPE_NOTES.get(applicant_type or ""),
        "eligibility_codes_used": codes,
        "coverage_note": _coverage_note(
            total=int(everything.get("hitCount") or 0),
            returned=len(all_hits),
            gates_decided=gates_decided,
            include_forecasts=include_forecasts,
        ),
        "source": "Grants.gov",
    }


def _applicant_label(applicant_type: Optional[str]) -> str:
    codes = APPLICANT_TYPE_CODES.get(applicant_type or "") or ()
    labels = [ELIGIBILITY_LABELS.get(c, c) for c in codes]
    return " or ".join(labels) if labels else "your applicant type"


def _coverage_note(total: int, returned: int, gates_decided: bool,
                   include_forecasts: bool) -> str:
    """What this lane does NOT cover, said every time.

    The most useful sentence on the screen is the one that stops a
    practitioner believing an empty federal result means there is no
    money for them. State, county, community-foundation and corporate
    giving are most of the money most small nonprofits ever raise, and
    none of it is here."""
    parts = ["Federal opportunities only, from Grants.gov."]
    if total > returned:
        parts.append(f"Showing {returned} of {total} — narrow the search to see more.")
    if include_forecasts:
        parts.append("Forecasts are included and marked; their dates are intentions, not deadlines.")
    if not gates_decided:
        parts.append(
            "Your applicant type is not on file, so nothing here has been "
            "checked against your eligibility yet."
        )
    parts.append(
        "State, city, community-foundation and corporate funders are not in "
        "this lane."
    )
    return " ".join(parts)
