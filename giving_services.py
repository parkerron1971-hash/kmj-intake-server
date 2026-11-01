"""
giving_services.py: giving recorded by service (Kevin, 2026-11-01).

    "if tithes and offering coming in sunday and it's time to record that the
    system ask or allow selection for sunday or where ever type of service it
    is and they can record the giving for that sunday and put in multiple
    people that sunday or service ... the system should be able to recognize
    Sunday and already prepare for that service for giving. and when someone
    gives online the system see that and automatic connect the online giving
    to that service as a prefill"

The schedule (giving_services)
  The church's services, each one of:
    - weekly: a weekday and a time, e.g. every Sunday at 11:00;
    - once: a date and a time, e.g. a revival night or Christmas Eve.
  Times are on the church's clock (church_checkin.church_zone_name).
  `collects_online`: the online gifts given since the last such service
  count toward this one. Love City: Sunday, so Sunday shows the whole week.

The counts (giving_counts)
  One row per service per day: that service's giving, recorded together.
  A count is made when its day comes (on the church's clock), so the screen
  is ready on Sunday morning. Days before the service was added never get
  one. A service's next date shows as "coming up" before then.

  Gifts point at their count (invoices.giving_count_id):
    - A gift recorded into a count takes the service's date: no date on
      each row.
    - Online gifts (card through the give page, Subsplash payouts) are
      placed in the open count of a service that collects online. They
      land in the window from the previous such service plus GRACE to this
      one plus GRACE, so a gift during the service counts toward it.
    - A gift in a closed count's window stays out of every count, and the
      treasurer places it.
    - The treasurer can move any gift between open counts. Moving never
      changes a gift's date or amount.

Who
  The same people as the giving records: owner, admin, or the outside
  accountant (giving_records.require_finance), behind the giving keeper
  (church_keys "giving_money").

Switched by GIVING_SERVICES (giving_ways.switched_on): owner until a
Thursday flip.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

import church_keys
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("giving_services")
router = APIRouter(tags=["giving"])

GRACE = timedelta(hours=3)          # a gift during the service counts toward it
LOOK_BACK_DAYS = 63                 # counts listed: nine weeks back
COMING_DAYS = 14                    # services shown as coming up
MAX_SERVICES = 12
MAX_ROWS = 100                      # gifts recorded in one press
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ONLINE_METHODS = ("stripe", "subsplash bank payout")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

COUNT_FIELDS = ("id,business_id,service_id,name,service_date,starts_at,collects_online,status,"
                "counted_cash_cents,counted_checks_cents,counters,closed_at,closed_by,note,updated_at")
GIFT_FIELDS = ("id,invoice_number,total,paid_at,gift_fund,payment_method,contact_id,refund_amount_cents,"
               "notes,updated_at,giving_count_id,contacts(name)")


def _q(v: Any) -> str:
    return urllib.parse.quote(str(v), safe="")


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise HTTPException(503, "Giving couldn't be read just now. Please try again.")
    return rows


# ─── The gate ─────────────────────────────────────────────────────────

def _business(business_id: str) -> Dict[str, Any]:
    if not UUID_RE.match(str(business_id or "")):
        raise HTTPException(404, "Not found")
    rows = _need(f"/businesses?id=eq.{_q(business_id)}&select=id,type,settings,owner_id&limit=1")
    if not rows:
        raise HTTPException(404, "Not found")
    return rows[0]


def _gate(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Finance people, behind the giving keeper, where it's switched on."""
    import giving_ways
    from giving_records import require_finance
    biz = _business(business_id)
    if not giving_ways.switched_on(business_id):
        raise HTTPException(404, "Giving by service isn't switched on here yet")
    require_finance(business_id, user)
    church_keys.wall(business_id, user, "giving_money")
    return biz


def zone_of(biz: Dict[str, Any]) -> ZoneInfo:
    from church_checkin import church_zone_name
    return ZoneInfo(church_zone_name(biz))


# ─── The schedule (pure) ──────────────────────────────────────────────

def _hm(raw: Any) -> time:
    m = _TIME.match(str(raw or "")[:5])
    if not m:
        raise ValueError("bad time")
    return time(int(m.group(1)), int(m.group(2)))


