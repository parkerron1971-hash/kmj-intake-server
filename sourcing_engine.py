"""
sourcing_engine.py — THE SOURCING DESK, stage 1: "who makes this?"
(2026-08-21).

WHAT THIS IS
  A practitioner sells something and needs somebody to make it, print it,
  or wholesale it to them. This runs that search against the live web and
  returns a short, comparable, CITED shortlist.

WHY THERE IS NO VENDOR DATABASE BEHIND IT
  Because the list is not the moat. Google has the list. What nobody else
  in this price band can do is know what the practitioner sells, at what
  price, in what volume — and turn that into a search worth running and,
  in stage 2, an RFQ a real manufacturer answers. So this layer stays
  thin on purpose: no directory to curate, no rows to re-verify forever,
  and no implied endorsement of anyone.

THE RULE THIS MODULE EXISTS TO ENFORCE
  **Every candidate must carry a source_url that came back from an actual
  web search in THIS run. No citation, no card.**

  That is enforced in code — `_surviving()` intersects what the model
  wrote against `_harvest_sources()`, the URLs Anthropic's search tool
  actually returned — and NOT by asking the model nicely in a prompt. A
  plausible-looking manufacturer with an invented address is strictly
  worse than an empty result: it is an empty-state-that-lies with a wire
  transfer attached. A prompt instruction is a request; a set
  intersection is a guarantee.

WHY TWO CALLS AND NOT ONE
  Pass 1 searches and reasons, and its output is prose — that is what a
  model with a live search tool is good at. Pass 2 turns that prose into
  the exact JSON shape with `output_config.format`, which cannot drift.
  Doing both in one call means asking for a rigid schema from the same
  turn that is making judgement calls over messy search results, and the
  turn that loses is the schema. The second pass is also where the model
  is told the citation list, so it cannot cite anything else.

WHY THE RAW HTTP PAYLOAD AND NOT THE SDK
  requirements.txt pins anthropic==0.34.2. Wire features newer than that
  pin (`output_config`, adaptive thinking, the 2026 web-search tool) do
  not exist as typed kwargs in it. Every heavy call in this service
  already goes out as a payload dict through llm_call — the model seam —
  so it is version-independent by construction, metered for free, and
  redirectable by one env var. Same path as chief_of_staff.

COST SHAPE
  Up to `_MAX_SEARCHES` live searches plus two model calls per run. The
  router gates it with billing_limits.require_units (an AI action, every
  tier) and a per-business daily cap. This module never charges anything
  itself.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

import llm_call

logger = logging.getLogger("sourcing_engine")

# The model that does the judging. Vendor sourcing is a reasoning task
# over messy, adversarial search results (page one of "hoodie
# manufacturer" is aggregator farms), so it gets the strong model rather
# than the cheap one.
SOURCING_MODEL = "claude-opus-5"

# The search tool's own budget. Chief's chat turn is capped at 3 uses,
# which is right for "look that up mid-conversation" and far too small
# for a real sweep — so this path has its own and does not raid Chief's.
_MAX_SEARCHES = 6

_PASS1_MAX_TOKENS = 16000
_PASS2_MAX_TOKENS = 8000
_TIMEOUT = 180.0

# Better three real ones than twelve padded to look thorough. Padding is
# how a tool like this becomes untrustworthy in a single session.
MAX_CANDIDATES = 8

_CANDIDATE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "website": {"type": "string"},
                    "source_url": {"type": "string"},
                    "why": {"type": "string"},
                    "moq": {"type": "string"},
                    "region": {"type": "string"},
                    "contact_route": {"type": "string"},
                },
                "required": ["name", "website", "source_url", "why",
                             "moq", "region", "contact_route"],
                "additionalProperties": False,
            },
        },
        "coverage_note": {"type": "string"},
    },
    "required": ["candidates", "coverage_note"],
    "additionalProperties": False,
}


# ─── The rubric ──────────────────────────────────────────────────────
#
# A rubric, not a lookup table of known suppliers by industry: a table is
# wrong for the seventh vertical and silently wrong for the eighth. This
# describes what a real candidate LOOKS like, so it generalizes to a
# barber's pomade distributor and a nonprofit's printer without either
# ever being enumerated.

_PASS1_SYSTEM = """You are a sourcing researcher for a small business. \
Your job is to find real companies that could SUPPLY what this business \
sells — manufacturers, wholesalers, distributors, printers, packaging \
suppliers, fulfilment. Whoever actually fits the need.

USE THE WEB SEARCH TOOL. You cannot do this from memory, and a company \
you remember is a company you might be inventing.

WHAT COUNTS AS A CANDIDATE (all four, or leave it out):
1. It is reachable at its OWN domain — not only as a listing on an \
aggregator or directory.
2. It plainly supplies at trade level: it states wholesale/trade/OEM/ \
private-label terms, quotes minimums, or is obviously a maker rather \
than a retailer.
3. There is a contact route a human can actually use — an address, a \
form, a phone number, a quote request.
4. It is not an SEO farm, a lead-broker, or a directory-of-directories.

