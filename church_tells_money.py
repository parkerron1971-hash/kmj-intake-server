"""church_tells_money.py — the treasurer hears about the church's money
hand-offs: a count that just closed, and a new pay-back request.

Love City's connection map (2026-11-21) found two money hand-offs that
worked on the screen but never told the treasurer:

  * two counters close a service's count, and the treasurer only learns it
    by opening Giving: the count waits to be matched to the bank deposit;
  * a volunteer asks to be paid back from the member app (or the office
    files one), and nobody is told it waits for a yes. church_money_levels
    tells the pastor and a board member, but only after a first yes
    (tell_next); the first yes itself was never asked for.

Two finders for church_tells (its sweep tells the people once, groups,
waits out quiet hours and never tells the person who did it):

  count_closed   giving_counts closed in the last LOOK_BACK_DAYS, not yet
                 matched to a deposit (every gift that rides a bank deposit
                 already in gift_deposit_items) -> duty "deposit"; never
                 whoever closed it
  payback_asked  church_check_requests still "new", made in the last
                 LOOK_BACK_DAYS, with no decision and no yes yet (a yes
                 means someone is on it, and tell_next takes it from there)
                 -> duty "pay"; never the login who filed it

A lock screen never carries an amount, the receipt or what it was for:
the service and its day, or the asker's first name and the ministry. A read
that fails is [] (the next sweep tries again); a guard read that fails (has
it been matched? has anyone said yes?) holds the item back rather than tell
something that may be done.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

import church_tells as ct
import sb_clients

LOOK_BACK_DAYS = 3
MAX_ROWS = 50
CHUNK = 100

COUNT_FIELDS = "id,name,service_date,status,closed_at,closed_by"
REQUEST_FIELDS = "id,contact_id,asker_name,ministry,source,status,created_by,created_at,decided_by,decided_at"


def _strict(path: str) -> Optional[List[Dict[str, Any]]]:
    """A service read that says when it failed (None), for the guard reads."""
    try:
        got = sb_clients.sb_get_as_service(path)
    except Exception:  # noqa: BLE001
        return None
    return got if isinstance(got, list) else None


def _chunks(ids: Iterable[Any]) -> List[List[str]]:
    want = sorted({str(i) for i in ids if i})
    return [want[i:i + CHUNK] for i in range(0, len(want), CHUNK)]


def _in(ids: List[str]) -> str:
    return "in.(" + ",".join(ct.q(x) for x in ids) + ")"


def _plain(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _day(v: Any) -> str:
    """'2026-11-22' -> 'Nov 22'; '' when it isn't a date."""
    try:
        d = date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return ""
    return f"{d.strftime('%b')} {d.day}"


# ─── A count closed ───────────────────────────────────────────────────

def _deposit_gifts(biz: str, count_ids: List[str]) -> Optional[Dict[str, List[str]]]:
    """count id -> the gifts in it that ride a bank deposit (cash, checks,
    Subsplash payouts, transfers; card gifts ride Stripe's payouts). None
    when they can't be read."""
    from giving_deposits import gift_kind
    out: Dict[str, List[str]] = {c: [] for c in count_ids}
    for part in _chunks(count_ids):
        got = _strict(f"/invoices?business_id=eq.{ct.q(biz)}&is_gift=eq.true&giving_count_id={_in(part)}"
                      "&select=id,giving_count_id,payment_method,status&limit=1000")
        if got is None:
            return None
        for g in got:
            if g.get("status") and g.get("status") != "paid":
                continue
            if gift_kind(g.get("payment_method")) is None:
                continue
            out.setdefault(str(g.get("giving_count_id")), []).append(str(g["id"]))
    return out


def _matched(biz: str, gift_ids: List[str]) -> Optional[set]:
    """The gifts already in a deposit match. None when it can't be read."""
    seen: set = set()
    for part in _chunks(gift_ids):
        got = _strict(f"/gift_deposit_items?business_id=eq.{ct.q(biz)}&side=eq.gift&ref={_in(part)}"
                      "&select=ref&limit=1000")
        if got is None:
            return None
        seen |= {str(r.get("ref")) for r in got}
    return seen


