"""giving_week.py — what a church was given in one week, for the pastor's eyes.

Kevin, 2026-11-17, after the church's weekly briefing was rewritten with no
giving in it: "yes" to putting giving in. The letter itself can't carry it:
the Briefing page opens to office logins that never see giving, the letter
is written once and kept for the whole church (the `insights` row, which
those logins read straight from the database), and whatever is in its
prompt, its words or its kept numbers is theirs to read.

So giving is NOT in the letter. It is this, beside it:

    THE BLOCK ...... "Giving this week": seven days ending on the letter's
                     day, and the seven days before, on the church's own
                     clock. What was given, how many gifts, how many
                     givers, and the week by fund. Read numbers, never a
                     model's words, and never a giver's name
    THE GATE ....... giving_records.require_finance: the owner, an active
                     Admin seat, the church's outside accountant. The same
                     rule as the gift amounts (GET /giving/{biz}/amounts)
                     and as the database's own (ministry_finance_access on
                     invoices.is_gift). Anyone else: 403, before a row is
                     read. No Giving keeper's wall, as for the amounts: the
                     keeper guards who gave what, not the picture
    NEVER KEPT ..... worked out when the page asks, for the week it asks
                     about. Nothing here is written anywhere

EVERY NUMBER IS THE GIVING PAGE'S
Gifts are `invoices` rows with is_gift true and status paid, read by
giving_records.read_gifts (keyset pages of 500, a failed or short read is a
503, never zero). A gift is worth its total less what was refunded, as the
Giving page counts it (givingMath.netOf, giving_services.net_cents). A gift
refunded in full is not counted as a gift. A fund is the gift's own fund,
"General" when it names none, as the Giving page shows it. A giver is a
person on file with at least one gift in the week; gifts with no giver on
file are in the total and are said apart, as Reports says them.

A week is cut on the church's clock (the one Sunday Planning uses). A clock
that can't be read is a 503: a week is never cut on a guessed clock.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import sb_clients

DAYS = 7
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def business_id_of(raw: Any) -> str:
    """The id as a uuid, or 404: it goes into a query string."""
    s = str(raw or "").strip()
    if not _UUID.match(s):
        raise HTTPException(404, "Business not found")
    return s.lower()


def _business(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,type,settings,owner_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Giving could not be loaded. Please retry.")
    if not rows:
        raise HTTPException(404, "Business not found")
    return rows[0]


def _zone(biz: Dict[str, Any]):
    """The church's clock (church_leaders_note._zone: a 503 when it can't be read)."""
    import church_leaders_note
    return church_leaders_note._zone(biz)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(d: date, tz) -> str:
    """Midnight on the church's clock, as the UTC instant read_gifts takes."""
    return datetime.combine(d, time(0), tzinfo=tz).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(raw: Optional[str], today: date) -> date:
    """The week's last day: the one asked for, else today. Never a day that
    hasn't come."""
    if raw is None or str(raw).strip() == "":
        return today
    s = str(raw).strip()
    if not _DAY.match(s):
        raise HTTPException(400, "Choose a valid day")
    try:
        d = date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "Choose a valid day")
    if d.year < 2000:
        raise HTTPException(400, "Choose a valid day")
    return min(d, today)


def net_cents(gift: Dict[str, Any]) -> int:
    """What the gift is worth after any refund (giving_services.net_cents)."""
    return max(0, round(float(gift.get("total") or 0) * 100) - int(gift.get("refund_amount_cents") or 0))


def fund_of(gift: Dict[str, Any]) -> str:
    """The gift's fund as the Giving page names it (givingMath.fundOf)."""
    return " ".join(str(gift.get("gift_fund") or "").split()) or "General"


def summary(gifts: List[Dict[str, Any]]) -> Dict[str, int]:
    """One week's giving: the total, the gifts, the givers on file, and what
    came with no giver on file."""
    total = count = unnamed = 0
    givers = set()
    for g in gifts:
        net = net_cents(g)
        if net <= 0:
            continue
        total += net
        count += 1
        if g.get("contact_id"):
            givers.add(str(g["contact_id"]))
        else:
            unnamed += net
    return {"total_cents": total, "gifts": count, "givers": len(givers), "no_giver_cents": unnamed}


def by_fund(gifts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The week by fund, the largest first. "Building" and "building" are one fund."""
    funds: Dict[str, Dict[str, Any]] = {}
    for g in gifts:
        net = net_cents(g)
        if net <= 0:
            continue
        name = fund_of(g)
        f = funds.setdefault(name.lower(), {"fund": name, "total_cents": 0, "gifts": 0})
        f["total_cents"] += net
        f["gifts"] += 1
    return sorted(funds.values(), key=lambda f: (-f["total_cents"], f["fund"].lower()))


def _paid_at(gift: Dict[str, Any]) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(gift.get("paid_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _has_any_gift(business_id: str) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{business_id}&is_gift=eq.true&status=eq.paid&select=id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Giving could not be loaded. Please retry.")
    return bool(rows)


def read(business_id: str, day: Optional[str] = None) -> Dict[str, Any]:
    """The week ending on `day` and the week before it. The caller has
    already passed the gate (giving_router.giving_week)."""
    from giving_records import read_gifts
    biz = _business(business_id)
    tz = _zone(biz)
    last = day_of(day, _now().astimezone(tz).date())
    first = last - timedelta(days=DAYS - 1)          # this week: first .. last
    before_first = first - timedelta(days=DAYS)      # the week before: before_first .. first - 1
    if not _has_any_gift(business_id):
        # A church that has never recorded a gift is not shown a card of zeros.
        return {"uses_giving": False, "day": last.isoformat()}
    cut = datetime.combine(first, time(0), tzinfo=tz)
    gifts = read_gifts(business_id, _utc(before_first, tz), _utc(last + timedelta(days=1), tz))
    this_week, before = [], []
    for g in gifts:
        at = _paid_at(g)
        if at is None:
            continue
        (this_week if at >= cut else before).append(g)
    return {
        "uses_giving": True,
        "day": last.isoformat(),
        "week": {"from": first.isoformat(), "to": last.isoformat(), **summary(this_week)},
        "before": {"from": before_first.isoformat(), "to": (first - timedelta(days=1)).isoformat(), **summary(before)},
        "funds": by_fund(this_week),
    }
