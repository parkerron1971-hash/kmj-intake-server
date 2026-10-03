# site_concept.py
# ─────────────────────────────────────────────────────────────────────
# THE CONCEPT LAYER (2026-10-01, the concept-layer plan, step 4).
#
# The liaisongraphics.com study: the course pages people remember are
# built on ONE idea (the course is a college), carried through the menu,
# the headlines, the buttons, the prices and the photos. Our Director
# already mines the client's world for a LOOK; nothing decided what a
# site is ABOUT, how far that idea should go, or carried it into words
# and objects. This module is that decision.
#
# THE DIAL (Kevin's rulings, 2026-10-01):
#   plain      no concept. The default for health, legal, finance and
#              therapy, and for anyone who asks for simple.
#   signature  one object carries one moment; the rest stays plain. The
#              default for everyone else.
#   world      the idea runs the page: renamed parts, objects as
#              containers, a living detail. Only when the owner picks it.
#   World lives on ONE OFFER PAGE by default (a course, a cohort, a
#   launch) and across the whole site only on request. The owner sees
#   the options as cards in the Design Coach and chooses; nothing is
#   forced.
#
# THE SHEET: the Director writes "0. CONCEPT" at the top of the blueprint
# as labeled lines a practitioner can read and a parser can trust.
# The builder follows it; check_page holds the built page to it on the
# soft tier (a repair round, never the fallback).
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("site_concept")

INTENSITIES = ("plain", "signature", "world")
SCOPES = ("site", "offer")

# The Coach's four cards, and what each one sets.
COACH_KEYS: Dict[str, Tuple[str, str]] = {
    "plain": ("plain", "site"),
    "signature": ("signature", "site"),
    "world-offer": ("world", "offer"),
    "world-site": ("world", "site"),
}

# Trades whose clients come for trust and calm. Their default is plain.
_PLAIN_TRADE_RE = re.compile(
    r"therap|counsel|psycholog|psychiatr|mental health|clinic|medical|"
    r"doctor|physician|dental|dentist|orthodont|chiropract|physio|"
    r"nurs(e|ing)|hospice|pharma|optometr|health ?care|medic\b|"
    r"\blaw\b|legal|attorney|lawyer|notary|paralegal|"
    r"account|\bcpa\b|bookkeep|\btax|payroll|"
    r"financ|insur|wealth|mortgage|\bbank|credit union|investment|"
    r"estate planning",
    re.IGNORECASE)

# Library objects that are layout rather than concept: a plain site may
# still use a shaped seam or underline one word.
_PLAIN_OK_OBJECTS = {"edge", "marker"}


def enabled() -> bool:
    return (os.environ.get("SITE_CONCEPT") or "on").strip().lower() not in (
        "off", "0", "false", "no")


def default_intensity(business_type: str) -> str:
    return "plain" if _PLAIN_TRADE_RE.search(business_type or "") else "signature"


def _leaf(v: Any) -> str:
    if isinstance(v, dict):
        v = v.get("value")
    return str(v or "").strip()


