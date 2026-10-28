"""church_money_levels.py — Money going out: the more it is, the more people say yes.

Kevin, 2026-10-23 ("Church Areas and Keys", moving money: approval levels
by amount) and 2026-10-26 ("go with your picks"): under $500 the treasurer
alone; $500 to $2,500 the pastor too; over $2,500 a board member too.
Kevin, 2026-10-28: "change check requests yourself". So Check requests
(church_checks.py), the church's money going out, asks these for every
amount, in place of its one limit and a Giving keeper's yes above it.

    the STEPS ..... treasurer: the treasurer's role (church_checks.treasurer:
                    the owner, admins, the accountant, a Giving & money
                    login), from a login that may act on check requests
                    pastor: a login whose email is one of the church's people
                    holding the senior role (church_roles' "senior" job, the
                    Lead or Senior Pastor; an executive or associate pastor
                    isn't one, Kevin 2026-10-27)
                    board: a login on one of the church's boards (Board &
                    minutes: an active member row with that login, on a
                    board that isn't archived)
                    The pastor and a board member give their yes whatever
                    their login's level: it's who they are, not their seat
    what COUNTS ... a request's own amount and every other request to the
                    same payee within 7 days of it (any but a declined one):
                    $400 on Monday and $400 on Tuesday to the same camp is
                    $800, and the pastor says yes too
    the BUDGET .... a request that takes its ministry past this year's
                    budget needs a board member too, whatever its size
    the RULES ..... each step is a different person; whoever asked never
                    counts; nothing is approved by waiting. A login that can
                    give two steps gives the scarcer one (the pastor's, then
                    a board member's, then the treasurer's). Changing what a
                    request asks (amount, ministry, payee) takes its yeses
                    back

The yeses are kept in church_check_approvals
(supabase/APPLY-2026-10-28-church-money-levels.sql). Switched by
CHURCH_MONEY_LEVELS: on (the default, and what any other value reads as) |
off, which goes back to the one limit and the Giving keeper above it.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger(__name__)

STEPS = ("treasurer", "pastor", "board")
FILL_ORDER = ("pastor", "board", "treasurer")      # the scarcer yes first
WORD = {"treasurer": "the treasurer", "pastor": "the pastor", "board": "a board member"}
PASTOR_FROM_CENTS = 50_000      # $500 and up: the pastor too
BOARD_OVER_CENTS = 250_000      # over $2,500: a board member too
SPLIT_DAYS = 7

APPROVAL_FIELDS = "request_id,step,user_id,created_at"


def mode() -> str:
    """on unless it says off: a typo keeps the levels, never drops them."""
    m = (os.environ.get("CHURCH_MONEY_LEVELS") or "on").strip().lower()
    return "off" if m == "off" else "on"


def on() -> bool:
    return mode() == "on"


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _at(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one is a 503, never "nobody"."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Who says yes couldn't be read just now. Try again.")
    return rows


def _ids(values: Iterable[Any]) -> str:
    return ",".join(_q(v) for v in sorted({str(v) for v in values if v}))


def usd(cents: Any) -> str:
    c = int(cents or 0)
    return f"${c // 100:,}" if c % 100 == 0 else f"${c / 100:,.2f}"


def words(steps: Iterable[str]) -> str:
    """"the pastor", "the pastor and a board member"."""
    said = [WORD[s] for s in steps]
    return " and ".join(said) if len(said) < 3 else f"{', '.join(said[:-1])} and {said[-1]}"


def required(counted_cents: int, *, over_budget: bool = False) -> List[str]:
    """The steps a request needs, by what it counts as."""
    steps = ["treasurer"]
    if counted_cents >= PASTOR_FROM_CENTS:
        steps.append("pastor")
    if counted_cents > BOARD_OVER_CENTS or over_budget:
        steps.append("board")
    return steps


# ─── Who can give each step ───────────────────────────────────────────

def _seats(me: Dict[str, Any]) -> Dict[str, str]:
    """user id → sign-in email, for every login on the church (the owner's
    too, when it can be read)."""
    if "_seats" not in me:
        import church_checks
        biz = me["biz"]
        rows = _need(f"/business_users?business_id=eq.{_q(biz['id'])}&status=eq.active"
                     "&select=user_id,invited_email&limit=500")
        out = {str(r["user_id"]): (r.get("invited_email") or "").strip().lower() for r in rows if r.get("user_id")}
        owner = str(biz.get("owner_id") or "")
        if owner:
            out[owner] = (church_checks._church_owner_email(owner) or "").strip().lower()
        me["_seats"] = out
    return me["_seats"]


def pastors(me: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The church's people who hold the senior role: their name, and the
    login that is theirs (by email), if any."""
    if "_pastors" in me:
        return me["_pastors"]
    b = _q(me["biz"]["id"])
    out: List[Dict[str, Any]] = []
    defs = _need(f"/church_role_defs?business_id=eq.{b}&job=eq.senior&status=eq.active&select=key&limit=20")
    keys = _ids(d.get("key") for d in defs)
    holders = _need(f"/church_leader_roles?business_id=eq.{b}&role=in.({keys})&status=eq.active"
                    "&select=contact_id&limit=50") if keys else []
    ids = _ids(h.get("contact_id") for h in holders)
    if ids:
        logins: Dict[str, List[str]] = {}
        for uid, email in _seats(me).items():
            if "@" in email:
                logins.setdefault(email, []).append(uid)
        for p in _need(f"/contacts?business_id=eq.{b}&id=in.({ids})&select=id,name,email&limit=50"):
            email = (p.get("email") or "").strip().lower()
            out.append({"name": _plain(p.get("name")) or "The pastor", "email": email,
                        "logins": sorted(logins.get(email, [])) if "@" in email else []})
    out.sort(key=lambda p: p["name"].lower())
    me["_pastors"] = out
    return out