def occurrences(services: List[Dict[str, Any]], tz: ZoneInfo, start: date, end: date) -> List[Dict[str, Any]]:
    """Every service day from start to end (inclusive), oldest first:
    {service_id, name, date, starts_at (UTC), collects_online}. Archived
    services and rows that don't read are skipped."""
    out: List[Dict[str, Any]] = []
    for s in services:
        if s.get("archived_at"):
            continue
        try:
            at = _hm(s.get("start_time"))
        except ValueError:
            continue
        days: List[date] = []
        if s.get("kind") == "weekly":
            wd = s.get("weekday")
            if not isinstance(wd, int) or not 0 <= wd <= 6:
                continue
            d = start + timedelta(days=(wd - start.weekday()) % 7)
            while d <= end:
                days.append(d)
                d += timedelta(days=7)
        elif s.get("kind") == "once":
            try:
                d = date.fromisoformat(str(s.get("on_date"))[:10])
            except ValueError:
                continue
            if start <= d <= end:
                days.append(d)
        for d in days:
            local = datetime.combine(d, at, tzinfo=tz)
            out.append({"service_id": s.get("id"), "name": s.get("name") or "Service", "date": d,
                        "starts_at": local.astimezone(timezone.utc),
                        "collects_online": bool(s.get("collects_online"))})
    out.sort(key=lambda o: (o["starts_at"], str(o["service_id"])))
    return out


def online_window(starts_at: datetime, collecting_starts: List[datetime]) -> Tuple[datetime, datetime]:
    """The online gifts that count toward a collecting service starting at
    `starts_at`: after the previous collecting service (plus GRACE) up to
    this one (plus GRACE). With none before it, the week before."""
    hi = starts_at + GRACE
    before = [s for s in collecting_starts if s < starts_at]
    lo = (max(before) + GRACE) if before else hi - timedelta(days=7)
    return lo, hi


def is_online(gift: Dict[str, Any]) -> bool:
    return (not str(gift.get("invoice_number") or "").startswith("GIVE-manual-")
            and str(gift.get("payment_method") or "").lower() in ONLINE_METHODS)


def kind_of(gift: Dict[str, Any]) -> str:
    """cash | check | online | other: the count's subtotals."""
    if is_online(gift):
        return "online"
    pm = str(gift.get("payment_method") or "").lower()
    return pm if pm in ("cash", "check") else "other"


def net_cents(gift: Dict[str, Any]) -> int:
    return max(0, round(float(gift.get("total") or 0) * 100) - int(gift.get("refund_amount_cents") or 0))


def totals(gifts: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"cash": 0, "check": 0, "online": 0, "other": 0, "all": 0, "gifts": 0}
    for g in gifts:
        c = net_cents(g)
        out[kind_of(g)] += c
        out["all"] += c
        out["gifts"] += 1
    return out


# ─── Reads ────────────────────────────────────────────────────────────

def _services(business_id: str) -> List[Dict[str, Any]]:
    return _need(f"/giving_services?business_id=eq.{_q(business_id)}&archived_at=is.null"
                 f"&select=id,name,kind,weekday,on_date,start_time,collects_online,created_at,updated_at,archived_at"
                 f"&order=created_at.asc&limit={MAX_SERVICES * 2}")


def _first_day(service: Dict[str, Any], tz: ZoneInfo) -> date:
    """A weekly service counts from the day it was added or last changed,
    never before: a service moved from Wednesday to Sunday makes no Sunday
    counts for the weeks before the change. A one-time service counts from
    its own date (it may be a past night being recorded now)."""
    if service.get("kind") == "once":
        return date.min
    days = []
    for key in ("created_at", "updated_at"):
        try:
            days.append(datetime.fromisoformat(str(service.get(key)).replace("Z", "+00:00")).astimezone(tz).date())
        except ValueError:
            continue
    return max(days) if days else date.min


