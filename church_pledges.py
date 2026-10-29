"""church_pledges.py — the Giving door's office pages: recurring gifts,
pledges and campaigns.

Kevin, 2026-10-27: "lets start building this" — the gap check of a
church's staff menu (artifact 4oXF1Be46RddJxXnKAHodn, "The other doors",
Giving card) found two gaps: the office had no list of recurring gifts,
and pledges and campaigns (a building fund, a missions push) didn't exist.
Subsplash has them. Lane: Build, "Love City leaves Subsplash (M-1)".

    a CAMPAIGN ... a name, a goal, start and end dates, and one of the
                   church's funds (settings.giving.funds, the same list the
                   give page offers)
    a PLEDGE ..... one giver (a contact) to one campaign: a total, or an
                   amount per week / two weeks / month for so many periods.
                   It carries a note and who recorded it (from a pledge card)
    PROGRESS ..... real gifts only: paid gifts to the campaign's fund dated
                   inside its dates (the church's own calendar days), net of
                   refunds, for the campaign against its goal and for each
                   giver against their pledge. Gifts are the paid invoices
                   every giving surface reads (giving_records.read_gifts),
                   matched on gift_fund. Two campaigns on one fund with
                   overlapping dates both count the same gift: a fund is all
                   a gift says about where it was meant to go.

  GET    /church/giving/status?business_id=        {enabled, recurring, pledges} for this login
  GET    /church/giving/recurring?business_id=     every recurring gift (church_recurring_gifts)
  GET    /church/giving/campaigns?business_id=     each campaign: goal, given, pledged; the funds
  POST   /church/giving/campaigns                  {business_id, name, goal_cents, fund, starts_on, ends_on, note?}
  PATCH  /church/giving/campaigns/{id}             any of the same fields
  GET    /church/giving/pledges?business_id=&campaign_id=   the pledges, each with its giver's progress
  POST   /church/giving/pledges                    {business_id, campaign_id, contact_id, total_cents
                                                    | per_period_cents + period + periods, note?, request_id?}
  DELETE /church/giving/pledges/{id}?business_id=  a pledge recorded by mistake

WHO. Money is the owner's, the admins' and the accountant's
(giving_records.require_finance, the same gate as the gift ledger and the
statements), whatever a login's areas say. Who gave what (the recurring
list and the pledges) also sits behind the church's keys
(church_keys.wall, giving_money): where the church named a keeper for
Giving, everyone else needs a key. Campaign totals stay open, as the keys
leave totals open.

THE SWITCH. CHURCH_PLEDGES = off | owner | on, owner until a Thursday:
owner shows the pages to the platform owner only; off hides them. Status
answers false (never an error) when the switch is closed, the login isn't
finance, the business isn't a church, or the tables aren't there yet;
`pledges` stays false until supabase/APPLY-2026-10-27-church-pledges.sql
is applied, while `recurring` needs no table.
"""
from __future__ import annotations

import os
import urllib.parse
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix="/church/giving", tags=["church"])

NAME_MAX = 80
NOTE_MAX = 500
FUND_MAX = 40
GOAL_MAX_CENTS = 100_000_000_00    # $100 million
PLEDGE_MAX_CENTS = 10_000_000_00   # $10 million
PERIODS_MAX = 520                  # ten years of weeks
PERIODS = ("weekly", "biweekly", "monthly")
CAMPAIGNS_MAX = 200


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_PLEDGES") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


# ─── Small helpers ────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return urllib.parse.quote(str(v), safe="")


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Giving couldn't be read just now. Nothing was changed; try again.")
    return rows


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,name,type,owner_id,settings,stripe_account_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Giving couldn't be read just now. Try again.")
    return rows[0] if rows else None


def _is_church(biz: Dict[str, Any]) -> bool:
    import church_follow_up as cfu
    return cfu.is_church(biz)


def _finance(business_id: str, user: AuthedUser) -> None:
    from giving_records import require_finance
    require_finance(business_id, user)


def tables_ready() -> bool:
    """Whether the campaigns and pledges tables are there (the migration is
    applied by hand). A failed read counts as not ready: status says false
    and the pages stay off the menu, never a 500."""
    return all(isinstance(sb_clients.sb_get_as_service(f"/{t}?select=id&limit=1"), list)
               for t in ("church_campaigns", "church_pledges"))


