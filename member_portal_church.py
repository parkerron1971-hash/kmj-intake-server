"""
member_portal_church.py — the member page, part 2: coming up, prayer, my details.

Part 1 (member_portal.py) signs a member in and shows their giving. This
adds the three things Kevin asked the page to do next, each acting as the
signed-in person — no name or email to type, because the church already
knows who they are:

  COMING UP  The church's upcoming occasions (every active Services &
             Events room, the same list the public events page builds).
             "I'm coming", serve in an open role, or "Can't make it".
             One signup per person per occasion: acting again replaces
             their earlier answer. Capacity, the occasion's own roles and
             role fills are the public page's rules (events_rsvp_router),
             and every write carries the entry's updated_at, so a
             concurrent change is re-read rather than overwritten.
  PRAYER     A request goes to Prayer & care (ministry_care_requests —
             owner-only, never scored, never followed up automatically),
             linked to the member's record.
  MY DETAILS Phone and mailing address, written onto their own contact
             (metadata.mailing_address). Email is how they sign in, so it
             changes only through the church office.

Every route: same-origin POST, a live session re-checked against the
records, a per-person rate limit, and a redirect back with a short code
(never a name or an address in the URL).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_portal_church")

router = APIRouter(tags=["member-portal"])

PRAYER_MAX = 4000
FIELD_MAX = 120
PHONE_RE = re.compile(r"^[0-9+()\-.\s]{7,25}(\s*(x|ext\.?)\s*\d{1,6})?$", re.IGNORECASE)

DONE = {
    "coming": "You're on the list. See you there.",
    "serving": "Thank you for serving. You're on the roster.",
    "cant": "Thanks for letting us know.",
    "prayer": "Your prayer request was sent privately to the pastor.",
    "details": "Your details are saved.",
}
ERRORS = {
    "full": "That one is full now.",
    "role": "That role was just filled, or isn't on this event any more.",
    "gone": "That event isn't available any more.",
    "past": "That event has already happened.",
    "busy": "Someone else was updating that event at the same moment. Please try again.",
    "error": "That didn't save. Please try again in a moment.",
    "slow": "That's a lot at once. Wait a few minutes, then try again.",
    "empty": "Write your prayer request first.",
    "phone": "That phone number doesn't look right.",
}


# ─── Occasions ────────────────────────────────────────────────────────


def _norm_name(s: Any) -> str:
    return " ".join(str(s or "").split()).casefold()


def is_mine(signup: Dict[str, Any], me: Dict[str, Any]) -> bool:
    """A signup belongs to this person when it carries their contact id —
    or carries NO contact id and exactly their name: the office typed
    "Ana Rivers" onto the roster before Ana ever signed in, and her own
    answer must replace that line, not sit beside it."""
    cid = str(signup.get("contact_id") or "")
    if cid:
        return cid == str(me["id"])
    mine = _norm_name(me.get("name"))
    return bool(mine) and _norm_name(signup.get("name")) == mine


def can_see(data: Dict[str, Any], f: Dict[str, Any], me: Dict[str, Any]) -> bool:
    """Public: yes. Private: never (the church only). Invite only: when it
    was shared with them, or they are on its roster — by record, or by the
    name the office typed before they had one."""
    import events_rsvp_router as er
    v = er.occasion_visibility(data)
    if v != "invite":
        return v == "public"
    return er.visible_to_member(data, str(me["id"]), f["signups_field"]) or any(
        is_mine(s, me) for s in er.read_signups(data, f["signups_field"]))


def _roster_modules(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """The church's active Services & Events rooms, or None when the read
    failed ("try again", never "that event is gone")."""
    mods = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{quote(str(business_id), safe='')}"
        f"&archetype=eq.event_roster&is_active=eq.true&select=id,name,archetype_params&limit=50")
    return mods if isinstance(mods, list) else None


def upcoming_for(business_id: str, me: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The church's upcoming occasions, each with this person's answer.
    None when the read failed (the page says so; it never shows "nothing
    coming up" for a failed read).

    Each room is read NEWEST first: occasions stay active after they
    happen, so an oldest-first read with a cap would, after a year of
    Sundays, return only the past and drop what is actually coming."""
    import events_rsvp_router as er
    mods = _roster_modules(business_id)
    if mods is None:
        return None
    if not mods:
        return []
    by_mod: Dict[str, List[Dict[str, Any]]] = {}
    entries: Dict[str, Dict[str, Any]] = {}
    for m in mods:
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?module_id=eq.{quote(str(m['id']), safe='')}"
            f"&business_id=eq.{quote(str(business_id), safe='')}&status=eq.active"
            f"&select=id,module_id,data,updated_at&order=created_at.desc&limit=200")
        if not isinstance(rows, list):
            return None
        by_mod[str(m["id"])] = rows
        entries.update({str(r.get("id")): r for r in rows})
    fields = {str(m["id"]): er.resolve_fields(m.get("archetype_params")) for m in mods}
    out = er.build_occasions(mods, by_mod, include=lambda data, f: can_see(data, f, me))
    for o in out:
        entry = entries.get(str(o.get("entry_id"))) or {}
        f = fields.get(str(o.get("module_id")))
        signups = er.read_signups(entry.get("data") or {}, f["signups_field"]) if f else []
        mine = next((s for s in signups if is_mine(s, me)), None)
        o["mine"] = ({"status": mine.get("status") or "yes", "role": mine.get("role")} if mine else None)
    return out