def board(me: Dict[str, Any]) -> Dict[str, str]:
    """user id → name, for each login on one of the church's boards."""
    if "_board" in me:
        return me["_board"]
    b = _q(me["biz"]["id"])
    out: Dict[str, str] = {}
    boards = _ids(x.get("id") for x in _need(f"/church_boards?business_id=eq.{b}&archived=eq.false&select=id&limit=100"))
    rows = _need(f"/church_board_members?business_id=eq.{b}&board_id=in.({boards})&active=eq.true"
                 "&user_id=not.is.null&select=user_id,contact_id,name&limit=500") if boards else []
    ids = _ids(r.get("contact_id") for r in rows)
    names = {str(c["id"]): _plain(c.get("name")) for c in
             _need(f"/contacts?business_id=eq.{b}&id=in.({ids})&select=id,name&limit=500")} if ids else {}
    for r in rows:
        uid = str(r["user_id"])
        out.setdefault(uid, names.get(str(r.get("contact_id") or "")) or _plain(r.get("name")) or "A board member")
    me["_board"] = out
    return out


def steps_of(me: Dict[str, Any]) -> Set[str]:
    """The steps this login can give here."""
    if "_steps" in me:
        return me["_steps"]
    out: Set[str] = set()
    if me.get("writer"):
        out.add("treasurer")
    email = (getattr(me["user"], "email", "") or "").strip().lower()
    if any(me["uid"] in p["logins"] or ("@" in email and p["email"] == email) for p in pastors(me)):
        out.add("pastor")
    if me["uid"] in board(me):
        out.add("board")
    me["_steps"] = out
    return out


def approver(me: Dict[str, Any]) -> bool:
    """A login that isn't the treasurer's but can say yes: the pastor or a
    board member. The page opens to them for that."""
    return on() and bool(steps_of(me) & {"pastor", "board"})


