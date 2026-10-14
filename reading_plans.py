"""
reading_plans.py — a church reads the Bible together, a day at a time.

The Subsplash LCC app's dated reading plan was one of its best parts in
the 9/30 walkthrough. Here the church's team picks a plan and a start
date; every member sees today's reading on Home, reads it in the app's
own Bible (KJV and WEB, both public domain, so no licence is involved),
and ticks it off.

Plans are COMPUTED from the Bible's own chapter list, never typed in, so
a plan can't skip or repeat a chapter:

    bible-year           every chapter, in order, in 365 days (3-4 a day)
    nt-260               the New Testament, a chapter a day (260 days)
    gospels-30           Matthew to John in 30 days (about 3 a day)
    psalms-proverbs-31   a Proverbs chapter and about 5 Psalms a day

Where things live:
    businesses.settings.reading_plan   {key, start}   one plan at a time
    reading_progress                   one row per member per day read

Staff (owner, admin, manager) choose and stop the plan; any active seat
reads it. Members only ever write their own ticks, through /my.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

import bible_text as bt
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("reading_plans")

router = APIRouter(prefix="/church", tags=["church"])

Reading = List[Tuple[str, int, int]]          # [(book code, first ch, last ch)]

PLANS: Dict[str, Dict[str, Any]] = {
    "bible-year": {"title": "The whole Bible in a year", "days": 365,
                   "about": "Every chapter from Genesis to Revelation, three or four a day."},
    "nt-260": {"title": "The New Testament in 260 days", "days": 260,
               "about": "One chapter a day, Matthew to Revelation."},
    "gospels-30": {"title": "The Gospels in 30 days", "days": 30,
                   "about": "Matthew, Mark, Luke and John, about three chapters a day."},
    "psalms-proverbs-31": {"title": "Psalms and Proverbs in a month", "days": 31,
                           "about": "A chapter of Proverbs and about five Psalms each day."},
}
STAFF_ROLES = ("owner", "admin", "manager")


def _chapters(codes: List[str]) -> List[Tuple[str, int]]:
    return [(c, n) for c in codes for n in range(1, bt.chapter_count(c) + 1)]


def _ranges(chapters: List[Tuple[str, int]]) -> Reading:
    """[(GEN,1),(GEN,2),(EXO,1)] -> [(GEN,1,2),(EXO,1,1)]"""
    out: Reading = []
    for code, n in chapters:
        if out and out[-1][0] == code and out[-1][2] == n - 1:
            out[-1] = (code, out[-1][1], n)
        else:
            out.append((code, n, n))
    return out


def _spread(chapters: List[Tuple[str, int]], days: int) -> List[Reading]:
    """Cut the chapters into `days` runs as even as whole chapters allow."""
    total = len(chapters)
    return [_ranges(chapters[round(d * total / days):round((d + 1) * total / days)])
            for d in range(days)]


@lru_cache(maxsize=None)
def schedule(key: str) -> Tuple[Reading, ...]:
    """Every day of a plan, day 1 first."""
    codes = [c for c, _, _ in bt.BOOKS]
    if key == "bible-year":
        days = _spread(_chapters(codes), 365)
    elif key == "nt-260":
        days = _spread(_chapters(codes[39:]), 260)
    elif key == "gospels-30":
        days = _spread(_chapters(["MAT", "MAR", "LUK", "JOH"]), 30)
    elif key == "psalms-proverbs-31":
        psalms = _spread(_chapters(["PSA"]), 31)
        days = [psalms[d] + [("PRO", d + 1, d + 1)] for d in range(31)]
    else:
        raise KeyError(key)
    return tuple(days)


def label(reading: Reading) -> str:
    """'Genesis 1–3; Exodus 1' — what a person reads aloud."""
    parts = []
    for code, a, b in reading:
        parts.append(f"{bt.NAME[code]} {a}" + (f"–{b}" if b != a else ""))
    return "; ".join(parts)


def href(reading: Reading) -> str:
    code, a, _ = reading[0]
    return f"/my/bible/{bt.slug(code)}/{a}"


# ─── the church's current plan ───────────────────────────────────────

def current(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """{key, title, start, days} from settings, or None."""
    raw = (biz.get("settings") or {}).get("reading_plan")
    if not isinstance(raw, dict) or raw.get("key") not in PLANS:
        return None
    try:
        start = date.fromisoformat(str(raw.get("start")))
    except ValueError:
        return None
    meta = PLANS[raw["key"]]
    return {"key": raw["key"], "title": meta["title"], "start": start, "days": meta["days"]}


def day_number(plan: Dict[str, Any], today: Optional[date] = None) -> Optional[int]:
    """1-based day of the plan for `today`, or None before it starts or
    after it ends."""
    today = today or date.today()
    n = (today - plan["start"]).days + 1
    return n if 1 <= n <= plan["days"] else None


def today_for(biz: Dict[str, Any], today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """What Home shows: {day, of, label, href, title} or None."""
    plan = current(biz)
    if not plan:
        return None
    n = day_number(plan, today)
    if not n:
        return None
    reading = schedule(plan["key"])[n - 1]
    return {"day": n, "of": plan["days"], "label": label(reading), "href": href(reading),
            "title": plan["title"], "key": plan["key"], "start": plan["start"].isoformat()}


# ─── a member's ticks ────────────────────────────────────────────────

def read_days(business_id: str, contact_id: str, plan: Dict[str, Any]) -> Optional[set]:
    rows = sb_clients.sb_get_as_service(
        f"/reading_progress?business_id=eq.{business_id}&contact_id=eq.{contact_id}"
        f"&plan_key=eq.{plan['key']}&start_date=eq.{plan['start'].isoformat()}"
        "&select=day&limit=400")
    if rows is None:
        return None
    return {int(r["day"]) for r in rows}


def readable_upto(plan: Dict[str, Any], today: Optional[date] = None) -> int:
    """The last day a member may tick: today's, or every day once the
    plan is over; 0 before it starts. A future day can't be ticked."""
    elapsed = ((today or date.today()) - plan["start"]).days + 1
    return max(0, min(elapsed, plan["days"]))