def owner_pick(dossier: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """The card the owner tapped in the Design Coach, or None."""
    taste = ((dossier or {}).get("taste") or {}) if isinstance(dossier, dict) else {}
    key = _leaf(taste.get("concept")).lower()
    if key not in COACH_KEYS:
        return None
    intensity, scope = COACH_KEYS[key]
    return {"key": key, "intensity": intensity, "scope": scope,
            "idea": _leaf(taste.get("concept_idea"))[:300],
            "offer": _leaf(taste.get("concept_offer"))[:160]}


def resolve(ctx: Dict[str, Any]) -> Dict[str, str]:
    """{intensity, scope, idea, offer, by} for this business: the owner's
    pick first, the trade's default otherwise."""
    dd = (((ctx.get("site") or {}).get("site_config") or {})
          .get("discovery_dossier")) or {}
    pick = owner_pick(dd)
    if pick:
        return {**pick, "by": "owner"}
    btype = str((ctx.get("business") or {}).get("type") or "")
    return {"key": default_intensity(btype), "intensity": default_intensity(btype),
            "scope": "site", "idea": "", "offer": "", "by": "default"}


def attach(ctx: Dict[str, Any]) -> Dict[str, str]:
    """Resolve onto ctx for the Director's brief. Fail-open."""
    try:
        if not enabled():
            ctx["concept"] = {"intensity": "plain", "scope": "site", "idea": "",
                              "offer": "", "by": "switched off", "key": "plain"}
        else:
            ctx["concept"] = resolve(ctx)
    except Exception as e:
        logger.info(f"[concept] resolve skipped: {e}")
        ctx["concept"] = {"intensity": "signature", "scope": "site", "idea": "",
                          "offer": "", "by": "default", "key": "signature"}
    return ctx["concept"]


def brief_block(c: Optional[Dict[str, str]]) -> str:
    """THE CONCEPT block for the Director's user prompt."""
    if not c:
        return ""
    who = {"owner": "the owner chose this in the Design Coach",
           "default": "the trade's default; the owner has not chosen",
           }.get(c.get("by", ""), c.get("by", ""))
    lines = ["== THE CONCEPT (how far this site's idea goes) ==",
             f"- intensity: {c.get('intensity')} ({who})"]
    if c.get("intensity") == "world":
        lines.append("- scope: " + ("ONE OFFER PAGE: the home page stays Signature; "
                                     "the World concept belongs to the offer page"
                                     if c.get("scope") == "offer" else "the whole site"))
        if c.get("offer"):
            lines.append(f"- the offer: {c['offer']}")
    if c.get("idea"):
        lines.append(f"- the owner's idea, in their words: {c['idea']}")
    lines.append("Write section 0, THE CONCEPT, to this intensity.")
    return "\n".join(lines)


DIRECTOR_LAW = """THE CONCEPT LAW (2026-10-01; the dial is set per business and shown in THE CONCEPT block below):
A design language decides how the site LOOKS. A concept decides what the site is ABOUT: one sentence the whole page obeys, taken from the business's own world and grounded in true facts about it ("the course is a college semester" for a real five-week cohort; "the shop is a take-a-number counter" for a walk-in barbershop). The concept sets the words, the objects and the photo list. The design language still owns color and type, and THE LAYOUT owns the page's structure. Three intensities:
- PLAIN: no concept. Nothing is renamed, no objects (a shaped seam or one underlined word at most). Clarity and craft carry the page. Write section 0 with INTENSITY: plain, its LAYOUT line, and nothing else but STAYS PLAIN: everything.
- SIGNATURE: one object carries one moment (the price list as a letterboard, the welcome as a letter), two renamed labels at most, everything else plain.
- WORLD: the idea runs the page. The navigation and section names use the concept's vocabulary, two to four objects hold the content, one living detail moves. When SCOPE is offer, the home page stays at SIGNATURE and the World concept is written for the offer page in section 6.
THE PLAIN-WORD RULE: every in-world label keeps its plain word beside it ("Tuition" over a small "Pricing"), so a first-time visitor never has to guess and search still reads what the thing is. A concept never hides what something is or what it costs.
THE GENEROSITY RULE STILL HOLDS: a World page renames, merges and reorders sections, and every function still has a home. A concept is never a reason to leave something out.
Ground it: every line of the sheet traces to the dossier. Never invent a credential, a class size or a date to make an idea work; pick a different idea. Decorative numbers (ticket serials, card numbers) stay one or two digits: THE FACTS LAW reads any longer number as a claim.

{OBJECT_CATALOG}

SECTION 0, THE CONCEPT, is written FIRST, as labeled lines exactly in this form (one line each; omit a line that does not apply):
INTENSITY: plain | signature | world
LAYOUT: one of the twelve layout keys from THE LAYOUT block, then a dash and the reason in one plain sentence (always present)
SCOPE: site | offer (and the offer's name, when offer)
IDEA: the one sentence
GROUNDED IN: the true facts it rests on
VOCABULARY: plain word -> in-world word | plain word -> in-world word
OBJECTS: library keys, each with its finish in brackets, e.g. ticket (paper), seal (metal)
MARKS: two or three recurring marks (a seal ring, a glyph, a stripe)
LIVING DETAIL: the one thing that moves
PHOTO LIST: what the owner should photograph, in the concept's own terms, one shot per item
STAYS PLAIN: what deliberately does not wear the concept"""

_SHEET_KEYS = ("INTENSITY", "LAYOUT", "SCOPE", "IDEA", "GROUNDED IN", "VOCABULARY",
               "OBJECTS", "MARKS", "LIVING DETAIL", "PHOTO LIST", "STAYS PLAIN")
_SHEET_LINE_RE = re.compile(
    r"^\s*[-*•]?\s*(" + "|".join(re.escape(k) for k in _SHEET_KEYS)
    + r")\s*[:\-—]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def parse_sheet(spec_text: str) -> Dict[str, str]:
    """The concept sheet's labeled lines, keyed lower_snake. Reads only
    the part of the blueprint before section 1 (OVERVIEW) when that
    heading exists, so a section-3 line that happens to start with
    'Objects:' is never mistaken for the sheet."""
    text = spec_text or ""
    m = re.search(r"^\s*(?:=+\s*)?1\s*[.)]\s*OVERVIEW", text, re.IGNORECASE | re.MULTILINE)
    head = text[:m.start()] if m else text[:6000]
    out: Dict[str, str] = {}
    for lm in _SHEET_LINE_RE.finditer(head):
        key = lm.group(1).strip().lower().replace(" ", "_")
        if key not in out:
            out[key] = lm.group(2).strip()
    raw = out.get("intensity", "").lower()
    out["intensity"] = next((i for i in INTENSITIES if i in raw), "")
    out["scope_raw"] = out.get("scope", "")
    scope = out.get("scope", "").lower()
    out["scope"] = "offer" if scope.startswith("offer") or " offer" in scope else (
        "site" if scope else "")
    return out


def vocabulary_pairs(sheet: Dict[str, str]) -> List[Tuple[str, str]]:
    """'Prices -> The board | Book -> Take a number' → [(plain, world)]."""
    pairs: List[Tuple[str, str]] = []
    for chunk in re.split(r"\s*[|;]\s*", sheet.get("vocabulary") or ""):
        m = re.match(r"(.+?)\s*(?:->|→|=>|=)\s*(.+)", chunk.strip())
        if m:
            plain = m.group(1).strip(" .\"'“”")
            world = m.group(2).strip(" .\"'“”")
            if plain and world and plain.lower() != world.lower():
                pairs.append((plain, world))
    return pairs[:12]


# ─── THE SAMENESS GUARD (2026-10-01, the concept-layer plan) ─────────
# A library of objects risks a house style of its own: every course a
# semester, every shop a ticket counter. The Director sees the concepts
# the platform has used most recently on OTHER businesses and is told not
# to repeat an idea, and to reuse an object only in a different way.
# One small query (the spec text alone, by JSON path), cached ten
# minutes. Fail-open: no rows, no block.

RECENT_LIMIT = 12
_RECENT_TTL_S = 600
_recent_cache: Dict[str, Any] = {"at": None, "rows": []}   # None: never loaded


def recent_concepts(exclude_business: str = "", limit: int = RECENT_LIMIT) -> List[Dict[str, str]]:
    import time
    now = time.monotonic()
    # "never loaded" is its own state: a freshly booted container's
    # monotonic clock can read under the TTL, which made 0.0 look fresh.
    if _recent_cache["at"] is None or now - _recent_cache["at"] > _RECENT_TTL_S:
        rows: List[Dict[str, Any]] = []
        try:
            import sb_clients
            rows = sb_clients.sb_get_as_service(
                "/business_sites?select=business_id,spec:site_config->design_spec->>text"
                f"&order=updated_at.desc&limit={limit * 3}") or []
        except Exception as e:
            logger.info(f"[concept] recent concepts skipped: {e}")
        _recent_cache.update(at=now, rows=rows)
    out: List[Dict[str, str]] = []
    for r in _recent_cache["rows"]:
        if str(r.get("business_id") or "") == exclude_business:
            continue
        sheet = parse_sheet(str(r.get("spec") or ""))
        if sheet.get("intensity") in ("signature", "world") and sheet.get("idea"):
            out.append({"intensity": sheet["intensity"], "idea": sheet["idea"][:160],
                        "objects": (sheet.get("objects") or "")[:120]})
        if len(out) >= limit:
            break
    return out


def recent_layouts(exclude_business: str = "", limit: int = 6) -> List[str]:
    """The layouts the platform's most recent OTHER blueprints chose, newest
    first, from the same cached rows as recent_concepts (the variety signal
    of site_layouts.rank). Fail-open: no rows, no layouts."""
    try:
        recent_concepts(exclude_business)          # fills the cache when stale
        import site_layouts
    except Exception:
        return []
    out: List[str] = []
    for r in _recent_cache.get("rows") or []:
        if str(r.get("business_id") or "") == exclude_business:
            continue
        k = site_layouts.key_from_sheet(parse_sheet(str(r.get("spec") or "")))
        if k:
            out.append(k)
        if len(out) >= limit:
            break
    return out


def recent_block(items: List[Dict[str, str]]) -> str:
    if not items:
        return ""
    lines = ["== RECENT CONCEPTS ON THE PLATFORM (other businesses' sites: never "
             "repeat an idea; reuse an object only with a different finish or a "
             "different job) =="]
    for it in items:
        objs = f" (objects: {it['objects']})" if it.get("objects") else ""
        lines.append(f"- {it['intensity']}: {it['idea']}{objs}")
    return "\n".join(lines)


_NAV_RE = re.compile(r"<nav\b.*?</nav>|<[^>]+role\s*=\s*[\"']navigation[\"'][^>]*>.*?</(?:div|ul|header)>",
                     re.IGNORECASE | re.DOTALL)
_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def check_page(html: str, sheet: Dict[str, str]) -> List[str]:
    """The built page against its concept sheet. Soft tier."""
    if not sheet or not sheet.get("intensity"):
        return []
    try:
        import site_objects
        used = site_objects.page_objects(html)
        named = site_objects.object_names_in("OBJECTS: " + (sheet.get("objects") or ""))
    except Exception:
        used, named = [], []
    problems: List[str] = []
    intensity = sheet["intensity"]
    concept_objects = [k for k in used if k not in _PLAIN_OK_OBJECTS]
    if intensity == "plain" and concept_objects:
        problems.append("CONCEPT: the blueprint is PLAIN, but the page carries "
                        f"concept objects ({', '.join(concept_objects)}). Plain means "
                        "no props: set that content as clean sections.")
    if intensity in ("signature", "world") and sheet.get("scope") != "offer":
        missing = [k for k in named if k not in used]
        if missing:
            problems.append("CONCEPT: the blueprint names objects the page does not "
                            f"carry ({', '.join(missing)}). Build each from its "
                            "library source with data-sx-object on its root.")
    if intensity == "world" and sheet.get("scope") != "offer" and len(used) < 2:
        problems.append("CONCEPT: a WORLD page holds its content in at least two "
                        "library objects; this page has "
                        f"{len(used)}. Put the content the sheet names inside them.")
    # the plain-word rule, where it matters most: the navigation
    pairs = vocabulary_pairs(sheet)
    if pairs:
        nav = " ".join(m.group(0) for m in _NAV_RE.finditer(html or ""))
        orphans: List[str] = []
        for attrs, inner in _A_RE.findall(nav):
            label = _text(inner).lower()
            aria = " ".join(re.findall(r"(?:aria-label|title)\s*=\s*[\"']([^\"']*)", attrs)).lower()
            for plain, world in pairs:
                if world.lower() in label and plain.lower() not in label \
                        and plain.lower() not in aria:
                    if world not in orphans:
                        orphans.append(f"'{world}' (keep '{plain}')")
        if orphans:
            problems.append("CONCEPT: in-world menu labels hide their plain word: "
                            + ", ".join(orphans[:4]) + ". Show the plain word "
                            "beneath the label or put it in the link's aria-label.")
    return problems[:4]
