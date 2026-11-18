"""church_money_ticks.py — giving as its own tick, the server piece.

Kevin, 2026-11-18 ("One sheet per person", step three): "yes build with C."
Giving stops being "an Admin login or nothing". A person's sheet carries a
Giving block: See, Work or Lead, with two more ticks beside it, "who gave"
(the gift records, statements, pledges and counts: everything that names a
giver) and "bank and payouts".

    WHO GIVES IT ... the OWNER alone, with the password. An Admin, or
                     whoever sets up jobs and people's sheets, may only ASK:
                     no password, nothing opens, the owner is told, and the
                     owner answers yes (with the password) or no. Nobody
                     asks for themselves. An ask waits seven days and the
                     owner is reminded once after 48 hours
    WHO HOLDS IT ... a Member or Manager login at See, Work or Lead; a
                     Viewer login only See. An Admin login sees and works
                     giving already, so the only thing the owner adds to one
                     is "bank and payouts"
    BANK & PAYOUTS . the holder sees and works the bank, the charges and the
                     payouts, and refunds freely (every refund is recorded).
                     Connecting or disconnecting Stripe or a bank, and where
                     payouts land, stay the owner's alone
    THE SWITCH ..... CHURCH_MONEY_TICKS = off (the default: nothing here is
                     read by any door, today's rules exactly) | owner (the
                     platform owner's own church) | on
    THE RULES ...... church_money_gate asks holder() and nothing else here.
                     The rows live in two server-only tables
                     (supabase/APPLY-2026-11-18-church-money-holders.sql);
                     until that file is applied every read answers "no tick"
                     (church_money_holders), so this behaves as off

  GET  /church/money-asks?business_id=        the owner: every ask waiting;
                                              anyone else: the ones they sent
  POST /church/money-asks/{id}/answer         {yes: true|false}, the owner;
                                              a yes asks for the password
  POST /church/money-asks/{id}/withdraw       whoever asked, or the owner
  POST /church/alerts/read                    {business_id, ids?}: mark the
                                              alerts this login may see as
                                              read (a login that only Sees
                                              giving can't change an alert
                                              row itself)

The sheet's own Giving block is read and saved through church_sheet
(`money` on GET and PUT /church/sheet): block(), plan() and apply() below.
Nothing here grants by itself: a grant is church_money_grant, which raises
unless the one acting is businesses.owner_id.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

import church_money_holders as mh
import sb_clients
from auth_supabase import UserSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

LEVELS = mh.LEVELS
LEVEL_LABEL = {"see": "See", "work": "Work", "lead": "Lead"}
LEVEL_MEANS = {
    "see": "Reads the books, the bills and what is owed. Changes nothing.",
    "work": "Enters and corrects: bills, checks, the count, the books.",
    "lead": "Everything Work does, and reopens a closed count.",
}
_RANK = {None: 0, "see": 1, "work": 2, "lead": 3}
ASK_DAYS = 7
REMIND_HOURS = 48

NOT_ON = "Giving as its own switch isn't on for this church yet."
OWNER_ONLY_GRANTS = ("Only the owner gives giving access. You can ask: nothing opens until the owner says yes "
                     "with the password.")
OWNER_HAS_IT = "The owner sees and works all of giving."
ADMIN_HAS_IT = ("An Admin login sees and works giving already. The one thing the owner adds to it is the bank "
                "and payouts.")
VIEWER_SEES = ("A Viewer login can only see giving. Make them a Member or Manager login to let them work it.")
NOT_A_MONEY_LEVEL = "Pick Off, See, Work or Lead for giving."
LOWER_IS_ADMINS = "Only the owner or an Admin lowers someone's giving access."
ALREADY_WAITING = "There is already a request waiting for the owner about {name}."
ASK_503 = "That request didn't send. Nothing changed. Try again."
MONEY_503 = "Giving didn't save. Try that part again."
EXPIRED = "That request ran out before it was answered. Ask them to send it again."
NOT_WAITING = "That request isn't waiting any more."
ONLY_OWNER_ANSWERS = "Only the owner answers a request for giving access."


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_MONEY_TICKS") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_for(business_id: Any) -> bool:
    """Whether the giving tick is switched on for this church. Off reads
    nothing. `owner`: the platform owner's own church only. A check that
    fails is a no."""
    m = mode()
    if m == "on":
        return bool(business_id)
    if m == "owner":
        try:
            import member_asks
            return bool(member_asks.platform_church(business_id))
        except Exception:  # noqa: BLE001 — couldn't tell: closed
            return False
    return False


def holder(business_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
    """The tick this login holds here, or None. The ONE read the money gate
    makes. None when the switch is off (nothing is read), when there is no
    row, when the seat it was given to is gone, or when a read failed."""
    if not open_for(business_id):
        return None
    return mh.money_holder(business_id, user_id)


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(at: _dt.datetime) -> str:
    return at.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def words(tick: Optional[Dict[str, Any]]) -> str:
    """A tick in the sheet's words: "Work, with who gave and the bank"."""
    if not tick or tick.get("level") not in LEVELS:
        return "off"
    extra = [w for w, on in (("who gave", tick.get("who_gave")), ("the bank and payouts", tick.get("bank"))) if on]
    return LEVEL_LABEL[tick["level"]] + (", with " + " and ".join(extra) if extra else "")


