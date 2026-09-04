"""
agent_site.py — every Solutionist site, legible to a customer's agent.

WHY THIS EXISTS
  Practitioners' customers are about to have agents of their own, and
  those agents will book the salon whose availability they can READ and
  skip the one they have to phone. A page-builder cannot do this: it does
  not own the booking data behind the page. We do. docs/future_architecture.md
  §3 calls this the least contested ground in the strategy; it was queued
  as Arc 1 on 2026-07-10 and shipped the day a general computer-using
  agent reached every paid ChatGPT tier (2026-09-04).

THREE THINGS, ONE SOURCE OF TRUTH
  1. JSON-LD in every served page's <head> — schema.org LocalBusiness
     with openingHoursSpecification read from the SAME availability the
     booking engine enforces (the build-time block read a free-text hours
     string that disagreed with it), one Service / Product / Course /
     Event node per active offering with an Offer only when the
     practitioner shows the price, and a ReserveAction at the booking URL.
  2. /.well-known/agent.json and /llms.txt on the site's own origin —
     the discovery point. The manifest names the JSON endpoints below by
     absolute URL on the API host, so a custom domain and a platform
     subdomain hand out the same truth.
  3. /public/agent/{slug}/services, /availability, /book on the API
     host — cheap JSON, no model call, no session. `availability` answers
     "what is open on THESE dates for THIS offering", which the widget's
     30-day blob never could. `book` rides the exact walk-in booking flow
     the human widget uses (same validation, same double-book guard,
     same confirmation email + SMS consent) and records that an agent
     did the typing.

WHAT IT DELIBERATELY IS NOT
  Not the Site Concierge. The concierge is a fenced conversational
  agent behind LLM spend and daily caps; an agent-readable surface must
  be static or nearly so, or every crawler becomes a bill. Nothing here
  invokes a model.

  Not a second permission model. The client surface's own evaluator,
  policy_engine.evaluate_client(actor="client_agent"), decides the API
  endpoints — the same vertical gate the client layer designed, which
  refuses a client portal to regulated practices. The page-level JSON-LD
  and manifest carry only what is already printed on the public page.

FAIL SOFT ON THE PAGE, FAIL CLOSED ON THE API
  A page must never 500 because structured data could not be built —
  every injection path returns the HTML unchanged on any error. The API
  endpoints are the opposite: an unresolvable business, a refused
  vertical, or a limiter that cannot run all answer with a refusal.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import rate_limit
import sb_clients

logger = logging.getLogger("agent_site")

router = APIRouter(prefix="/public/agent", tags=["agent-site"])

MANIFEST_SCHEMA = "solutionist-agent-manifest/1"
API_BASE = (os.environ.get("MCP_PUBLIC_BASE_URL")
            or "https://kmj-intake-server-production.up.railway.app").rstrip("/")
PUBLIC_DOMAIN = "mysolutionist.app"

# The marker that makes injection idempotent and lets a test tell our
# block from the builder's. An attribute, not a comment: comments get
# stripped by minifiers, attributes do not.
_MARK = 'data-solutionist="agent"'

# Availability queries are bounded. An agent that wants a month asks
# three times; a crawler that wants a year is the reason for the bound.
MAX_AVAILABILITY_DAYS = 14

_DAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_SCHEMA = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
               "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
               "sun": "Sunday"}

# schema.org types by offering category. Anything unmapped is a Service
# — the safest general claim about a thing a business sells its time for.
_SCHEMA_TYPE = {
    "service": "Service", "session": "Service", "package": "Service",
    "custom": "Service", "product": "Product", "course": "Course",
    "event": "Event",
}
_BOOKABLE = ("service", "session", "package")


# ═══════════════════════════════════════════════════════════════════════
# Facts — one resolver for the four competing sources
# ═══════════════════════════════════════════════════════════════════════

def resolve_facts(biz: Dict[str, Any], site: Dict[str, Any],
                  profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The public facts about one business, resolved ONCE with a stated
    precedence, from the four places the codebase keeps them:

      settings.contact_* > settings.link_page.* > practitioner_profiles

    site_composer, site_facts and the concierge each pick their own
    order today; this surface picks the one the composer prints on the
    page, so the structured data never contradicts the visible page.
    Pure: takes rows, returns a dict, touches no I/O.
    """
    biz = biz or {}
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    link = settings.get("link_page") if isinstance(settings.get("link_page"), dict) else {}
    kit = settings.get("brand_kit") if isinstance(settings.get("brand_kit"), dict) else {}
    prof = profile or {}
    cfg = site.get("site_config") if isinstance(site.get("site_config"), dict) else {}
    slug = str(site.get("slug") or "").strip()
    custom = str(cfg.get("custom_domain") or "").strip().lower().lstrip("/")
    origin = f"https://{custom}" if custom else (f"https://{slug}.{PUBLIC_DOMAIN}" if slug else "")
    social = link.get("social_profiles") if isinstance(link.get("social_profiles"), dict) else {}
    return {
        "id": str(biz.get("id") or ""),
        "slug": slug,
        "name": str(biz.get("name") or "").strip(),
        "type": str(biz.get("type") or "").strip(),
        "tagline": str(kit.get("tagline") or "").strip(),
        "phone": str(settings.get("contact_phone") or link.get("phone")
                     or prof.get("phone") or "").strip(),
        "email": str(settings.get("contact_email") or "").strip(),
        "address": str(settings.get("address") or link.get("address") or "").strip(),
        "city": str(prof.get("address_city") or "").strip(),
        "region": str(prof.get("address_state") or "").strip(),
        "timezone": str(((settings.get("availability") or {}) if isinstance(
            settings.get("availability"), dict) else {}).get("timezone")
            or prof.get("timezone") or "").strip(),
        "logo": str(kit.get("logo_url") or biz.get("logo_url") or "").strip(),
        "origin": origin,
        "booking_url": f"{origin}/book" if origin else "",
        "store_url": f"{origin}/store" if origin else "",
        "same_as": [str(v).strip() for v in social.values()
                    if isinstance(v, str) and v.strip().startswith("http")],
        "availability": settings.get("availability")
        if isinstance(settings.get("availability"), dict) else {},
    }