def count_closed(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    """A count closed in the last few days that still waits for its deposit
    -> whoever does the Sunday deposit."""
    biz = str(church["id"])
    counts = ct.rows(f"/giving_counts?business_id=eq.{ct.q(biz)}&status=eq.closed"
                     f"&closed_at=gte.{ct.since(now, LOOK_BACK_DAYS)}"
                     f"&select={COUNT_FIELDS}&order=closed_at.asc&limit={MAX_ROWS}")
    counts = [c for c in counts if c.get("id") and c.get("status") == "closed"]
    if not counts:
        return []
    gifts = _deposit_gifts(biz, [str(c["id"]) for c in counts])
    if gifts is None:
        return []
    matched = _matched(biz, [g for ids in gifts.values() for g in ids])
    if matched is None:
        return []
    out: List[ct.Item] = []
    for c in counts:
        mine = gifts.get(str(c["id"])) or []
        # Nothing rides a bank deposit (no gifts, or card gifts only), or
        # every one of them is matched already: nothing to tell.
        if not mine or all(g in matched for g in mine):
            continue
        day = _day(c.get("service_date"))
        name = _plain(c.get("name"), 60) or "The service"
        out.append(ct.Item(
            key=f"count:{c['id']}",
            title=f"{day} count is closed" if day else "A count is closed",
            line=f"{name}{', ' + day if day else ''}: match it to the bank deposit when it lands.",
            duty="deposit",
            actor=str(c["closed_by"]) if c.get("closed_by") else None))
    return out


# ─── A pay-back asked for ─────────────────────────────────────────────

def _first(name: Any) -> str:
    parts = _plain(name, 120).split(" ")
    return parts[0] if parts and parts[0] else ""


def _people(biz: str, ids: List[str]) -> Dict[str, Dict[str, str]]:
    """contact id -> {name, email}; {} for any that can't be read."""
    out: Dict[str, Dict[str, str]] = {}
    for part in _chunks(ids):
        for r in ct.rows(f"/contacts?business_id=eq.{ct.q(biz)}&id={_in(part)}&select=id,name,email&limit={CHUNK}"):
            out[str(r.get("id"))] = {"name": str(r.get("name") or ""),
                                     "email": str(r.get("email") or "").strip().lower()}
    return out


def _logins_by_email(church: Dict[str, Any]) -> Dict[str, str]:
    """sign-in email -> login, for the church's office logins (the owner too
    when it can be read), so a member who is also a login isn't told about
    their own request."""
    biz = str(church["id"])
    out: Dict[str, str] = {}
    for r in ct.rows(f"/business_users?business_id=eq.{ct.q(biz)}&status=eq.active"
                     "&select=user_id,invited_email&limit=500"):
        email = str(r.get("invited_email") or "").strip().lower()
        if email and r.get("user_id"):
            out[email] = str(r["user_id"])
    owner = str(church.get("owner_id") or "")
    if owner:
        try:
            import church_checks
            email = (church_checks._church_owner_email(owner) or "").strip().lower()
        except Exception:  # noqa: BLE001
            email = ""
        if email:
            out[email] = owner
    return out


def payback_asked(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    """A new pay-back or check request nobody has said yes or no to ->
    whoever does bills and pay-backs."""
    biz = str(church["id"])
    reqs = ct.rows(f"/church_check_requests?business_id=eq.{ct.q(biz)}&status=eq.new"
                   f"&created_at=gte.{ct.since(now, LOOK_BACK_DAYS)}&decided_at=is.null"
                   f"&select={REQUEST_FIELDS}&order=created_at.asc&limit={MAX_ROWS}")
    reqs = [r for r in reqs if r.get("id") and r.get("status") == "new" and not r.get("decided_by")
            and not r.get("decided_at")]
    if not reqs:
        return []
    # A yes already given (the money levels): someone is on it, and
    # church_money_levels.tell_next asks for the next yes.
    said = set()
    for part in _chunks(r["id"] for r in reqs):
        got = _strict(f"/church_check_approvals?business_id=eq.{ct.q(biz)}&request_id={_in(part)}"
                      "&select=request_id&limit=1000")
        if got is None:
            return []
        said |= {str(a.get("request_id")) for a in got}
    reqs = [r for r in reqs if str(r["id"]) not in said]
    if not reqs:
        return []
    people = _people(biz, [r.get("contact_id") for r in reqs])
    logins = _logins_by_email(church) if any(r.get("source") == "app" for r in reqs) else {}
    out: List[ct.Item] = []
    for r in reqs:
        person = people.get(str(r.get("contact_id") or "")) or {}
        first = _first(person.get("name") or r.get("asker_name"))
        ministry = _plain(r.get("ministry"), 40)
        for_what = f" for {ministry}" if ministry else ""
        if r.get("source") == "office" and r.get("created_by"):
            actor: Optional[str] = str(r["created_by"])
        else:
            actor = logins.get(person.get("email") or "") if person.get("email") else None
        if first:
            title = f"{first} asked to be paid back"
            line = f"{first} asked to be paid back{for_what}. It's waiting for your yes or no."
        else:
            title = "A check request is waiting for you"
            line = f"A new check request{for_what} is waiting for your yes or no."
        out.append(ct.Item(key=f"payback:{r['id']}", title=title, line=line, duty="pay", actor=actor))
    return out