def page_view(me: Dict[str, Any]) -> Dict[str, Any]:
    """The levels, who can give each step, and what keeps a step from
    being given at all."""
    if not on():
        return {"on": False}
    ps = pastors(me)
    with_login = [p["name"] for p in ps if p["logins"]]
    gaps: List[str] = []
    if not ps:
        gaps.append(f"No one holds the senior pastor's role yet, so {usd(PASTOR_FROM_CENTS)} and up can't be "
                    "approved. Name who does on the Lead tab.")
    elif not with_login:
        gaps.append(f"{ps[0]['name']}, the pastor, has no login here by their email, so {usd(PASTOR_FROM_CENTS)} "
                    "and up can't be approved. Give them one in Logins & areas.")
    bd = board(me)
    if not bd:
        gaps.append(f"No board member has a login, so over {usd(BOARD_OVER_CENTS)}, or past a ministry's budget, "
                    "can't be approved. Add one in Board & minutes.")
    return {"on": True, "pastor_from_cents": PASTOR_FROM_CENTS, "board_over_cents": BOARD_OVER_CENTS,
            "split_days": SPLIT_DAYS, "pastors": with_login, "board": sorted(set(bd.values()), key=str.lower),
            "gaps": gaps, "mine": [s for s in STEPS if s in steps_of(me)]}


# ─── What a request counts as, and needs ──────────────────────────────

def payee_keys(r: Dict[str, Any]) -> Set[str]:
    """Who a request pays, as keys two requests to the same payee share:
    the name paid, and the person when it's them."""
    payee, asker = _plain(r.get("payee")).lower(), _plain(r.get("asker_name")).lower()
    keys = {f"n:{payee or asker}"} if (payee or asker) else set()
    if r.get("contact_id") and (not payee or payee == asker):
        keys.add(f"c:{r['contact_id']}")
    return keys