def ensure_counts(biz: Dict[str, Any], services: List[Dict[str, Any]], tz: ZoneInfo,
                  today: date) -> None:
    """A count for every service day from LOOK_BACK_DAYS ago to today that
    doesn't have one yet (the unique index keeps one per service and day)."""
    start = today - timedelta(days=LOOK_BACK_DAYS)
    by_id = {s["id"]: s for s in services}
    want = [o for o in occurrences(services, tz, start, today)
            if o["date"] >= _first_day(by_id.get(o["service_id"]) or {}, tz)]
    if not want:
        return
    have = _need(f"/giving_counts?business_id=eq.{_q(biz['id'])}&service_date=gte.{start.isoformat()}"
                 f"&select=service_id,service_date&limit=2000")
    seen = {(str(r.get("service_id")), str(r.get("service_date"))[:10]) for r in have}
    rows = [{"business_id": biz["id"], "service_id": o["service_id"], "name": o["name"],
             "service_date": o["date"].isoformat(), "starts_at": o["starts_at"].isoformat(),
             "collects_online": o["collects_online"]}
            for o in want if (str(o["service_id"]), o["date"].isoformat()) not in seen]
    if not rows:
        return
    out = sb_clients.sb_post_as_service(
        "/giving_counts?on_conflict=business_id,service_id,service_date", rows,
        prefer="resolution=ignore-duplicates,return=representation")
    if out is None:
        raise HTTPException(503, "The service counts couldn't be prepared. Please try again.")


def _gifts_of(business_id: str, count_ids: List[str]) -> List[Dict[str, Any]]:
    if not count_ids:
        return []
    ids = ",".join(_q(i) for i in count_ids)
    return _need(f"/invoices?business_id=eq.{_q(business_id)}&is_gift=eq.true&giving_count_id=in.({ids})"
                 f"&select={GIFT_FIELDS}&limit=5000")


def attach_online(biz: Dict[str, Any], count: Dict[str, Any], collecting_starts: List[datetime]) -> int:
    """Place the online gifts in this open, collecting count's window that
    aren't in any count yet. Returns how many were placed."""
    if count.get("status") != "open" or not count.get("collects_online"):
        return 0
    starts = datetime.fromisoformat(str(count["starts_at"]).replace("Z", "+00:00"))
    lo, hi = online_window(starts, collecting_starts)
    if lo >= hi:
        return 0
    rows = _need(f"/invoices?business_id=eq.{_q(biz['id'])}&is_gift=eq.true&giving_count_id=is.null"
                 f"&paid_at=gt.{_q(lo.isoformat())}&paid_at=lte.{_q(hi.isoformat())}"
                 f"&select=id,invoice_number,payment_method&limit=1000")
    ids = [r["id"] for r in rows if is_online(r)]
    if not ids:
        return 0
    out = sb_clients.sb_patch_as_service(
        f"/invoices?business_id=eq.{_q(biz['id'])}&giving_count_id=is.null&id=in.({','.join(_q(i) for i in ids)})",
        {"giving_count_id": count["id"]})
    if out is None:
        logger.warning(f"[giving_services] placing online gifts failed for count {count['id']}")
        return 0
    return len(out)


def _collecting_starts(business_id: str) -> List[datetime]:
    """When each collecting count that exists started. The windows come from
    the counts already made, never from today's schedule: a service removed
    or moved keeps its past windows, so a gift left out of a closed count
    stays out instead of sliding into the next one."""
    rows = _need(f"/giving_counts?business_id=eq.{_q(business_id)}&collects_online=eq.true"
                 f"&select=starts_at&order=starts_at.desc&limit=1000")
    out: List[datetime] = []
    for r in rows:
        try:
            out.append(datetime.fromisoformat(str(r.get("starts_at")).replace("Z", "+00:00")))
        except ValueError:
            continue
    return out


def _gift_out(g: Dict[str, Any]) -> Dict[str, Any]:
    """A gift as the count screen shows it: never the note's user ids."""
    import giving_ways
    notes = str(g.get("notes") or "")
    named = [m.group(1) for m in re.finditer(r"^Given through (.+)$", notes, re.M)]
    check = re.search(r"^Check #(\S+)$", notes, re.M)
    pm = str(g.get("payment_method") or "")
    return {"id": g["id"], "amount_cents": net_cents(g), "total": g.get("total"),
            "paid_at": g.get("paid_at"), "fund": g.get("gift_fund") or "General",
            "giver": (g.get("contacts") or {}).get("name") or "", "contact_id": g.get("contact_id"),
            "method": pm, "method_label": named[-1] if (pm == "other" and named) else giving_ways.method_label(pm),
            "kind": kind_of(g), "online": is_online(g), "loose": "Loose offering" in notes,
            "check_number": check.group(1) if check else None,
            "refunded_cents": int(g.get("refund_amount_cents") or 0), "updated_at": g.get("updated_at")}