def _guard(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The switch, then finance, then a church. Returns the business."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    bid = _uuid(business_id, "church")
    _finance(bid, user)
    biz = _business(bid)
    if not biz:
        raise HTTPException(404, "business not found")
    if not _is_church(biz):
        raise HTTPException(404, "These pages are for churches.")
    return biz


def _ready() -> None:
    if not tables_ready():
        raise HTTPException(409, "Pledges and campaigns aren't set up yet.")


def _wall(business_id: str, user: AuthedUser) -> None:
    import church_keys
    church_keys.wall(business_id, user, "giving_money")


# ─── Status ───────────────────────────────────────────────────────────

@router.get("/status")
def status(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What this login's Giving door shows: `recurring` (the list needs no
    table) and `pledges` (once the migration is in). False, never an error,
    for anyone the pages aren't for."""
    off = {"enabled": False, "recurring": False, "pledges": False}
    try:
        _guard(business_id, user)
    except HTTPException:
        return off
    pledges = tables_ready()
    return {"enabled": True, "recurring": True, "pledges": pledges}


# ─── Recurring gifts ──────────────────────────────────────────────────

@router.get("/recurring")
def recurring(business_id: str, fresh: bool = False, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(business_id, user)
    _wall(str(biz["id"]), user)
    import church_recurring_gifts as crg
    out = crg.recurring_for(biz, fresh=fresh)
    if out is None:
        raise HTTPException(503, "Recurring gifts couldn't be read from Stripe just now. Nothing has changed; try again.")
    return out


# ─── Funds and dates ──────────────────────────────────────────────────

def fund_key(fund: Any) -> str:
    """One fund however it's written: 'Building', 'building fund' and
    'Building Fund' are the same fund (gift rows carry either form)."""
    norm = " ".join(str(fund or "").lower().split())
    if norm.endswith(" fund"):
        norm = norm[: -len(" fund")]
    return norm or "general"


def _funds(biz: Dict[str, Any]) -> List[str]:
    from giving_router import configured_funds, giving_settings
    return configured_funds(giving_settings(biz.get("settings")))


def _tz(biz: Dict[str, Any]):
    from zoneinfo import ZoneInfo
    s = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    av = s.get("availability") if isinstance(s.get("availability"), dict) else {}
    name = s.get("timezone") or av.get("timezone") or "America/New_York"
    try:
        return ZoneInfo(str(name))
    except Exception:
        return ZoneInfo("America/New_York")


def _day(v: Any, what: str) -> date:
    try:
        d = date.fromisoformat(str(v or "")[:10])
    except ValueError:
        raise HTTPException(400, f"Enter the {what} as a date.")
    if d.year < 2000 or d.year > 2200:
        raise HTTPException(400, f"Enter the {what} as a date.")
    return d


def _cents(v: Any, what: str, top: int) -> int:
    try:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
            raise ValueError
        n = int(v)
    except (ValueError, OverflowError):
        raise HTTPException(400, f"Enter the {what} in whole cents.")
    if not 1 <= n <= top:
        raise HTTPException(400, f"Enter a {what} between $0.01 and ${top // 100:,}.")
    return n


def _text(v: Any, top: int) -> str:
    return " ".join(str(v or "").split())[:top]


# ─── Progress (pure) ──────────────────────────────────────────────────

def net_cents(gift: Dict[str, Any]) -> int:
    """A gift less any refund, in cents. A refunded gift was not a gift."""
    try:
        total = int(round(float(gift.get("total") or 0) * 100))
        refund = int(gift.get("refund_amount_cents") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, total - max(0, refund))


def local_day(paid_at: Any, tz) -> Optional[date]:
    try:
        dt = datetime.fromisoformat(str(paid_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def counted(campaign: Dict[str, Any], gifts: List[Dict[str, Any]], tz) -> List[Dict[str, Any]]:
    """The gifts that count toward a campaign: its fund, inside its dates
    (the church's calendar), worth something after refunds."""
    key = fund_key(campaign.get("fund"))
    start, end = date.fromisoformat(str(campaign["starts_on"])[:10]), date.fromisoformat(str(campaign["ends_on"])[:10])
    out = []
    for g in gifts:
        if fund_key(g.get("gift_fund") or "General") != key:
            continue
        day = local_day(g.get("paid_at"), tz)
        if day is None or not start <= day <= end:
            continue
        net = net_cents(g)
        if net > 0:
            out.append({**g, "net_cents": net})
    return out


def progress(campaign: Dict[str, Any], pledges: List[Dict[str, Any]], gifts: List[Dict[str, Any]], tz) -> Dict[str, Any]:
    """The campaign against its goal, and each pledge against its giver's
    gifts to the campaign. `gifts` are paid gift rows (any fund, any date:
    counted() picks)."""
    mine = counted(campaign, gifts, tz)
    by_giver: Dict[str, int] = defaultdict(int)
    for g in mine:
        if g.get("contact_id"):
            by_giver[str(g["contact_id"])] += g["net_cents"]
    rows = []
    for p in pledges:
        given = by_giver.get(str(p.get("contact_id")), 0)
        total = int(p.get("total_cents") or 0)
        rows.append({**p, "given_cents": given, "left_cents": max(0, total - given),
                     "percent": min(100, round(given * 100 / total)) if total else 0})
    pledged = sum(int(p.get("total_cents") or 0) for p in pledges)
    goal = int(campaign.get("goal_cents") or 0)
    given = sum(g["net_cents"] for g in mine)
    return {
        "given_cents": given,
        "pledged_cents": pledged,
        "pledges": len(pledges),
        # What pledgers have given toward their pledges (capped at each pledge).
        "pledged_given_cents": sum(min(r["given_cents"], int(r.get("total_cents") or 0)) for r in rows),
        "givers": len({str(g.get("contact_id")) for g in mine if g.get("contact_id")}),
        "goal_percent": min(100, round(given * 100 / goal)) if goal else 0,
        "rows": rows,
    }


def windows(campaigns: List[Dict[str, Any]], today: date) -> List[tuple]:
    """The stretches of days whose gifts the campaigns need: each one's
    dates up to today (a campaign that hasn't started has no gifts yet),
    with a day's slack each side for the time zone, overlapping stretches
    merged, so the gaps between old campaigns are never read."""
    spans = sorted(
        (date.fromisoformat(str(c["starts_on"])[:10]) - timedelta(days=1),
         min(date.fromisoformat(str(c["ends_on"])[:10]), today) + timedelta(days=2))
        for c in campaigns if date.fromisoformat(str(c["starts_on"])[:10]) <= today)
    out: List[list] = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _gifts_for(biz: Dict[str, Any], campaigns: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """Paid gifts in the campaigns' stretches (counted() trims each
    campaign to its own fund and the church's own days)."""
    from giving_records import read_gifts
    gifts: List[Dict[str, Any]] = []
    for a, b in windows(campaigns, today):
        gifts.extend(read_gifts(str(biz["id"]), f"{a.isoformat()}T00:00:00Z", f"{b.isoformat()}T00:00:00Z"))
    return gifts


# ─── Campaigns ────────────────────────────────────────────────────────

CAMPAIGN_FIELDS = "id,name,goal_cents,fund,starts_on,ends_on,note,created_at,updated_at"
PLEDGE_FIELDS = ("id,campaign_id,contact_id,total_cents,per_period_cents,period,periods,note,"
                 "recorded_by,recorded_at,contacts(name,email)")


def _campaigns(business_id: str) -> List[Dict[str, Any]]:
    return _need(f"/church_campaigns?business_id=eq.{_q(business_id)}&select={CAMPAIGN_FIELDS}"
                 f"&order=starts_on.desc&limit={CAMPAIGNS_MAX}")


def _campaign(business_id: str, campaign_id: Any) -> Dict[str, Any]:
    cid = _uuid(campaign_id, "campaign")
    rows = _need(f"/church_campaigns?id=eq.{_q(cid)}&business_id=eq.{_q(business_id)}"
                 f"&select={CAMPAIGN_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That campaign isn't one of this church's.")
    return rows[0]


def _pledges(business_id: str, campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
    path = f"/church_pledges?business_id=eq.{_q(business_id)}&select={PLEDGE_FIELDS}&order=recorded_at.desc&limit=5000"
    if campaign_id:
        path += f"&campaign_id=eq.{_q(campaign_id)}"
    return _need(path)


def _phase(c: Dict[str, Any], today: date) -> str:
    if today < date.fromisoformat(str(c["starts_on"])[:10]):
        return "upcoming"
    if today > date.fromisoformat(str(c["ends_on"])[:10]):
        return "ended"
    return "running"


def _campaign_fields(body: Dict[str, Any], biz: Dict[str, Any], *, partial: bool,
                     current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not partial or "name" in body:
        name = _text(body.get("name"), NAME_MAX)
        if not name:
            raise HTTPException(400, "Give the campaign a name.")
        out["name"] = name
    if not partial or "goal_cents" in body:
        out["goal_cents"] = _cents(body.get("goal_cents"), "goal", GOAL_MAX_CENTS)
    if not partial or "fund" in body:
        want = fund_key(body.get("fund"))
        match = next((f for f in _funds(biz) if fund_key(f) == want), None)
        if not match or not str(body.get("fund") or "").strip():
            raise HTTPException(400, "Choose one of your funds. Add a fund on Giving page & funds first.")
        out["fund"] = match[:FUND_MAX]
    if not partial or "starts_on" in body:
        out["starts_on"] = _day(body.get("starts_on"), "start date").isoformat()
    if not partial or "ends_on" in body:
        out["ends_on"] = _day(body.get("ends_on"), "end date").isoformat()
    if "note" in body:
        out["note"] = _text(body.get("note"), NOTE_MAX)
    starts = out.get("starts_on") or (current or {}).get("starts_on")
    ends = out.get("ends_on") or (current or {}).get("ends_on")
    if starts and ends and str(ends)[:10] < str(starts)[:10]:
        raise HTTPException(400, "The end date comes before the start date.")
    return out


@router.get("/campaigns")
def list_campaigns(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(business_id, user)
    _ready()
    bid = str(biz["id"])
    campaigns = _campaigns(bid)
    pledges = _pledges(bid)
    tz = _tz(biz)
    today = _now().astimezone(tz).date()
    gifts = _gifts_for(biz, campaigns, today)
    by_campaign: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in pledges:
        by_campaign[str(p.get("campaign_id"))].append(p)
    out = []
    for c in campaigns:
        prog = progress(c, by_campaign.get(str(c["id"]), []), gifts, tz)
        prog.pop("rows")  # totals only: who gave what is the pledges route's, behind the keys
        out.append({**c, **prog, "phase": _phase(c, today)})
    return {"campaigns": out, "funds": _funds(biz), "today": today.isoformat()}


@router.post("/campaigns")
def create_campaign(body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(body.get("business_id"), user)
    _ready()
    fields = _campaign_fields(body, biz, partial=False)
    saved = sb_clients.sb_post_as_service("/church_campaigns", {
        **fields, "business_id": str(biz["id"]), "created_by": str(user.id)})
    if not (isinstance(saved, list) and saved):
        raise HTTPException(503, "The campaign didn't save. Nothing was changed; try again.")
    return {"ok": True, "campaign": saved[0]}


@router.patch("/campaigns/{campaign_id}")
def edit_campaign(campaign_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(body.get("business_id"), user)
    _ready()
    bid = str(biz["id"])
    current = _campaign(bid, campaign_id)
    fields = _campaign_fields(body, biz, partial=True, current=current)
    if not fields:
        raise HTTPException(400, "Nothing to change.")
    fields["updated_at"] = _now().isoformat()
    saved = sb_clients.sb_patch_as_service(
        f"/church_campaigns?id=eq.{_q(current['id'])}&business_id=eq.{_q(bid)}", fields)
    if not (isinstance(saved, list) and saved):
        raise HTTPException(503, "The campaign didn't save. Nothing was changed; try again.")
    return {"ok": True, "campaign": saved[0]}


# ─── Pledges ──────────────────────────────────────────────────────────

def _pledge_amount(body: Dict[str, Any]) -> Dict[str, Any]:
    """A total, or an amount per period for so many periods (whose total
    the server works out)."""
    per = body.get("per_period_cents")
    if per is None or per == "":
        total = _cents(body.get("total_cents"), "pledge", PLEDGE_MAX_CENTS)
        return {"total_cents": total, "per_period_cents": None, "period": None, "periods": None}
    per_cents = _cents(per, "amount each time", PLEDGE_MAX_CENTS)
    period = body.get("period")
    if period not in PERIODS:
        raise HTTPException(400, "Choose weekly, every two weeks or monthly.")
    n = body.get("periods")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= PERIODS_MAX:
        raise HTTPException(400, f"Enter how many times, from 1 to {PERIODS_MAX}.")
    total = per_cents * n
    if total > PLEDGE_MAX_CENTS:
        raise HTTPException(400, f"A pledge can be up to ${PLEDGE_MAX_CENTS // 100:,}.")
    return {"total_cents": total, "per_period_cents": per_cents, "period": period, "periods": n}


def _shown(p: Dict[str, Any]) -> Dict[str, Any]:
    c = p.get("contacts") if isinstance(p.get("contacts"), dict) else {}
    out = {k: p.get(k) for k in ("id", "campaign_id", "contact_id", "total_cents", "per_period_cents",
                                 "period", "periods", "note", "recorded_at", "given_cents", "left_cents", "percent")}
    out["giver"] = c.get("name") or c.get("email") or "A giver"
    return out


@router.get("/pledges")
def list_pledges(business_id: str, campaign_id: Optional[str] = None,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(business_id, user)
    _ready()
    bid = str(biz["id"])
    _wall(bid, user)
    if campaign_id:
        campaigns = [_campaign(bid, campaign_id)]
    else:
        campaigns = _campaigns(bid)
    pledges = _pledges(bid, campaigns[0]["id"] if campaign_id else None)
    tz = _tz(biz)
    gifts = _gifts_for(biz, campaigns, _now().astimezone(tz).date())
    by_campaign: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in pledges:
        by_campaign[str(p.get("campaign_id"))].append(p)
    rows: List[Dict[str, Any]] = []
    for c in campaigns:
        rows.extend(progress(c, by_campaign.get(str(c["id"]), []), gifts, tz)["rows"])
    rows.sort(key=lambda r: str(r.get("recorded_at") or ""), reverse=True)
    return {"pledges": [_shown(r) for r in rows]}


@router.post("/pledges")
def record_pledge(body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(body.get("business_id"), user)
    _ready()
    bid = str(biz["id"])
    campaign = _campaign(bid, body.get("campaign_id"))
    contact_id = _uuid(body.get("contact_id"), "giver")
    contact = _need(f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(bid)}&select=id,name&limit=1")
    if not contact:
        raise HTTPException(400, "Choose a giver from this church's people.")
    amount = _pledge_amount(body)
    request_id = None
    if body.get("request_id"):
        request_id = _uuid(body.get("request_id"), "request")
        again = _need(f"/church_pledges?business_id=eq.{_q(bid)}&request_id=eq.{_q(request_id)}&select=id&limit=1")
        if again:
            return {"ok": True, "id": again[0]["id"], "already": True}
    have = _need(f"/church_pledges?campaign_id=eq.{_q(campaign['id'])}&contact_id=eq.{_q(contact_id)}"
                 f"&business_id=eq.{_q(bid)}&select=id&limit=1")
    if have:
        raise HTTPException(409, f"{contact[0].get('name') or 'This giver'} already has a pledge to "
                                 f"{campaign['name']}. Remove it first to record a new one.")
    row = {"business_id": bid, "campaign_id": campaign["id"], "contact_id": contact_id, **amount,
           "note": _text(body.get("note"), NOTE_MAX), "recorded_by": str(user.id)}
    if request_id:
        row["request_id"] = request_id
    saved = sb_clients.sb_post_as_service("/church_pledges", row)
    if not (isinstance(saved, list) and saved):
        raise HTTPException(503, "The pledge didn't save. Try again; it won't be recorded twice.")
    return {"ok": True, "id": saved[0].get("id")}


@router.delete("/pledges/{pledge_id}")
def remove_pledge(pledge_id: str, business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _guard(business_id, user)
    _ready()
    bid = str(biz["id"])
    pid = _uuid(pledge_id, "pledge")
    if not _need(f"/church_pledges?id=eq.{_q(pid)}&business_id=eq.{_q(bid)}&select=id&limit=1"):
        raise HTTPException(404, "That pledge isn't one of this church's.")
    if not sb_clients.sb_delete_as_service(f"/church_pledges?id=eq.{_q(pid)}&business_id=eq.{_q(bid)}"):
        raise HTTPException(503, "The pledge wasn't removed. Try again.")
    return {"ok": True}
