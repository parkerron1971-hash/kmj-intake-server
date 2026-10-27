"""church_help.py — Help requests (benevolence): a fund, a limit, a yes and a record.

Kevin, 2026-10-27, on the Church Office Prototypes ("Help requests" tab,
artifact 2vGqaUZUynRuiFVKuQEZWo): "lets go with your list", help requests
first. A single mom asks for help with a light bill; the office needs a
fund, a limit, a yes, and a record. Lane: Build, under the Build item
"Love City leaves Subsplash (M-1)" (Love City's Food focus lives here).

    the FUND ...... one line per church (church_help_settings): the fund's
                    name (one of the church's giving funds, or its own), a
                    monthly budget and the single-gift limit ($150 unless
                    the church sets another). What's left this month is the
                    budget less what was given this month and what was
                    promised (approved, not given yet)
    a REQUEST ..... who asked (one of the church's people, a name, or no
                    one), the need (food, a bill, a ride, other), an amount
                    if any, the story, a status (new, approved, helped,
                    declined) and where it came from (the member app, a
                    phone call, a walk-in at the pantry)
    an ASK ........ a member's "Ask for help" from the app (member_asks.py)
                    lands in Prayer & care (ministry_care_requests,
                    submission.kind "help"). It shows here as a new request
                    from the app, and becomes a row of its own the first
                    time the office acts on it (care_request_id, once). The
                    Prayer & care row moves along with it: reviewed once
                    approved, closed once helped or declined
    the LIMIT ..... staff who work People & care approve up to the limit.
                    Above it a keeper of Giving & money says yes, through
                    the church keys (church_keys.py): a keeper approves it
                    here, or the asker asks for a key (an hour's yes, by tap
                    or code) and approves it while it's open. A church with
                    no keeper for Giving & money has only the limit: nobody
                    gives more than it at once, and the page says so.
                    Raising the limit needs the same yes
    HELP GIVEN .... cash, a check to the utility, a gift card, groceries, a
                    ride: each with an amount and a date. Money given goes
                    into the books the way every expense does: one
                    business_expenses row (Operating, subcategory the fund's
                    name, no name and no story), which the GL triggers turn
                    into journal entries. Giving more than was approved is
                    approving more, under the same limit

Who: the owner and admins, and office logins whose areas include People &
care (church_areas, "Who sees what"). They read the stories; anyone below a
member-level login only reads. A request marked private shows who asked to
the owner and admins only. A youth's ask (the member app's youth way) is
the owner's and admins' alone. A login that works Giving & money but not
People & care sees amounts, needs and dates, never a name or a story.

  GET    /church/help/status?business_id=      {enabled, view, approve, settings}
  GET    /church/help?business_id=             the fund, the keeper, the requests
  PUT    /church/help/settings                 {business_id, fund?, monthly_budget?, gift_limit?}
  POST   /church/help/requests                 {business_id, need, amount?, notes?, contact_id?, name?,
                                                anonymous?, wants_call?, source?}
  PATCH  /church/help/requests/{ref}           {business_id, ...what changes}
  POST   /church/help/requests/{ref}/decide    {business_id, status: approved | declined, amount?}
  POST   /church/help/requests/{ref}/given     {business_id, how, amount?, given_on?, payee?, note?}
  POST   /church/help/requests/{ref}/keeper    {business_id, amount?}     ask a keeper (church keys)
  POST   /church/help/key-code                 {business_id, key_id, code}
  DELETE /church/help/given/{id}?business_id=  take a record back (and its expense)

A request's ref is its id, or "care-<id>" for an ask from the app the
office hasn't acted on yet. Switched by CHURCH_HELP: off | owner | on (owner
until a Thursday). Until supabase/APPLY-2026-10-27-church-help.sql is
applied the status says enabled false and every other route answers 503,
never 500.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/help", tags=["church"])

NEEDS = ("food", "bill", "ride", "other")
STATUSES = ("new", "approved", "helped", "declined")
SOURCES = ("app", "phone", "walk_in", "other")
HOWS = ("cash", "check", "gift_card", "groceries", "ride", "other")
# Help that is money by its nature: it needs an amount.
MONEY_HOWS = ("cash", "check", "gift_card")
WRITERS = ("owner", "admin", "manager", "member")   # approve, record, add
KEEPS_ALL = ("owner", "admin")                      # the settings, private names, youth asks, undo
CARE_AREA = "people_care"
MONEY_AREA = "giving_money"                         # whose keepers say yes above the limit

DEFAULT_FUND = "Benevolence"
DEFAULT_LIMIT_CENTS = 15000
MONEY_MAX_CENTS = 10_000_000
NAME_MAX, NOTES_MAX, PAYEE_MAX, NOTE_MAX, FUND_MAX = 120, 2000, 120, 500, 80
OPEN_DAYS = 365          # a closed request stays on the page a year

# member_asks.py's contract: submission.kind "help", the pick's words in
# submission.need, the youth way in submission.youth / its source.
KIND_HELP = "help"
YOUTH_SOURCE = "Member app, Youth"
APP_NEED = {"food": "food", "a bill": "bill", "bill": "bill", "a ride": "ride", "ride": "ride",
            "something else": "other", "other": "other"}

NEED_WORD = {"food": "Food", "bill": "A bill", "ride": "A ride", "other": "Something else"}
HOW_WORD = {"cash": "cash", "check": "a check", "gift_card": "a gift card", "groceries": "groceries",
            "ride": "a ride", "other": "other help"}

REQ_FIELDS = ("id,contact_id,name,anonymous,pastors_only,wants_call,need,amount_cents,approved_cents,notes,"
              "status,source,care_request_id,created_by,decided_by,decided_at,created_at,updated_at")
GIVEN_FIELDS = "id,request_id,how,amount_cents,given_on,payee,note,expense_id,recorded_by,created_at"
CARE_FIELDS = "id,created_at,status,submission,contact_id"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_HELP") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _text(v: Any, most: int) -> str:
    """Words someone typed: kept as written (line breaks too), trimmed."""
    return str(v or "").replace("\r\n", "\n").strip()[:most]


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one (or the tables before their
    migration) is a 503, never an empty fund."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Help requests couldn't be read just now. Try again.")
    return rows


def usd(cents: Any) -> str:
    c = int(cents or 0)
    return f"${c // 100:,}" if c % 100 == 0 else f"${c / 100:,.2f}"


def cents(v: Any, what: str = "amount", *, allow_none: bool = True) -> Optional[int]:
    """Dollars as typed ("180", "$1,200.50") → cents; blank is None."""
    if v in (None, ""):
        if allow_none:
            return None
        raise HTTPException(400, f"Enter the {what} in dollars.")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = round(float(v) * 100)
    else:
        s = str(v).strip().replace("$", "").replace(",", "")
        if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
            raise HTTPException(400, f"Enter the {what} in dollars, like 150 or 42.50.")
        n = round(float(s) * 100)
    if not 0 <= n <= MONEY_MAX_CENTS:
        raise HTTPException(400, f"Enter the {what} in dollars, like 150 or 42.50.")
    return int(n)


def _tz(biz_id: str) -> ZoneInfo:
    try:
        import outside_calendar
        return ZoneInfo(outside_calendar.business_timezone(biz_id) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, Exception):
        return ZoneInfo("UTC")


def _today(me: Dict[str, Any]) -> date:
    """Today in the church's clock (read once per request, when needed)."""
    if "tz" not in me:
        me["tz"] = _tz(str(me["biz"]["id"]))
    return _now().astimezone(me["tz"]).date()