def _registration_key(business_id: str, entry_id: str, email: str) -> str:
    """The key the public events page stores when someone RSVPs there
    (events_rsvp_router.public_event_rsvp) — so an answer given here can
    clear it and the public page does not later say "already registered"."""
    import hashlib
    return hashlib.sha256(f"{business_id}:{entry_id}:{str(email or '').strip().lower()}".encode()).hexdigest()


def member_rsvp(business_id: str, me: Dict[str, Any], entry_id: str, action: str,
                role_id: str = "") -> Tuple[bool, str]:
    """Record this person's answer for one occasion. Returns (ok, code):
    a DONE code on success, an ERRORS code otherwise. Their earlier answer
    for the occasion is replaced, never duplicated, and keeps whatever the
    office wrote on it (a note, say)."""
    import events_rsvp_router as er
    if action not in ("coming", "serve", "cant"):
        return False, "error"
    cid = str(me["id"])
    name = (me.get("name") or "").strip() or "A member"
    for _ in range(4):
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?id=eq.{quote(entry_id, safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
            f"&status=eq.active&select=id,module_id,data,updated_at&limit=1")
        if not isinstance(rows, list):
            return False, "error"
        if not rows:
            return False, "gone"
        entry = rows[0]
        mods = _roster_modules(business_id)
        if mods is None:
            return False, "error"
        module = next((m for m in mods if str(m.get("id")) == str(entry.get("module_id"))), None)
        if not module:
            return False, "gone"
        f = er.resolve_fields(module.get("archetype_params"))
        data = dict(entry.get("data") or {})
        signups = er.read_signups(data, f["signups_field"])
        # Private, or invite-only and not shared with them: it does not
        # exist as far as their page is concerned.
        if not can_see(data, f, me):
            return False, "gone"
        day = er._parse_day(data.get(f["date_field"]))
        if day is None or day < date.today():
            return False, "past"
        old = next((s for s in signups if is_mine(s, me)), None) or {}
        others = [s for s in signups if not is_mine(s, me)]
        base = {k: v for k, v in old.items() if k != "role"}
        if action in ("coming", "serve"):
            cap = er._capacity_of(data, f["capacity_field"])
            if cap is not None and er.attending_count(others) >= cap:
                return False, "full"
            new: Dict[str, Any] = {**base, "name": name, "status": "yes", "contact_id": cid}
            if action == "serve":
                role = next((r for r in er.occasion_roles(data, f["roles"]) if r.get("id") == role_id), None)
                if not role or er.role_fill(role, others)["full"]:
                    return False, "role"
                new["role"] = role_id
            others.append(new)
            done = "serving" if action == "serve" else "coming"
        else:
            others.append({**base, "name": name, "status": "no", "contact_id": cid})
            keys = data.get("_registration_keys")
            if isinstance(keys, dict):
                data["_registration_keys"] = {
                    k: v for k, v in keys.items()
                    if k != _registration_key(str(business_id), str(entry["id"]), me.get("email") or "")}
            done = "cant"
        data[f["signups_field"]] = others
        revision = entry.get("updated_at")
        if not revision:
            return False, "error"
        saved = sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{quote(str(entry['id']), safe='')}"
            f"&business_id=eq.{quote(str(business_id), safe='')}"
            f"&updated_at=eq.{quote(str(revision), safe='')}", {"data": data})
        if isinstance(saved, list) and saved:
            return True, done
        # A concurrent change (or a failed write): read again and retry.
    return False, "busy"


