"""
chief_giving_summary.py: what came in, for a day or a span of days.

Kevin, 2026-11-22: "I signed up Elevation of Grace ... the treasurer ... went
to ask Chief what was the giving today, Chief couldn't find it."

Chief had two reads near that question and neither answered it. The service
counts (giving_counts) are giving BY SERVICE: a church that hasn't added its
services there is told there are none, whatever it was given. And show_revenue
opened the Revenue screen and handed back no figure. So a treasurer asking the
plainest question a treasurer asks got nothing.

    giving_summary   read: one day or a span of days on the church's own
                     clock ("today", "yesterday", the last seven days, this
                     month, last month, this year, or from/to). The total,
                     how many gifts, how many givers on file, the gifts by
                     fund and by how they were given, the span by day when
                     it is short, and the same number of days before it.

EVERY NUMBER IS THE GIVING PAGE'S (giving_week's own readers: read_gifts in
keyset pages, a failed or short read is a 503 and never zero; a gift is worth
its total less what was refunded; a fund is the gift's own, "General" when it
names none).

NO GIVER IS NAMED. This is the picture, as "Giving this week" beside the
briefing is (giving_week): amounts, never who gave. So it asks the giving
gate (giving_records.require_finance: the owner, an Admin, the church's
accountant, or the giving tick where that is on). The total, the count, the
funds and the days are what those people already read without the Giving
keeper's key (GET /giving/{biz}/week and /amounts). HOW it was given (cash,
check, online) is not on those pages, and Chief's service counts keep it
behind the keeper, so here too it is said only where Giving & money is open
to this person (church_keys.is_open); locked, the rest is still answered and
the reply says that part needs the key. One person's giving is
giving_statement, behind the key.

A long span is answered small: past BY_DAY_MAX days there is no day-by-day,
past COMPARE_MAX no "days before" (it would read a second year of gifts),
and at most FUNDS_MAX funds are named, the rest counted. The tool loop cuts
a result over its size to a sample that says "do not infer totals".

Only inside a signed-in turn: with no person in the turn nothing is read, so
it never reaches an agent surface (action_registry: sensitive, chief_only).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "giving"}
ATYPE = "giving_summary"
MAX_DAYS = 400              # a year and a month; longer is a report's job (Reports, Giving & income)
BY_DAY_MAX = 31             # a span this short is also said day by day
COMPARE_MAX = 92            # a span this short is set beside the same number of days before it
FUNDS_MAX = 12              # funds named; the rest are counted (a result cut short reads as a sample)
PERIODS = ("today", "yesterday", "last_7_days", "this_month", "last_month", "this_year")

TOOL = {
    "name": ATYPE,
    "description": (
        "What a church or nonprofit was GIVEN over one day or a span of days, on its own clock: the total, how many "
        "gifts, how many givers, by fund, by how it was given (cash, check, online, an app), by day for a short "
        "span, and the same number of days before it. Use it for 'what was the giving today', 'what came in "
        "Sunday', 'how much this week / this month', 'how much to the building fund in October'. It works whether "
        "or not services are set up for giving (the service counts are the picture service by service, and where "
        "gifts are recorded). Give `period`, or `from` and `to` for any other day or span (one day: the same date "
        "in both). Quote its figures and its dates; never estimate, and never say nothing came in unless it says "
        "so. It names no giver: one person's giving is giving_statement."),
    "input_schema": {
        "type": "object",
        "properties": {
            "period": {"type": "string", "enum": list(PERIODS),
                       "description": "Default today. last_7_days ends today."},
            "from": {"type": "string", "description": "First day, YYYY-MM-DD (with `to`; instead of period)."},
            "to": {"type": "string", "description": "Last day, YYYY-MM-DD. Defaults to `from`."},
        },
    },
}


def _fail(msg: str) -> Dict[str, Any]:
    return {"type": ATYPE, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _day(d: date) -> str:
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _detail(e: HTTPException) -> str:
    d = e.detail
    return str((d.get("message") if isinstance(d, dict) else d) or "")


# ─── Which days ───────────────────────────────────────────────────────

def _iso(raw: Any) -> Optional[date]:
    try:
        d = date.fromisoformat(str(raw or "").strip()[:10])
    except ValueError:
        return None
    return d if d.year >= 2000 else None


def span(action: Dict[str, Any], today: date) -> Tuple[Optional[date], Optional[date], str]:
    """(first day, last day, '') for what was asked, or (None, None, why).
    `from`/`to` win over `period`; a day that hasn't come is cut to today."""
    raw_from, raw_to = action.get("from") or action.get("date"), action.get("to")
    if raw_from or raw_to:
        first = _iso(raw_from or raw_to)
        last = _iso(raw_to or raw_from)
        if not first or not last:
            return None, None, "say the days as YYYY-MM-DD"
        if last < first:
            first, last = last, first
        if first > today:
            return None, None, f"{_day(first)} hasn't come yet"
        last = min(last, today)
    else:
        period = str(action.get("period") or "today").strip().lower().replace(" ", "_").replace("-", "_")
        if period in ("week", "this_week", "last_week", "past_week", "last_seven_days"):
            period = "last_7_days"
        if period == "today":
            first = last = today
        elif period == "yesterday":
            first = last = today - timedelta(days=1)
        elif period == "last_7_days":
            first, last = today - timedelta(days=6), today
        elif period == "this_month":
            first, last = today.replace(day=1), today
        elif period == "last_month":
            last = today.replace(day=1) - timedelta(days=1)
            first = last.replace(day=1)
        elif period == "this_year":
            first, last = date(today.year, 1, 1), today
        else:
            return None, None, "choose " + ", ".join(PERIODS) + ", or give from and to"
    if (last - first).days + 1 > MAX_DAYS:
        return None, None, (f"that is more than {MAX_DAYS} days; ask for a shorter span, or open Reports for "
                            "Giving & income")
    return first, last, ""