def _chunks(ids: Iterable[str], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def view_of(biz_id: str, uid: str, role: str) -> Optional[str]:
    """'care' (the stories), 'money' (amounts only) or None, for one login.
    The owner and admins always care; while Who sees what is off every login
    sees the whole church, as before; else a login whose areas are the whole
    church or include People & care, and amounts for one that works Giving
    & money. A view that couldn't be read is a 503, never a yes."""
    if role in KEEPS_ALL:
        return "care"
    import church_areas
    if church_areas.mode() != "on":
        return "care"
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    if areas is None or CARE_AREA in areas:
        return "care"
    if MONEY_AREA in areas:
        return "money"
    return None


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and this login's standing in its help requests. 404 when
    the switch is closed to them, they have no login here, or it isn't a
    church; 403 for a login that doesn't work People & care or Giving."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Help requests are for churches")
    view = view_of(biz_id, str(user.id), role)
    if view is None:
        raise HTTPException(403, "Help requests are kept with the pastors and the care team. "
                                 "An admin can add People & care to your areas.")
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user, "view": view,
            "boss": role in KEEPS_ALL, "writer": view == "care" and role in WRITERS}


def _writer(me: Dict[str, Any]) -> None:
    if not me["writer"]:
        raise HTTPException(403, "Your login can read help requests but not act on them."
                            if me["view"] == "care" else
                            "Help requests are kept with the pastors and the care team. You see the amounts.")


def _boss(me: Dict[str, Any], why: str) -> None:
    if not me["boss"]:
        raise HTTPException(403, why)


def _ready(biz_id: str) -> bool:
    """The three tables answer (one migration makes them)."""
    return isinstance(sb_clients.sb_get_as_service(
        f"/church_help_given?business_id=eq.{_q(biz_id)}&select=id&limit=1"), list)


# ─── The fund ─────────────────────────────────────────────────────────

def settings(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/church_help_settings?business_id=eq.{_q(biz_id)}"
                 "&select=fund,monthly_budget_cents,gift_limit_cents,updated_at&limit=1")
    s = rows[0] if rows else {}
    limit = s.get("gift_limit_cents")
    return {"fund": _plain(s.get("fund"))[:FUND_MAX] or DEFAULT_FUND,
            "monthly_budget_cents": int(s.get("monthly_budget_cents") or 0),
            "gift_limit_cents": int(limit) if limit is not None else DEFAULT_LIMIT_CENTS,
            "saved": bool(rows)}


def _funds(biz: Dict[str, Any]) -> List[str]:
    """The church's giving funds, to pick the benevolence fund from."""
    try:
        from giving_router import configured_funds, giving_settings
        s = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
        return configured_funds(giving_settings(s))
    except Exception:
        return []


# ─── The keepers (church_keys) ────────────────────────────────────────