# ─── Prayer and details ──────────────────────────────────────────────


def save_prayer(business_id: str, me: Dict[str, Any], text: str, confidential: bool) -> bool:
    text = (text or "").strip()[:PRAYER_MAX]
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": str(business_id), "form_id": None, "contact_id": str(me["id"]),
        "status": "new",
        "submission": {
            "name": (me.get("name") or "").strip(), "email": me.get("email") or "",
            "phone": me.get("phone") or "", "prayer_request": text,
            "confidential": "yes" if confidential else "no",
            "source": "Member page",
        },
    })
    return isinstance(rows, list) and bool(rows)


def load_me(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{quote(str(contact_id), safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
        f"&select=id,name,email,phone,metadata,updated_at&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def clean_details(form: Dict[str, Any], stored_phone: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    phone = str(form.get("phone") or "").strip()
    # The number the office already stored is never re-judged: a member
    # changing only their address must not be stopped by its format.
    if phone and phone != (stored_phone or "").strip() and (
            not PHONE_RE.match(phone) or len(re.sub(r"\D", "", phone)) < 7):
        return None, "phone"
    addr = {k: str(form.get(k) or "").strip()[:FIELD_MAX] for k in ("line1", "line2", "city", "state", "postal")}
    return {"phone": phone, "address": addr}, ""


def update_details(business_id: str, contact_id: str, details: Dict[str, Any]) -> bool:
    """Write phone + mailing address onto the member's own contact, guarded
    by its updated_at so an office edit at the same moment is not lost."""
    for _ in range(3):
        me = load_me(business_id, contact_id)
        if not me or not me.get("updated_at"):
            return False
        meta = dict(me.get("metadata") or {})
        addr = {k: v for k, v in details["address"].items() if v}
        if addr:
            meta["mailing_address"] = addr
        else:
            meta.pop("mailing_address", None)
        meta["details_updated_by_member_at"] = datetime.now(timezone.utc).isoformat()
        saved = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{quote(str(contact_id), safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
            f"&updated_at=eq.{quote(str(me['updated_at']), safe='')}",
            {"phone": details["phone"] or None, "metadata": meta})
        if isinstance(saved, list) and saved:
            return True
    return False


# ─── Pages ────────────────────────────────────────────────────────────


def _flash(request: Request) -> str:
    from member_portal import _e
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def _status_line(o: Dict[str, Any]) -> str:
    from member_portal import _e
    mine = o.get("mine")
    if not mine:
        return ""
    if mine["status"] == "no":
        return '<p class="mp-mine">You said you can\'t make it.</p>'
    if mine["status"] == "maybe":
        return '<p class="mp-mine">You said maybe.</p>'
    if mine.get("role"):
        label = next((r["label"] for r in o.get("roles") or [] if r.get("id") == mine["role"]), "serving")
        return f'<p class="mp-mine">You\'re serving: <strong>{_e(label)}</strong></p>'
    return '<p class="mp-mine">You\'re coming.</p>'


def occasion_card(o: Dict[str, Any], back: str, level: int = 2) -> str:
    """One occasion with the actions that fit this person's answer.
    Nothing offered can only fail: on a full occasion someone not already
    coming is not offered "I'm coming" OR a role (servers count toward the
    headcount). Each button names the occasion for a screen reader."""
    from member_portal import _e
    eid = _e(o.get("entry_id"))
    title_id = f"mp-occ-{eid}"
    facts = [o.get("location") or ""]
    if o.get("capacity") is not None:
        facts.append("Full" if o.get("full") else f"{o.get('spots_left')} places left")
    facts_html = " · ".join(_e(x) for x in facts if x)
    mine = o.get("mine") or {}
    coming = bool(mine) and mine.get("status") == "yes"
    serving_role = mine.get("role") if coming else None
    can_join = coming or not o.get("full")
    hidden = f'<input type="hidden" name="entry_id" value="{eid}"><input type="hidden" name="back" value="{_e(back)}">'
    about = f'aria-describedby="{title_id}"'
    actions = []
    if (not coming or serving_role) and can_join:
        label = "Just attend instead" if serving_role else "I'm coming"
        actions.append(f'<form method="post" action="/my/rsvp">{hidden}<input type="hidden" name="action" value="coming">'
                       f'<button class="{"mp-link" if serving_role else "mp-go"}" type="submit" {about}>{label}</button></form>')
    open_roles = [r for r in o.get("roles") or [] if not r.get("full") and r.get("id") != serving_role]
    if open_roles and can_join:
        opts = "".join(f'<option value="{_e(r["id"])}">{_e(r["label"])} — {r["needed"] - r["filled"]} needed</option>'
                       for r in open_roles)
        actions.append(f'<form method="post" action="/my/rsvp" class="mp-serve">{hidden}<input type="hidden" name="action" value="serve">'
                       f'<label class="mp-sr" for="mp-role-{eid}">Role to serve in</label>'
                       f'<select class="mp-input" id="mp-role-{eid}" name="role">{opts}</select>'
                       f'<button class="mp-go mp-go-2" type="submit" {about}>Serve</button></form>')
    if mine.get("status") != "no":
        actions.append(f'<form method="post" action="/my/rsvp">{hidden}<input type="hidden" name="action" value="cant">'
                       f'<button class="mp-link" type="submit" {about}>Can\'t make it</button></form>')
    h = "h3" if level == 3 else "h2"
    return f"""<article class="mp-card mp-occ" aria-labelledby="{title_id}">
  <p class="mp-when">{_e(o.get('date_label') or '')}</p>
  <{h} id="{title_id}">{_e(o.get('title') or '')}</{h}>
  {f'<p class="mp-muted">{facts_html}</p>' if facts_html else ''}
  {_status_line(o)}
  <div class="mp-actions">{''.join(actions)}</div>
</article>"""


def render_events(biz, site, request: Request, occasions: Optional[List[Dict[str, Any]]]) -> str:
    from member_portal import _shell
    if occasions is None:
        body = '<p class="mp-err" role="alert">What\'s coming up couldn\'t load just now. Please try again in a moment.</p>'
    elif not occasions:
        body = '<p class="mp-muted">Nothing is on the calendar yet. Check back soon.</p>'
    else:
        body = "".join(occasion_card(o, "/my/events") for o in occasions)
    return _shell(biz, site, "Coming up", f"""
<p><a class="mp-link" href="/my">← My page</a></p>
<h1>Coming up</h1>
<p class="mp-muted">Let the church know you're coming, or sign up to serve.</p>
{_flash(request)}
{body}""")


def render_prayer(biz, site, request: Request) -> str:
    from member_portal import _e, _shell
    church = _e(biz.get("name") or "the church")
    return _shell(biz, site, "Prayer", f"""
<p><a class="mp-link" href="/my">← My page</a></p>
<h1>How can we pray for you?</h1>
<p class="mp-muted">Your request goes privately to the pastor at {church}. It isn't posted anywhere or shared with other members.</p>
{_flash(request)}
<form class="mp-card mp-form" method="post" action="/my/prayer">
  <label for="mp-prayer">Your prayer request</label>
  <textarea class="mp-input mp-text" id="mp-prayer" name="request" rows="6" maxlength="{PRAYER_MAX}" required></textarea>
  <label class="mp-check"><input type="checkbox" name="confidential" value="yes"> Keep this between me and the pastor</label>
  <button class="mp-go" type="submit">Send privately</button>
</form>""")


def render_details(biz, site, request: Request, me: Dict[str, Any]) -> str:
    from member_portal import _e, _shell
    addr = (me.get("metadata") or {}).get("mailing_address") or {}
    if not isinstance(addr, dict):
        addr = {}
    field = lambda k, label, auto: (
        f'<label for="mp-{k}">{label}</label>'
        f'<input class="mp-input" id="mp-{k}" name="{k}" autocomplete="{auto}" maxlength="{FIELD_MAX}" value="{_e(addr.get(k) or "")}">')
    return _shell(biz, site, "My details", f"""
<p><a class="mp-link" href="/my">← My page</a></p>
<h1>My details</h1>
<p class="mp-muted">Keep the church's records up to date, so they can reach you by phone or mail.</p>
{_flash(request)}
<form class="mp-card mp-form" method="post" action="/my/details">
  <p class="mp-muted">Email: <strong>{_e(me.get('email') or '')}</strong>. It's how you sign in, so to change it, ask the church office.</p>
  <label for="mp-phone">Phone</label>
  <input class="mp-input" id="mp-phone" name="phone" type="tel" autocomplete="tel" maxlength="25" value="{_e(me.get('phone') or '')}">
  {field('line1', 'Street address', 'address-line1')}
  {field('line2', 'Apartment, suite (optional)', 'address-line2')}
  {field('city', 'City', 'address-level2')}
  {field('state', 'State', 'address-level1')}
  {field('postal', 'ZIP code', 'postal-code')}
  <button class="mp-go" type="submit">Save my details</button>
</form>""")


def home_cards(occasions: Optional[List[Dict[str, Any]]]) -> str:
    """The home page's part-2 cards: the next few occasions, prayer, details."""
    if occasions is None:
        coming = '<p class="mp-err" role="alert">What\'s coming up couldn\'t load just now.</p>'
    elif not occasions:
        coming = '<p class="mp-muted">Nothing is on the calendar yet.</p>'
    else:
        coming = "".join(occasion_card(o, "/my", level=3) for o in occasions[:2])
        if len(occasions) > 2:
            coming += f'<p><a class="mp-link" href="/my/events">See all {len(occasions)} coming up</a></p>'
    return f"""
<section aria-labelledby="mp-coming"><h2 id="mp-coming" class="mp-sect">Coming up</h2>{coming}</section>
<div class="mp-card mp-tiles">
  <a class="mp-tile" href="/my/prayer"><strong>Prayer</strong><span>Send a private request to the pastor</span></a>
  <a class="mp-tile" href="/my/details"><strong>My details</strong><span>Phone and mailing address</span></a>
</div>"""


# ─── POST ─────────────────────────────────────────────────────────────


async def _signed_in(request: Request):
    """(church, me, unavailable): me is None without a live session;
    unavailable is True when the records could not be read, so the route
    says "try again" instead of dropping the member at sign-in."""
    import asyncio
    from member_portal import _church_or_404, _session_for
    church = await _church_or_404(request)
    sess = await asyncio.to_thread(_session_for, request, church)
    if sess and sess.get("unavailable"):
        return church, None, True
    if not sess or not sess.get("me"):
        return church, None, False
    return church, sess["me"], False


def _back(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target not in ("/my", "/my/events", "/my/prayer", "/my/details"):
        target = "/my"
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


def _allowed(church, me) -> bool:
    import rate_limit
    return rate_limit.allow_strict("member_action", f"{church['business']['id']}|{me['id']}")


@router.post("/my/rsvp", include_in_schema=False)
async def rsvp(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    form = await request.form()
    back = str(form.get("back") or "/my")
    if unavailable:
        return _back(back, err="error")
    if not me:
        return _back("/my")
    if not _allowed(church, me):
        return _back(back, err="slow")
    ok, code = await asyncio.to_thread(
        member_rsvp, church["business"]["id"], me, str(form.get("entry_id") or ""),
        str(form.get("action") or ""), str(form.get("role") or ""))
    return _back(back, **({"done": code} if ok else {"err": code}))


@router.post("/my/prayer", include_in_schema=False)
async def prayer(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/prayer", err="error")
    if not me:
        return _back("/my")
    form = await request.form()
    text = str(form.get("request") or "").strip()
    if not text:
        return _back("/my/prayer", err="empty")
    if not _allowed(church, me):
        return _back("/my/prayer", err="slow")
    full = await asyncio.to_thread(load_me, church["business"]["id"], me["id"]) or me
    ok = await asyncio.to_thread(save_prayer, church["business"]["id"], full, text,
                                 str(form.get("confidential") or "") == "yes")
    return _back("/my", done="prayer") if ok else _back("/my/prayer", err="error")


@router.post("/my/details", include_in_schema=False)
async def details(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/details", err="error")
    if not me:
        return _back("/my")
    form = await request.form()
    stored = await asyncio.to_thread(load_me, church["business"]["id"], me["id"])
    if not stored:
        return _back("/my/details", err="error")
    cleaned, err = clean_details(dict(form), stored.get("phone") or "")
    if not cleaned:
        return _back("/my/details", err=err)
    if not _allowed(church, me):
        return _back("/my/details", err="slow")
    ok = await asyncio.to_thread(update_details, church["business"]["id"], me["id"], cleaned)
    return _back("/my/details", **({"done": "details"} if ok else {"err": "error"}))
