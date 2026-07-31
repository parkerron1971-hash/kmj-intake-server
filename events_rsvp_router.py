"""
events_rsvp_router.py — public event RSVP for event_roster modules.

THE GAP THIS CLOSES
  The event_roster archetype (G03) is internal-only: the operator can
  track a picnic's headcount and volunteer roles, but a member cannot
  sign THEMSELVES up — every RSVP arrives by phone call and gets typed
  in by hand. This adds the public events page
  (https://<slug>.mysolutionist.app/events): upcoming occasions from the
  business's event_roster modules, each with its open volunteer roles
  (needed vs filled) and a signup form. Mirrors the /give pattern
  (giving_router): SSR page in its own module, routed from
  public_site.py, brand-kit CSS vars, gated, rate-limited, branded
  404-status page when off.

THE GATE (a deliberate ruling — broader than giving's)
  ANY business with at least one active event_roster module + the
  explicit settings.events_public.enabled toggle. Giving is
  nonprofit-family-only because money + IRS acknowledgment language is
  vertical-specific compliance surface; an RSVP page has none of that,
  and the archetype itself is vertical-agnostic by design (a coach's
  group workshop is the same shape as a church picnic — one occasion,
  many people). The roster module's existence is the real capability
  signal; the toggle keeps the page from surfacing uninvited.

WHERE SIGNUPS LAND
  Appended to the entry's data[signups_field] array — the EXACT shape
  event_roster/internal.tsx reads ({contact_id?, name?, status?, role?,
  note?}; only status='yes' counts toward capacity). A public signup is
  therefore indistinguishable from an operator-typed one, which is the
  point: no second roster, no new render path. The congregation-scale
  read-modify-write trade-off is documented in event_roster/types.ts
  ("WHERE SIGNUPS LIVE") and applies unchanged here.

CONTACTS
  Every RSVP find-or-creates a contact — dedup by email within the
  business (case-insensitive ilike with LIKE wildcards escaped),
  service-role writes: the same discipline as giving_router
  ._find_or_create_giver / public_site._capture_contact_from_form. A
  returning member's second RSVP for the same occasion is idempotent
  (their contact is already on the signup list → no duplicate row).

EVENT SPINE — deliberately NO emit this wave: the catalog
  (event_spine.EVENT_CATALOG) has no RSVP-shaped type, the closest
  ('contact_form_submitted') is semantically the composed-site contact
  form, and the catalog drift test exists precisely so types don't get
  invented casually. If the spine grows an attendance family, wire it
  then. Per-signup operator notifications are also skipped on purpose —
  forty picnic RSVPs must not be forty pings; the briefing's
  roster-gaps section is the operator surface for fill status.

CAPACITY
  capacity_field (a number on the entry) is honored: a full occasion
  renders "Full" with no form, and the server refuses the signup (409)
  regardless of what the page showed. Named roles refuse individually
  when their needed count is filled.
"""
from __future__ import annotations

import html as _html_mod
import logging
import time
import urllib.parse
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

import sb_clients
from auth_supabase import AuthedUser, require_user
from business_sites_helpers import PUBLIC_DOMAIN, ensure_business_site

logger = logging.getLogger("events_rsvp_router")

router = APIRouter(tags=["events-rsvp"])

# How far ahead the public page looks. Congregation planning horizon;
# also bounds the entry scan.
UPCOMING_WINDOW_DAYS = 90
MAX_OCCASIONS = 50
MAX_ENTRIES_PER_MODULE = 200


# ─── Settings + gate ─────────────────────────────────────────────────


def events_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """settings.events_public sub-dict; tolerate missing/malformed."""
    raw = (settings or {}).get("events_public") or {}
    return raw if isinstance(raw, dict) else {}


def events_public_is_active(biz: Dict[str, Any],
                            roster_modules: List[Dict[str, Any]]) -> bool:
    """The ONE activation rubric (see module docstring for the ruling):
    operator flipped the toggle AND the business actually has an active
    event_roster module — a public page with nothing behind it is dead
    weight. No vertical gate on purpose."""
    if not events_settings(biz.get("settings")).get("enabled"):
        return False
    return bool(roster_modules)


