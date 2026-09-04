"""
standing_permissions.py — the approval that earns a standing permission.

KEVIN'S RULE (2026-09-04, the "Chief to Eight" plan, phase five)
  "If it asks, do you want me to send this out, and they say yes — for
  future reference — then that default can be turned on based on that
  level of approval." The approval itself is the moment Chief earns the
  right to do that KIND of thing on its own.

HOW IT WORKS
  1. Chief files a proposal (a text, an invoice send…). The practitioner
     taps Yes, do that. On the third approval in a row of the same kind
     — read off the outcome ledger, never a counter someone could set —
     the approval's response carries ONE question: "You've approved the
     last three texts I drafted. Want me to send texts like this on my
     own from now on? You'll still see every one, and you get two
     minutes to pull one back." Yes grants that ONE kind. No is
     remembered for thirty days. Chat has the same door (grant / revoke
     verbs); a grant from chat is class C, because it releases sends.
  2. With a standing permission, Chief still files the proposal, but
     the row carries a release time RECALL_MINUTES out. The phone gets
     "Sending to Ada in 2 minutes" with Stop and Open. Silence means it
     goes: the release tick (every minute) claims the row and runs it
     through the same door an approval uses, marked surface="standing",
     authorized by the grant. Stop dismisses it — nothing was sent.
  3. Every standing send is on the record like any other move, and it
     feeds the same ledger. Stop three in a row and the permission is
     revoked for that kind (the retire rule, applied here) and the
     practitioner is told. "Stop sending texts on your own" in chat, or
     the switch in Settings, turns it off at once.

THE GUARDRAILS THAT DO NOT MOVE
  Only the kinds in ELIGIBLE; never bulk (proposals never are); only to
  a contact on file (proposals already refuse a raw recipient); money
  above STANDING_MONEY_CAP_USD still needs a tap; a regulated practice
  with client-facing autonomy disabled cannot grant a send; and a
  grant is per business and per kind, made in the moment of a real
  approval or in the practitioner's own words — never from a page that
  only lists switches.

STORAGE
  businesses.settings.autonomy.standing = {verb: {granted_at, granted_by,
  via}} and settings.autonomy.standing_declined = {verb: at}. Written
  with the same shallow merge chief_agent's switch uses. The release
  time is agent_queue.scheduled_for on the proposal row; the spec in
  the body carries "standing": true so nothing else mistakes it.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("standing_permissions")

router = APIRouter(prefix="/agents/chief/standing", tags=["chief-standing"])

# The kinds a practitioner may hand over. publish_to_site stays out: a
# public page is not a message to one person.
ELIGIBLE = ("send_sms", "send_invoice", "generate_payment_link", "mark_invoice_paid")
CLIENT_FACING = ("send_sms",)
MONEY_VERBS = ("send_invoice",)

RECALL_MINUTES = int(os.environ.get("STANDING_RECALL_MINUTES", "2") or 2)
ASK_AFTER = int(os.environ.get("STANDING_ASK_AFTER", "3") or 3)
DECLINE_QUIET_DAYS = 30
MONEY_CAP_USD = float(os.environ.get("STANDING_MONEY_CAP_USD", "500") or 500)
MAX_PER_TICK = 50

_WORDS = {"send_sms": "texts", "send_invoice": "invoice sends",
          "generate_payment_link": "payment links", "mark_invoice_paid": "payments recorded"}
_ONE = {"send_sms": "a text", "send_invoice": "an invoice", "generate_payment_link": "a payment link",
        "mark_invoice_paid": "a payment as recorded"}


def enabled() -> bool:
    return (os.environ.get("STANDING_PERMISSIONS") or "on").strip().lower() != "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def words(verb: str) -> str:
    return _WORDS.get(verb, verb.replace("_", " ") + "s")


# ─── Reading the grant ───────────────────────────────────────────────

def _autonomy(biz: Dict[str, Any]) -> Dict[str, Any]:
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    a = settings.get("autonomy")
    return a if isinstance(a, dict) else {}


def granted(biz: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    st = _autonomy(biz).get("standing")
    return {k: v for k, v in st.items() if isinstance(v, dict)} if isinstance(st, dict) else {}


def is_granted(biz: Dict[str, Any], verb: str) -> bool:
    return enabled() and verb in granted(biz) and eligible(biz, verb)[0]


def eligible(biz: Dict[str, Any], verb: str) -> Tuple[bool, str]:
    """May this business hand this kind over at all? The guardrails
    that do not move."""
    if verb not in ELIGIBLE:
        return False, "this kind always needs a tap"
    if verb in CLIENT_FACING:
        try:
            import policy_engine
            if policy_engine.client_facing_autonomy(biz) == "disabled":
                return False, "client-facing sends stay yours in a regulated practice"
        except Exception:
            pass
    return True, ""


def money_cap(biz: Dict[str, Any]) -> float:
    raw = _autonomy(biz).get("standing_money_cap")
    try:
        return float(raw) if raw is not None else MONEY_CAP_USD
    except (TypeError, ValueError):
        return MONEY_CAP_USD


def _load(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,owner_id,settings&limit=1") or []
    return rows[0] if rows else None


def load_for_filing(business_id: str) -> Optional[Dict[str, Any]]:
    """The business row action_proposals.file needs, or None: never a
    raise, never a read without a configured database (tests, scripts)."""
    if not enabled() or not os.environ.get("SUPABASE_URL"):
        return None
    try:
        return _load(business_id)
    except Exception:
        return None


def _write_autonomy(business_id: str, mutate) -> Dict[str, Any]:
    """Reload, mutate settings.autonomy, write back with a shallow merge
    on settings so a neighbouring key is never clobbered."""
    biz = _load(business_id) or {"settings": {}}
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    autonomy = dict(_autonomy(biz))
    mutate(autonomy)
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                   {"settings": {**settings, "autonomy": autonomy}})
    return autonomy


def grant(business_id: str, verb: str, *, by: str, via: str) -> Tuple[bool, str]:
    biz = _load(business_id)
    if not biz:
        return False, "business not found"
    ok, why = eligible(biz, verb)
    if not ok:
        return False, why
    when = _z(_now())

    def _m(a):
        st = dict(a.get("standing") or {})
        st[verb] = {"granted_at": when, "granted_by": by, "via": via}
        a["standing"] = st
        declined = dict(a.get("standing_declined") or {})
        declined.pop(verb, None)
        a["standing_declined"] = declined
    _write_autonomy(business_id, _m)
    try:
        import audit_log
        audit_log.record(business_id, actor_type="user", actor_id=by, verb="standing_grant",
                         ok=True, source=via, summary=f"Chief may send {words(verb)} on its own",
                         payload={"verb": verb, "recall_minutes": RECALL_MINUTES})
    except Exception:
        pass
    return True, when


def revoke(business_id: str, verb: str, *, by: str, via: str, reason: str = "") -> bool:
    had = {"v": False}

    def _m(a):
        st = dict(a.get("standing") or {})
        had["v"] = verb in st
        st.pop(verb, None)
        a["standing"] = st
    _write_autonomy(business_id, _m)
    if had["v"]:
        try:
            import audit_log
            audit_log.record(business_id, actor_type="user" if via != "retire" else "chief",
                             actor_id=by, verb="standing_revoke", ok=True, source=via,
                             summary=f"Chief asks again before {words(verb)}" + (f" — {reason}" if reason else ""),
                             payload={"verb": verb, "reason": reason})
        except Exception:
            pass
    return had["v"]


def decline(business_id: str, verb: str) -> None:
    when = _z(_now())

    def _m(a):
        d = dict(a.get("standing_declined") or {})
        d[verb] = when
        a["standing_declined"] = d
    _write_autonomy(business_id, _m)


# ─── The question, at the third approval ─────────────────────────────

def question(verb: str) -> str:
    return (f"You've approved the last {ASK_AFTER} {words(verb)} I drafted. Want me to send "
            f"{words(verb)} like this on my own from now on? You'll still see every one, and "
            f"you get {RECALL_MINUTES} minutes to pull one back.")


def offer_after_approval(biz: Dict[str, Any], verb: str,
                         moves: Optional[List[Dict[str, Any]]] = None,
                         now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The one-time question, or None. Read off the outcome ledger: the
    last ASK_AFTER resolved outcomes for this verb must all be
    approvals (pending rows do not count). The approval that just
    happened is usually still pending in the ledger, so it counts as
    one of them here."""
    if not enabled() or not verb:
        return None
    now = now or _now()
    ok, _ = eligible(biz, verb)
    if not ok or verb in granted(biz):
        return None
    declined = _autonomy(biz).get("standing_declined") or {}
    at = _ts(declined.get(verb)) if isinstance(declined, dict) else None
    if at and now - at < timedelta(days=DECLINE_QUIET_DAYS):
        return None
    if moves is None:
        try:
            import outcome_ledger
            moves = outcome_ledger.recent_moves(str(biz.get("id")), 30)
        except Exception:
            moves = []
    seen: List[str] = ["approved"]   # the tap that just happened
    for m in sorted(moves, key=lambda r: str(r.get("made_at") or ""), reverse=True):
        if str(m.get("verb")) != verb or not m.get("queue_id"):
            continue
        o = str(m.get("outcome") or "pending")
        if o in ("pending", "no_signal"):
            continue
        seen.append(o)
        if len(seen) >= ASK_AFTER:
            break
    if len(seen) < ASK_AFTER or not all(o in ("approved", "replied") for o in seen):
        return None
    return {"verb": verb, "kind": words(verb), "count": ASK_AFTER,
            "question": question(verb), "recall_minutes": RECALL_MINUTES}


