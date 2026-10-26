"""church_my_week.py — My week: a church login's first page.

Kevin, 2026-10-26 ("Who sees what", canvas 99aFvCSRXU1x9pmqUcncoP, boards
"Built: My week"): pastors, admins and teams signing in would find the whole
system overwhelming. Each person's first page is what's theirs: what's been
handed to them, one line for each area they work in, and what crossed from
one area to another this week. The owner and admins see the whole church,
an area to a line; a login that works some areas sees only those.

    GET /church/my-week?business_id=          the page (any office login)
    GET /church/my-week/status?business_id=   whether this app shows it

Everything is read from where it already lives: the areas map
(church_areas.build: who works each area and what's missing), follow-ups
(church_follow_ups: handed to the person, matched by their sign-in email),
and Prayer & care requests handed to their login (assigned_to, said as one
line with nothing of what was asked). A read that fails is a 503, never an
empty week. Switched with the map: CHURCH_AREAS (off | owner | on).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import church_areas
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

HANDED_DAYS = 7
SHOWN = 6
FINANCE_ROLES = ("owner", "admin")

# Where each kind of thing opens in the app (churchStructure's leaf ids).
DOOR = {
    "follow_up": {"area": "operate", "id": "follow-up", "label": "Open the Follow-up board"},
    "care": {"area": "operate", "id": "care", "label": "Open Prayer & care"},
    "areas": {"area": "operate", "id": "areas", "label": "Open Areas"},
    "kids_youth": {"area": "operate", "id": "kids", "label": "Open Kids check-in"},
    "groups_classes": {"area": "operate", "id": "groups", "label": "Open Groups"},
    "worship_media": {"area": "operate", "id": "sundays", "label": "Open Sundays"},
    "people_care": {"area": "operate", "id": "follow-up", "label": "Open the Follow-up board"},
    "messages_safety": {"area": "operate", "id": "messaging", "label": "Open Member messaging"},
    "website_outreach": {"area": "build", "id": "my-site", "label": "Open the website"},
    "office": {"area": "operate", "id": "tasks", "label": "Open Tasks"},
    "giving_money": {"area": "operate", "id": "bookkeeping", "label": "Open Giving"},
}


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    return rows


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "Someone"


def _when(ts: Any, now: datetime) -> str:
    """'Sunday', 'yesterday', 'Oct 12': how a person says when."""
    d = _parse(ts)
    if not d:
        return ""
    days = (now.date() - d.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%b')} {d.day}"


def _area_line(area: Dict[str, Any]) -> Dict[str, Any]:
    gaps = list(area.get("gaps") or [])
    names = list(dict.fromkeys(p.get("name") for p in area.get("people") or [] if p.get("name")))
    return {
        "key": area["key"], "label": area["label"],
        "line": gaps[0] if gaps else ("Nothing missing." if names else f"No one works it yet. Usually: {area.get('team')}."),
        "more": max(0, len(gaps) - 1), "gaps": len(gaps),
        "state": "watch" if gaps or not names else "ok",
        "people": len(names), "names": names[:3],
        "door": DOOR.get(area["key"]),
    }


def build(business: Dict[str, Any], user_id: str, email: str, role: str) -> Dict[str, Any]:
    biz = str(business["id"])
    now = _now()
    view = church_areas.view_for(biz, user_id, role)
    if view is None:
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    whole = view["areas"] is None
    finance = role in FINANCE_ROLES
    mine_areas = [a for a in church_areas.AREA_ORDER if (whole or a in view["areas"]) and (finance or a != "giving_money")]
    the_map = church_areas.build(business)
    by_key = {a["key"]: a for a in the_map["areas"]}
    areas = [_area_line(by_key[a]) for a in mine_areas if a in by_key]

    # The person behind this login, by their sign-in email.
    email = (email or "").strip().lower()
    me_ids: List[str] = []
    if email and "@" in email:
        me = _need(f"/contacts?business_id=eq.{_q(biz)}&email=ilike.{_q(church_areas._escape_ilike(email))}"
                   "&select=id&limit=10")
        me_ids = [str(c["id"]) for c in me]

    needs: List[Dict[str, Any]] = []
    # Follow-ups handed to them.
    if me_ids:
        rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&leader_contact_id=in.({','.join(_q(i) for i in me_ids)})"
                     "&status=eq.open&select=id,contact_id,card_name,due_at,created_at&order=due_at.asc&limit=50")
        names = _names(biz, [r["contact_id"] for r in rows])
        for r in rows:
            due = _parse(r.get("due_at"))
            late = bool(due and due < now)
            who = names.get(str(r["contact_id"])) or "Someone"
            needs.append({"kind": "follow_up", "late": late, "area": "people_care",
                          "title": f"{who} is waiting to hear from you." if late else f"{who} was handed to you.",
                          "detail": f"{r.get('card_name') or 'A card'} · " + (
                              f"due {_when(r.get('due_at'), now)}" if late else f"handed {_when(r.get('created_at'), now)}"),
                          "door": DOOR["follow_up"]})
    # Prayer & care handed to their login: one line, nothing of what was asked.
    care = _need(f"/ministry_care_requests?business_id=eq.{_q(biz)}&assigned_to=eq.{_q(user_id)}"
                 "&status=in.(new,reviewed)&select=id&limit=50")
    if care:
        n = len(care)
        needs.append({"kind": "care", "late": False, "area": "people_care",
                      "title": "A prayer or care request was handed to you." if n == 1
                      else f"{n} prayer or care requests were handed to you.",
                      "detail": "Private to you and the pastors.", "door": DOOR["care"]})
    # The whole church: follow-ups with no one, and late ones.
    if whole:
        open_rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&status=in.(open,handed_back)"
                          "&select=status,leader_contact_id,due_at&limit=500")
        no_one = sum(1 for r in open_rows if r.get("status") == "handed_back" or not r.get("leader_contact_id"))
        late = sum(1 for r in open_rows if r.get("status") == "open" and (_parse(r.get("due_at")) or now) < now)
        if no_one:
            needs.append({"kind": "no_one", "late": True, "area": "people_care",
                          "title": f"{no_one} {'person' if no_one == 1 else 'people'} in follow-up "
                                   f"{'has' if no_one == 1 else 'have'} no one.",
                          "detail": "Hand them to someone on the Follow-up board.", "door": DOOR["follow_up"]})
        if late:
            needs.append({"kind": "late", "late": False, "area": "people_care",
                          "title": f"{late} follow-up{'s are' if late != 1 else ' is'} late.",
                          "detail": "Each one has already been nudged; the board says who has it.", "door": DOOR["follow_up"]})
        unplaced = [x for x in the_map.get("logins") or [] if x.get("by") == "none"]
        if unplaced:
            n = len(unplaced)
            needs.append({"kind": "logins", "late": False, "area": "office",
                          "title": f"{n} office login{'s still see' if n != 1 else ' still sees'} everything.",
                          "detail": "Give them their areas, so each sees their part.", "door": DOOR["areas"]})
    else:
        # A login that works some areas: what's missing in them is theirs.
        for a in areas:
            for gap in (by_key[a["key"]].get("gaps") or [])[:2]:
                needs.append({"kind": "gap", "late": False, "area": a["key"], "title": gap, "detail": a["label"],
                              "door": a["door"]})

    handed = _handed(biz, now, whole, set(mine_areas))
    order = {"follow_up": 0, "no_one": 1, "care": 2, "gap": 3, "late": 4, "logins": 5}
    needs.sort(key=lambda n: (not n["late"], order.get(n["kind"], 9)))
    return {
        "me": {"role": role, "areas": view["areas"], "by": view["by"], "why": view["why"]},
        "next": needs[0] if needs else None,
        "needs": needs[1:SHOWN + 1],
        "areas": areas,
        "handed": handed,
        "counts": {"needs": len(needs), "areas": len(areas), "handed": len(handed)},
    }


def _role(business: Dict[str, Any], user_id: str) -> str:
    """The caller's standing: the owner, or their seat's role. A read that
    fails is a 503, never "no seat" (business_access has already let them in)."""
    if str(business.get("owner_id")) == str(user_id):
        return "owner"
    rows = _need(f"/business_users?business_id=eq.{_q(business['id'])}&user_id=eq.{_q(user_id)}"
                 "&status=eq.active&select=role&limit=1")
    if not rows or not rows[0].get("role"):
        raise HTTPException(404, "Not Found")
    return str(rows[0]["role"])


def _names(biz: str, ids: List[Any]) -> Dict[str, str]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    rows = _need(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name&limit=200")
    return {str(r["id"]): (r.get("name") or "").strip() or "Someone" for r in rows}


def _handed(biz: str, now: datetime, whole: bool, mine: set) -> List[Dict[str, Any]]:
    """Follow-ups started this week, as hand-offs between areas: a first
    check-in goes from the kids desk to Welcome, a card from the card to its
    role. The whole church sees them all; a login that works People & care
    sees them too; Kids & youth sees the first check-ins."""
    if not (whole or mine & {"people_care", "kids_youth"}):
        return []
    since = (now - timedelta(days=HANDED_DAYS)).isoformat()
    rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&created_at=gte.{_q(since)}"
                 "&select=id,contact_id,card_key,card_name,leader_contact_id,leader_role,status,due_at,done_at,created_at"
                 "&order=created_at.desc&limit=40")
    if not (whole or "people_care" in mine):
        rows = [r for r in rows if r.get("card_key") == "checkin:first"]
    names = _names(biz, [r.get("contact_id") for r in rows] + [r.get("leader_contact_id") for r in rows])
    import church_roles as cr
    defs = cr.defs(biz)
    if defs is None:
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    out = []
    for r in rows[:SHOWN]:
        who = names.get(str(r.get("contact_id"))) or "Someone"
        leader = names.get(str(r.get("leader_contact_id") or "")) if r.get("leader_contact_id") else None
        first = r.get("card_key") == "checkin:first"
        due = _parse(r.get("due_at"))
        status = r.get("status")
        if status == "done":
            state, said = "reached", f"{_first(leader) if leader else 'Someone'} reached them {_when(r.get('done_at'), now)}".strip()
        elif status == "handed_back" or not leader:
            state, said = "no_one", "With no one yet"
        elif due and due < now:
            state, said = "late", f"With {_first(leader)}, late"
        else:
            state, said = "with", f"With {_first(leader)}"
        out.append({
            "id": str(r.get("id")),
            "from": "Kids check-in" if first else (r.get("card_name") or "A card"),
            "to": cr.title_of(r.get("leader_role") or "", defs) if r.get("leader_role") else "The office",
            "title": f"{who}, first time" if first else who,
            "detail": f"{'Checked in' if first else 'Came in'} {_when(r.get('created_at'), now)} · {said}",
            "state": state,
        })
    return out


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/my-week/status")
def my_week_status(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                   biz: Dict[str, Any] = Depends(business_access("viewer"))):
    """Whether this person's app shows My week: a church, the switch on for
    them. Reads nothing but the business."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    return {"enabled": cfu.is_church(biz)}


@router.get("/my-week")
def my_week(business_id: str, as_user: Optional[str] = None, session: UserSession = Depends(sb_clients.authed_request),
            biz: Dict[str, Any] = Depends(business_access("viewer"))):
    """The caller's week, or, for the owner or an admin seeing as another
    office login (See as), that login's week: what it's shown, what's
    handed to it. Admins already see the whole church."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "My week is for churches")
    bid = str(biz["id"])
    role = _role(biz, str(session.user.id))
    if as_user and as_user != str(session.user.id):
        if role not in FINANCE_ROLES:
            raise HTTPException(403, "Only the owner or an admin can see as someone else")
        try:
            uid = str(uuid.UUID(as_user))
        except (ValueError, TypeError):
            raise HTTPException(400, "That login isn't valid")
        seat = _need(f"/business_users?business_id=eq.{_q(bid)}&user_id=eq.{_q(uid)}&status=eq.active"
                     "&select=role,invited_email&limit=1")
        if not seat:
            raise HTTPException(404, "That login isn't on this church")
        return build(biz, uid, seat[0].get("invited_email") or "", seat[0].get("role") or "viewer")
    return build(biz, str(session.user.id), session.user.email or "", role)