def keeper_state(me: Dict[str, Any]) -> Dict[str, Any]:
    """Whether a keeper of Giving & money says yes above the limit here, and
    where this login stands: a keeper, holding an open key, or waiting on
    one. `on` is false while the keys are off or the church named no keeper:
    then the limit alone governs."""
    import church_keys
    off = {"on": False, "mine": False, "open_until": None, "asked": None, "keepers": 0}
    if church_keys.mode() == "off":
        return off
    biz = str(me["biz"]["id"])
    keepers = church_keys.active_keepers(biz, MONEY_AREA)
    if not keepers:
        return off
    state = {**off, "on": True, "keepers": len(keepers), "mine": me["uid"] in keepers}
    if state["mine"]:
        return state
    now = _now()
    rows = _need(f"/church_area_keys?business_id=eq.{_q(biz)}&user_id=eq.{_q(me['uid'])}&area=eq.{MONEY_AREA}"
                 "&status=in.(asked,open)&select=id,status,asked_at,opens_until&order=asked_at.desc&limit=5")
    for r in rows:
        until, asked = _at(r.get("opens_until")), _at(r.get("asked_at"))
        if r.get("status") == "open" and until and until > now and not state["open_until"]:
            state["open_until"] = r["opens_until"]
        elif (r.get("status") == "asked" and asked and asked > now - timedelta(hours=church_keys.ASK_HOURS)
              and not state["asked"]):
            state["asked"] = {"id": r["id"], "asked_at": r["asked_at"]}
    return state


def may_approve(me: Dict[str, Any], total: int, fund: Dict[str, Any]) -> None:
    """Whether this login may say yes to `total` cents for one request: up to
    the limit, any login that acts here; above it, only while Giving & money
    is open to them (a keeper, or an open key), and never where the church
    has no keeper (the limit alone governs)."""
    _writer(me)
    limit = fund["gift_limit_cents"]
    if total <= limit:
        return
    ks = keeper_state(me)
    if not ks["on"]:
        raise HTTPException(403, {
            "code": "over_limit", "limit_cents": limit,
            "message": f"Your church has no keeper for Giving & money, so {usd(limit)} is the most anyone gives "
                       "at once. The owner or an admin can change the limit on this page."})
    import church_keys
    if not church_keys.is_open(str(me["biz"]["id"]), me["user"], MONEY_AREA):
        raise HTTPException(403, {
            "code": "needs_keeper", "limit_cents": limit,
            "message": f"Above the {usd(limit)} limit, a keeper of Giving & money says yes. Ask a keeper: "
                       "their yes opens it for an hour."})


# ─── Requests: reading ────────────────────────────────────────────────

def _is_help(care: Dict[str, Any]) -> bool:
    sub = care.get("submission")
    return isinstance(sub, dict) and sub.get("kind") == KIND_HELP


def from_ask(care: Dict[str, Any]) -> Dict[str, Any]:
    """A member's ask from the app, in a request's own shape."""
    sub = care.get("submission") if isinstance(care.get("submission"), dict) else {}
    youth = str(sub.get("youth") or "").lower() in ("yes", "true", "1") or sub.get("source") == YOUTH_SOURCE
    try:
        amount = cents(sub.get("amount"))
    except HTTPException:
        amount = None
    return {
        "contact_id": care.get("contact_id"), "name": _plain(sub.get("name"))[:NAME_MAX] or None,
        "anonymous": False, "pastors_only": youth,
        "wants_call": str(sub.get("wants_call") or "").lower() in ("yes", "true", "1"),
        "need": APP_NEED.get(_plain(sub.get("need")).lower(), "other"), "amount_cents": amount,
        "approved_cents": None,
        "notes": _text(sub.get("request") or sub.get("prayer_request"), NOTES_MAX),
        "status": "new", "source": "app", "care_request_id": str(care["id"]),
        "created_at": care.get("created_at"),
    }


def _asks(biz_id: str) -> List[Dict[str, Any]]:
    """The app's help asks the office hasn't acted on: still open in Prayer
    & care, and with no request row of their own yet."""
    rows = _need(f"/ministry_care_requests?business_id=eq.{_q(biz_id)}&submission->>kind=eq.{KIND_HELP}"
                 f"&status=in.(new,reviewed)&select={CARE_FIELDS}&order=created_at.desc&limit=200")
    rows = [r for r in rows if _is_help(r)]
    linked: Set[str] = set()
    for ids in _chunks(r["id"] for r in rows):
        linked |= {str(x.get("care_request_id")) for x in _need(
            f"/church_help_requests?business_id=eq.{_q(biz_id)}&care_request_id=in.({','.join(ids)})"
            "&select=care_request_id&limit=200")}
    return [{**from_ask(r), "id": f"care-{r['id']}", "virtual": True} for r in rows if str(r["id"]) not in linked]


def _rows(biz_id: str) -> List[Dict[str, Any]]:
    """Open requests, and the year's closed ones, newest first."""
    since = _q(_iso(_now() - timedelta(days=OPEN_DAYS)))
    open_ = _need(f"/church_help_requests?business_id=eq.{_q(biz_id)}&status=in.(new,approved)"
                  f"&select={REQ_FIELDS}&order=created_at.desc&limit=500")
    done = _need(f"/church_help_requests?business_id=eq.{_q(biz_id)}&status=in.(helped,declined)"
                 f"&created_at=gte.{since}&select={REQ_FIELDS}&order=created_at.desc&limit=500")
    return open_ + done