def _count_out(c: Dict[str, Any], gifts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"id": c["id"], "service_id": c.get("service_id"), "name": c.get("name"),
            "date": str(c.get("service_date"))[:10], "starts_at": c.get("starts_at"),
            "collects_online": bool(c.get("collects_online")), "status": c.get("status"),
            "counted_cash_cents": c.get("counted_cash_cents"), "counted_checks_cents": c.get("counted_checks_cents"),
            "counters": c.get("counters") or [], "closed_at": c.get("closed_at"), "note": c.get("note") or "",
            "totals": totals(gifts)}


# ─── The schedule: endpoints ──────────────────────────────────────────

def _clean_service(body: Dict[str, Any], tz: ZoneInfo) -> Dict[str, Any]:
    name = " ".join(str(body.get("name") or "").split())
    if not 1 <= len(name) <= 80:
        raise HTTPException(400, "Name the service (up to 80 characters).")
    kind = body.get("kind")
    out: Dict[str, Any] = {"name": name, "collects_online": body.get("collects_online") is True}
    try:
        out["start_time"] = _hm(body.get("time")).strftime("%H:%M")
    except ValueError:
        raise HTTPException(400, "Choose the time the service starts.")
    if kind == "weekly":
        wd = body.get("weekday")
        if isinstance(wd, str) and wd.strip().title() in DAYS:
            wd = DAYS.index(wd.strip().title())
        if not isinstance(wd, int) or isinstance(wd, bool) or not 0 <= wd <= 6:
            raise HTTPException(400, "Choose the day of the week.")
        out.update(kind="weekly", weekday=wd, on_date=None)
    elif kind == "once":
        try:
            d = date.fromisoformat(str(body.get("date") or "")[:10])
        except ValueError:
            raise HTTPException(400, "Choose the service's date.")
        today = datetime.now(tz).date()
        if not (today - timedelta(days=366)) <= d <= (today + timedelta(days=366)):
            raise HTTPException(400, "Choose a date within a year of today.")
        out.update(kind="once", on_date=d.isoformat(), weekday=None)
    else:
        raise HTTPException(400, "Choose every week, or one date.")
    return out


def _service_out(s: Dict[str, Any], tz: ZoneInfo) -> Dict[str, Any]:
    nxt = occurrences([s], tz, datetime.now(tz).date(), datetime.now(tz).date() + timedelta(days=370))
    return {"id": s["id"], "name": s.get("name"), "kind": s.get("kind"), "weekday": s.get("weekday"),
            "day": DAYS[s["weekday"]] if isinstance(s.get("weekday"), int) else None,
            "date": s.get("on_date"), "time": str(s.get("start_time") or "")[:5],
            "collects_online": bool(s.get("collects_online")),
            "next": nxt[0]["date"].isoformat() if nxt else None}