def _rpc(name: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    got = sb_clients.sb_post_as_service(f"/rpc/{name}", body, redact=True)
    return got if isinstance(got, dict) else None


def _forget(business_id: Any, user_id: Any) -> None:
    try:
        import chief_areas
        import church_areas
        chief_areas.forget(business_id)
        church_areas._forget(str(business_id), str(user_id))
    except Exception:  # noqa: BLE001 — Chief reads the new sheet within the minute either way
        pass


# ─── The sheet's Giving block ─────────────────────────────────────────

def _pending(ch: Any, business_id: str, target: str) -> Optional[Dict[str, Any]]:
    ask = mh.open_ask(business_id, target)
    if not ask:
        return None
    by = str(ask.get("asked_by") or "")
    return {"id": ask.get("id"), "asked_by": by, "asked_by_name": ch.login_name(by) if by else "",
            "asked_at": ask.get("asked_at"), "expires_at": ask.get("expires_at"), "wants": ask["wants"],
            "wants_words": words(ask["wants"])}


def block(business: Dict[str, Any], ch: Any, st: Dict[str, Any], target: str) -> Optional[Dict[str, Any]]:
    """The Giving block of one person's sheet for one viewer, or None while
    the switch is off for this church (the app then shows nothing new)."""
    biz = str(business.get("id") or "")
    if not open_for(biz):
        return None
    trole, ed = st["target_role"], st["editor"]
    if trole == "owner":
        return {"level": "lead", "who_gave": True, "bank": True, "pending": None, "can": None, "why": OWNER_HAS_IT,
                "words": "everything", "levels": []}
    held = mh.money_holder(biz, target)
    pending = _pending(ch, biz, target)
    can: Optional[str] = None
    why = ""
    if not st["can_edit"]:
        why = st.get("why_not") or ""
    elif ed == "owner":
        can = "grant"
    elif ed in ("admin", "holder") and trole != "admin":
        can, why = "ask", OWNER_ONLY_GRANTS
    if trole == "admin":
        bank = bool(held and held["bank"])
        return {"level": "lead", "who_gave": True, "bank": bank, "pending": pending, "can": can,
                "why": ADMIN_HAS_IT, "words": words({"level": "lead", "who_gave": True, "bank": bank}),
                "levels": []}
    viewer_seat = trole == "viewer"
    levels = [{"key": k, "label": LEVEL_LABEL[k], "means": LEVEL_MEANS[k],
               "allowed": not (viewer_seat and k != "see"), "why": VIEWER_SEES if viewer_seat and k != "see" else ""}
              for k in LEVELS]
    return {"level": held["level"] if held else None, "who_gave": bool(held and held["who_gave"]),
            "bank": bool(held and held["bank"]), "pending": pending, "can": can, "why": why,
            "words": words(held), "levels": levels}


# ─── Changing it, as part of a sheet's save ───────────────────────────

def plan(business: Dict[str, Any], ch: Any, st: Dict[str, Any], viewer: str, target: str, body: Dict[str, Any],
         level_after: str) -> Optional[Dict[str, Any]]:
    """What a sheet's save would do to this person's giving, checked before
    anything is written; None when the save doesn't touch it.

    {kind, wants, now, more, first, said}:
      kind  "grant" — the owner's own change (church_money_grant, his id)
            "lower" — an Admin taking some of it away (never adding)
            "ask"   — an Admin or a holder asking the owner for more
      more  the login would end with more than it has: a grant with `more`
            is what asks for the password; an ask never does
      first written before the level (a change that only takes away), so a
            save that fails part way leaves the login with less, never more
    """
    if "money" not in body or body.get("money") is None:
        return None
    biz = str(business.get("id") or "")
    if not open_for(biz):
        raise HTTPException(400, NOT_ON)
    raw = body.get("money")
    if not isinstance(raw, dict):
        raise HTTPException(400, NOT_A_MONEY_LEVEL)
    ed, name = st["editor"], ch.login_name(target)
    for k in ("who_gave", "bank"):
        if k in raw and not isinstance(raw.get(k), bool):
            raise HTTPException(400, "Send who gave and the bank as yes or no.")
    level = raw.get("level")
    if level is not None and level not in LEVELS:
        raise HTTPException(400, NOT_A_MONEY_LEVEL)
    if level_after == "admin":
        if ed != "owner":
            raise HTTPException(403, ADMIN_HAS_IT)
        wants: Optional[Dict[str, Any]] = {"level": "lead", "who_gave": True, "bank": raw.get("bank") is True}
        if not wants["bank"]:
            wants = None                    # nothing an Admin doesn't have already: no row is kept
    elif level is None:
        wants = None
    else:
        if level_after == "viewer" and level != "see":
            raise HTTPException(400, VIEWER_SEES)
        wants = {"level": level, "who_gave": raw.get("who_gave") is True, "bank": raw.get("bank") is True}
    now = mh.money_holder(biz, target)
    now_t = {"level": now["level"], "who_gave": now["who_gave"], "bank": now["bank"]} if now else None
    if (wants or None) == (now_t or None):
        return None
    w, n = wants or {}, now_t or {}
    more = bool(wants) and (_RANK[w.get("level")] > _RANK[n.get("level")]
                            or (w.get("who_gave") and not n.get("who_gave"))
                            or (w.get("bank") and not n.get("bank")))
    if ed == "owner":
        kind = "grant"
    elif more:
        if ed not in ("admin", "holder"):
            raise HTTPException(403, OWNER_ONLY_GRANTS)
        if viewer == target:
            raise HTTPException(403, "Nobody asks for their own giving access.")
        if mh.open_ask(biz, target):
            raise HTTPException(409, ALREADY_WAITING.format(name=name))
        kind = "ask"
    elif ed == "admin":
        kind = "lower"
    else:
        raise HTTPException(403, LOWER_IS_ADMINS)
    said = (f"asked the owner for giving: {words(wants)}" if kind == "ask"
            else f"giving: {words(wants)} (was {words(now_t)})")
    return {"kind": kind, "wants": wants, "now": now_t, "more": more, "first": kind != "ask" and not more,
            "said": said, "name": name}


def apply(p: Dict[str, Any], business: Dict[str, Any], viewer: str, viewer_name: str, target: str) -> None:
    """Write one planned change. A write that fails is a 503 (an ask that
    lost a race to another ask, a 409); nothing is half done."""
    biz, wants = str(business["id"]), p["wants"]
    if p["kind"] == "grant":
        out = _rpc("church_money_grant", {
            "p_business": biz, "p_user": target, "p_level": wants["level"] if wants else None,
            "p_who_gave": bool(wants and wants["who_gave"]), "p_bank": bool(wants and wants["bank"]),
            "p_by": viewer})
        if not out or out.get("ok") is not True:
            raise HTTPException(503, MONEY_503)
    elif p["kind"] == "lower":
        path = f"/{mh.HOLDERS}?business_id=eq.{_q(biz)}&user_id=eq.{_q(target)}"
        if wants is None:
            ok = sb_clients.sb_delete_as_service(path)
        else:
            ok = isinstance(sb_clients.sb_patch_as_service(
                path, {"level": wants["level"], "who_gave": wants["who_gave"], "bank": wants["bank"]},
                redact=True), list)
        if not ok:
            raise HTTPException(503, MONEY_503)
    else:
        out = _rpc("church_money_ask", {
            "p_business": biz, "p_user": target, "p_by": viewer, "p_level": wants["level"],
            "p_who_gave": wants["who_gave"], "p_bank": wants["bank"]})
        if not out or out.get("ok") is not True:
            err = sb_clients.last_error() or {}
            if err.get("code") == "23505":
                raise HTTPException(409, ALREADY_WAITING.format(name=p["name"]))
            raise HTTPException(503, ASK_503)
        try:
            import church_job_defs as cj
            cj.tell_owner(business, f"{viewer_name} asks to open giving for {p['name']}"[:150],
                          f"{viewer_name} asked to give {p['name']} giving access at "
                          f"{business.get('name') or 'your church'}: {words(wants)}. Nothing is open. Say yes or no "
                          f"on Logins & areas; the request waits {ASK_DAYS} days.",
                          tag=f"money-ask-{target}")
        except Exception:  # noqa: BLE001 — the ask is saved; the owner also sees it on the page
            logger.warning("money ask: the owner couldn't be told (business %s)", biz[:8])
    _forget(biz, target)


# ─── A login that leaves, or is lowered ───────────────────────────────

def seat_gone(business_id: Any, user_id: Any) -> bool:
    """A login taken off the team keeps no tick and no ask about it. True
    when both were cleared (or the switch is off: nothing to clear)."""
    if mode() == "off" or not mh._id(business_id) or not mh._id(user_id):
        return True
    b, u = _q(str(business_id).lower()), _q(str(user_id).lower())
    gone = sb_clients.sb_delete_as_service(f"/{mh.HOLDERS}?business_id=eq.{b}&user_id=eq.{u}")
    asks = sb_clients.sb_patch_as_service(
        f"/{mh.ASKS}?business_id=eq.{b}&user_id=eq.{u}&status=eq.asked",
        {"status": "withdrawn", "answered_at": _iso(_now())}, redact=True)
    return bool(gone) and isinstance(asks, list)


def seat_lowered_to_viewer(business_id: Any, user_id: Any) -> bool:
    """Before a login becomes a Viewer its tick is lowered to See, so moving
    it back up later never brings Work back without the owner. True when
    that is so (or the switch is off)."""
    if mode() == "off" or not mh._id(business_id) or not mh._id(user_id):
        return True
    got = sb_clients.sb_patch_as_service(
        f"/{mh.HOLDERS}?business_id=eq.{_q(str(business_id).lower())}&user_id=eq.{_q(str(user_id).lower())}"
        "&level=in.(work,lead)", {"level": "see"}, redact=True)
    return isinstance(got, list)


# ─── Who holds the bank, for the doors outside the gate's table ───────

def bank_holders(business_id: Any) -> List[str]:
    """The logins that hold "bank and payouts" here, for a payout alert.
    Empty when the switch is off or the read fails: the owner alone hears."""
    biz = mh._id(business_id)
    if not biz or not open_for(biz):
        return []
    rows = mh._rows(f"/{mh.HOLDERS}?business_id=eq.{_q(biz)}&bank=is.true&select=user_id&limit=20")
    out = []
    for r in rows or []:
        uid = mh._id((r or {}).get("user_id"))
        if uid and mh.money_holder(biz, uid):
            out.append(uid)
    return out


# ─── The asks ─────────────────────────────────────────────────────────

def _church(biz: str) -> Dict[str, Any]:
    import church_sheet
    business = church_sheet._business(biz)
    if not open_for(biz):
        raise HTTPException(404, "Not Found")
    return business


def _ask_row(ask_id: str) -> Dict[str, Any]:
    rows = mh._rows(f"/{mh.ASKS}?id=eq.{_q(ask_id)}"
                    "&select=id,business_id,user_id,asked_by,wants,status,asked_at,expires_at&limit=1")
    if rows is None:
        raise HTTPException(503, "That request couldn't be read just now. Try again.")
    if not rows or not isinstance(rows[0], dict) or not mh._id(rows[0].get("business_id")):
        raise HTTPException(404, "That request isn't here.")
    return rows[0]


def open_asks(business: Dict[str, Any], uid: str) -> Optional[List[Dict[str, Any]]]:
    """The asks waiting at this church that this login may read: the owner,
    all of them; anyone else, the ones they sent. None when unread."""
    import church_over as co
    biz = str(business["id"])
    rows = mh._rows(f"/{mh.ASKS}?business_id=eq.{_q(biz)}&status=eq.asked"
                    "&select=id,user_id,asked_by,wants,asked_at,expires_at&order=asked_at.asc&limit=100")
    if rows is None:
        return None
    owner = str(business.get("owner_id") or "") == uid
    ch, now, out = co.Church(business), _now(), []
    for r in rows:
        ends = mh._when((r or {}).get("expires_at"))
        wants = r.get("wants") if isinstance(r.get("wants"), dict) else {}
        if ends is None or ends <= now or wants.get("level") not in LEVELS:
            continue
        by, who = str(r.get("asked_by") or ""), str(r.get("user_id") or "")
        if not owner and by != uid:
            continue
        w = {"level": wants["level"], "who_gave": wants.get("who_gave") is True, "bank": wants.get("bank") is True}
        out.append({"id": r.get("id"), "user_id": who, "name": ch.login_name(who), "asked_by": by,
                    "asked_by_name": ch.login_name(by), "wants": w, "wants_words": words(w),
                    "asked_at": r.get("asked_at"), "expires_at": r.get("expires_at")})
    return out


@router.get("/money-asks")
def list_asks(business_id: str, session: UserSession = Depends(sb_clients.authed_request)):
    """The requests for giving access waiting at this church."""
    from business_users_router import role_of
    biz, uid = _uuid(business_id, "church"), str(session.user.id)
    business = _church(biz)
    if not role_of(biz, uid):
        raise HTTPException(403, "not authorized")
    asks = open_asks(business, uid)
    if asks is None:
        raise HTTPException(503, "The requests couldn't be read just now. Try again.")
    return {"ok": True, "asks": asks, "can_answer": str(business.get("owner_id") or "") == uid}


@router.post("/money-asks/{ask_id}/answer")
def answer_ask(ask_id: str, body: Dict[str, Any], request: Request,
               session: UserSession = Depends(sb_clients.authed_request)):
    """The owner says yes (with the password) or no. A yes opens exactly
    what was asked; a no opens nothing."""
    uid = str(session.user.id)
    ask = _ask_row(_uuid(ask_id, "request"))
    biz = str(ask["business_id"])
    business = _church(biz)
    if str(business.get("owner_id") or "") != uid:
        raise HTTPException(403, ONLY_OWNER_ANSWERS)
    yes = (body or {}).get("yes")
    if not isinstance(yes, bool):
        raise HTTPException(400, "Say yes or no.")
    if ask.get("status") != "asked":
        raise HTTPException(409, NOT_WAITING)
    if yes:
        import ledger_unlock
        ledger_unlock.require_unlock(request, uid, ledger_unlock.SCOPE_ACCESS, business_id=biz)
    out = _rpc("church_money_answer", {"p_ask": ask["id"], "p_yes": yes, "p_by": uid})
    if not out:
        code = (sb_clients.last_error() or {}).get("code")
        if code == "22023":
            raise HTTPException(409, NOT_WAITING)
        if code == "P0002":
            raise HTTPException(404, "That request isn't here.")
        raise HTTPException(503, "That didn't save. Nothing changed. Try again.")
    if out.get("ok") is not True:
        raise HTTPException(409, EXPIRED)
    target = str(ask.get("user_id") or "")
    wants = ask.get("wants") if isinstance(ask.get("wants"), dict) else {}
    try:
        import church_job_defs as cj
        import church_over as co
        ch = co.Church(business)
        name = ch.login_name(target)
        summary = (f"said yes to giving for {name}: {words(wants)}" if yes
                   else f"said no to giving for {name} ({words(wants)} was asked)")
        cj.changed(business, "sheet", uid, "owner", ch.login_name(uid), summary, subject=target,
                   detail={"money": {"kind": "answer", "yes": yes, "wants": wants, "ask": ask["id"]}})
    except Exception:  # noqa: BLE001 — the answer is saved; the record is the lesser thing
        logger.warning("money ask: the answer wasn't recorded (business %s)", biz[:8])
    _forget(biz, target)
    return {"ok": True, "status": out.get("status"), "user_id": target}


@router.post("/money-asks/{ask_id}/withdraw")
def withdraw_ask(ask_id: str, session: UserSession = Depends(sb_clients.authed_request)):
    """Whoever asked takes the request back, or the owner clears it."""
    uid = str(session.user.id)
    ask = _ask_row(_uuid(ask_id, "request"))
    biz = str(ask["business_id"])
    business = _church(biz)
    if uid not in (str(business.get("owner_id") or ""), str(ask.get("asked_by") or "")):
        raise HTTPException(403, "Only whoever asked, or the owner, takes a request back.")
    saved = sb_clients.sb_patch_as_service(
        f"/{mh.ASKS}?id=eq.{_q(ask['id'])}&business_id=eq.{_q(biz)}&status=eq.asked",
        {"status": "withdrawn", "answered_by": uid, "answered_at": _iso(_now())}, redact=True)
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not saved:
        raise HTTPException(409, NOT_WAITING)
    _forget(biz, ask.get("user_id"))
    return {"ok": True, "status": "withdrawn"}


# ─── The hourly sweep ─────────────────────────────────────────────────

def sweep(now: Optional[_dt.datetime] = None) -> Dict[str, int]:
    """Mark the asks that ran out, and remind each owner once, 48 hours in.
    Each reminder is claimed by its row first, so two replicas send one."""
    out = {"expired": 0, "reminded": 0}
    if mode() == "off":
        return out
    now = now or _now()
    stale = sb_clients.sb_patch_as_service(
        f"/{mh.ASKS}?status=eq.asked&expires_at=lte.{_q(_iso(now))}", {"status": "expired"}, redact=True)
    out["expired"] = len(stale) if isinstance(stale, list) else 0
    due = mh._rows(f"/{mh.ASKS}?status=eq.asked&reminded_at=is.null"
                   f"&asked_at=lte.{_q(_iso(now - _dt.timedelta(hours=REMIND_HOURS)))}"
                   f"&expires_at=gt.{_q(_iso(now))}&select=id,business_id,user_id,asked_by,wants,expires_at&limit=200")
    for a in due or []:
        biz, aid = mh._id((a or {}).get("business_id")), mh._id((a or {}).get("id"))
        if not biz or not aid or not open_for(biz) or _sample(biz):
            continue
        claimed = sb_clients.sb_patch_as_service(
            f"/{mh.ASKS}?id=eq.{_q(aid)}&status=eq.asked&reminded_at=is.null", {"reminded_at": _iso(now)},
            redact=True)
        if not isinstance(claimed, list) or not claimed:
            continue
        try:
            import church_job_defs as cj
            import church_over as co
            rows = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
            if not isinstance(rows, list) or not rows:
                continue
            ch = co.Church(rows[0])
            name = ch.login_name(str(a.get("user_id") or ""))
            wants = a.get("wants") if isinstance(a.get("wants"), dict) else {}
            cj.tell_owner(rows[0], f"Still waiting: giving access for {name}"[:150],
                          f"{ch.login_name(str(a.get('asked_by') or ''))} asked to give {name} giving access "
                          f"({words(wants)}). Nothing is open. Say yes or no on Logins & areas before the request "
                          "runs out.", tag=f"money-ask-remind-{aid}")
            out["reminded"] += 1
        except Exception:  # noqa: BLE001 — one church's reminder never stops the rest
            logger.warning("money ask: a reminder couldn't be sent (business %s)", biz[:8])
    return out


def _sample(business_id: str) -> bool:
    """A sample church is a pastor trying things out: nobody is reminded
    about a request made in one."""
    try:
        import sample_church
        return bool(sample_church.is_sample(business_id))
    except Exception:  # noqa: BLE001 — couldn't tell: say nothing
        return True


async def tick() -> Dict[str, Any]:
    """Hourly on the scheduler's leader. Off: nothing is read."""
    if mode() == "off":
        return {"skipped": "off"}
    import asyncio
    try:
        return await asyncio.to_thread(sweep)
    except Exception as e:  # noqa: BLE001 — the next hour tries again
        logger.warning("money ask sweep failed: %s", type(e).__name__)
        return {"error": type(e).__name__}


# ─── Marking alerts read ──────────────────────────────────────────────

GIVING_ALERT_KINDS = ("gift_received", "recurring_gift_ended")
FINANCE_ALERT_KINDS = ("invoice_paid",)


@router.post("/alerts/read")
def read_alerts(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Mark this business's unread alerts as read, for the login signed in:
    only the alerts that login may see. The money alerts follow the money
    gate (a login that Sees giving reads them, and since 2026-11-18 can't
    change the row itself), every other alert is the office's, a Member
    login and up, as it always was. {ids} narrows it to those."""
    from business_access import assert_access
    import church_money_gate as gate
    user = session.user
    body = body or {}
    biz = _uuid(body.get("business_id"), "business")
    assert_access(biz, user, "member")
    ids = body.get("ids")
    if ids is not None and (not isinstance(ids, list) or len(ids) > 200):
        raise HTTPException(400, "Send up to 200 alerts at a time.")
    idf = ""
    if ids is not None:
        clean = [_uuid(i, "alert") for i in ids]
        if not clean:
            return {"ok": True, "read": 0}
        idf = "&id=in.(" + ",".join(clean) + ")"
    hidden: List[str] = []
    standing = gate.money_standing(biz, user, "see", "books")
    if standing is None:
        hidden += list(FINANCE_ALERT_KINDS)
    if standing != gate.NOT_ASKED:
        import church_keys
        giving = False
        try:
            giving = gate.may_money(biz, user, "see", "giving") and church_keys.is_open(biz, user, "giving_money")
        except HTTPException:
            giving = False
        if not giving:
            hidden += list(GIVING_ALERT_KINDS)
    kinds = ""
    if hidden:
        kinds = "&or=(data->>kind.is.null,data->>kind.not.in.(" + ",".join(hidden) + "))"
    saved = sb_clients.sb_patch_as_service(
        f"/chief_notifications?business_id=eq.{_q(biz)}&status=eq.unread{idf}{kinds}",
        {"status": "read", "read_at": _iso(_now())}, redact=True)
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True, "read": len(saved)}