def events_url_for_site(site: Dict[str, Any]) -> str:
    """Canonical public events URL — same shape as give_url_for_site."""
    slug = (site or {}).get("slug") or "business"
    return f"https://{slug}.{PUBLIC_DOMAIN}/events"


def roster_modules_for(business_id: str) -> List[Dict[str, Any]]:
    """Active event_roster modules for a business (service-role read —
    both callers are public-surface paths)."""
    rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}"
        f"&archetype=eq.event_roster&is_active=eq.true"
        f"&select=id,name,archetype_params&limit=50"
    ) or []
    return rows if isinstance(rows, list) else []


# ─── Pure occasion math (no DB — unit-testable) ──────────────────────
# Field resolution + counting rules mirror the frontend
# (event_roster/types.ts resolveParams / attendingCount / roleFills)
# and briefing_verticals' roster-gaps scan: defaults 'title'/'date'/
# 'location'/'capacity'/'signups'; only status='yes' (or absent) holds
# a seat.


def resolve_fields(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    p = params if isinstance(params, dict) else {}
    roles = [r for r in (p.get("roles") or [])
             if isinstance(r, dict) and r.get("id") and r.get("label")]
    return {
        "title_field": p.get("title_field") or "title",
        "date_field": p.get("date_field") or "date",
        "location_field": p.get("location_field") or "location",
        "capacity_field": p.get("capacity_field") or "capacity",
        "signups_field": p.get("signups_field") or "signups",
        "roles": roles,
        "occasion_noun": str(p.get("occasion_noun") or "").strip() or None,
    }


def read_signups(data: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    raw = (data or {}).get(field)
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict)]


def attending_count(signups: List[Dict[str, Any]]) -> int:
    """Only 'yes' counts toward capacity — same rule as the frontend's
    attendingCount (a maybe is not a seat taken)."""
    return sum(1 for s in signups if (s.get("status") or "yes") == "yes")


def role_fill(role: Dict[str, Any], signups: List[Dict[str, Any]]) -> Dict[str, Any]:
    needed = max(1, int(role.get("needed") or 1))
    filled = sum(1 for s in signups
                 if s.get("role") == role.get("id")
                 and (s.get("status") or "yes") == "yes")
    return {"id": role.get("id"), "label": role.get("label") or role.get("id"),
            "needed": needed, "filled": filled, "full": filled >= needed}


def _parse_day(v: Any) -> Optional[date]:
    """A date out of whatever the entry holds — '2026-08-04', an ISO
    datetime, or junk (None). Same tolerance as briefing_verticals."""
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        pass
    try:
        return date.fromisoformat(v[:10])
    except (ValueError, TypeError):
        return None