def _given_for(biz_id: str, request_ids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for ids in _chunks(request_ids):
        for g in _need(f"/church_help_given?business_id=eq.{_q(biz_id)}&request_id=in.({','.join(ids)})"
                       f"&select={GIVEN_FIELDS}&order=given_on.asc&limit=2000"):
            out.setdefault(str(g["request_id"]), []).append(g)
    return out


def _names(biz_id: str, rows: List[Dict[str, Any]]) -> Dict[str, str]:
    people: Dict[str, str] = {}
    for ids in _chunks(r.get("contact_id") for r in rows):
        for c in _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(ids)})&select=id,name&limit=200"):
            people[str(c["id"])] = _plain(c.get("name"))
    return people


def _seat_names(biz: Dict[str, Any], uids: Iterable[Any]) -> Dict[str, str]:
    want = {str(u) for u in uids if u}
    if not want:
        return {}
    owner = str(biz.get("owner_id") or "")
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(biz['id'])}&status=eq.active&select=user_id,invited_email&limit=500")
    by = {str(s["user_id"]): str(s.get("invited_email") or "") for s in seats or [] if isinstance(s, dict)}
    return {u: ("The owner" if u == owner else by.get(u) or "Someone who left") for u in want}


def ref_of(row: Dict[str, Any]) -> str:
    return f"care-{row['care_request_id']}" if row.get("virtual") else str(row["id"])