@router.get("/giving/{business_id}/services")
def list_services(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _gate(business_id, user)
    tz = zone_of(biz)
    return {"services": [_service_out(s, tz) for s in _services(business_id)], "timezone": tz.key}


@router.post("/giving/{business_id}/services")
def add_service(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _gate(business_id, user)
    tz = zone_of(biz)
    if len(_services(business_id)) >= MAX_SERVICES:
        raise HTTPException(409, f"Keep up to {MAX_SERVICES} services. Remove one first.")
    row = {**_clean_service(body or {}, tz), "business_id": business_id}
    saved = sb_clients.sb_post_as_service("/giving_services", row)
    if not saved:
        raise HTTPException(503, "The service couldn't be saved. Please try again.")
    return {"ok": True, "service": _service_out(saved[0], tz)}


@router.patch("/giving/{business_id}/services/{service_id}")
def change_service(business_id: str, service_id: str, body: Dict[str, Any],
                   user: AuthedUser = Depends(require_user)):
    """A change applies to service days from now on: counts already made
    keep their name and time."""
    biz = _gate(business_id, user)
    tz = zone_of(biz)
    if not UUID_RE.match(service_id):
        raise HTTPException(404, "Service not found")
    row = _clean_service(body or {}, tz)
    saved = sb_clients.sb_patch_as_service(
        f"/giving_services?id=eq.{_q(service_id)}&business_id=eq.{_q(business_id)}&archived_at=is.null",
        {**row, "updated_at": datetime.now(timezone.utc).isoformat()})
    if saved is None:
        raise HTTPException(503, "The service couldn't be saved. Please try again.")
    if not saved:
        raise HTTPException(404, "Service not found")
    return {"ok": True, "service": _service_out(saved[0], tz)}


@router.delete("/giving/{business_id}/services/{service_id}")
def remove_service(business_id: str, service_id: str, user: AuthedUser = Depends(require_user)):
    """Takes the service off the schedule. Its counts and their gifts stay."""
    _gate(business_id, user)
    if not UUID_RE.match(service_id):
        raise HTTPException(404, "Service not found")
    saved = sb_clients.sb_patch_as_service(
        f"/giving_services?id=eq.{_q(service_id)}&business_id=eq.{_q(business_id)}&archived_at=is.null",
        {"archived_at": datetime.now(timezone.utc).isoformat()})
    if saved is None:
        raise HTTPException(503, "The service couldn't be removed. Please try again.")
    if not saved:
        raise HTTPException(404, "Service not found")
    return {"ok": True}


# ─── The counts: endpoints ────────────────────────────────────────────

def _count(business_id: str, count_id: str) -> Dict[str, Any]:
    if not UUID_RE.match(str(count_id or "")):
        raise HTTPException(404, "Count not found")
    rows = _need(f"/giving_counts?id=eq.{_q(count_id)}&business_id=eq.{_q(business_id)}&select={COUNT_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "Count not found")
    return rows[0]


@router.get("/giving/{business_id}/counts")
def list_counts(business_id: str, user: AuthedUser = Depends(require_user)):
    """The last nine weeks of counts (newest first, each with its totals),
    the services coming up in the next two weeks, and how many online gifts
    sit outside every count since the first count."""
    biz = _gate(business_id, user)
    tz = zone_of(biz)
    today = datetime.now(tz).date()
    services = _services(business_id)
    ensure_counts(biz, services, tz, today)
    start = today - timedelta(days=LOOK_BACK_DAYS)
    counts = _need(f"/giving_counts?business_id=eq.{_q(business_id)}&service_date=gte.{start.isoformat()}"
                   f"&select={COUNT_FIELDS}&order=starts_at.desc&limit=200")
    counts.sort(key=lambda c: str(c.get("starts_at") or ""), reverse=True)
    starts = _collecting_starts(business_id)
    for c in counts:
        if c.get("status") == "open" and c.get("collects_online"):
            attach_online(biz, c, starts)
    gifts = _gifts_of(business_id, [c["id"] for c in counts])
    by: Dict[str, List[Dict[str, Any]]] = {}
    for g in gifts:
        by.setdefault(str(g.get("giving_count_id")), []).append(g)
    have = {(str(c.get("service_id")), str(c.get("service_date"))[:10]) for c in counts}
    coming = [{"service_id": o["service_id"], "name": o["name"], "date": o["date"].isoformat(),
               "starts_at": o["starts_at"].isoformat(), "collects_online": o["collects_online"]}
              for o in occurrences(services, tz, today, today + timedelta(days=COMING_DAYS))
              if (str(o["service_id"]), o["date"].isoformat()) not in have][:6]
    return {"timezone": tz.key, "today": today.isoformat(),
            "counts": [_count_out(c, by.get(str(c["id"]), [])) for c in counts],
            "coming": coming, "has_services": bool(services),
            "unplaced": _unplaced_count(business_id, counts)}


def _unplaced_count(business_id: str, counts: List[Dict[str, Any]]) -> Optional[int]:
    """Online gifts since the oldest count listed that no count holds. None
    when they couldn't be read: never "0" for a read that failed."""
    if not counts:
        return 0
    oldest = min(str(c.get("starts_at")) for c in counts)
    rows = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{_q(business_id)}&is_gift=eq.true&giving_count_id=is.null"
        f"&paid_at=gte.{_q(oldest)}&select=id,invoice_number,payment_method&limit=1000")
    if rows is None:
        return None
    return sum(1 for r in rows if is_online(r))


@router.get("/giving/{business_id}/counts/{count_id}")
def get_count(business_id: str, count_id: str, user: AuthedUser = Depends(require_user)):
    biz = _gate(business_id, user)
    tz = zone_of(biz)
    count = _count(business_id, count_id)
    if count.get("status") == "open" and count.get("collects_online"):
        attach_online(biz, count, _collecting_starts(business_id))
    gifts = sorted(_gifts_of(business_id, [count_id]), key=lambda g: (not is_online(g), str(g.get("paid_at"))))
    return {"count": _count_out(count, gifts), "gifts": [_gift_out(g) for g in gifts]}


@router.get("/giving/{business_id}/unplaced")
def unplaced_gifts(business_id: str, user: AuthedUser = Depends(require_user)):
    """Online gifts in the last nine weeks that no count holds (their window
    was in a closed count, or no service collects online), newest first."""
    biz = _gate(business_id, user)
    since = datetime.now(timezone.utc) - timedelta(days=LOOK_BACK_DAYS)
    rows = _need(f"/invoices?business_id=eq.{_q(business_id)}&is_gift=eq.true&giving_count_id=is.null"
                 f"&paid_at=gte.{_q(since.isoformat())}&select={GIFT_FIELDS}&order=paid_at.desc&limit=500")
    return {"gifts": [_gift_out(g) for g in rows if is_online(g)]}


def _clean_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """One row the treasurer typed: request_id, amount_cents, fund, method,
    contact_id?, check_number?, loose?."""
    if not isinstance(raw, dict):
        raise ValueError("Each row needs an amount.")
    out = {k: raw.get(k) for k in ("request_id", "amount_cents", "fund", "method", "contact_id")}
    cn = str(raw.get("check_number") or "").strip()
    if cn and not re.fullmatch(r"[A-Za-z0-9-]{1,20}", cn):
        raise ValueError("A check number is up to 20 letters or numbers.")
    out["check_number"] = cn or None
    out["loose"] = raw.get("loose") is True
    return out


@router.post("/giving/{business_id}/counts/{count_id}/gifts")
def record_gifts(business_id: str, count_id: str, body: Dict[str, Any],
                 user: AuthedUser = Depends(require_user)):
    """Record several gifts into an open count at once, each dated the
    service's day. Every row has its own request_id, so pressing again after
    a dropped connection never records one twice. Each row answers for
    itself: {results: [{request_id, ok, id?, already?, error?}]}."""
    biz = _gate(business_id, user)
    from vertical_family import is_nonprofit_like
    if not is_nonprofit_like(biz.get("type")):
        raise HTTPException(409, "Giving is available to ministries and nonprofits")
    count = _count(business_id, count_id)
    if count.get("status") != "open":
        raise HTTPException(409, "This count is closed. Reopen it to add gifts.")
    rows = (body or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "Add at least one gift.")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"Record up to {MAX_ROWS} gifts at a time.")
    import giving_router
    day = str(count["service_date"])[:10]
    # A count's day is never after the church's today; a church ahead of UTC
    # records Sunday's gifts on Sunday morning, before UTC's Sunday.
    today = datetime.now(zone_of(biz)).date()
    results: List[Dict[str, Any]] = []
    for raw in rows:
        rid = str((raw or {}).get("request_id") or "") if isinstance(raw, dict) else ""
        try:
            row = _clean_row(raw)
            notes = []
            if row["loose"]:
                notes.append("Loose offering")
            if row["check_number"]:
                notes.append(f"Check #{row['check_number']}")
            out = giving_router.record_manual_gift(
                business_id, {**row, "received_on": day}, user,
                extra={"giving_count_id": count_id}, notes=notes, type_checked=True, latest=today)
            results.append({"request_id": rid, "ok": True, "id": out.get("id"), "already": bool(out.get("already"))})
        except ValueError as e:
            results.append({"request_id": rid, "ok": False, "error": str(e)})
        except HTTPException as e:
            detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
            results.append({"request_id": rid, "ok": False, "error": str(detail)})
    return {"results": results, "saved": sum(1 for r in results if r["ok"])}


@router.post("/giving/{business_id}/gifts/{gift_id}/count")
def move_gift(business_id: str, gift_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Put a gift in another open count. Its date and amount don't change,
    and a gift in a closed count stays there. There is no "in no count": an
    online gift taken out of every count would be placed again by its
    window on the next read."""
    _gate(business_id, user)
    if not UUID_RE.match(gift_id):
        raise HTTPException(404, "Gift not found")
    rows = _need(f"/invoices?id=eq.{_q(gift_id)}&business_id=eq.{_q(business_id)}&is_gift=eq.true"
                 f"&select=id,giving_count_id&limit=1")
    if not rows:
        raise HTTPException(404, "Gift not found")
    current = rows[0].get("giving_count_id")
    if current:
        if _count(business_id, str(current)).get("status") != "open":
            raise HTTPException(409, "That gift is in a closed count. Reopen the count to move it.")
    target = str((body or {}).get("count_id") or "")
    if not target:
        raise HTTPException(400, "Choose the service the gift belongs to.")
    if _count(business_id, target).get("status") != "open":
        raise HTTPException(409, "That count is closed. Reopen it to add a gift.")
    cond = f"giving_count_id=eq.{_q(current)}" if current else "giving_count_id=is.null"
    saved = sb_clients.sb_patch_as_service(
        f"/invoices?id=eq.{_q(gift_id)}&business_id=eq.{_q(business_id)}&{cond}",
        {"giving_count_id": target})
    if saved is None:
        raise HTTPException(503, "The gift couldn't be moved. Please try again.")
    if not saved:
        raise HTTPException(409, "That gift just changed. Reload and try again.")
    return {"ok": True, "count_id": target}


# ─── Closing a count (step 3) ─────────────────────────────────────────
# The standard church money control: the counters count the plate before
# anything is itemized, two of them sign, and the itemized cash and checks
# must equal what they counted. A closed count is locked. A change after
# that means reopening it with a reason (owner or admin), and the reason
# stays on the count.

MAX_COUNTERS = 4


def _counters(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        raise HTTPException(400, "Name who counted.")
    out: List[str] = []
    for n in raw:
        name = " ".join(str(n or "").split())
        if not name:
            continue
        if len(name) > 60:
            raise HTTPException(400, "Keep each counter's name to 60 characters.")
        if name.lower() not in (o.lower() for o in out):
            out.append(name)
    if not out:
        raise HTTPException(400, "Name who counted.")
    if len(out) > MAX_COUNTERS:
        raise HTTPException(400, f"Name up to {MAX_COUNTERS} counters.")
    return out


def _cents_in(raw: Any, what: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 100_000_000:
        raise HTTPException(400, f"Enter the counted {what} (zero if none).")
    return raw


@router.post("/giving/{business_id}/counts/{count_id}/close")
def close_count(business_id: str, count_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """{counted_cash_cents, counted_checks_cents, counters: [names], note?}.
    Refused (409, with the differences) when the cash or checks recorded
    don't equal what was counted."""
    _gate(business_id, user)
    body = body or {}
    count = _count(business_id, count_id)
    if count.get("status") != "open":
        raise HTTPException(409, "This count is already closed.")
    cash = _cents_in(body.get("counted_cash_cents"), "cash")
    checks = _cents_in(body.get("counted_checks_cents"), "checks")
    counters = _counters(body.get("counters"))
    note = " ".join(str(body.get("note") or "").split())[:500]
    t = totals(_gifts_of(business_id, [count_id]))
    off_cash, off_checks = cash - t["cash"], checks - t["check"]
    if off_cash or off_checks:
        parts = []
        if off_cash:
            parts.append(f"cash is {usd_text(abs(off_cash))} {'more' if off_cash > 0 else 'less'} than recorded")
        if off_checks:
            parts.append(f"checks are {usd_text(abs(off_checks))} {'more' if off_checks > 0 else 'less'} than recorded")
        raise HTTPException(409, {
            "error": "count_differs",
            "message": "The count doesn't match what's recorded: " + " and ".join(parts) + ".",
            "cash_difference_cents": off_cash, "checks_difference_cents": off_checks,
            "recorded_cash_cents": t["cash"], "recorded_checks_cents": t["check"]})
    now = datetime.now(timezone.utc).isoformat()
    saved = sb_clients.sb_patch_as_service(
        f"/giving_counts?id=eq.{_q(count_id)}&business_id=eq.{_q(business_id)}&status=eq.open",
        {"status": "closed", "counted_cash_cents": cash, "counted_checks_cents": checks, "counters": counters,
         "closed_at": now, "closed_by": str(user.id), "updated_at": now,
         "note": _note_add(count.get("note"), f"Closed {now[:10]}" + (f": {note}" if note else ""))})
    if saved is None:
        raise HTTPException(503, "The count couldn't be closed. Please try again.")
    if not saved:
        raise HTTPException(409, "This count just changed. Reload it.")
    # A gift recorded (or placed) between the totals read above and the
    # close would sit in a closed count the counters never signed for: read
    # again, and if the cash or checks moved, open it again and say so.
    after = _gifts_of(business_id, [count_id])
    t2 = totals(after)
    if (t2["cash"], t2["check"]) != (t["cash"], t["check"]):
        back = sb_clients.sb_patch_as_service(
            f"/giving_counts?id=eq.{_q(count_id)}&business_id=eq.{_q(business_id)}&status=eq.closed",
            {"status": "open", "updated_at": datetime.now(timezone.utc).isoformat(),
             "note": _note_add(saved[0].get("note"), "Opened again: a gift came in while it was closing")})
        if not back:
            logger.warning(f"[giving_services] count {count_id} closed against old totals and couldn't be reopened")
        raise HTTPException(409, "A gift was added while the count was closing, so it stays open. Check the rows "
                                 "and close it again.")
    return {"ok": True, "count": _count_out(saved[0], after)}


@router.post("/giving/{business_id}/counts/{count_id}/reopen")
def reopen_count(business_id: str, count_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Owner or admin, with a reason that stays on the count. The counted
    totals and counters stay until it's closed again."""
    from giving_records import require_finance
    _gate(business_id, user)
    if require_finance(business_id, user) not in ("owner", "admin"):
        raise HTTPException(403, "Only the owner or an admin can reopen a closed count.")
    reason = " ".join(str((body or {}).get("reason") or "").split())[:300]
    if not reason:
        raise HTTPException(400, "Say why the count is being reopened. The reason stays with it.")
    count = _count(business_id, count_id)
    if count.get("status") != "closed":
        raise HTTPException(409, "This count is already open.")
    now = datetime.now(timezone.utc).isoformat()
    saved = sb_clients.sb_patch_as_service(
        f"/giving_counts?id=eq.{_q(count_id)}&business_id=eq.{_q(business_id)}&status=eq.closed",
        {"status": "open", "updated_at": now,
         "note": _note_add(count.get("note"), f"Reopened {now[:10]}: {reason}")})
    if saved is None:
        raise HTTPException(503, "The count couldn't be reopened. Please try again.")
    if not saved:
        raise HTTPException(409, "This count just changed. Reload it.")
    return {"ok": True}


def _note_add(old: Any, line: str) -> str:
    text = (str(old or "").strip() + "\n" + line).strip()
    return text[-1000:]


def usd_text(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def gift_in_closed_count(business_id: str, gift: Dict[str, Any]) -> Optional[str]:
    """The closed count's name when this gift sits in one, else None. For the
    correction endpoint: a closed count is locked."""
    cid = gift.get("giving_count_id")
    if not cid:
        return None
    rows = _need(f"/giving_counts?id=eq.{_q(cid)}&business_id=eq.{_q(business_id)}&select=name,service_date,status&limit=1")
    if rows and rows[0].get("status") == "closed":
        return f"{rows[0].get('name')} ({str(rows[0].get('service_date'))[:10]})"
    return None