def _capacity_of(data: Dict[str, Any], field: str) -> Optional[int]:
    try:
        n = int(data.get(field))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def build_occasions(
    modules: List[Dict[str, Any]],
    entries_by_module: Dict[str, List[Dict[str, Any]]],
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """The page's data: dated, upcoming occasions across every roster
    module, soonest first. Undated entries are skipped — internally an
    undated occasion is "being planned" (types.ts isUpcoming), but a
    public RSVP needs a date a member can commit to."""
    today = today or date.today()
    out: List[Dict[str, Any]] = []
    for mod in modules or []:
        f = resolve_fields(mod.get("archetype_params"))
        for e in entries_by_module.get(str(mod.get("id"))) or []:
            data = e.get("data") or {}
            d = _parse_day(data.get(f["date_field"]))
            if d is None or d < today or (d - today).days > UPCOMING_WINDOW_DAYS:
                continue
            signups = read_signups(data, f["signups_field"])
            attending = attending_count(signups)
            capacity = _capacity_of(data, f["capacity_field"])
            full = capacity is not None and attending >= capacity
            out.append({
                "entry_id": e.get("id"),
                "module_id": mod.get("id"),
                "title": str(data.get(f["title_field"]) or "").strip() or "(untitled)",
                "date": d.isoformat(),
                "date_label": f"{d.strftime('%A, %B')} {d.day}",
                "location": str(data.get(f["location_field"]) or "").strip(),
                "capacity": capacity,
                "attending": attending,
                "spots_left": (max(0, capacity - attending)
                               if capacity is not None else None),
                "full": full,
                "occasion_noun": f["occasion_noun"],
                "roles": [role_fill(r, signups) for r in f["roles"]],
            })
    out.sort(key=lambda o: o["date"])
    return out[:MAX_OCCASIONS]


# ─── Rate limiting (public endpoint) ─────────────────────────────────
# Same in-process sliding-window pattern as giving_router. Checked
# BEFORE any read or write — first line of the endpoint by contract
# (pinned in tests). 10/min per IP: a family device RSVPing four people
# is fine; a scraper isn't.

_rsvp_rate: Dict[str, List[float]] = {}
RSVP_RATE_MAX_PER_MIN = 10


def _check_rsvp_rate(ip: str) -> bool:
    now = time.time()
    cutoff = now - 60
    bucket = [t for t in _rsvp_rate.get(ip, []) if t > cutoff]
    if len(bucket) >= RSVP_RATE_MAX_PER_MIN:
        _rsvp_rate[ip] = bucket
        return False
    bucket.append(now)
    _rsvp_rate[ip] = bucket
    return True


# ─── Contact find-or-create (the PR #344 dedup discipline) ───────────


def _escape_ilike(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))


def _now_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


def _find_or_create_attendee(business_id: str, name: str, email: str) -> Optional[str]:
    """Find-or-create the attendee's contact row — dedup by email
    (case-insensitive, LIKE wildcards escaped) WITHIN the business,
    service-role writes; identical discipline to giving_router
    ._find_or_create_giver. Returns contact_id, or None when the
    contact write fails (the signup still proceeds name-only — a
    first-time visitor must not be turned away by a contacts hiccup;
    same principle as the Signup type's name-only allowance)."""
    email_clean = (email or "").strip().lower()
    if not email_clean:
        return None
    try:
        pattern = urllib.parse.quote(_escape_ilike(email_clean), safe="")
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}"
            f"&email=ilike.{pattern}&select=id&limit=1") or []
        if rows:
            sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{rows[0]['id']}&business_id=eq.{business_id}",
                {"last_interaction": _now_iso()})
            return rows[0]["id"]
        created = sb_clients.sb_post_as_service("/contacts", {
            "business_id": business_id,
            "name": (name or "").strip() or email_clean.split("@")[0],
            "email": email_clean,
            "status": "lead",
            "source": "event_rsvp",
            "last_interaction": _now_iso(),
        })
        if isinstance(created, list) and created:
            return created[0]["id"]
        logger.warning(f"[rsvp] contact create failed biz={business_id[:8]}")
    except Exception as e:
        logger.warning(f"[rsvp] contact find-or-create failed: {e}")
    return None


# ─── Public RSVP endpoint ────────────────────────────────────────────


