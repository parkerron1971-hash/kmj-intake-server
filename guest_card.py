"""
guest_card.py — the card a first-time guest scans, and who picks it.

Kevin, 2026-11-17, "build that": a printed connect card and guest QR that
the first-time guests' login (Tiara, People & Care) makes herself. The cards
print in the app (Forms › Print for guests, and Text › New here): a table
tent, seat cards and a half-sheet connect card, each with a big QR code to a
card she picks or to the New here text. Nothing here prints.

What the server keeps is the church's GUEST CARD: which of its cards a guest
lands on when they scan the bulletin's "New here?" code. Media &
Communications still makes the bulletin and the connect card (Bulletins &
print); this only says where a guest who scans one lands. Unset, the code
opens the church's links page, as before.

  GET /church/guest-card/{business_id}   any login of the church: the cards a
                                         guest can be sent to (switched on,
                                         not private), each with the address
                                         its QR code opens; the guest card;
                                         the New here text when it is on;
                                         and whether this login may choose
  PUT /church/guest-card/{business_id}   {form_id} or {form_id: null}: whoever
                                         does the first-time guests
                                         (church_duties first_guests: People
                                         & Care's by default, the owner and
                                         the admins always). A duty that can't
                                         be read is a 503, never a yes

Where it is kept: settings.new_here.guest_form, inside New here's own key (a
server key with its own checked endpoints, business_settings.SERVER_KEYS),
written with business_settings.merge under ["new_here"], so the app's own
logins can never write it and nothing else in New here is touched. New
here's PUT keeps it (new_here.KEPT).

A private card (a prayer or help card: settings.private_care, or "prayer"
in its name) is never a guest card: it goes only to Prayer & care and never
gives the guest a person and a call date, which is the first-time guests'
whole job.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("guest_card")

router = APIRouter(tags=["guest-card"])

DUTY = "first_guests"
KEY = "guest_form"                      # settings.new_here.guest_form
UNDER = ["new_here"]
MOST_FORMS = 100
MOST_QUESTIONS = 8
PRIVATE_NAME = re.compile(r"\bprayer\b", re.I)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(v: Any, missing: int = 404, said: str = "Church not found") -> str:
    from uuid import UUID
    try:
        return str(UUID(str(v)))
    except (TypeError, ValueError):
        raise HTTPException(missing, said)


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _church(biz: str) -> Dict[str, Any]:
    rows = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,settings,owner_id&limit=1")
    if rows is None:
        raise HTTPException(503, "The church couldn't be read just now. Try again in a minute.")
    business = rows[0] if rows else None
    import church_follow_up
    if not business or not church_follow_up.is_church(business):
        raise HTTPException(404, "The guest card is for churches.")
    return business


def is_private(form: Dict[str, Any]) -> bool:
    """A prayer or help card: Prayer & care's alone (the app's isPrayerName
    and settings.private_care)."""
    settings = form.get("settings") if isinstance(form.get("settings"), dict) else {}
    return bool(settings.get("private_care")) or bool(PRIVATE_NAME.search(str(form.get("name") or "")))


def origin(biz: str) -> str:
    """Where a card's page is opened: the church's own address (its domain,
    else its subdomain), or the API host, which serves the same page
    (chief_form_actions.public_form_url's rule)."""
    import church_follow_up
    own = church_follow_up.site_origin(biz)
    if own:
        return own
    from chief_host import FALLBACK_BASE
    return FALLBACK_BASE.rstrip("/")


def _questions(form: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The card's questions as a paper card prints them: a label, the kind
    of answer, and the choices when it has some."""
    out = []
    for f in (form.get("fields") if isinstance(form.get("fields"), list) else [])[:MOST_QUESTIONS]:
        if not isinstance(f, dict):
            continue
        label = " ".join(str(f.get("label") or f.get("name") or "").split())[:120]
        if not label:
            continue
        q: Dict[str, Any] = {"label": label, "type": str(f.get("type") or "text")[:20]}
        opts = f.get("options")
        if isinstance(opts, list) and opts:
            q["options"] = [" ".join(str(o).split())[:60] for o in opts[:8]]
        out.append(q)
    return out


def guest_forms(biz: str) -> List[Dict[str, Any]]:
    """The cards a guest can be sent to: switched on and not private, oldest
    first, each with the address its QR code opens. A read that fails is a
    503: an unread list is never "no cards"."""
    rows = _rows(f"/intake_forms?business_id=eq.{_q(biz)}&is_active=eq.true"
                 f"&select=id,name,form_type,fields,settings&order=created_at.asc&limit={MOST_FORMS}")
    if rows is None:
        raise HTTPException(503, "Your church's cards couldn't be read just now. Try again in a minute.")
    base = origin(biz)
    out = []
    for f in rows:
        if not f.get("id") or is_private(f):
            continue
        out.append({
            "id": str(f["id"]),
            "name": " ".join(str(f.get("name") or "").split()) or "Untitled card",
            "connect": f.get("form_type") == "connect_card",
            "url": f"{base}/public/widget/form/{_q(f['id'])}",
            "questions": _questions(f),
        })
    return out


def saved_of(business: Dict[str, Any]) -> str:
    nh = ((business.get("settings") or {}).get("new_here"))
    value = nh.get(KEY) if isinstance(nh, dict) else None
    return str(value) if isinstance(value, str) else ""


def _text(business: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The New here text, when a guest can send it: the switch open for the
    church, New here on, and the church's own number. None otherwise."""
    import new_here
    biz = str(business["id"])
    try:
        settings = new_here.settings_of(business)
        if not (settings.get("on") and new_here.switched_on(biz)):
            return None
        number = new_here.own_number(biz)
    except Exception:  # noqa: BLE001 - the print sheet works without it
        logger.info("guest card: New here not read", exc_info=True)
        return None
    if not number:
        return None
    return {"word": settings["word"], "number": number, "number_pretty": new_here.pretty_phone(number),
            "sms_link": f"sms:{number}?&body={settings['word']}"}


def may_choose(biz: str, user: AuthedUser) -> bool:
    """Whoever does the first-time guests (the owner and the admins always).
    A duty that can't be read is a 503."""
    import church_duties
    return church_duties.holds(biz, user, DUTY)


def _may_choose_quietly(biz: str, user: AuthedUser) -> bool:
    try:
        return may_choose(biz, user)
    except HTTPException as e:
        if e.status_code != 503:
            raise
        return False


def view(business: Dict[str, Any], *, can_choose: bool) -> Dict[str, Any]:
    biz = str(business["id"])
    forms = guest_forms(biz)
    saved = saved_of(business)
    chosen = next((f for f in forms if f["id"] == saved), None)
    return {
        "forms": forms,
        "chosen": chosen["id"] if chosen else None,
        # Chosen, then switched off, made private or deleted: the bulletin's
        # code is back on the links page until someone picks again.
        "chosen_gone": bool(saved) and chosen is None,
        "can_choose": can_choose,
        "text": _text(business),
    }


@router.get("/church/guest-card/{business_id}")
def get_guest_card(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    import business_access
    business_access.assert_access(biz, user, "viewer")
    business = _church(biz)
    return view(business, can_choose=_may_choose_quietly(biz, user))


class GuestCardIn(BaseModel):
    form_id: Optional[str] = None


@router.put("/church/guest-card/{business_id}")
def put_guest_card(business_id: str, body: GuestCardIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    import business_access
    import business_settings
    import church_duties
    business_access.assert_access(biz, user, "viewer")
    business = _church(biz)
    if not may_choose(biz, user):
        raise HTTPException(403, church_duties.refusal(biz, DUTY))
    form_id = str(body.form_id or "").strip()
    if not form_id:
        if business_settings.merge(biz, drop=[KEY], under=UNDER) is None:
            raise HTTPException(503, "That didn't save just now. Try again in a minute.")
        settings = dict(business.get("settings") or {})
        nh = dict(settings.get("new_here") or {}) if isinstance(settings.get("new_here"), dict) else {}
        nh.pop(KEY, None)
        return view({**business, "settings": {**settings, "new_here": nh}}, can_choose=True)
    form_id = _uuid(form_id, 400, "That isn't one of your church's cards.")
    rows = _rows(f"/intake_forms?id=eq.{_q(form_id)}&business_id=eq.{_q(biz)}"
                 "&select=id,name,is_active,settings&limit=1")
    if rows is None:
        raise HTTPException(503, "Your church's cards couldn't be read just now. Try again in a minute.")
    if not rows:
        raise HTTPException(404, "That isn't one of your church's cards.")
    form = rows[0]
    if form.get("is_active") is False:
        raise HTTPException(400, "That card is switched off. Switch it on in Forms first.")
    if is_private(form):
        raise HTTPException(400, "A prayer or help card stays private, so guests can't be sent to it. "
                                 "Pick a card that adds the guest to your members.")
    if business_settings.merge(biz, set={KEY: form_id}, under=UNDER) is None:
        raise HTTPException(503, "That didn't save just now. Try again in a minute.")
    settings = dict(business.get("settings") or {})
    nh = dict(settings.get("new_here") or {}) if isinstance(settings.get("new_here"), dict) else {}
    nh[KEY] = form_id
    return view({**business, "settings": {**settings, "new_here": nh}}, can_choose=True)