def opening_hours(availability: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """schema.org OpeningHoursSpecification from settings.availability.

    Read through the same parser the booking engine uses, so the hours
    a search engine or an agent sees are the hours a booking is refused
    outside of. An open-default business (no weekly hours configured)
    gets NO specification rather than a 24/7 claim: the engine treats
    that as bookable any time, but "open around the clock" is not a
    thing to print about a barber who has not filled the form in yet.
    """
    try:
        from availability import BusinessAvailability, is_open_default
        av = BusinessAvailability.from_settings_dict(availability)
    except Exception:
        return []
    try:
        if is_open_default(av):
            return []
    except Exception:
        pass
    out: List[Dict[str, Any]] = []
    for key in _DAY_ORDER:
        ranges = getattr(av.weekly, key, None) or []
        for r in ranges:
            start = getattr(r, "start", None)
            end = getattr(r, "end", None)
            if not start or not end:
                continue
            out.append({
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": f"https://schema.org/{_DAY_SCHEMA[key]}",
                "opens": start,
                "closes": end,
            })
    return out


def hours_lines(availability: Optional[Dict[str, Any]]) -> List[str]:
    """The same hours as prose, for llms.txt. Closed days are said."""
    try:
        from availability import BusinessAvailability, is_open_default
        av = BusinessAvailability.from_settings_dict(availability)
        if is_open_default(av):
            return []
    except Exception:
        return []
    out: List[str] = []
    for key in _DAY_ORDER:
        ranges = getattr(av.weekly, key, None) or []
        label = _DAY_SCHEMA[key]
        if not ranges:
            out.append(f"{label}: closed")
        else:
            out.append(f"{label}: " + ", ".join(f"{r.start}–{r.end}" for r in ranges))
    return out


# ═══════════════════════════════════════════════════════════════════════
# Offerings
# ═══════════════════════════════════════════════════════════════════════

def public_offering(o: Dict[str, Any]) -> Dict[str, Any]:
    """The customer-safe shape of one offering — the columns the booking
    widget already hands to anyone, and nothing else. Price is present
    only when the practitioner shows it; a hidden price is ABSENT, not
    null, so an agent cannot tell "free" from "ask"."""
    o = o or {}
    out: Dict[str, Any] = {
        "id": str(o.get("id") or ""),
        "name": str(o.get("name") or "").strip(),
        "slug": str(o.get("slug") or ""),
        "category": str(o.get("category") or "service"),
        "description": str(o.get("description") or "").strip() or None,
        "duration_min": o.get("duration_min"),
        "bookable": str(o.get("category") or "") in _BOOKABLE and bool(o.get("duration_min")),
    }
    if o.get("show_price_to_customer", True) and o.get("current_price") is not None:
        out["price"] = o.get("current_price")
        out["currency"] = str(o.get("currency") or "USD").upper()
    return out


def offering_node(o: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """One schema.org node per offering."""
    pub = public_offering(o)
    kind = _SCHEMA_TYPE.get(pub["category"], "Service")
    node: Dict[str, Any] = {
        "@type": kind,
        "@id": f"{facts['origin']}/#offering-{pub['slug'] or pub['id']}",
        "name": pub["name"],
    }
    if pub.get("description"):
        node["description"] = pub["description"]
    if pub.get("duration_min"):
        node["duration"] = f"PT{int(pub['duration_min'])}M"
    if kind in ("Service",):
        node["provider"] = {"@id": f"{facts['origin']}/#business"}
    if kind in ("Product", "Course"):
        node["brand"] = {"@id": f"{facts['origin']}/#business"}
    if "price" in pub:
        node["offers"] = {
            "@type": "Offer",
            "price": pub["price"],
            "priceCurrency": pub["currency"],
            "availability": "https://schema.org/InStock",
            "url": facts["booking_url"] if pub["bookable"] else (facts["store_url"] or facts["origin"]),
        }
    if pub["bookable"] and facts.get("booking_url"):
        node["potentialAction"] = {
            "@type": "ReserveAction",
            "target": {"@type": "EntryPoint", "urlTemplate": facts["booking_url"],
                       "actionPlatform": ["https://schema.org/DesktopWebPlatform",
                                          "https://schema.org/MobileWebPlatform"]},
        }
    return node


# ═══════════════════════════════════════════════════════════════════════
# JSON-LD
# ═══════════════════════════════════════════════════════════════════════

def business_jsonld(facts: Dict[str, Any], offerings: List[Dict[str, Any]],
                    hours: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The graph: one LocalBusiness that owns the offerings, and the
    offerings themselves. Ids are stable URLs on the site's own origin so
    a second page of the same site links to the same nodes."""
    origin = facts.get("origin") or ""
    biz: Dict[str, Any] = {
        "@type": "LocalBusiness",
        "@id": f"{origin}/#business",
        "name": facts.get("name") or "",
        "url": origin,
    }
    if facts.get("tagline"):
        biz["description"] = facts["tagline"]
    if facts.get("phone"):
        biz["telephone"] = facts["phone"]
    if facts.get("email"):
        biz["email"] = facts["email"]
    if facts.get("logo"):
        biz["logo"] = facts["logo"]
    if facts.get("address") or facts.get("city"):
        addr: Dict[str, Any] = {"@type": "PostalAddress"}
        if facts.get("address"):
            addr["streetAddress"] = facts["address"]
        if facts.get("city"):
            addr["addressLocality"] = facts["city"]
        if facts.get("region"):
            addr["addressRegion"] = facts["region"]
        biz["address"] = addr
    if facts.get("same_as"):
        biz["sameAs"] = facts["same_as"]
    hours = opening_hours(facts.get("availability")) if hours is None else hours
    if hours:
        biz["openingHoursSpecification"] = hours
    nodes = [offering_node(o, facts) for o in (offerings or []) if (o or {}).get("name")]
    if nodes:
        biz["makesOffer"] = [{"@id": n["@id"]} for n in nodes]
    if facts.get("booking_url") and any(public_offering(o)["bookable"] for o in offerings or []):
        biz["potentialAction"] = {
            "@type": "ReserveAction",
            "target": {"@type": "EntryPoint", "urlTemplate": facts["booking_url"]},
        }
    return {"@context": "https://schema.org", "@graph": [biz, *nodes]}


def render_jsonld_tag(doc: Dict[str, Any]) -> str:
    """The script tag. `</` is escaped so a name like `</script>` in a
    description cannot close the block early — the one HTML-injection
    vector a JSON blob in a page has."""
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("</", "<\\/")
    return f'<script type="application/ld+json" {_MARK}>{text}</script>'


_BUILD_TIME_LD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)


def inject_jsonld(html: str, tag: str) -> str:
    """Put our block in the head, ONCE, and retire the builder's own
    LocalBusiness block so the page does not carry two of them with
    different hours. Article blocks (news posts) and anything else are
    left alone. Idempotent: a page that already carries our marker is
    returned as-is."""
    if not html or not tag:
        return html
    if _MARK in html:
        return html

    def _drop(m: re.Match) -> str:
        body = m.group(1) or ""
        if _MARK in m.group(0):
            return m.group(0)
        return "" if '"LocalBusiness"' in body.replace(" ", "") else m.group(0)

    html = _BUILD_TIME_LD.sub(_drop, html)
    for close in ("</head>", "</HEAD>"):
        if close in html:
            return html.replace(close, tag + "\n" + close, 1)
    return html


# ═══════════════════════════════════════════════════════════════════════
# Manifest + llms.txt
# ═══════════════════════════════════════════════════════════════════════

def manifest(facts: Dict[str, Any], offerings: List[Dict[str, Any]],
             booking_open: bool) -> Dict[str, Any]:
    """/.well-known/agent.json — what an agent may do here and where.

    `booking_open` is the client-surface verdict for this vertical: when
    it is False the manifest advertises NO booking endpoints, so an agent
    at a therapist's site is told plainly rather than refused later.
    """
    slug = facts.get("slug") or ""
    api = f"{API_BASE}/public/agent/{slug}"
    doc: Dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "name": facts.get("name") or "",
        "description": facts.get("tagline") or None,
        "url": facts.get("origin") or "",
        "business_type": facts.get("type") or None,
        "timezone": facts.get("timezone") or None,
        "contact": {k: v for k, v in (("phone", facts.get("phone")),
                                      ("email", facts.get("email")),
                                      ("address", facts.get("address"))) if v},
        "hours": hours_lines(facts.get("availability")),
        "structured_data": f"{facts.get('origin')}/",
        "summary": f"{facts.get('origin')}/llms.txt",
        "capabilities": {
            "read_services": True,
            "read_availability": bool(booking_open),
            "book": bool(booking_open),
            "message_business": False,
            "pay": False,
        },
        "endpoints": {
            "services": {"method": "GET", "url": f"{api}/services"},
        },
        "offerings": [public_offering(o) for o in (offerings or []) if (o or {}).get("name")],
        "rules": [
            "Read services and availability freely; they are the same facts printed on the site.",
            "Book only with a real person's name and email — the confirmation goes to them, "
            "and the business will contact them at that address.",
            "Name your agent in the `agent` field of a booking. The practitioner sees who typed.",
            "Nothing here sends a message to the business, moves money, or changes an existing "
            "booking. Those happen with the practitioner.",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if booking_open:
        doc["endpoints"]["availability"] = {
            "method": "GET",
            "url": f"{api}/availability",
            "params": {"offering_id": "required", "from": "YYYY-MM-DD, default today",
                       "to": f"YYYY-MM-DD, at most {MAX_AVAILABILITY_DAYS} days after from"},
        }
        doc["endpoints"]["book"] = {
            "method": "POST",
            "url": f"{api}/book",
            "body": {"name": "the customer's name", "email": "the customer's email",
                     "offering_id": "from services", "start": "a slot start from availability",
                     "agent": "your agent's name", "notes": "optional",
                     "sms_consent": "optional boolean; only true if the customer agreed to texts"},
        }
        doc["booking_page"] = facts.get("booking_url") or None
    return doc


def llms_txt(facts: Dict[str, Any], offerings: List[Dict[str, Any]],
             booking_open: bool) -> str:
    """The plain-language summary an LLM crawler reads first. Facts only,
    in the order an assistant answers questions: who, what, when, how."""
    name = facts.get("name") or "This business"
    lines: List[str] = [f"# {name}"]
    if facts.get("tagline"):
        lines.append(f"> {facts['tagline']}")
    lines.append("")
    lines.append(f"Website: {facts.get('origin') or ''}")
    if facts.get("phone"):
        lines.append(f"Phone: {facts['phone']}")
    if facts.get("email"):
        lines.append(f"Email: {facts['email']}")
    if facts.get("address"):
        lines.append(f"Address: {facts['address']}")
    if facts.get("timezone"):
        lines.append(f"Timezone: {facts['timezone']}")
    pubs = [public_offering(o) for o in (offerings or []) if (o or {}).get("name")]
    if pubs:
        lines += ["", "## Services and products"]
        for p in pubs:
            bits = [p["name"]]
            if p.get("duration_min"):
                bits.append(f"{int(p['duration_min'])} min")
            if "price" in p:
                bits.append(f"{p['currency']} {p['price']}")
            line = " — ".join(bits)
            if p.get("description"):
                line += f": {p['description']}"
            lines.append(f"- {line}")
    hours = hours_lines(facts.get("availability"))
    if hours:
        lines += ["", "## Hours"] + [f"- {h}" for h in hours]
    lines += ["", "## For AI agents"]
    lines.append(f"- Machine-readable manifest: {facts.get('origin')}/.well-known/agent.json")
    if booking_open and facts.get("booking_url"):
        lines.append(f"- Book online: {facts['booking_url']}")
        lines.append("- Live availability and booking endpoints are listed in the manifest.")
    else:
        lines.append("- Booking through an agent is not offered for this business; "
                     "contact them directly.")
    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════════════
# Loading — one bundle per business, cached briefly
# ═══════════════════════════════════════════════════════════════════════

_CACHE_TTL = 60.0
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _load_bundle(business_id: str) -> Optional[Dict[str, Any]]:
    """facts + offerings + verdict for one business. Three service-role
    reads, cached 60s: a served page must not cost three queries per
    view, and offerings do not change between two visitors."""
    if not business_id:
        return None
    now = time.time()
    with _cache_lock:
        hit = _cache.get(business_id)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    try:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            "&select=id,name,type,settings,owner_id,logo_url&limit=1") or []
        if not rows:
            return None
        biz = rows[0]
        sites = sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{business_id}"
            "&select=slug,site_config&order=updated_at.desc&limit=1") or []
        site = sites[0] if sites else {}
        profile: Dict[str, Any] = {}
        if biz.get("owner_id"):
            prows = sb_clients.sb_get_as_service(
                f"/practitioner_profiles?owner_id=eq.{biz['owner_id']}"
                "&select=phone,address_city,address_state,timezone&limit=1") or []
            profile = prows[0] if prows else {}
        offerings = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
            "&order=name.asc&select=id,name,slug,description,category,"
            "current_price,currency,duration_min,show_price_to_customer&limit=200") or []
    except Exception as e:
        logger.warning("[agent_site] bundle load failed for %s: %s", business_id, e)
        return None
    facts = resolve_facts(biz, site, profile)
    bundle = {
        "facts": facts,
        "offerings": offerings if isinstance(offerings, list) else [],
        "booking_open": _booking_open(biz),
        "biz": biz,
    }
    with _cache_lock:
        _cache[business_id] = (now, bundle)
    return bundle


def _booking_open(biz: Dict[str, Any]) -> bool:
    """May an agent book here? The client surface's own vertical rule,
    plus whether booking is actually live for the business."""
    try:
        import vertical_scope
        if not vertical_scope.client_surface_allowed(biz.get("type")):
            return False
    except Exception:
        return False
    try:
        from booking_widget_router import booking_is_live
        return bool(booking_is_live(str(biz.get("id") or ""), biz.get("settings") or {}))
    except Exception:
        return False


def _bundle_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    try:
        sites = sb_clients.sb_get_as_service(
            f"/business_sites?slug=eq.{slug}&select=business_id&limit=1") or []
    except Exception:
        return None
    if not sites or not sites[0].get("business_id"):
        return None
    return _load_bundle(str(sites[0]["business_id"]))


# ═══════════════════════════════════════════════════════════════════════
# Page-level hooks — called by public_site, never raise
# ═══════════════════════════════════════════════════════════════════════

def head_tag(business_id: Optional[str]) -> str:
    """The JSON-LD tag for a served page, or '' on any failure."""
    try:
        b = _load_bundle(str(business_id or ""))
        if not b or not b["facts"].get("name"):
            return ""
        return render_jsonld_tag(business_jsonld(b["facts"], b["offerings"]))
    except Exception as e:
        logger.info("[agent_site] head tag skipped: %s", e)
        return ""


def inject_into_page(html: str, business_id: Optional[str]) -> str:
    try:
        tag = head_tag(business_id)
        return inject_jsonld(html, tag) if tag else html
    except Exception:
        return html


def manifest_for(business_id: Optional[str]) -> Optional[Dict[str, Any]]:
    b = _load_bundle(str(business_id or ""))
    if not b:
        return None
    return manifest(b["facts"], b["offerings"], b["booking_open"])


def llms_for(business_id: Optional[str]) -> Optional[str]:
    b = _load_bundle(str(business_id or ""))
    if not b:
        return None
    return llms_txt(b["facts"], b["offerings"], b["booking_open"])


# ═══════════════════════════════════════════════════════════════════════
# The API — cheap JSON on the API host
# ═══════════════════════════════════════════════════════════════════════

def _ip(request: Request) -> str:
    try:
        return rate_limit.client_ip(request)
    except Exception:
        return "unknown"


def _guard(request: Request, slug: str, verb: str) -> Dict[str, Any]:
    """Limiter, business, and the client-surface verdict — the three
    refusals every endpoint shares, in the order that costs least.
    Fails CLOSED: an agent that loops is a different problem from a
    person who clicks twice."""
    if not rate_limit.allow_strict("agent_site", _ip(request)):
        raise HTTPException(status_code=429, detail="rate limit exceeded — try again in a minute")
    b = _bundle_by_slug(str(slug or "").strip().lower())
    if not b:
        raise HTTPException(status_code=404, detail="no business at this address")
    try:
        import policy_engine
        v = policy_engine.evaluate_client(
            b["facts"]["id"], verb=verb, actor="client_agent", biz_row=b["biz"])
    except Exception as e:
        logger.warning("[agent_site] client policy unavailable: %s", e)
        raise HTTPException(status_code=503, detail="the booking policy is unavailable")
    if not v.allowed:
        raise HTTPException(status_code=403, detail=v.reason)
    return b


@router.get("/{slug}/services")
async def services(slug: str, request: Request) -> Dict[str, Any]:
    b = _guard(request, slug, "client_view_booking_config")
    f = b["facts"]
    return {
        "business": {"name": f["name"], "url": f["origin"], "timezone": f["timezone"] or None},
        "offerings": [public_offering(o) for o in b["offerings"] if (o or {}).get("name")],
        "booking": {"open": bool(b["booking_open"]),
                    "page": f["booking_url"] if b["booking_open"] else None},
    }


def _parse_day(v: Optional[str], default: date) -> date:
    if not v:
        return default
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="dates are YYYY-MM-DD")


@router.get("/{slug}/availability")
async def availability(slug: str, request: Request,
                       offering_id: str = Query(..., min_length=1),
                       from_: Optional[str] = Query(None, alias="from"),
                       to: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Open slots for ONE offering on a bounded run of days. The widget
    computes 30 days for every offering on every load; an agent asking
    about Thursday should pay for Thursday."""
    b = _guard(request, slug, "client_view_booking_config")
    if not b["booking_open"]:
        raise HTTPException(status_code=404, detail="online booking is not open for this business")
    off = next((o for o in b["offerings"] if str(o.get("id")) == offering_id), None)
    if not off:
        raise HTTPException(status_code=404, detail="offering not found")
    if not public_offering(off)["bookable"]:
        raise HTTPException(status_code=400, detail="that offering is not booked by the slot")

    today = date.today()
    start = _parse_day(from_, today)
    end = _parse_day(to, start + timedelta(days=6))
    if end < start:
        raise HTTPException(status_code=400, detail="`to` is before `from`")
    if (end - start).days >= MAX_AVAILABILITY_DAYS:
        raise HTTPException(status_code=400,
                            detail=f"ask for at most {MAX_AVAILABILITY_DAYS} days at a time")

    try:
        from availability import BusinessAvailability
        from availability_engine import compute_slots
        av = BusinessAvailability.from_settings_dict(b["facts"].get("availability"))
        lo = (start - timedelta(days=1)).isoformat()
        hi = (end + timedelta(days=1)).isoformat()
        bookings = sb_clients.sb_get_as_service(
            f"/module_entries?business_id=eq.{b['facts']['id']}"
            f"&appointment_at=gte.{lo}&appointment_at=lte.{hi}&status=eq.active"
            "&select=appointment_at,duration_min_at_booking,duration_min&limit=2000") or []
        slots = compute_slots(
            availability=av,
            practitioner_tz=b["facts"].get("timezone") or None,
            existing_bookings=bookings if isinstance(bookings, list) else [],
            offering_duration_min=int(off.get("duration_min") or 60),
            from_date=start, to_date=end)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[agent_site] slot compute failed: %s", e)
        raise HTTPException(status_code=503, detail="availability is unavailable right now")

    return {
        "offering_id": offering_id,
        "timezone": b["facts"].get("timezone") or "UTC",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "slots": slots,
        "quoted_at": int(time.time()),
    }


class AgentBookBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)
    offering_id: str = Field(..., min_length=1)
    start: str = Field(..., min_length=10, max_length=40,
                       description="A slot start from /availability, ISO 8601.")
    # Who typed. Required: the practitioner's calendar says which agent
    # made the booking, and a booking with no author is a booking they
    # cannot ask about.
    agent: str = Field(..., min_length=1, max_length=80)
    notes: Optional[str] = Field(None, max_length=1000)
    sms_consent: bool = False

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        from booking_widget_router import _validate_email_shape
        return _validate_email_shape(v)

    @field_validator("start")
    @classmethod
    def _iso(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("start must be ISO 8601, e.g. 2026-09-10T14:00:00Z")
        return v


@router.post("/{slug}/book")
async def book(slug: str, body: AgentBookBody, request: Request) -> Dict[str, Any]:
    """Book on a customer's behalf. Rides the SAME walk-in flow the human
    widget uses — contact dedupe, offering denormalization, the
    double-book guard, confirmation email, SMS consent record — so an
    agent booking is a booking, not a special case. What differs is the
    ledger: actor `client`, source `agent_site`, and the agent's name."""
    b = _guard(request, slug, "client_book_appointment")
    if not b["booking_open"]:
        raise HTTPException(status_code=404, detail="online booking is not open for this business")
    off = next((o for o in b["offerings"] if str(o.get("id")) == body.offering_id), None)
    if not off or not public_offering(off)["bookable"]:
        raise HTTPException(status_code=404, detail="offering not found or not bookable")

    import booking_widget_router as bw
    module = bw._bookings_module(b["facts"]["id"])
    if not module:
        raise HTTPException(status_code=404, detail="online booking is not open for this business")
    pdf = (module.get("archetype_params") or {}).get("primary_date_field") or "appointment_at"
    agent_label = " ".join(body.agent.split())[:80]
    data: Dict[str, Any] = {
        pdf: body.start,
        "appointment_at": body.start,
        "booked_via": f"agent:{agent_label}",
    }
    if body.notes:
        data["notes"] = body.notes.strip()

    anon = bw.BookAnonBody(name=body.name, email=body.email, data=data,
                           sms_consent=body.sms_consent,
                           offering_id=body.offering_id, quoted_price=None)
    result = await bw.book_anon(b["facts"]["id"], anon, request)

    # The ledger says an agent typed, for a client, and which rule
    # allowed it. Never fatal — the booking exists either way.
    try:
        import audit_log
        audit_log.record(
            b["facts"]["id"], actor_type="client", verb="client_book_appointment",
            actor_id=f"agent:{agent_label}"[:120], ok=True, source="agent_site",
            authorized_by="client:agent",
            target_type="appointment", target_id=str(result.get("appointment_id") or ""),
            summary=f"{agent_label} booked {off.get('name')} for {body.name}",
            payload={"offering_id": body.offering_id, "start": body.start})
    except Exception as e:
        logger.warning("[agent_site] ledger write failed (non-fatal): %s", e)

    return {
        "ok": True,
        "appointment_id": result.get("appointment_id"),
        "offering": off.get("name"),
        "start": body.start,
        "timezone": b["facts"].get("timezone") or "UTC",
        "confirmation": f"A confirmation email is on its way to {body.email}.",
        "manage_url": f"{b['facts']['booking_url']}?token={result.get('token')}"
        if result.get("token") and b["facts"].get("booking_url") else None,
    }