@router.post("/public/events/{slug}/rsvp")
async def public_event_rsvp(
    slug: str, body: Dict[str, Any], request: Request,
) -> Dict[str, Any]:
    """Anonymous: sign one person up for one occasion.

    Body: { entry_id: str, name: str, email: str, role?: str }
    Returns { ok, attending, already } — `already` when this contact is
    on the list for the occasion (idempotent double-tap, not an error).
    """
    # Rate limit FIRST — before any read or write (pinned in tests).
    from rate_limit import client_ip
    ip = client_ip(request)
    if not _check_rsvp_rate(ip):
        raise HTTPException(429, "Too many attempts. Please try again in a minute.")

    body = body or {}

    # ── Validate input before touching the database ──
    entry_id = str(body.get("entry_id") or "").strip()
    if not entry_id:
        raise HTTPException(400, "entry_id required")
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(400, "please tell us your name")
    email = str(body.get("email") or "").strip().lower()[:200]
    if not email or "@" not in email or "." not in email:
        raise HTTPException(400, "that email doesn't look right")
    role_id = str(body.get("role") or "").strip()[:80] or None

    # ── Resolve slug → business ──
    sites = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{urllib.parse.quote(slug, safe='')}"
        f"&order=updated_at.desc&limit=1&select=business_id,slug"
    ) or []
    if not sites:
        raise HTTPException(404, "not found")
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{sites[0]['business_id']}"
        f"&select=id,name,type,settings&limit=1"
    ) or []
    if not biz_rows:
        raise HTTPException(404, "not found")
    biz = biz_rows[0]
    business_id = str(biz["id"])

    # ── The gate — same rubric as the page ──
    modules = roster_modules_for(business_id)
    if not events_public_is_active(biz, modules):
        raise HTTPException(404, "event signups aren't available here")

    # ── Load the occasion; it must belong to one of THIS business's
    #    roster modules (an entry id from another business or another
    #    archetype is a 404, not a write) ──
    entries = sb_clients.sb_get_as_service(
        f"/module_entries?id=eq.{urllib.parse.quote(entry_id, safe='')}"
        f"&business_id=eq.{business_id}&status=eq.active"
        f"&select=id,module_id,data&limit=1"
    ) or []
    if not entries:
        raise HTTPException(404, "that occasion wasn't found")
    entry = entries[0]
    module = next((m for m in modules
                   if str(m.get("id")) == str(entry.get("module_id"))), None)
    if not module:
        raise HTTPException(404, "that occasion wasn't found")

    f = resolve_fields(module.get("archetype_params"))
    data = dict(entry.get("data") or {})
    signups = read_signups(data, f["signups_field"])

    # ── Capacity honored server-side, whatever the page showed ──
    capacity = _capacity_of(data, f["capacity_field"])
    if capacity is not None and attending_count(signups) >= capacity:
        raise HTTPException(409, "this occasion is full")

    # ── Role validation: must exist; must have an open slot ──
    if role_id:
        role = next((r for r in f["roles"] if r.get("id") == role_id), None)
        if not role:
            raise HTTPException(400, "unknown role")
        fill = role_fill(role, signups)
        if fill["full"]:
            raise HTTPException(
                409, f"the {fill['label']} role is already filled")

    # ── Contact find-or-create (dedup by email within the business) ──
    contact_id = _find_or_create_attendee(business_id, name, email)

    # Idempotent double-tap: this person is already on the list.
    if contact_id and any(
        s.get("contact_id") == contact_id
        and (s.get("status") or "yes") == "yes"
        for s in signups
    ):
        return {"ok": True, "already": True,
                "attending": attending_count(signups)}

    # ── Append the signup — the exact Signup shape internal.tsx reads
    #    and writes ({contact_id?, name, status, role?}), so a public
    #    signup renders indistinguishably from an operator-typed one ──
    new_signup: Dict[str, Any] = {"name": name, "status": "yes"}
    if contact_id:
        new_signup["contact_id"] = contact_id
    if role_id:
        new_signup["role"] = role_id
    data[f["signups_field"]] = signups + [new_signup]

    updated = sb_clients.sb_patch_as_service(
        f"/module_entries?id=eq.{urllib.parse.quote(entry_id, safe='')}"
        f"&business_id=eq.{business_id}",
        {"data": data})
    if updated is None:
        logger.warning(f"[rsvp] signup append failed biz={business_id[:8]} "
                       f"entry={entry_id[:8]}")
        raise HTTPException(500, "something went wrong — please try again")

    logger.info(f"[rsvp] signup recorded biz={business_id[:8]} "
                f"entry={entry_id[:8]}"
                + (f" role={role_id}" if role_id else ""))
    return {"ok": True, "already": False,
            "attending": attending_count(read_signups(data, f["signups_field"]))}


# ─── Owner config endpoints ──────────────────────────────────────────


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner gate — same shape as giving_router._require_owner."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,type,owner_id,settings&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    return rows[0]