def counted(row: Dict[str, Any], others: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    """(what a request counts as, the part of it that is other requests to
    the same payee within SPLIT_DAYS of it, declined ones aside)."""
    own = int(row.get("amount_cents") or 0)
    at, keys = _at(row.get("created_at")), payee_keys(row)
    if not at or not keys:
        return own, 0
    more = 0
    for o in others:
        if str(o.get("id")) == str(row.get("id")) or o.get("status") == "declined":
            continue
        t = _at(o.get("created_at"))
        if t and abs(t - at) <= timedelta(days=SPLIT_DAYS) and keys & payee_keys(o):
            more += int(o.get("amount_cents") or 0)
    return own + more, more


def over_budget(row: Dict[str, Any], lines: Dict[str, Dict[str, Any]]) -> bool:
    """Whether a request waiting for its yes takes its ministry past this
    year's budget (spent, and approved not paid, and this). No budget set
    is never over."""
    line = lines.get(_plain(row.get("ministry")).lower())
    if not line or not line.get("budget_cents"):
        return False
    used = int(line.get("spent_cents") or 0) + int(line.get("committed_cents") or 0)
    return used + int(row.get("amount_cents") or 0) > int(line["budget_cents"])


def approvals(biz_id: str, request_ids: Iterable[Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    ids = sorted({str(i) for i in request_ids if i})
    for i in range(0, len(ids), 100):
        chunk = ",".join(_q(x) for x in ids[i:i + 100])
        for a in _need(f"/church_check_approvals?business_id=eq.{_q(biz_id)}&request_id=in.({chunk})"
                       f"&select={APPROVAL_FIELDS}&order=created_at.asc&limit=1000"):
            out.setdefault(str(a["request_id"]), []).append(a)
    return out


def _asker_emails(biz_id: str, rows: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    ids = _ids(r.get("contact_id") for r in rows)
    if not ids:
        return {}
    return {str(c["id"]): (c.get("email") or "").strip().lower() for c in
            _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({ids})&select=id,email&limit=500")}


def asked_it(me: Dict[str, Any], row: Dict[str, Any], emails: Dict[str, str]) -> bool:
    """Whether this login is who asked: the office login that added it, or
    the person whose request it is (by their email)."""
    if row.get("created_by") and str(row["created_by"]) == me["uid"]:
        return True
    mine = (getattr(me["user"], "email", "") or "").strip().lower()
    theirs = emails.get(str(row.get("contact_id") or ""), "")
    return "@" in mine and mine == theirs


def context(me: Dict[str, Any], rows: List[Dict[str, Any]], lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the levels read once for a set of requests: their yeses, the
    askers' emails, each ministry's year, and the requests the splits are
    summed over (`rows`: the page's open and the year's done)."""
    biz = str(me["biz"]["id"])
    new = [r for r in rows if r.get("status") == "new"]
    return {"rows": rows, "lines": {_plain(x.get("name")).lower(): x for x in lines},
            "approvals": approvals(biz, [r.get("id") for r in rows]), "emails": _asker_emails(biz, new)}


def _names(me: Dict[str, Any], uids: Iterable[str]) -> Dict[str, str]:
    import church_checks
    want = {str(u) for u in uids if u}
    names = church_checks._seat_names(me["biz"], want)
    bd = board(me)
    for p in pastors(me):
        for uid in p["logins"]:
            if uid in want:
                names[uid] = p["name"]
    return {u: bd.get(u) or names.get(u) or "Someone" for u in want}


def of(me: Dict[str, Any], row: Dict[str, Any], ctx: Dict[str, Any],
       names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One request's levels for this login: the steps it needs, the yeses it
    has, what's missing, and the step this login would give now (or why
    not)."""
    have = ctx["approvals"].get(str(row["id"]), [])
    names = names if names is not None else _names(me, [a.get("user_id") for a in have])
    given = [{"step": a["step"], "by": names.get(str(a.get("user_id")), "Someone"), "at": a.get("created_at")}
             for a in have]
    if row.get("status") != "new":
        return {"needs": [a["step"] for a in have], "have": given, "missing": [], "counted_cents": None,
                "others_cents": 0, "over_budget": False, "mine": None, "why_not": None}
    total, more = counted(row, ctx["rows"])
    over = over_budget(row, ctx["lines"])
    needs = required(total, over_budget=over)
    filled = {a["step"] for a in have}
    missing = [s for s in needs if s not in filled]
    mine, why = None, None
    if asked_it(me, row, ctx["emails"]):
        why = "You asked for this one, so your yes doesn't count: someone else gives it."
    elif any(str(a.get("user_id")) == me["uid"] for a in have):
        why = f"Your yes is in. It waits on {words(missing)}." if missing else "Your yes is in."
    else:
        mine = next((s for s in FILL_ORDER if s in missing and s in steps_of(me)), None)
        if not mine:
            why = f"This one waits on {words(missing)}."
    return {"needs": needs, "have": given, "missing": missing, "counted_cents": total, "others_cents": more,
            "over_budget": over, "mine": mine, "why_not": why}


def annotate(me: Dict[str, Any], views: List[Dict[str, Any]], rows: List[Dict[str, Any]],
             lines: List[Dict[str, Any]], all_rows: Optional[List[Dict[str, Any]]] = None) -> None:
    """Puts `levels` on each shown request (the page, or one request after
    an action): `all_rows` are the requests the splits sum over."""
    if not on():
        return
    ctx = context(me, all_rows if all_rows is not None else rows, lines)
    names = _names(me, [a.get("user_id") for got in ctx["approvals"].values() for a in got])
    by_id = {str(r["id"]): r for r in rows}
    for v in views:
        row = by_id.get(v["id"])
        if row:
            v["levels"] = of(me, row, ctx, names)


# ─── Saying yes ───────────────────────────────────────────────────────

def _later(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _tell(biz: Dict[str, Any], to: Set[str], title: str, body: str, emails: Dict[str, str], tag: str) -> None:
    """A phone alert and an email to each person who can give a step still
    missing; one that fails never stops the rest."""
    def run() -> None:
        import asyncio
        import push_notifications
        for uid in sorted(to):
            try:
                push_notifications.send_to_user(uid, title=title, body=body[:160], nav="operate:checks",
                                                tag=tag, business_id=str(biz["id"]))
            except Exception:
                logger.warning("church money levels: a phone alert failed", exc_info=True)
            email = emails.get(uid, "")
            if "@" not in email:
                continue
            try:
                import app_base
                import email_sender
                asyncio.run(email_sender.send_via_resend(
                    to_email=email, to_name=None,
                    from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                    from_name=biz.get("name") or "Your church", subject=title[:150], reply_to=None,
                    business_id=str(biz["id"]), idempotency_key=f"{tag}-{uid}",
                    body=f"{title}\n\n{body}\n\nSay yes or no here:\n{app_base.app_base_url()}/?nav=operate:checks\n"))
            except Exception:
                logger.warning("church money levels: an email failed", exc_info=True)
    _later(run)


def tell_next(me: Dict[str, Any], row: Dict[str, Any], missing: List[str], have: List[Dict[str, Any]],
              emails: Dict[str, str]) -> int:
    """Tell whoever can give the pastor's or a board member's yes that a
    request waits on them (never whoever asked, or said yes already)."""
    seats = _seats(me)
    asker = emails.get(str(row.get("contact_id") or ""), "")
    to: Set[str] = set()
    if "pastor" in missing:
        to |= {uid for p in pastors(me) for uid in p["logins"]}
    if "board" in missing:
        to |= set(board(me))
    to -= {str(a.get("user_id")) for a in have}
    to = {u for u in to if u != str(row.get("created_by") or "") and not ("@" in asker and seats.get(u) == asker)}
    if not to:
        return 0
    steps = [s for s in missing if s != "treasurer"]
    paid_to = _plain(row.get("payee") or row.get("asker_name")) or "someone"
    said = [WORD[s] for s in STEPS if any(a.get("step") == s for a in have)]
    title = f"A check request needs {words(steps)}: {usd(row.get('amount_cents'))}"
    body = (f"{usd(row.get('amount_cents'))} for {_plain(row.get('ministry'))} ({_plain(row.get('about'))}), "
            f"paid to {paid_to}. Yes so far: {', '.join(said) or 'none'}. It waits on {words(missing)}.")
    _tell(me["biz"], to, title, body, seats, f"check-levels-{row['id']}-{len(have)}")
    return len(to)


def check(me: Dict[str, Any], row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(what the levels read, and one request's levels) for an action on it."""
    import church_checks as cc
    biz = str(me["biz"]["id"])
    rows = cc._rows(biz)
    if not any(str(r["id"]) == str(row["id"]) for r in rows):
        rows.append(row)
    ctx = context(me, rows, cc.budgets(me, cc.settings(biz), rows)["lines"])
    return ctx, of(me, row, ctx)


def approve(me: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """Give this login's yes to a request waiting for one, at the step it
    gives; once every step it needs has its yes, the request is approved."""
    import church_checks as cc
    biz = str(me["biz"]["id"])
    rid = str(row["id"])
    ctx, lv = check(me, row)
    step = lv["mine"]
    if not step:
        raise HTTPException(403, {"code": "not_your_step", "missing": lv["missing"],
                                  "message": lv["why_not"] or "This one isn't waiting on you."})
    saved = sb_clients.sb_post_as_service("/church_check_approvals", {
        "business_id": biz, "request_id": rid, "step": step, "user_id": me["uid"]})
    if not isinstance(saved, list) or not saved:
        now = approvals(biz, [rid]).get(rid, [])
        if any(a.get("step") == step or str(a.get("user_id")) == me["uid"] for a in now):
            raise HTTPException(409, "Someone said yes to this one at the same moment. Open it again.")
        raise HTTPException(503, "Your yes didn't save. Try again.")
    have = approvals(biz, [rid]).get(rid, [])
    missing = [x for x in lv["needs"] if x not in {a.get("step") for a in have}]
    if missing:
        told = tell_next(me, row, missing, have, ctx["emails"])
        return {"request": cc._one(me, cc.resolve(me, rid)), "approved": False, "step": step,
                "missing": missing, "told": told}
    try:
        done = cc._patch(me, row, {"status": "approved", "decline_reason": None, "decided_by": me["uid"],
                                   "decided_at": cc._iso(cc._now())}, was="new")
    except HTTPException as e:
        if e.status_code != 409:
            raise
        done = cc.resolve(me, rid)      # the last yes landed twice at once: it's approved either way
    return {"request": cc._one(me, done), "approved": done.get("status") == "approved", "step": step,
            "missing": [], "told": 0}


def take_back_yeses(biz_id: str, rid: str) -> bool:
    """A request that changed what it asks loses the yeses it had."""
    return bool(sb_clients.sb_delete_as_service(
        f"/church_check_approvals?request_id=eq.{_q(rid)}&business_id=eq.{_q(biz_id)}"))