# ─── Filing under a standing permission ──────────────────────────────

def filing_extras(biz: Optional[Dict[str, Any]], verb: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """What a proposal row carries when the kind is granted: its release
    time. Empty otherwise."""
    if not biz or not is_granted(biz, verb):
        return {}
    now = now or _now()
    return {"scheduled_for": _z(now + timedelta(minutes=RECALL_MINUTES))}


def announce_standing(business_id: str, owner_id: Optional[str], queue_id: str, sentence: str) -> int:
    """'Sending in 2 minutes' with Stop and Open. Best-effort."""
    if not owner_id:
        return 0
    try:
        import push_notifications
        if not push_notifications.push_enabled():
            return 0
        return push_notifications.send_to_user(
            str(owner_id), title=f"Sending in {RECALL_MINUTES} minutes",
            body=(sentence or "")[:160], nav="operate:queue", tag=f"standing-{queue_id}",
            actions=[{"action": "stop", "title": "Stop"}, {"action": "open", "title": "Open"}],
            data={"stop_id": queue_id, "business_id": business_id})
    except Exception as e:
        logger.warning(f"[standing] push failed: {e}")
        return 0


# ─── The release tick ────────────────────────────────────────────────

def due_rows(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?channel=eq.action&status=eq.draft&scheduled_for=lte.{_z(now)}"
        f"&select=id,business_id,contact_id,subject,body,scheduled_for,agent,action_type,channel,status"
        f"&order=scheduled_for.asc&limit={MAX_PER_TICK}") or []
    return rows if isinstance(rows, list) else []


def _claim(queue_id: str, now: datetime) -> bool:
    """Only a row still in draft is released — a Stop that landed in
    between wins, and two replicas cannot both send."""
    rows = sb_clients.sb_patch_as_service(
        f"/agent_queue?id=eq.{queue_id}&status=eq.draft",
        {"status": "approved", "reviewed_at": _z(now)})
    return bool(rows)


def _hold(queue_id: str, why: str) -> None:
    """Back to an ordinary proposal: no release time, the reason on the row."""
    sb_clients.sb_patch_as_service(f"/agent_queue?id=eq.{queue_id}",
                                   {"scheduled_for": None,
                                    "ai_reasoning": f"Needs your tap: {why}"})


def _over_cap(biz: Dict[str, Any], action: Dict[str, Any]) -> Optional[str]:
    if action.get("type") not in MONEY_VERBS:
        return None
    iid = action.get("invoice_id")
    if not iid:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/invoices?id=eq.{iid}&business_id=eq.{biz.get('id')}&select=total&limit=1") or []
    try:
        total = float((rows[0] if rows else {}).get("total") or 0)
    except (TypeError, ValueError):
        total = 0.0
    cap = money_cap(biz)
    if total > cap:
        return f"${total:,.2f} is above your ${cap:,.0f} standing cap"
    return None


async def release_one(row: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    import action_proposals
    import policy_engine
    now = now or _now()
    qid = str(row.get("id") or "")
    bid = str(row.get("business_id") or "")
    spec = action_proposals.spec_from_body(row.get("body") or "")
    if not spec or not spec.get("standing"):
        return {"id": qid, "did": "skipped", "why": "not a standing send"}
    verb = str((spec.get("action") or {}).get("type") or "")
    biz = await asyncio.to_thread(_load, bid)
    if not biz:
        return {"id": qid, "did": "skipped", "why": "no business"}
    if not is_granted(biz, verb):
        await asyncio.to_thread(_hold, qid, "the standing permission was turned off")
        return {"id": qid, "did": "held", "why": "revoked"}
    if policy_engine.is_paused(biz):
        await asyncio.to_thread(_hold, qid, "automations are paused")
        return {"id": qid, "did": "held", "why": "paused"}
    over = await asyncio.to_thread(_over_cap, biz, spec.get("action") or {})
    if over:
        await asyncio.to_thread(_hold, qid, over)
        await asyncio.to_thread(_tell, biz, f"Needs your tap: {row.get('subject') or 'a send'}",
                                f"{over}. It is waiting in your Approval Queue.", f"standing_cap:{qid}")
        return {"id": qid, "did": "held", "why": "cap"}
    if not await asyncio.to_thread(_claim, qid, now):
        return {"id": qid, "did": "skipped", "why": "stopped or already handled"}
    async with httpx.AsyncClient() as client:
        result = await action_proposals.execute(client, biz, {**row, "_standing": verb})
    ok = bool(result.get("ok"))
    try:
        import audit_log
        await asyncio.to_thread(
            audit_log.record, bid, actor_type="chief", actor_id="standing", verb=verb,
            ok=ok, error=None if ok else str(result.get("message") or "")[:300],
            summary=(f"Sent on standing permission: {row.get('subject') or verb}")[:240],
            payload={"queue_id": qid, "verb": verb,
                     "granted_at": (granted(biz).get(verb) or {}).get("granted_at")},
            source="standing", authorized_by=f"standing:{verb}")
    except Exception as e:
        logger.warning(f"[standing] audit failed: {e}")
    try:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/chief_activity", {
            "user_id": biz.get("owner_id"), "business_id": bid, "source": "system",
            "action_type": "standing_send",
            "label": (("Sent on your standing permission: " if ok else "Could not send: ") + str(row.get("subject") or verb))[:120],
            "summary": str(result.get("message") or "")[:240], "nav": None,
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[standing] activity row failed: {e}")
    if not ok:
        sb_clients.sb_patch_as_service(f"/agent_queue?id=eq.{qid}", {"status": "failed"})
    return {"id": qid, "did": "sent" if ok else "failed", "verb": verb}


def _tell(biz: Dict[str, Any], title: str, body: str, key: str) -> None:
    try:
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": biz.get("id"), "type": "reminder", "priority": "normal",
            "title": title[:120], "body": body[:300],
            "action_payload": {"type": "navigate", "tab": "operate", "sub": "queue", "dedup_key": key},
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[standing] notification failed: {e}")


async def release_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every minute, leader-gated."""
    if not enabled():
        return {"skipped": "off"}
    now = now or _now()
    rows = await asyncio.to_thread(due_rows, now)
    out: Dict[str, int] = {}
    for r in rows:
        try:
            res = await release_one(r, now)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[standing] {str(r.get('id'))[:8]} crashed: {e}")
            continue
        out[res["did"]] = out.get(res["did"], 0) + 1
    return out


# ─── The retire rule, applied to a grant ─────────────────────────────

def sweep_revocations(now: Optional[datetime] = None) -> List[str]:
    """A kind stopped three times running loses its standing permission.
    Called from the outcome ledger's tick. Returns 'biz:verb' revoked."""
    if not enabled():
        return []
    import outcome_ledger
    rows = sb_clients.sb_get_as_service(
        "/businesses?select=id,owner_id,settings&settings->autonomy->standing=not.is.null&limit=500") or []
    revoked: List[str] = []
    for biz in rows if isinstance(rows, list) else []:
        grants = granted(biz)
        if not grants:
            continue
        try:
            retired = outcome_ledger.retired_verbs(outcome_ledger.recent_moves(str(biz["id"]), outcome_ledger.RETIRE_WINDOW_DAYS), now)
        except Exception:
            continue
        for verb in grants:
            if verb in retired:
                revoke(str(biz["id"]), verb, by="chief", via="retire", reason="you stopped the last three")
                _tell(biz, f"I'm back to asking before {words(verb)}",
                      f"You stopped the last {outcome_ledger.RETIRE_AFTER} {words(verb)} I sent on my own, so I "
                      f"turned that permission off. Say the word in chat if you want it back.",
                      f"standing_revoked:{verb}")
                revoked.append(f"{str(biz['id'])[:8]}:{verb}")
    return revoked


# ─── Chief's words ───────────────────────────────────────────────────

def context_lines(biz: Dict[str, Any]) -> List[str]:
    g = granted(biz)
    if not g:
        return []
    parts = [f"{words(v)} (since {str(i.get('granted_at') or '')[:10]})" for v, i in sorted(g.items())]
    return [f"  Chief sends these on its own after a {RECALL_MINUTES}-minute window the practitioner can stop: "
            + "; ".join(parts) + ". revoke_standing_permission turns one off."]


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    import chief_of_staff
    return chief_of_staff._fail(atype, msg)


def _verb_from(action: Dict[str, Any]) -> str:
    raw = str(action.get("verb") or action.get("kind") or "").strip().lower()
    aliases = {"texts": "send_sms", "text": "send_sms", "sms": "send_sms", "messages": "send_sms",
               "invoices": "send_invoice", "invoice": "send_invoice", "invoice sends": "send_invoice",
               "payment links": "generate_payment_link", "payment link": "generate_payment_link",
               "payments": "mark_invoice_paid", "payments recorded": "mark_invoice_paid"}
    return aliases.get(raw, raw)


async def handle_grant_standing_permission(client, biz, action) -> Dict[str, Any]:
    """Class C: it releases sends. The practitioner's own words are the
    approval; the chat gate stands in front of it."""
    verb = _verb_from(action)
    if not verb:
        return _fail("grant_standing_permission", "say which kind: texts, invoice sends, payment links, or payments recorded")
    ok, why = eligible(biz, verb)
    if not ok:
        return _fail("grant_standing_permission", why)
    import chief_of_staff as cos
    done, info = await asyncio.to_thread(grant, str(biz.get("id")), verb,
                                         by=(cos._TURN_USER_ID.get() or "owner"), via="chat")
    if not done:
        return _fail("grant_standing_permission", info)
    return {"type": "grant_standing_permission",
            "result": (f"from now on I'll send {words(verb)} on my own, with a {RECALL_MINUTES}-minute "
                       f"window to stop each one; every one stays on the record"),
            "label": f"🔓 Standing permission: {words(verb)}", "verb": verb}


async def handle_revoke_standing_permission(client, biz, action) -> Dict[str, Any]:
    verb = _verb_from(action)
    g = granted(biz)
    if not verb and len(g) == 1:
        verb = next(iter(g))
    if not verb:
        return _fail("revoke_standing_permission", "say which kind" if g else "nothing is on standing permission")
    import chief_of_staff as cos
    had = await asyncio.to_thread(revoke, str(biz.get("id")), verb,
                                  by=(cos._TURN_USER_ID.get() or "owner"), via="chat")
    return {"type": "revoke_standing_permission",
            "result": (f"back to asking before {words(verb)}" if had else f"{words(verb)} already needed your tap"),
            "label": f"🔒 Asks first again: {words(verb)}", "verb": verb}


# ─── The door ─────────────────────────────────────────────────────────

def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    biz = _load(business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="business not found")
    if str(biz.get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
    return biz


class _Body(BaseModel):
    business_id: str
    verb: str
    grant: bool


@router.get("")
def standing(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner(business_id, user)
    return {"ok": True, "granted": granted(biz),
            "eligible": [{"verb": v, "kind": words(v), "ok": eligible(biz, v)[0], "why": eligible(biz, v)[1]}
                         for v in ELIGIBLE],
            "recall_minutes": RECALL_MINUTES, "ask_after": ASK_AFTER, "money_cap": money_cap(biz)}


@router.post("")
def set_standing(body: _Body, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner(body.business_id, user)
    verb = _verb_from({"verb": body.verb})
    if body.grant:
        ok, info = grant(body.business_id, verb, by=str(user.id), via="app")
        if not ok:
            raise HTTPException(status_code=400, detail=info)
        return {"ok": True, "granted": True, "verb": verb, "since": info}
    if verb in granted(biz):
        revoke(body.business_id, verb, by=str(user.id), via="app")
    else:
        decline(body.business_id, verb)
    return {"ok": True, "granted": False, "verb": verb}