def _config_payload(biz: Dict[str, Any], site: Dict[str, Any],
                    modules: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = events_settings(biz.get("settings"))
    return {
        "ok": True,
        "business_id": biz.get("id"),
        "enabled": bool(cfg.get("enabled")),
        # has_roster_modules = the prerequisite; the panel points the
        # operator at BUILD when it's False.
        "has_roster_modules": bool(modules),
        "active": events_public_is_active(biz, modules),
        "slug": site.get("slug"),
        "url": events_url_for_site(site),
    }


@router.get("/events-public/{business_id}")
def get_events_public_config(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Current events-page config + the canonical URL (lazy-creates the
    business_sites row, mirroring giving, so there is always a URL to
    share)."""
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    return _config_payload(biz, site, roster_modules_for(business_id))


@router.patch("/events-public/{business_id}")
def patch_events_public_config(
    business_id: str,
    body: Dict[str, Any],
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Update settings.events_public. Owner-gated. Body: { enabled? }."""
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    settings = dict(biz.get("settings") or {})
    cfg = dict(events_settings(settings))
    if "enabled" in (body or {}):
        cfg["enabled"] = bool(body["enabled"])
    settings["events_public"] = cfg
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings},
    )
    biz = {**biz, "settings": settings}
    return _config_payload(biz, site, roster_modules_for(business_id))


# ─── SSR page renderers (pure — unit-testable) ───────────────────────


def _esc(s: Optional[str]) -> str:
    return _html_mod.escape(s or "", quote=True)


def _brand_css_vars(business: Dict[str, Any]) -> str:
    """Brand kit → CSS variables. Reuses the booking page's mapping (the
    same seam giving uses) so /events matches /give and /book."""
    from booking_page_renderer import _css_vars, _brand_kit
    return _css_vars(_brand_kit(business))


def _occasion_card(o: Dict[str, Any]) -> str:
    """One occasion card: facts, open roles, and the signup form (or the
    Full state)."""
    loc = (f'<div class="ev-loc">{_esc(o["location"])}</div>'
           if o.get("location") else "")

    spots = ""
    if o.get("capacity") is not None:
        if o["full"]:
            spots = '<span class="ev-full">Full</span>'
        else:
            n = o["spots_left"]
            spots = (f'<span class="ev-spots">{n} '
                     f'spot{"s" if n != 1 else ""} left</span>')

    roles_html = ""
    open_roles = [r for r in o.get("roles") or [] if not r["full"]]
    if o.get("roles"):
        pills = "".join(
            f'<span class="ev-role{" done" if r["full"] else ""}">'
            f'{_esc(r["label"])} · {r["filled"]}/{r["needed"]}</span>'
            for r in o["roles"])
        roles_html = f'<div class="ev-roles">{pills}</div>'

    if o["full"]:
        form = ('<div class="ev-fullnote">This one is full — check back in '
                'case a spot opens.</div>')
    else:
        role_select = ""
        if open_roles:
            opts = "".join(
                f'<option value="{_esc(r["id"])}">'
                f'{_esc(r["label"])} (needs {r["needed"] - r["filled"]})</option>'
                for r in open_roles)
            role_select = (
                '<select name="role" class="ev-input" aria-label="Volunteer role">'
                '<option value="">Just attending</option>'
                f'{opts}</select>')
        form = f"""<form class="ev-form" data-entry="{_esc(str(o["entry_id"]))}">
      <input type="text" name="name" class="ev-input" placeholder="Your name"
             autocomplete="name" maxlength="120" required>
      <input type="email" name="email" class="ev-input" placeholder="Email"
             autocomplete="email" maxlength="200" required>
      {role_select}
      <button type="submit" class="ev-go">Count me in</button>
      <div class="ev-msg" role="status"></div>
    </form>"""

    return f"""<article class="ev-card">
    <div class="ev-when">{_esc(o["date_label"])}</div>
    <h2 class="ev-title">{_esc(o["title"])} {spots}</h2>
    {loc}
    {roles_html}
    {form}
  </article>"""