def mark(business_id: str, contact_id: str, plan: Dict[str, Any], day: int, read: bool) -> bool:
    if not (1 <= day <= readable_upto(plan)):
        return False
    where = (f"business_id=eq.{business_id}&contact_id=eq.{contact_id}"
             f"&plan_key=eq.{plan['key']}&start_date=eq.{plan['start'].isoformat()}&day=eq.{day}")
    if not read:
        return bool(sb_clients.sb_delete_as_service(f"/reading_progress?{where}"))
    rows = sb_clients.sb_post_as_service(
        "/reading_progress?on_conflict=business_id,contact_id,plan_key,start_date,day",
        {"business_id": business_id, "contact_id": contact_id, "plan_key": plan["key"],
         "start_date": plan["start"].isoformat(), "day": day},
        prefer="return=representation,resolution=ignore-duplicates")
    return isinstance(rows, list)


def streak(done: set, today_n: int) -> int:
    """Days in a row up to today (or yesterday, if today isn't read yet)."""
    n = today_n if today_n in done else today_n - 1
    out = 0
    while n >= 1 and n in done:
        out += 1
        n -= 1
    return out


# ─── staff: choose, stop, read ───────────────────────────────────────

def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")


def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{biz}&select=id,owner_id,settings&limit=1")
    if rows is None:
        raise HTTPException(503, "The reading plan couldn't be read. Try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _role(biz: str, user: AuthedUser) -> Optional[str]:
    from business_users_router import role_of
    return role_of(biz, str(user.id))


@router.get("/reading-plans")
def reading_plans(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    if not _role(biz, user):
        raise HTTPException(404, "business not found")
    b = _business(biz)
    plan = current(b)
    return {
        "plans": [{"key": k, "title": v["title"], "days": v["days"], "about": v["about"],
                   "first_day": label(schedule(k)[0])} for k, v in PLANS.items()],
        "current": ({"key": plan["key"], "title": plan["title"], "start": plan["start"].isoformat(),
                     "days": plan["days"], "today": today_for(b)} if plan else None),
    }


@router.put("/reading-plans")
def choose_reading_plan(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    if _role(biz, user) not in STAFF_ROLES:
        raise HTTPException(403, "Only the owner, an admin or a manager chooses the reading plan")
    key = str((body or {}).get("plan") or "")
    if key not in PLANS:
        raise HTTPException(400, "Choose one of the plans")
    try:
        start = date.fromisoformat(str((body or {}).get("start") or ""))
    except ValueError:
        raise HTTPException(400, "Choose a start date")
    if abs((start - date.today()).days) > 400:
        raise HTTPException(400, "Choose a start date within a year of today")
    b = _business(biz)
    settings = dict(b.get("settings") or {})
    settings["reading_plan"] = {"key": key, "start": start.isoformat(),
                                "chosen_at": datetime.now(timezone.utc).isoformat()}
    saved = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz}", {"settings": settings})
    if not saved:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "current": {"key": key, "title": PLANS[key]["title"], "start": start.isoformat(),
                                    "days": PLANS[key]["days"]}}


@router.delete("/reading-plans")
def stop_reading_plan(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    if _role(biz, user) not in STAFF_ROLES:
        raise HTTPException(403, "Only the owner, an admin or a manager stops the reading plan")
    b = _business(biz)
    settings = dict(b.get("settings") or {})
    if "reading_plan" not in settings:
        return {"ok": True, "current": None}
    settings.pop("reading_plan")
    if not sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz}", {"settings": settings}):
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "current": None}