WHAT TO AVOID
- Marketplace aggregator pages standing in for a company.
- Retailers who would sell them one at retail price.
- Any company you cannot point at a specific page for.

HOW MANY
Return the ones that genuinely fit. THREE GOOD ONES BEATS TWELVE. Never \
pad the list to look thorough — a padded list is the fastest way to make \
this feature untrustworthy. If the honest answer is "the open web does \
not cover this well", say that.

WRITE UP, for each candidate: the company name, its website, THE EXACT \
URL FROM YOUR SEARCH RESULTS where you found it, one line on why it fits \
THIS need, any minimum order you saw, roughly where it is, and how to \
contact them. If you did not see a minimum, say so — do not guess one.

Then write a short, honest coverage note: how well the open web covers \
this kind of supplier, and what would beat it. For niche, regulated or \
trade-show-driven goods the honest answer is often that a trade \
association or a show beats an open web search, and saying so is more \
useful than a padded list.

You are FINDING options, not recommending or vetting anyone. The \
practitioner checks them out and signs the contract. Never describe a \
company as trustworthy, verified, or recommended."""

_PASS2_SYSTEM = """Convert the research notes into the exact JSON schema.

RULES:
- `source_url` MUST be copied EXACTLY, character for character, from the \
ALLOWED SOURCE URLS list you are given. Do not shorten it, tidy it, \
strip parameters, or substitute the company's home page. A candidate \
whose URL is not in that list will be DISCARDED, so if the notes do not \
tie a candidate to one of those URLs, leave that candidate out.
- Never invent a company that is not in the notes.
- Use "" for anything the notes do not state — especially `moq`. Never \
guess a minimum order.
- `why` is one short sentence about why it fits this need.
- Keep the coverage note as written; do not make it more optimistic."""


def _norm_url(u: str) -> str:
    """Compare URLs by host+path, case- and trailing-slash-insensitively.

    Deliberately ignores query and fragment. The model routinely echoes a
    result URL back with tracking parameters dropped, and rejecting a
    real citation over `?utm_source=` would fail closed against the
    honest case while catching nothing — an invented URL does not
    accidentally share a host AND path with a real result.
    """
    try:
        s = urlsplit((u or "").strip())
        host = (s.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (s.path or "").rstrip("/").lower()
        return f"{host}{path}"
    except Exception:
        return (u or "").strip().lower()


def _blocks(data: Any) -> List[Any]:
    content = (data or {}).get("content") if isinstance(data, dict) else None
    return content if isinstance(content, list) else []


def _text_of(data: Any) -> str:
    out = []
    for b in _blocks(data):
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text") or "")
    return "".join(out)


def _harvest_sources(data: Any) -> List[str]:
    """Every URL the web search tool actually returned.

    A server-tool ERROR does not raise and does not come back as an
    exception — it is a 200 whose result block holds a single error
    object instead of a list of results (`{"error_code": ...}`).

    Two distinct shapes have to survive, and only one of them is loud.
    An error DICT iterates as its keys, so it would quietly yield
    nothing — wrong but silent. A missing or null `content` raises
    TypeError, mid-way through a request the practitioner has already
    paid for. The isinstance check covers both, and turns the silent
    case into a log line that says a search failed.
    """
    urls: List[str] = []
    for b in _blocks(data):
        if not isinstance(b, dict) or b.get("type") != "web_search_tool_result":
            continue
        content = b.get("content")
        if not isinstance(content, list):
            # The error shape. Nothing to harvest; the run continues and
            # simply finds fewer sources, which the caller can see.
            logger.info("[sourcing] search result carried an error: %s", content)
            continue
        for r in content:
            if isinstance(r, dict) and r.get("url"):
                urls.append(str(r["url"]))
    # De-duplicate, keep order — the first appearance is the one the
    # model most likely quoted.
    seen: Set[str] = set()
    out: List[str] = []
    for u in urls:
        k = _norm_url(u)
        if k and k not in seen:
            seen.add(k)
            out.append(u)
    return out


def _surviving(candidates: List[Dict[str, Any]],
               sources: List[str]) -> Tuple[List[Dict[str, Any]], int]:
    """THE CITATION GATE. Keep only candidates whose source_url really
    came back from this run's search. Returns (kept, dropped_count).

    This is the whole anti-hallucination guarantee, and it is a set
    intersection rather than a prompt instruction on purpose.
    """
    allowed = {_norm_url(u): u for u in sources}
    kept: List[Dict[str, Any]] = []
    dropped = 0
    seen: Set[str] = set()
    for c in candidates:
        if not isinstance(c, dict):
            dropped += 1
            continue
        name = (c.get("name") or "").strip()
        url = (c.get("source_url") or "").strip()
        key = _norm_url(url)
        if not name or not key or key not in allowed:
            dropped += 1
            continue
        # One card per company. Two results from the same domain for the
        # same vendor is a duplicate, not a second option.
        dedup = _norm_url(c.get("website") or "").split("/")[0] or name.lower()
        if dedup in seen:
            dropped += 1
            continue
        seen.add(dedup)
        kept.append({
            "name": name,
            "website": (c.get("website") or "").strip(),
            # Store the URL as the SEARCH returned it, not as the model
            # retyped it — the search result is the authority.
            "source_url": allowed[key],
            "why": (c.get("why") or "").strip(),
            "moq": (c.get("moq") or "").strip(),
            "region": (c.get("region") or "").strip(),
            "contact_route": (c.get("contact_route") or "").strip(),
        })
    return kept[:MAX_CANDIDATES], dropped


def _need_line(need: str, region: Optional[str], qty: Optional[int],
               budget: Optional[float], context: Optional[str]) -> str:
    bits = [f"What they need to source: {need.strip()}"]
    if qty:
        bits.append(f"Rough volume: {qty} units per order.")
    if budget:
        bits.append(f"Target cost: about ${budget:.2f} per unit.")
    if region:
        bits.append(f"Preferred region: {region.strip()}.")
    if context:
        bits.append(f"About the business: {context.strip()}")
    bits.append("Search the web and write up who could supply this.")
    return "\n".join(bits)


def _post(payload: Dict[str, Any]) -> Tuple[bool, Any]:
    resp = llm_call.post(payload, timeout=_TIMEOUT, task="sourcing")
    if resp.status_code != 200:
        logger.warning("[sourcing] model call %s: %s",
                       resp.status_code, resp.text[:400])
        return False, None
    try:
        return True, resp.json()
    except Exception:
        return False, None


def search_vendors(*, need: str,
                   region: Optional[str] = None,
                   qty: Optional[int] = None,
                   budget_per_unit: Optional[float] = None,
                   business_context: Optional[str] = None) -> Dict[str, Any]:
    """Run one sourcing search.

    Never raises for a model or search failure — returns a result whose
    `candidates` is empty and whose `coverage_note` says what happened.
    An empty shortlist is a true answer; an exception on a paid action is
    just a 500 the practitioner cannot act on.
    """
    empty: Dict[str, Any] = {
        "candidates": [], "sources": [], "coverage_note": "",
        "proposed_count": 0, "dropped_count": 0, "model": SOURCING_MODEL,
    }

    # ── Pass 1: search the live web and reason about what came back ──
    ok, data = _post({
        "model": SOURCING_MODEL,
        "max_tokens": _PASS1_MAX_TOKENS,
        "system": _PASS1_SYSTEM,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
        "tools": [{
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": _MAX_SEARCHES,
        }],
        "messages": [{
            "role": "user",
            "content": _need_line(need, region, qty, budget_per_unit,
                                  business_context),
        }],
    })
    if not ok:
        return {**empty,
                "coverage_note": "The search couldn't run just now. "
                                 "Nothing was charged for it — try again in a moment."}

    notes = _text_of(data)
    sources = _harvest_sources(data)
    if not sources:
        # No search results means nothing can pass the citation gate, so
        # there is no point paying for pass 2 to produce cards that will
        # all be discarded.
        return {**empty,
                "coverage_note": "The web search came back with nothing usable for "
                                 "this one. That happens with very niche or very "
                                 "new products — a trade association or a trade "
                                 "show is usually the better route there."}

    # ── Pass 2: the same findings, in a shape that cannot drift ──
    allowed_list = "\n".join(f"- {u}" for u in sources)
    ok2, data2 = _post({
        "model": SOURCING_MODEL,
        "max_tokens": _PASS2_MAX_TOKENS,
        "system": _PASS2_SYSTEM,
        "output_config": {
            "effort": "low",
            "format": {"type": "json_schema", "schema": _CANDIDATE_SCHEMA},
        },
        "messages": [{
            "role": "user",
            "content": (f"RESEARCH NOTES:\n{notes}\n\n"
                        f"ALLOWED SOURCE URLS (copy exactly, nothing else "
                        f"is accepted):\n{allowed_list}"),
        }],
    })
    if not ok2:
        return {**empty, "sources": sources,
                "coverage_note": "The search ran but the results couldn't be "
                                 "read back cleanly. Try again in a moment."}

    try:
        parsed = json.loads(_text_of(data2))
    except Exception:
        logger.warning("[sourcing] pass 2 was not valid JSON")
        return {**empty, "sources": sources,
                "coverage_note": "The search ran but the results couldn't be "
                                 "read back cleanly. Try again in a moment."}

    proposed = parsed.get("candidates")
    proposed = proposed if isinstance(proposed, list) else []
    kept, dropped = _surviving(proposed, sources)

    note = (parsed.get("coverage_note") or "").strip()
    if dropped:
        # Said out loud rather than swallowed. A silent trim reads as
        # "this is everything there is", which is the lie this whole
        # module is built to avoid.
        note = (note + " " if note else "") + (
            f"{dropped} more {'was' if dropped == 1 else 'were'} left out because "
            f"{'it' if dropped == 1 else 'they'} couldn't be traced back to a real "
            f"page from this search.")
    if not kept and not note:
        note = ("Nothing here cleared the bar of being a real, reachable supplier "
                "for this. That is a real answer, not an error.")

    return {
        "candidates": kept,
        "sources": sources,
        "coverage_note": note.strip(),
        "proposed_count": len(proposed),
        "dropped_count": dropped,
        "model": SOURCING_MODEL,
    }
