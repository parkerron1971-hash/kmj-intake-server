"""
business_knowledge.py — what the system ACTUALLY knows about a business.

THE BUG THIS CLOSES
═══════════════════════════════════════════════════════════════════════
The Business Track dashboard said "Not covered yet" on all eight areas,
and "Chief hasn't met your business yet", for a business with a 95%
profile, seven offerings, eleven clients, payments, a bank and
QuickBooks connected. It read ONE store — the coach's narrative columns
on business_tracks — and the coach is only one of the ways a fact lands.
The profile editor, the catalog, a contact import and the plug-in list
all write the real stores directly, and the page never looked at them.

The coach had the same blind spot: its "ALREADY CAPTURED" block came
from the track row alone, so it would open a twenty-minute interview by
asking a practitioner with seven priced offerings what they sell.

So this module reads the stores the coach WRITES TO (see the table in
business_track_actions' docstring) plus the plug-in probes, and answers
per area: known / partial / open, with the facts in plain sentences.
Both the About Your Business page and the coach prompt read it, so the
page and the conversation can never disagree about what is on file.

EVERY READ MATCHES AN EXISTING READER
  owner       practitioner_profiles (owner_id)  — practitioner_profile_agent
              businesses.voice_profile          — AboutMeReview / Chief
  business    business_profiles                 — business_profile_agent
  offerings   offering_profiles.business_readiness (same select, same gaps
              the catalog shows as chips)
  clients     contacts (existence/count) + voice_profile.audience_note
  money       business_track_router probes (payments, bank, quickbooks)
              + invoices status in (sent, viewed) — revenue_analytics' open set
  operations  business_track_router probes (site, domains, email, hours…)
  growth      goals status=active                — goals_router
  plan        business_tracks.first_30_days

Every read is wrapped: a failed probe makes an area read LESS known, never
crashes the page. That direction matters — overstating what is on file
would make the coach skip a question it needed to ask.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import sb_clients

logger = logging.getLogger("business_knowledge")

KNOWN, PARTIAL, OPEN = "known", "partial", "open"

AREA_ORDER = ("owner", "business", "offerings", "clients",
              "money", "operations", "growth", "plan")

AREA_TITLES = {
    "owner": "You",
    "business": "Your business",
    "offerings": "What you sell",
    "clients": "Who you serve",
    "money": "How money moves",
    "operations": "How the work runs",
    "growth": "Where you're going",
    "plan": "Your next 30 days",
}

# Where each area is edited. Page ids are the existing Build/Operate
# routes, so every link resolves today; the About Your Business page
# maps the three that became its own sections onto its tabs.
AREA_EDIT = {
    "owner":      {"label": "Edit in You",                 "nav": {"tab": "build", "page": "about-me"}},
    "business":   {"label": "Edit in The business",        "nav": {"tab": "build", "page": "business-profile"}},
    "offerings":  {"label": "Open Services & Products",    "nav": {"tab": "operate", "sub": "offerings-manager"}},
    "clients":    {"label": "Open Clients",                "nav": {"tab": "operate", "sub": "contacts"}},
    "money":      {"label": "Open Payments",               "nav": {"tab": "operate", "sub": "payments"}},
    "operations": {"label": "Open Integrations",           "nav": {"tab": "build", "page": "integrations"}},
    "growth":     {"label": "Open Goals",                  "nav": {"tab": "grow", "sub": "goals"}},
    "plan":       {"label": "Talk it through",             "nav": None},
}

_CATEGORY_NOUN = {
    "session": ("session", "sessions"),
    "service": ("service", "services"),
    "package": ("package", "packages"),
    "event": ("event", "events"),
    "product": ("product", "products"),
    "course": ("course", "courses"),
}

# The profile stores enum keys (business_track_actions lists the valid
# ones); a practitioner should read words, never "package_3_12_months".
_SERVICE_MODEL = {
    "one_on_one": "1-on-1", "group_program": "group programs",
    "done_for_you": "done-for-you work", "done_with_you": "done-with-you work",
    "retainer": "retainers", "course_digital": "digital courses",
    "event_workshop": "events and workshops",
}
_ENGAGEMENT = {
    "single_session": "single sessions", "short_project": "short projects",
    "package_3_12_months": "3 to 12 month packages", "ongoing_retainer": "ongoing retainers",
}
_PRICING = {
    "hourly": "hourly", "package": "package", "retainer": "retainer",
    "milestone": "milestone", "subscription": "subscription",
    "one_time": "one-time", "tiered": "tiered",
}
_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "Washington, D.C.",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

_CONTACT_CAP = 1000
_EMPTY_WORDS = {"", "n/a", "na", "none", "no", "-", "—"}


# ═══════════════════════════════════════════════════════════════════════
# SAFE READS
# ═══════════════════════════════════════════════════════════════════════

def _get(path: str) -> List[Dict[str, Any]]:
    try:
        rows = sb_clients.sb_get_as_service(path)
        return rows if isinstance(rows, list) else []
    except Exception as e:
        logger.warning(f"[knowledge] read failed ({path.split('?')[0]}): {e}")
        return []


def _safe(fn: Callable[[], Any], fallback: Any) -> Any:
    try:
        return fn()
    except Exception as e:
        logger.warning(f"[knowledge] {getattr(fn, '__name__', 'probe')} failed: {e}")
        return fallback


def _filled(v: Any) -> bool:
    """A value the practitioner actually gave. 'N/A' typed into a key-people
    field is an answer to the form, not a person — it must not read as
    'we know your accountant'."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip().lower() not in _EMPTY_WORDS
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def assistant_name(biz: Dict[str, Any]) -> str:
    """The name this business gave its assistant (Settings → Chief), read
    fresh on every call so a rename lands everywhere at once. Falls back
    to the title 'Chief' — the same fallback the frontend uses."""
    prefs = ((biz or {}).get("settings") or {}).get("chief_preferences") or {}
    name = str(prefs.get("assistant_name") or "").strip()
    return name or "Chief"