def shown(me: Dict[str, Any], rows: List[Dict[str, Any]], given: Dict[str, List[Dict[str, Any]]],
          fund: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Requests as this login sees them. Care: who and the story (a private
    one's name only to the owner and admins). Money: needs, amounts and
    dates, never a name or a story. A youth's ask: the owner and admins."""
    biz = me["biz"]
    rows = [r for r in rows if me["boss"] or not r.get("pastors_only")]
    care = me["view"] == "care"
    people = _names(str(biz["id"]), rows) if care else {}
    by = _seat_names(biz, [r.get("decided_by") for r in rows])
    out = []
    for r in rows:
        mine = [] if r.get("virtual") else given.get(str(r["id"]), [])
        given_cents = sum(int(g.get("amount_cents") or 0) for g in mine)
        hidden = not care or (bool(r.get("anonymous")) and not me["boss"])
        who = None if hidden else (people.get(str(r.get("contact_id") or "")) or r.get("name") or None)
        asked = r.get("amount_cents")
        status = r.get("status")
        if mine and status in ("new", "approved") and given_cents >= int(r.get("approved_cents") or 0):
            status = "helped"   # a record whose request didn't catch up
        out.append({
            "id": ref_of(r), "need": r.get("need"), "status": status, "source": r.get("source"),
            "amount_cents": asked, "approved_cents": r.get("approved_cents"), "given_cents": given_cents,
            "over_limit": asked is not None and int(asked) > fund["gift_limit_cents"],
            "who": who, "contact_id": None if hidden else r.get("contact_id"), "private": hidden,
            "anonymous": bool(r.get("anonymous")), "pastors_only": bool(r.get("pastors_only")),
            "wants_call": bool(r.get("wants_call")), "notes": r.get("notes") if care else None,
            "from_app": bool(r.get("care_request_id")),
            "created_at": r.get("created_at"), "decided_at": r.get("decided_at"),
            "decided_by": by.get(str(r.get("decided_by") or "")) if r.get("decided_by") else None,
            "given": [{"id": g["id"], "how": g.get("how"), "amount_cents": int(g.get("amount_cents") or 0),
                       "given_on": g.get("given_on"), "payee": g.get("payee"),
                       "note": g.get("note") if care else None, "in_books": bool(g.get("expense_id"))}
                      for g in mine],
        })
    return out


def totals(me: Dict[str, Any], fund: Dict[str, Any], rows: List[Dict[str, Any]],
           given: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """The fund this month, and the families helped this year. Money is
    money: every request counts here, whoever may read its story."""
    biz = str(me["biz"]["id"])
    today = _today(me)
    month, year = today.replace(day=1).isoformat(), today.replace(month=1, day=1).isoformat()
    this_year = _need(f"/church_help_given?business_id=eq.{_q(biz)}&given_on=gte.{year}"
                      "&select=request_id,amount_cents,given_on&limit=10000")
    given_month = sum(int(g.get("amount_cents") or 0) for g in this_year if str(g.get("given_on") or "") >= month)
    given_year = sum(int(g.get("amount_cents") or 0) for g in this_year)
    promised = 0
    for r in rows:
        if r.get("status") == "approved" and not r.get("virtual"):
            done = sum(int(g.get("amount_cents") or 0) for g in given.get(str(r["id"]), []))
            promised += max(0, int(r.get("approved_cents") or 0) - done)
    # A family is one of the church's people; help for someone not on the
    # list counts once per request.
    contact = {str(r["id"]): r.get("contact_id") for r in rows if not r.get("virtual")}
    missing = {str(g["request_id"]) for g in this_year} - set(contact)
    for ids in _chunks(missing):
        for r in _need(f"/church_help_requests?business_id=eq.{_q(biz)}&id=in.({','.join(ids)})"
                       "&select=id,contact_id&limit=200"):
            contact[str(r["id"])] = r.get("contact_id")
    families = {f"c:{contact[k]}" if contact.get(k) else f"r:{k}" for k in {str(g["request_id"]) for g in this_year}}
    visible = [r for r in rows if me["boss"] or not r.get("pastors_only")]
    budget = fund["monthly_budget_cents"]
    return {
        "month": month[:7], "budget_cents": budget, "given_month_cents": given_month, "promised_cents": promised,
        "left_cents": budget - given_month - promised if budget else None,
        "given_year_cents": given_year, "families_year": len(families),
        "waiting": sum(1 for r in visible if r.get("status") == "new"),
    }


def page(me: Dict[str, Any]) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    fund = settings(biz)
    rows = _asks(biz) + _rows(biz)
    given = _given_for(biz, [r["id"] for r in rows if not r.get("virtual")])
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {
        "fund": {**fund, "funds": _funds(me["biz"]), **totals(me, fund, rows, given)},
        "keeper": keeper_state(me),
        "requests": shown(me, rows, given, fund),
        "me": _can(me),
    }


def _can(me: Dict[str, Any]) -> Dict[str, Any]:
    return {"view": me["view"], "approve": me["writer"], "settings": me["boss"]}


# ─── Requests: writing ────────────────────────────────────────────────

def _contact(biz_id: str, v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    cid = _uuid(v, "person")
    if not _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&select=id&limit=1"):
        raise HTTPException(400, "That person isn't one of this church's people.")
    return cid


def request_fields(me: Dict[str, Any], body: Dict[str, Any], *, partial: bool,
                   was: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    out: Dict[str, Any] = {}
    if not partial or "need" in body:
        need = body.get("need")
        if need not in NEEDS:
            raise HTTPException(400, "Pick what they need: food, a bill, a ride or something else.")
        out["need"] = need
    if "amount" in body:
        out["amount_cents"] = cents(body.get("amount"))
    if "notes" in body:
        out["notes"] = _text(body.get("notes"), NOTES_MAX)
    if "contact_id" in body:
        out["contact_id"] = _contact(biz, body.get("contact_id"))
    if "name" in body:
        out["name"] = _plain(body.get("name"))[:NAME_MAX] or None
    for k in ("anonymous", "wants_call"):
        if k in body:
            out[k] = body.get(k) is True
    if not partial or "source" in body:
        src = body.get("source") or "phone"
        if (was or {}).get("source") == "app":
            if src != "app":
                raise HTTPException(400, "This one came from the member app.")
        elif src not in SOURCES or src == "app":
            raise HTTPException(400, "Say how it came in: a phone call, a walk-in, or another way.")
        out["source"] = src
    return out


def _adopt(me: Dict[str, Any], care_id: str) -> Dict[str, Any]:
    """An ask from the app becomes a request of its own, once: two people
    acting at the same moment make one row (care_request_id is unique)."""
    biz = str(me["biz"]["id"])
    have = _need(f"/church_help_requests?business_id=eq.{_q(biz)}&care_request_id=eq.{_q(care_id)}"
                 f"&select={REQ_FIELDS}&limit=1")
    if have:
        return have[0]
    care = _need(f"/ministry_care_requests?id=eq.{_q(care_id)}&business_id=eq.{_q(biz)}&select={CARE_FIELDS}&limit=1")
    if not care or not _is_help(care[0]):
        raise HTTPException(404, "That request isn't here.")
    asked = from_ask(care[0])
    # Nothing is written for someone who can't see it (a youth's ask), or
    # for an ask Prayer & care already closed.
    if asked["pastors_only"] and not me["boss"]:
        raise HTTPException(404, "That request isn't here.")
    if care[0].get("status") == "closed":
        raise HTTPException(409, "This one was closed in Prayer & care.")
    now = _iso(_now())
    row = {**asked, "business_id": biz, "updated_at": now}
    row["created_at"] = row.get("created_at") or now
    saved = sb_clients.sb_post_as_service("/church_help_requests?on_conflict=care_request_id", row,
                                          prefer="resolution=ignore-duplicates,return=representation")
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Try again.")
    have = _need(f"/church_help_requests?business_id=eq.{_q(biz)}&care_request_id=eq.{_q(care_id)}"
                 f"&select={REQ_FIELDS}&limit=1")
    if not have:
        raise HTTPException(503, "That didn't save. Try again.")
    return have[0]


def resolve(me: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """The request a ref names, in this church: its own id, or an app ask
    ("care-<id>"), which becomes a row the first time anyone acts on it. A
    youth's ask reads as missing to anyone but the owner and admins."""
    biz = str(me["biz"]["id"])
    ref = str(ref or "")
    if ref.startswith("care-"):
        row = _adopt(me, _uuid(ref[5:], "request"))
    else:
        rows = _need(f"/church_help_requests?id=eq.{_q(_uuid(ref, 'request'))}&business_id=eq.{_q(biz)}"
                     f"&select={REQ_FIELDS}&limit=1")
        if not rows:
            raise HTTPException(404, "That request isn't here.")
        row = rows[0]
    if row.get("pastors_only") and not me["boss"]:
        raise HTTPException(404, "That request isn't here.")
    return row


def _one(me: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    fund = settings(biz)
    return shown(me, [row], _given_for(biz, [row["id"]]), fund)[0]


def _move_care(row: Dict[str, Any], status: str) -> None:
    """The ask's Prayer & care row follows: reviewed once approved, closed
    once helped or declined. Best effort: the help request is the record."""
    if not row.get("care_request_id"):
        return
    care = "closed" if status in ("helped", "declined") else "reviewed"
    frm = "(new,reviewed)" if care == "closed" else "(new)"
    now = _iso(_now())
    try:
        sb_clients.sb_patch_as_service(
            f"/ministry_care_requests?id=eq.{_q(row['care_request_id'])}&business_id=eq.{_q(row.get('business_id') or '')}"
            f"&status=in.{frm}", {"status": care, "status_changed_at": now, "updated_at": now})
    except Exception:
        logger.warning("church help: the Prayer & care row didn't move", exc_info=True)


def _patch(me: Dict[str, Any], row: Dict[str, Any], fields: Dict[str, Any], *, was: str) -> Dict[str, Any]:
    """Change a request only from the status it was read in: two people
    pressing at once settle once."""
    biz = str(me["biz"]["id"])
    fields["updated_at"] = _iso(_now())
    got = sb_clients.sb_patch_as_service(
        f"/church_help_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&status=eq.{_q(was)}", fields)
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone changed this request just now. Open it again.")
    return got[0]


def add(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    _writer(me)
    biz = str(me["biz"]["id"])
    fields = request_fields(me, body, partial=False)
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_help_requests", {
        "notes": "", **fields, "business_id": biz, "status": "new", "created_by": me["uid"],
        "created_at": now, "updated_at": now})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That request didn't save. Try again.")
    return {"request": _one(me, saved[0])}


def edit(me: Dict[str, Any], ref: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _writer(me)
    row = resolve(me, ref)
    fields = request_fields(me, body, partial=True, was=row)
    if row.get("anonymous") and not me["boss"] and (
            fields.get("anonymous") is False or "contact_id" in fields or "name" in fields):
        raise HTTPException(403, "Only the owner or an admin changes who asked on a private request.")
    if not fields:
        return {"request": _one(me, row)}
    return {"request": _one(me, _patch(me, row, fields, was=row["status"]))}


def _given_total(biz: str, request_id: str) -> int:
    return sum(int(g.get("amount_cents") or 0) for g in _given_for(biz, [request_id]).get(str(request_id), []))


def decide(me: Dict[str, Any], ref: str, status: Any, amount: Any) -> Dict[str, Any]:
    """Approve (up to the limit, or above it with a keeper's yes) or decline.
    Approving again changes the amount; never below what was given."""
    _writer(me)
    if status not in ("approved", "declined"):
        raise HTTPException(400, "A request is approved or declined.")
    biz = str(me["biz"]["id"])
    row = resolve(me, ref)
    given = _given_total(biz, row["id"])
    if status == "declined":
        if row["status"] not in ("new", "approved"):
            raise HTTPException(409, "This request was settled already.")
        if given:
            raise HTTPException(409, "Help was already given on this one. Take that record back first.")
        saved = _patch(me, row, {"status": "declined", "decided_by": me["uid"], "decided_at": _iso(_now())},
                       was=row["status"])
        _move_care({**row, "business_id": biz}, "declined")
        return {"request": _one(me, saved)}
    if row["status"] == "declined":
        raise HTTPException(409, "This request was declined. Add it again if things changed.")
    total = cents(amount) if amount not in (None, "") else row.get("amount_cents")
    if total is None:
        total = 0
    if total < given:
        raise HTTPException(400, f"{usd(given)} was already given. Approve at least that.")
    fund = settings(biz)
    may_approve(me, total, fund)
    fields = {"approved_cents": total, "decided_by": me["uid"], "decided_at": _iso(_now()),
              "status": "helped" if given and given >= total else "approved"}
    saved = _patch(me, row, fields, was=row["status"])
    _move_care({**row, "business_id": biz}, saved["status"])
    return {"request": _one(me, saved)}


def _day(v: Any, me: Dict[str, Any]) -> date:
    if v in (None, ""):
        return _today(me)
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, "Pick the day it was given.")
    if d > _today(me) + timedelta(days=1):
        raise HTTPException(400, "Record help once it's given: that day hasn't come yet.")
    return d


def _closed_books(biz: str, day: date) -> None:
    import period_lock
    period = period_lock.locked_period(biz, day.isoformat())
    if period:
        raise HTTPException(409, {
            "code": "books_closed",
            "message": f"{day:%b} {day.day}, {day.year} is in books that are closed "
                       f"({period.get('period_start')} to {period.get('period_end')}). Pick another day, "
                       "or reopen that period in Bookkeeping."})


def _expense(me: Dict[str, Any], fund: Dict[str, Any], row: Dict[str, Any], how: str, amount: int,
             day: date, payee: Optional[str]) -> str:
    """The money given, in the books the way every expense goes: a plain
    business_expenses row, which the GL triggers post. No name, no story."""
    saved = sb_clients.sb_post_as_service("/business_expenses", {
        "business_id": str(me["biz"]["id"]), "amount": round(amount / 100, 2), "category": "operating",
        "subcategory": fund["fund"][:FUND_MAX],
        "description": f"Help given from the {fund['fund']}: {NEED_WORD[row['need']].lower()} ({HOW_WORD[how]})",
        "date": day.isoformat(), "vendor": payee or None,
        "payment_method": how if how in ("cash", "check") else None,
    })
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        raise HTTPException(503, "That didn't reach the books, so nothing was saved. Try again.")
    return str(saved[0]["id"])


def record(me: Dict[str, Any], ref: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """How we helped: one record with an amount and a day. Money given goes
    into the books. Giving more than was approved approves it, under the
    same limit and keeper."""
    _writer(me)
    biz = str(me["biz"]["id"])
    how = body.get("how")
    if how not in HOWS:
        raise HTTPException(400, "Say how you helped: cash, a check, a gift card, groceries, a ride or other.")
    amount = cents(body.get("amount")) or 0
    if how in MONEY_HOWS and amount <= 0:
        raise HTTPException(400, f"Enter how much {HOW_WORD[how]} was for.")
    day = _day(body.get("given_on"), me)
    payee = _plain(body.get("payee"))[:PAYEE_MAX] or None
    note = _text(body.get("note"), NOTE_MAX)
    row = resolve(me, ref)
    if row["status"] == "declined":
        raise HTTPException(409, "This request was declined. Approve it before recording help.")
    fund = settings(biz)
    given = _given_total(biz, row["id"])
    total = given + amount
    approved = int(row.get("approved_cents") or 0)
    if total > approved:
        may_approve(me, total, fund)
    expense_id = None
    if amount:
        _closed_books(biz, day)
        expense_id = _expense(me, fund, row, how, amount, day, payee)
    saved = sb_clients.sb_post_as_service("/church_help_given", {
        "id": str(uuid.uuid4()), "business_id": biz, "request_id": row["id"], "how": how, "amount_cents": amount,
        "given_on": day.isoformat(), "payee": payee, "note": note, "expense_id": expense_id,
        "recorded_by": me["uid"], "created_at": _iso(_now())})
    if not isinstance(saved, list) or not saved:
        if expense_id:
            sb_clients.sb_delete_as_service(f"/business_expenses?id=eq.{_q(expense_id)}&business_id=eq.{_q(biz)}")
        raise HTTPException(503, "That didn't save. Try again.")
    # Helped once what was given reaches what was approved; until then the
    # rest is still promised (and counted against the month's fund).
    approved_now = max(approved, total)
    fields: Dict[str, Any] = {"status": "helped" if total >= approved_now else "approved"}
    if total > approved:
        fields["approved_cents"] = total
    if row["status"] == "new" or total > approved:
        fields.update(decided_by=me["uid"], decided_at=_iso(_now()))
    # Help given makes it helped whatever else changed in the moment: by id.
    fields["updated_at"] = _iso(_now())
    got = sb_clients.sb_patch_as_service(
        f"/church_help_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}", fields)
    # The record stands either way (it's in the books); a request that
    # didn't catch up reads as helped from its records (shown()).
    moved = got[0] if isinstance(got, list) and got else {**row, **fields}
    _move_care({**row, "business_id": biz}, fields["status"])
    return {"request": _one(me, moved), "in_books": bool(expense_id)}


def take_back(me: Dict[str, Any], given_id: str) -> Dict[str, Any]:
    """Take a record back, with its expense: the owner and admins."""
    _boss(me, "Only the owner or an admin takes a record of help back.")
    biz = str(me["biz"]["id"])
    rows = _need(f"/church_help_given?id=eq.{_q(_uuid(given_id, 'record'))}&business_id=eq.{_q(biz)}"
                 f"&select={GIVEN_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That record isn't here.")
    g = rows[0]
    if g.get("expense_id"):
        _closed_books(biz, date.fromisoformat(str(g["given_on"])[:10]))
    # The record first: a record left saying money was given while its
    # expense is gone would be the books and the page disagreeing.
    if not sb_clients.sb_delete_as_service(f"/church_help_given?id=eq.{_q(g['id'])}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "Nothing was taken back. Try again.")
    books = True
    if g.get("expense_id") and not sb_clients.sb_delete_as_service(
            f"/business_expenses?id=eq.{_q(g['expense_id'])}&business_id=eq.{_q(biz)}"):
        books = False
    req = _need(f"/church_help_requests?id=eq.{_q(g['request_id'])}&business_id=eq.{_q(biz)}"
                f"&select={REQ_FIELDS}&limit=1")
    said = None if books else ("The record is taken back, but its expense is still in the books. "
                               "Remove it in Bookkeeping, under Expenses.")
    if not req:
        return {"request": None, "books": books, "message": said}
    row = req[0]
    left, approved = _given_total(biz, row["id"]), int(row.get("approved_cents") or 0)
    if row["status"] == "helped" and (not left or left < approved):
        row = _patch(me, row, {"status": "approved" if approved else "new"}, was="helped")
    return {"request": _one(me, row), "books": books, "message": said}


def put_settings(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """The fund's name, its monthly budget and the single-gift limit: the
    owner and admins. Raising the limit needs a keeper's yes where the
    church has keepers (else it would be the way around them)."""
    _boss(me, "Only the owner or an admin changes the fund and its limit.")
    biz = str(me["biz"]["id"])
    have = settings(biz)
    out: Dict[str, Any] = {}
    if "fund" in body:
        name = _plain(body.get("fund"))[:FUND_MAX]
        if not name:
            raise HTTPException(400, "Name the fund help comes from, like Benevolence.")
        out["fund"] = name
    if "monthly_budget" in body:
        out["monthly_budget_cents"] = cents(body.get("monthly_budget"), "monthly budget") or 0
    if "gift_limit" in body:
        limit = cents(body.get("gift_limit"), "limit", allow_none=False)
        if limit > have["gift_limit_cents"]:
            ks = keeper_state(me)
            import church_keys
            if ks["on"] and not church_keys.is_open(biz, me["user"], MONEY_AREA):
                raise HTTPException(403, {
                    "code": "needs_keeper", "limit_cents": have["gift_limit_cents"],
                    "message": "Raising the limit needs a keeper of Giving & money. Ask a keeper: their yes "
                               "opens it for an hour."})
        out["gift_limit_cents"] = limit
    if not out:
        return {"fund": have}
    saved = sb_clients.sb_post_as_service("/church_help_settings?on_conflict=business_id", {
        "business_id": biz, "fund": have["fund"], "monthly_budget_cents": have["monthly_budget_cents"],
        "gift_limit_cents": have["gift_limit_cents"], **out, "updated_by": me["uid"], "updated_at": _iso(_now())},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"fund": settings(biz)}


def ask_keeper(me: Dict[str, Any], ref: str, amount: Any) -> Dict[str, Any]:
    """Ask the keepers of Giving & money for a yes above the limit: the
    church keys' own ask (every keeper hears it, with a code to read out).
    The reason names the need and the amount, never who or the story."""
    _writer(me)
    biz = str(me["biz"]["id"])
    row = resolve(me, ref)
    fund = settings(biz)
    total = cents(amount) if amount not in (None, "") else row.get("amount_cents")
    if total is None or total <= fund["gift_limit_cents"]:
        raise HTTPException(400, f"That's within the {usd(fund['gift_limit_cents'])} limit: approve it here.")
    ks = keeper_state(me)
    if not ks["on"]:
        raise HTTPException(409, {"code": "over_limit", "limit_cents": fund["gift_limit_cents"],
                                  "message": f"Your church has no keeper for Giving & money, so "
                                             f"{usd(fund['gift_limit_cents'])} is the most anyone gives at once."})
    if ks["mine"]:
        raise HTTPException(409, "You keep Giving & money, so you can approve it here.")
    import church_keys
    got = church_keys.ask(biz, me["user"], MONEY_AREA,
                          f"Help request: {NEED_WORD[row['need']].lower()}, {usd(total)} "
                          f"(over the {usd(fund['gift_limit_cents'])} limit)")
    return {"key": got.get("key"), "told": got.get("told", 0), "request": _one(me, row)}


def key_code(me: Dict[str, Any], key_id: Any, code: Any) -> Dict[str, Any]:
    """The code a keeper read out, for this login's ask for Giving & money."""
    _writer(me)
    biz = str(me["biz"]["id"])
    kid = _uuid(key_id, "ask")
    rows = _need(f"/church_area_keys?id=eq.{_q(kid)}&business_id=eq.{_q(biz)}&select=area,user_id&limit=1")
    if not rows or rows[0].get("area") != MONEY_AREA or str(rows[0].get("user_id")) != me["uid"]:
        raise HTTPException(404, "That ask isn't here.")
    import church_keys
    return church_keys.enter_code(biz, me["user"], kid, str(code or ""))


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def help_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows Help requests: the app asks once, so
    its menu offers the page only where it opens. Quietly false for a closed
    switch, a business that isn't a church, a login outside People & care
    and Giving, or tables not made yet."""
    off = {"enabled": False, "view": None, "approve": False, "settings": False}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == "Help requests are for churches":
            return off
        raise
    if not _ready(str(me["biz"]["id"])):
        return off
    return {"enabled": True, **_can(me)}


@router.get("")
def help_page(business_id: str, user: AuthedUser = Depends(require_user)):
    return page(_access(business_id, user))


@router.put("/settings")
def help_settings(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return put_settings(me, body or {})


@router.post("/requests")
def help_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return add(me, body or {})


@router.patch("/requests/{ref}")
def help_edit(ref: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return edit(me, ref, body or {})


@router.post("/requests/{ref}/decide")
def help_decide(ref: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return decide(me, ref, body.get("status"), body.get("amount"))


@router.post("/requests/{ref}/given")
def help_given(ref: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return record(me, ref, body or {})


@router.post("/requests/{ref}/keeper")
def help_keeper(ref: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return ask_keeper(me, ref, body.get("amount"))


@router.post("/key-code")
def help_key_code(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return key_code(me, body.get("key_id"), body.get("code"))


@router.delete("/given/{given_id}")
def help_take_back(given_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return take_back(_access(business_id, user), given_id)