def _span_words(first: date, last: date, today: date) -> str:
    if first == last:
        tag = " (today)" if first == today else " (yesterday)" if first == today - timedelta(days=1) else ""
        return f"{_day(first)}, {first.year}{tag}"
    days = (last - first).days + 1
    return f"{_day(first)} to {_day(last)}, {last.year} ({days} days" + (", through today)" if last == today else ")")


# ─── The picture (pure) ───────────────────────────────────────────────

def by_way(gifts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The gifts by how they were given, in the church's own words for
    each way (giving_ways.method_label), the largest first."""
    import giving_week as gw
    from giving_ways import method_label
    ways: Dict[str, Dict[str, Any]] = {}
    for g in gifts:
        net = gw.net_cents(g)
        if net <= 0:
            continue
        label = method_label(g.get("payment_method"))
        w = ways.setdefault(label, {"way": label, "total_cents": 0, "gifts": 0})
        w["total_cents"] += net
        w["gifts"] += 1
    return sorted(ways.values(), key=lambda w: (-w["total_cents"], w["way"].lower()))


def by_day(gifts: List[Dict[str, Any]], tz, first: date, last: date) -> List[Dict[str, Any]]:
    """Each day of the span that had a gift, oldest first, on the church's clock."""
    import giving_week as gw
    days: Dict[date, Dict[str, Any]] = {}
    for g in gifts:
        net, at = gw.net_cents(g), gw._paid_at(g)
        if net <= 0 or at is None:
            continue
        d = at.astimezone(tz).date()
        if not (first <= d <= last):
            continue
        row = days.setdefault(d, {"date": d.isoformat(), "total_cents": 0, "gifts": 0})
        row["total_cents"] += net
        row["gifts"] += 1
    return [days[d] for d in sorted(days)]


def words(first: date, last: date, today: date, now: Dict[str, int], before: Optional[Dict[str, int]],
          funds: List[Dict[str, Any]], ways: Optional[List[Dict[str, Any]]], days: List[Dict[str, Any]],
          ever: bool) -> str:
    """What Chief reads back: figures and dates only, no giver. `before`
    None: the span is too long to set beside the days before it. `ways`
    None: how it was given is behind the Giving keeper's key for this person."""
    when = _span_words(first, last, today)
    n_days = (last - first).days + 1
    prior = ""
    if before is not None:
        prior = (f"The {n_days} days before ({_day(first - timedelta(days=n_days))} to "
                 f"{_day(first - timedelta(days=1))}): " if n_days > 1
                 else f"The day before ({_day(first - timedelta(days=1))}): ")
        prior += (f"{_money(before['total_cents'])} in {_plural(before['gifts'], 'gift')}." if before["gifts"]
                  else "nothing recorded.")
    if not now["gifts"]:
        if not ever:
            return (f"No gift has ever been recorded for this church, so there is nothing for {when}. Gifts show "
                    "here once they are entered on the Giving page (Bookkeeping, Giving) or come in online.")
        return (f"No gifts are recorded for {when}. That is what is in the system: an offering still on paper, or "
                f"not entered yet, isn't in it. {prior}").rstrip()
    head = (f"Giving for {when}, on the church's clock: {_money(now['total_cents'])} in "
            f"{_plural(now['gifts'], 'gift')} from {_plural(now['givers'], 'giver')} on file")
    head += (f" ({_money(now['no_giver_cents'])} of it with no giver on file: loose cash or anonymous)."
             if now["no_giver_cents"] else ".")
    lines = [head]
    if funds:
        more = len(funds) - FUNDS_MAX
        lines.append("By fund: " + "; ".join(f"{f['fund']} {_money(f['total_cents'])} ({f['gifts']})"
                                             for f in funds[:FUNDS_MAX])
                     + (f"; and {more} more fund{'' if more == 1 else 's'} with "
                        f"{_money(sum(f['total_cents'] for f in funds[FUNDS_MAX:]))} between them" if more > 0 else "")
                     + ".")
    if ways is None:
        lines.append("How it was given (cash, check, online) is behind the Giving keeper's key for this login: it "
                     "opens for an hour once the keeper says yes, in Areas.")
    elif ways:
        lines.append("By how it was given: " + "; ".join(f"{w['way']} {_money(w['total_cents'])} ({w['gifts']})"
                                                         for w in ways[:10]) + ".")
    if n_days > 1 and days:
        lines.append("By day: " + "; ".join(f"{_day(date.fromisoformat(d['date']))} {_money(d['total_cents'])} "
                                            f"({d['gifts']})" for d in days) + ". A day not listed had no gift.")
    if prior:
        lines.append(prior)
    lines.append("Refunds are already taken out. No giver is named here.")
    return "\n".join(lines)


# ─── The read ─────────────────────────────────────────────────────────

def _gate(biz_id: str) -> Optional[Dict[str, Any]]:
    """The giving gate at "see" for the person in this turn, or the failure."""
    from chief_of_staff import _TURN_USER_ID
    from giving_records import require_finance
    uid = _TURN_USER_ID.get()
    if not uid:
        return _fail("giving is only read for a signed-in person who keeps the giving records")
    try:
        require_finance(biz_id, SimpleNamespace(id=uid), need="see")
    except HTTPException as e:
        if e.status_code >= 500:
            return _fail("who may see giving couldn't be checked just now; nothing was read. Try again")
        return _fail(_detail(e) or "this login can't see the giving records")
    return None


def _key_open(biz_id: str) -> bool:
    """Whether Giving & money is open to the person in this turn (no keeper,
    a keeper, or a key just given). A read that fails is a no."""
    try:
        import church_keys
        from chief_of_staff import _TURN_USER_ID
        return bool(church_keys.is_open(biz_id, SimpleNamespace(id=_TURN_USER_ID.get()), "giving_money"))
    except Exception:  # noqa: BLE001 — couldn't tell: the guarded part stays shut
        return False


def summary_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    import giving_records
    import giving_week as gw
    from growth_words import giving_is_private
    biz_id = str(biz["id"])
    if not giving_is_private(biz.get("type")):
        return _fail("giving is a church's or a nonprofit's. For what this business was paid, use show_revenue")
    refused = _gate(biz_id)
    if refused:
        return refused
    try:
        tz = gw._zone(biz)
        today = gw._now().astimezone(tz).date()
        first, last, why = span(action or {}, today)
        if not first or not last:
            return _fail(why)
        n_days = (last - first).days + 1
        compare = n_days <= COMPARE_MAX
        read_from = first - timedelta(days=n_days) if compare else first
        gifts = giving_records.read_gifts(biz_id, gw._utc(read_from, tz), gw._utc(last + timedelta(days=1), tz))
        cut = datetime.combine(first, time(0), tzinfo=tz)
        now_rows, before_rows = [], []
        for g in gifts:
            at = gw._paid_at(g)
            if at is None:
                continue
            (now_rows if at >= cut else before_rows).append(g)
        now = gw.summary(now_rows)
        before = gw.summary(before_rows) if compare else None
        ever = bool(now["gifts"] or before_rows) or gw._has_any_gift(gw.business_id_of(biz_id))
    except HTTPException as e:
        return _fail(_detail(e) or "giving couldn't be read just now; nothing is known. Try again")
    funds = gw.by_fund(now_rows)
    ways = by_way(now_rows) if _key_open(biz_id) else None
    days = by_day(now_rows, tz, first, last) if 1 < n_days <= BY_DAY_MAX else []
    text = words(first, last, today, now, before, funds, ways, days, ever)
    label = (f"{_money(now['total_cents'])} in {_plural(now['gifts'], 'gift')}" if now["gifts"]
             else "No gifts recorded")
    out = {"type": ATYPE, "result": text, "label": label, "nav": NAV,
           "range": {"from": first.isoformat(), "to": last.isoformat()},
           "total_cents": now["total_cents"], "gifts": now["gifts"], "givers": now["givers"],
           "no_giver_cents": now["no_giver_cents"], "funds": funds[:FUNDS_MAX], "days": days}
    if len(funds) > FUNDS_MAX:
        out["more_funds"] = {"funds": len(funds) - FUNDS_MAX,
                             "total_cents": sum(f["total_cents"] for f in funds[FUNDS_MAX:])}
    if ways is not None:
        out["ways"] = ways[:10]
    if before is not None:
        out["before"] = {"from": read_from.isoformat(), "to": (first - timedelta(days=1)).isoformat(), **before}
    return out


async def handle_giving_summary(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(summary_sync, biz, action or {})