def render_events_page(
    business: Dict[str, Any],
    occasions: List[Dict[str, Any]],
    canonical_url: str,
    slug: str,
    *,
    api_origin: str,
) -> str:
    """The public events page. Mobile-first by design — members RSVP
    from phones: single column, ≤480px shell (the /give shell), 44px+
    touch targets, 16px inputs (no iOS zoom), no horizontal scroll."""
    name = (business.get("name") or "").strip() or "Events"
    brand = (business.get("settings") or {}).get("brand_kit") or {}
    logo_url = ""
    if isinstance(brand, dict):
        logo_url = (brand.get("logo_url") or brand.get("logo") or "").strip()

    title = f"Events — {name}"
    description = f"See what's coming up at {name} and let us know you're coming."
    css_vars = _brand_css_vars(business)

    logo_html = (f'<img class="ev-logo" src="{_esc(logo_url)}" alt="{_esc(name)} logo">'
                 if logo_url else "")
    og_image_html = ""
    if logo_url:
        og_image_html = (f'<meta property="og:image" content="{_esc(logo_url)}">'
                         f'<link rel="icon" href="{_esc(logo_url)}">')

    if occasions:
        cards = "".join(_occasion_card(o) for o in occasions)
    else:
        cards = ('<div class="ev-empty">Nothing on the calendar just yet — '
                 'check back soon.</div>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical_url)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical_url)}">
<meta property="og:type" content="website">
{og_image_html}
<style>{css_vars}</style>
<style>
html,body{{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);
background:var(--surface);min-height:100vh;}}
*{{box-sizing:border-box;}}
.ev-shell{{max-width:480px;margin:0 auto;padding:28px 16px 48px;}}
.ev-header{{text-align:center;margin-bottom:22px;}}
.ev-logo{{max-width:88px;max-height:88px;display:block;margin:0 auto 12px;}}
.ev-name{{font-family:var(--font-heading);font-size:24px;font-weight:700;margin:0;}}
.ev-kicker{{font-family:var(--font-heading);font-size:15px;font-weight:600;
color:var(--text-secondary);margin:6px 0 0;letter-spacing:.06em;text-transform:uppercase;}}
.ev-card{{border:1px solid var(--border);border-radius:16px;padding:18px 16px;
margin-bottom:16px;}}
.ev-when{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
color:var(--accent);}}
.ev-title{{font-family:var(--font-heading);font-size:19px;font-weight:700;
margin:6px 0 0;line-height:1.3;}}
.ev-loc{{font-size:13px;color:var(--text-secondary);margin-top:4px;}}
.ev-spots{{display:inline-block;font-size:11px;font-weight:700;color:var(--accent);
border:1px solid var(--accent);border-radius:999px;padding:2px 9px;vertical-align:middle;
margin-left:6px;}}
.ev-full{{display:inline-block;font-size:11px;font-weight:700;color:var(--text-muted);
border:1px solid var(--border);border-radius:999px;padding:2px 9px;vertical-align:middle;
margin-left:6px;}}
.ev-roles{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}}
.ev-role{{font-size:12px;font-weight:600;color:var(--text-secondary);
border:1px solid var(--border);border-radius:999px;padding:4px 10px;}}
.ev-role.done{{opacity:.55;text-decoration:line-through;}}
.ev-form{{margin-top:14px;display:flex;flex-direction:column;gap:8px;}}
.ev-input{{width:100%;padding:12px 14px;font-size:16px;border:1.5px solid var(--border);
border-radius:12px;background:transparent;color:var(--text-primary);min-height:48px;
font-family:var(--font-body);}}
.ev-go{{width:100%;padding:14px 0;font-size:16px;font-weight:700;border:0;
border-radius:12px;background:var(--accent);color:#fff;cursor:pointer;min-height:48px;
font-family:var(--font-body);}}
.ev-go:disabled{{opacity:.55;cursor:default;}}
.ev-msg{{display:none;font-size:13px;line-height:1.5;}}
.ev-msg.ok{{display:block;color:var(--text-primary);font-weight:600;}}
.ev-msg.err{{display:block;color:#b3261e;}}
.ev-fullnote{{margin-top:12px;font-size:13px;color:var(--text-muted);line-height:1.5;}}
.ev-empty{{text-align:center;padding:32px 16px;color:var(--text-secondary);
border:1px dashed var(--border);border-radius:16px;font-size:14px;line-height:1.6;}}
.ev-footer{{text-align:center;font-size:11px;color:var(--text-muted);margin-top:28px;
padding-top:14px;border-top:1px solid var(--border);}}
.ev-footer a{{color:var(--text-muted);text-decoration:none;}}
</style>
</head>
<body>
<main class="ev-shell">
  <header class="ev-header">
    {logo_html}
    <h1 class="ev-name">{_esc(name)}</h1>
    <p class="ev-kicker">What's coming up</p>
  </header>
  {cards}
  <footer class="ev-footer">
    Powered by <a href="https://mysolutionist.app/" target="_blank" rel="noopener">Solutionist</a>
  </footer>
</main>
<script>
(function() {{
  var API = {api_origin!r};
  var SLUG = {slug!r};
  document.querySelectorAll('.ev-form').forEach(function(form) {{
    form.addEventListener('submit', function(ev) {{
      ev.preventDefault();
      var msg = form.querySelector('.ev-msg');
      var go = form.querySelector('.ev-go');
      msg.className = 'ev-msg';
      var name = form.querySelector('[name=name]').value.trim();
      var email = form.querySelector('[name=email]').value.trim();
      var roleSel = form.querySelector('[name=role]');
      if (!name) {{ msg.textContent = 'Please tell us your name.'; msg.className = 'ev-msg err'; return; }}
      if (!email) {{ msg.textContent = 'Please add your email.'; msg.className = 'ev-msg err'; return; }}
      go.disabled = true;
      fetch(API + '/public/events/' + SLUG + '/rsvp', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          entry_id: form.getAttribute('data-entry'),
          name: name,
          email: email,
          role: roleSel && roleSel.value ? roleSel.value : undefined
        }})
      }}).then(function(r) {{ return r.json().then(function(j) {{ return {{ok: r.ok, j: j}}; }}); }})
        .then(function(res) {{
          if (res.ok && res.j && res.j.ok) {{
            msg.textContent = res.j.already
              ? "You're already on the list — see you there!"
              : "You're in — see you there!";
            msg.className = 'ev-msg ok';
            form.querySelectorAll('input,select').forEach(function(el) {{ el.disabled = true; }});
            return;
          }}
          msg.textContent = (res.j && res.j.detail) || 'Something went wrong — please try again.';
          msg.className = 'ev-msg err';
          go.disabled = false;
        }})
        .catch(function() {{
          msg.textContent = 'Network hiccup — please try again.';
          msg.className = 'ev-msg err';
          go.disabled = false;
        }});
    }});
  }});
}})();
</script>
</body>
</html>"""


def render_events_unavailable_page(business: Dict[str, Any],
                                   canonical_url: str) -> str:
    """404-status page when the events page isn't enabled — brand-
    applied, mirroring giving's render_giving_unavailable_page."""
    name = (business.get("name") or "").strip() or "This organization"
    css_vars = _brand_css_vars(business)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>{_esc(name)}</title>",
        '<meta name="robots" content="noindex,nofollow">',
        f'<link rel="canonical" href="{_esc(canonical_url)}">',
        f"<style>{css_vars}</style>",
        "<style>html,body{margin:0;padding:0;font-family:var(--font-body);"
        "color:var(--text-primary);background:var(--surface);min-height:100vh;}"
        ".ev-shell{max-width:480px;margin:96px auto 0;padding:24px 16px;"
        "text-align:center;}"
        ".ev-name{font-family:var(--font-heading);font-size:22px;font-weight:700;}"
        ".ev-msg{margin-top:16px;color:var(--text-secondary);line-height:1.5;}"
        "</style>",
        "</head>",
        "<body>",
        '<main class="ev-shell">',
        f'<h1 class="ev-name">{_esc(name)}</h1>',
        '<p class="ev-msg">Event signups aren\'t available here yet.</p>',
        "</main>",
        "</body>",
        "</html>",
    ])