def _clip(s: Any, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ═══════════════════════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════════════════════

def _hour(hhmm: Any) -> Optional[str]:
    try:
        h, m = str(hhmm).split(":")[:2]
        h_i, m_i = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    suffix = "am" if h_i < 12 else "pm"
    h12 = h_i % 12 or 12
    return f"{h12}{'' if m_i == 0 else f':{m_i:02d}'} {suffix}"


def _tz_place(tz: Any) -> Optional[str]:
    tz = str(tz or "").strip()
    if "/" not in tz:
        return None
    return tz.rsplit("/", 1)[-1].replace("_", " ")


def _money(v: float) -> str:
    if v <= 0:
        return "free"
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def _words(key: str) -> str:
    return str(key or "").replace("_", " ").strip()


def _cap(s: str) -> str:
    """Capitalise the first letter only — str.capitalize() would turn
    'payments and QuickBooks' into 'Payments and quickbooks'."""
    return s[:1].upper() + s[1:] if s else s


def _join(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ═══════════════════════════════════════════════════════════════════════
# AREAS
# ═══════════════════════════════════════════════════════════════════════

def _area(area_id: str, status: str, facts: List[str],
          gap_count: int = 0, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {
        "id": area_id,
        "title": AREA_TITLES[area_id],
        "status": status,
        "facts": [f for f in facts if f][:3],
        "gap_count": gap_count,
        "edit": AREA_EDIT[area_id],
    }
    if extra:
        out.update(extra)
    return out


def _owner_area(pp: Dict[str, Any], voice: Dict[str, Any],
                track: Dict[str, Any], gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    facts: List[str] = []
    name = (pp.get("full_legal_name") or "").strip()
    title = (pp.get("preferred_title") or "").strip()
    if name:
        facts.append(f"{name}, {title}" if title else name)
    place = _tz_place(pp.get("timezone"))
    start, end = _hour(pp.get("working_hours_start")), _hour(pp.get("working_hours_end"))
    if place and start and end:
        facts.append(f"{place} time, works {start} to {end}")
    elif place:
        facts.append(f"{place} time")
    if _filled(voice.get("description")):
        facts.append("Voice: " + _clip(voice["description"], 90))
    owner_story = (track.get("owner_profile") or {}).get("summary")
    if owner_story and len(facts) < 3:
        facts.append(_clip(owner_story, 110))

    people = ("primary_accountant_name", "primary_attorney_name", "primary_mentor_name")
    if pp and not any(_filled(pp.get(k)) for k in people):
        gaps.append({
            "key": "key_people",
            "title": "Your key people",
            "detail": "No accountant, attorney or mentor on file. Right, or not added yet?",
            "nav": AREA_EDIT["owner"]["nav"],
        })
    if not _filled(pp.get("timezone")):
        gaps.append({
            "key": "timezone",
            "title": "Your timezone",
            "detail": "So messages and bookings land at the right hour for you.",
            "nav": AREA_EDIT["owner"]["nav"],
        })

    core = sum(1 for k in ("full_legal_name", "timezone", "working_hours_start") if _filled(pp.get(k)))
    status = KNOWN if core == 3 else PARTIAL if (core or facts) else OPEN
    return _area("owner", status, facts)


def _business_area(bp: Dict[str, Any], track: Dict[str, Any],
                   gaps: List[Dict[str, Any]], name: str = "Chief") -> Dict[str, Any]:
    facts: List[str] = []
    btype = _words(bp.get("business_type")).capitalize()
    sub = (bp.get("business_subtype") or "").strip()
    if btype and sub:
        facts.append(f"{btype}: {_clip(sub, 80)}")
    elif btype or sub:
        facts.append(_clip(btype or sub, 90))
    models = [_SERVICE_MODEL.get(m, _words(m)) for m in (bp.get("service_models") or []) if m]
    raw_len = bp.get("typical_engagement_length")
    length = _ENGAGEMENT.get(raw_len, _words(raw_len)) if raw_len else ""
    if models and length:
        facts.append(f"{_cap(_join(models))}, usually {length}")
    elif models:
        facts.append(_cap(_join(models)))
    state = (bp.get("governing_state") or "").strip()
    if state:
        facts.append(f"Governed in {_STATES.get(state.upper(), state)}"
                     + (", serves internationally" if bp.get("international_clients") else ""))
    shape = (track.get("business_shape") or {}).get("summary")
    if shape and len(facts) < 3:
        facts.append(_clip(shape, 110))

    try:
        pct = round(float(bp.get("profile_completeness") or 0) * 100)
    except (TypeError, ValueError):
        pct = 0
    if bp and pct < 80:
        gaps.append({
            "key": "profile",
            "title": "The rest of your business profile",
            "detail": f"It is {pct}% filled in. {name} tailors contracts and policies from it.",
            "nav": AREA_EDIT["business"]["nav"],
        })

    status = KNOWN if pct >= 80 else PARTIAL if (bp or shape) else OPEN
    return _area("business", status, facts, extra={"pct": pct if bp else None})


def _offerings_area(biz_id: str, track: Dict[str, Any],
                    gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    import offering_profiles
    rows = _get(
        f"/offerings?business_id=eq.{biz_id}&is_active=eq.true"
        "&select=id,name,category,current_price,duration_min,inventory_qty,"
        "requires_shipping,fulfillment_note,image_url&order=name.asc&limit=200")
    report = _safe(lambda: offering_profiles.business_readiness(biz_id, rows), None) or {}
    per = report.get("offerings") or []

    facts: List[str] = []
    gap_count = 0
    if rows:
        counts: Dict[str, int] = {}
        for o in rows:
            cat = (o.get("category") or "custom").lower()
            counts[cat] = counts.get(cat, 0) + 1
        parts = []
        for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            one, many = _CATEGORY_NOUN.get(cat, ("other", "other"))
            parts.append(f"{n} {one if n == 1 else many}")
        facts.append(f"{len(rows)} {'offering' if len(rows) == 1 else 'offerings'}: {', '.join(parts)}")

        prices = []
        for o in rows:
            try:
                prices.append(float(o.get("current_price") or 0))
            except (TypeError, ValueError):
                pass
        if prices:
            lo, hi = min(prices), max(prices)
            facts.append(f"Priced at {_money(hi)}" if lo == hi
                         else f"From {_money(lo)} to {_money(hi)}")
        bookable = (report.get("summary") or {}).get("bookable_ready") or 0
        if bookable:
            facts.append(f"{bookable} bookable online")

        # The catalog's own chips, grouped: one gap per KIND of problem,
        # naming the offerings, so the list stays short on a big catalog.
        by_code: Dict[str, List[str]] = {}
        for r in per:
            for issue in (r.get("issues") or []):
                code = issue.get("code")
                if code in ("no_delivery_path", "no_image"):
                    by_code.setdefault(code, []).append(r.get("name") or "an offering")
        if by_code.get("no_delivery_path"):
            names = by_code["no_delivery_path"]
            gaps.append({
                "key": "no_delivery_path",
                "title": f"How buyers receive {_plural_names(names)}",
                "detail": "Nothing says whether it is delivered live, online or shipped.",
                "nav": AREA_EDIT["offerings"]["nav"],
            })
            gap_count += 1
        if by_code.get("no_image"):
            names = by_code["no_image"]
            gaps.append({
                "key": "no_image",
                "title": f"A photo for {_plural_names(names)}",
                "detail": "They show blank on your site and store.",
                "nav": AREA_EDIT["offerings"]["nav"],
            })
            gap_count += 1
    else:
        captured = track.get("offerings_captured") or []
        if captured:
            facts.append(f"{len(captured)} described in conversation, not in your catalog yet")

    status = KNOWN if rows else PARTIAL if facts else OPEN
    return _area("offerings", status, facts, gap_count=gap_count)


def _plural_names(names: List[str]) -> str:
    if len(names) == 1:
        return _clip(names[0], 40)
    if len(names) == 2:
        return f"{_clip(names[0], 30)} and {_clip(names[1], 30)}"
    return f"{len(names)} offerings"


def _clients_area(biz_id: str, voice: Dict[str, Any],
                  track: Dict[str, Any]) -> Dict[str, Any]:
    rows = _get(f"/contacts?business_id=eq.{biz_id}&select=id&limit={_CONTACT_CAP}")
    n = len(rows)
    facts: List[str] = []
    if n:
        facts.append(f"{n:,}{'+' if n >= _CONTACT_CAP else ''} on your list")
    who = voice.get("audience_note") or (track.get("audience") or {}).get("who")
    if _filled(who):
        facts.append(_clip(who, 120))
    found = (track.get("audience") or {}).get("how_they_find_you")
    if _filled(found):
        facts.append("Found through: " + _clip(found, 90))
    status = KNOWN if (n and _filled(who)) else PARTIAL if (n or _filled(who)) else OPEN
    return _area("clients", status, facts, extra={"count": n})


def _money_area(biz: Dict[str, Any], bp: Dict[str, Any],
                track: Dict[str, Any], probe: Callable[[str], bool]) -> Dict[str, Any]:
    paid = probe("payments")
    bank = probe("bank")
    books = probe("quickbooks")
    facts: List[str] = []
    connected = [label for ok, label in ((paid, "payments"), (bank, "bank"), (books, "QuickBooks")) if ok]
    if connected:
        facts.append(_cap(_join(connected)) + " connected")
    pricing = [_PRICING.get(p, _words(p)) for p in (bp.get("pricing_models") or []) if p]
    if pricing:
        facts.append(f"{_cap(_join(pricing))} pricing")
    open_inv = _get(f"/invoices?business_id=eq.{biz['id']}"
                    "&status=in.(sent,viewed)&select=id&limit=200")
    if open_inv:
        k = len(open_inv)
        facts.append(f"{k} unpaid {'invoice' if k == 1 else 'invoices'} out")
    bills = (track.get("money_map") or {}).get("how_they_bill")
    if _filled(bills) and len(facts) < 3:
        facts.append("Bills by " + _clip(bills, 80))
    status = KNOWN if paid else PARTIAL if facts else OPEN
    return _area("money", status, facts)


def _operations_area(track: Dict[str, Any], probe: Callable[[str], bool]) -> Dict[str, Any]:
    site, domain = probe("site"), probe("site_domain")
    email, hours, concierge = probe("email_domain"), probe("availability"), probe("concierge")
    facts: List[str] = []
    if site and domain:
        facts.append("Site live on your own domain"
                     + (", with the website concierge" if concierge else ""))
    elif site:
        facts.append("Site is live")
    if email:
        facts.append("Email sends from your own address")
    if hours:
        facts.append("Booking hours set to your working day")
    tools = [str(t) for t in ((track.get("operations_map") or {}).get("tools_in_use") or []) if t]
    if tools and len(facts) < 3:
        facts.append("Also runs on " + _join(tools[:3]))
    signals = sum(1 for s in (site, domain, email, hours) if s)
    status = KNOWN if signals >= 2 else PARTIAL if (signals or tools) else OPEN
    return _area("operations", status, facts)


def _growth_area(biz_id: str, track: Dict[str, Any],
                 gaps: List[Dict[str, Any]], name: str = "Chief") -> Dict[str, Any]:
    goals = _get(f"/goals?business_id=eq.{biz_id}&status=eq.active"
                 "&select=title,target,period&order=created_at.desc&limit=5")
    facts: List[str] = []
    for g in goals[:2]:
        if g.get("title"):
            facts.append(_clip(g["title"], 90))
    if len(goals) > 2:
        facts.append(f"{len(goals) - 2} more active {'goal' if len(goals) == 3 else 'goals'}")
    target = (track.get("growth_plan") or {}).get("target")
    if _filled(target) and not goals:
        facts.append(_clip(target, 110))
    if not facts:
        gaps.append({
            "key": "growth",
            "title": "Where you want to be in a year",
            "detail": f"Revenue and client targets, so {name} can pace the plan.",
            "nav": None,
        })
    status = KNOWN if goals else PARTIAL if facts else OPEN
    return _area("growth", status, facts, extra={"goal_count": len(goals)})


def _plan_area(track: Dict[str, Any]) -> Dict[str, Any]:
    plan = track.get("first_30_days") or {}
    steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict) and s.get("title")]
    facts = [_clip(s["title"], 90) for s in steps[:3]]
    if not facts and plan.get("plugins"):
        facts.append(f"{len(plan['plugins'])} things to switch on, in order")
    return _area("plan", KNOWN if facts else OPEN, facts)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def knowledge_for(biz: Dict[str, Any]) -> Dict[str, Any]:
    """Eight areas, what is on file for each, and what is still missing.

    `biz` needs id, owner_id and settings; voice_profile is fetched when
    the caller's row does not carry it. Sync — call via asyncio.to_thread
    from async code (a dozen PostgREST reads)."""
    import business_track_router as btr

    biz_id = biz["id"]
    if "voice_profile" not in biz or "stripe_account_id" not in biz:
        extra = _get(f"/businesses?id=eq.{biz_id}"
                     "&select=voice_profile,stripe_account_id,settings,owner_id,type&limit=1")
        if extra:
            biz = {**extra[0], **{k: v for k, v in biz.items() if v is not None}}
    voice = biz.get("voice_profile") or {}

    owner_id = biz.get("owner_id")
    pp = (_get(f"/practitioner_profiles?owner_id=eq.{owner_id}&limit=1") or [{}])[0] if owner_id else {}
    bp = (_get(f"/business_profiles?business_id=eq.{biz_id}&select=*&limit=1") or [{}])[0]
    track = (_get(f"/business_tracks?business_id=eq.{biz_id}"
                  "&order=created_at.desc&limit=1&select=*") or [{}])[0]

    probe_cache: Dict[str, bool] = {}

    def probe(key: str) -> bool:
        if key not in probe_cache:
            probe_cache[key] = btr._probe(key, biz)
        return probe_cache[key]

    gaps: List[Dict[str, Any]] = []
    name = assistant_name(biz)
    builders = {
        "owner":      lambda: _owner_area(pp, voice, track, gaps),
        "business":   lambda: _business_area(bp, track, gaps, name),
        "offerings":  lambda: _offerings_area(biz_id, track, gaps),
        "clients":    lambda: _clients_area(biz_id, voice, track),
        "money":      lambda: _money_area(biz, bp, track, probe),
        "operations": lambda: _operations_area(track, probe),
        "growth":     lambda: _growth_area(biz_id, track, gaps, name),
        "plan":       lambda: _plan_area(track),
    }
    areas = []
    for area_id in AREA_ORDER:
        built = _safe(builders[area_id], None)
        areas.append(built or _area(area_id, OPEN, []))

    # Missing-offering gaps outrank the soft ones: they are visible to
    # customers today.
    rank = {"no_delivery_path": 0, "no_image": 1, "growth": 2, "profile": 3,
            "timezone": 4, "key_people": 5}
    gaps.sort(key=lambda g: rank.get(g["key"], 9))

    return {
        "ok": True,
        "areas": areas,
        "known_count": sum(1 for a in areas if a["status"] == KNOWN),
        "total": len(areas),
        "gaps": gaps[:6],
        "track_status": track.get("status") if track else None,
        "assistant_name": name,
    }


def known_block_for_coach(knowledge: Optional[Dict[str, Any]]) -> str:
    """The coach's view of the same answer: what is already on file from
    the practitioner's RECORDS (not this conversation), and which areas to
    skip. Empty when nothing is known, so a brand-new business gets the
    full interview."""
    if not knowledge or not knowledge.get("areas"):
        return ""
    known = [a for a in knowledge["areas"] if a["status"] == KNOWN]
    partial = [a for a in knowledge["areas"] if a["status"] == PARTIAL]
    if not known and not partial:
        return ""
    lines = ["ALREADY ON FILE FROM THEIR RECORDS (they entered this elsewhere in the app — not in this conversation):"]
    for a in known + partial:
        tag = "known" if a["status"] == KNOWN else "partly known"
        facts = "; ".join(a["facts"]) or "(on file)"
        lines.append(f"  {a['id']} [{tag}]: {facts}")
    if known:
        ids = ", ".join(a["id"] for a in known)
        lines.append(
            f"  SKIP THESE AREAS: {ids}. Do not interview them. At most ONE quick "
            "confirmation in passing (\"I can see you've got seven offerings loaded — "
            "anything missing?\"), then move straight to the first area that is not known. "
            "When you save_business_phase for a skipped area, summarise what is on file.")
    if knowledge.get("gaps"):
        lines.append("  Specific gaps worth asking about: "
                     + "; ".join(g["title"] for g in knowledge["gaps"][:4]) + ".")
    return "\n".join(lines)
