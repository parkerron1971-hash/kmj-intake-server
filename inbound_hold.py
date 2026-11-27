"""
inbound_hold.py — "Needs a look": hold the automation, never the person.

A card inbound_risk says needs a look is saved as usual: the contact, the note,
the event, the email notice to the church, all of it. What waits is everything
the system would do on its own because of it: the guest follow-up and its
volunteer call, the Welcome Path and its texts, the "new connect card" and
"still waiting" alerts, the morning brief's "greet her first", lead scoring and
Chief's proposed reply. The office gets one quiet line instead ("1 card needs a
look"). The visitor always sees the same thank-you.

A person clears it with one tap, here or through Chief:

    real person   everything held runs now, as if it had never waited, and
                  this church remembers the sender: their next card is clear
    not a guest   closes their follow-ups, takes them off the Welcome Path
                  (queued texts cancelled) and marks them inactive
    scam          the same, and the sender's fingerprints count toward the
                  shared list (two churches within 30 days; docs/INBOUND_SAFETY.md)

Every decision can be undone (the person goes back to "needs a look" and what
the decision did is put back), and leaves a row in inbound_decisions and a line
in the audit log: who, when, which signals, never the words.

Prayer is never held from the people who pray: a prayer request that scores is
delivered as always, with a "may not be genuine" mark on the request.

TABLES (supabase/APPLY-2026-11-27-needs-a-look.sql, server-only)
    inbound_checks       one row a checked submission: verdict, score, reasons,
                         salted hashes, state (held | clear | watched | flagged |
                         released | closed), what to run when released
    inbound_decisions    one row a tap: real | not_a_guest | scam, what it changed
    inbound_senders      a church's own memory of a sender (real | scam), by hash
    inbound_shared_list  hashes other churches will see as a +3 signal, 90 days
Before the file is applied every write here fails, and a card is never held
(a hold that couldn't be recorded couldn't be released): the doors run as before.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import inbound_risk as risk
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(tags=["inbound-safety"])

HELD, CLEAR, WATCHED, FLAGGED, RELEASED, CLOSED = "held", "clear", "watched", "flagged", "released", "closed"
REAL, NOT_A_GUEST, SCAM = "real", "not_a_guest", "scam"
DECISIONS = (REAL, NOT_A_GUEST, SCAM)
MIN_ROLE = "manager"              # the Members roll's own gate (church_roll.MIN_ROLE)
SHARED_WINDOW_DAYS = 30           # two churches' Scam taps inside this
SHARED_KEEP_DAYS = 90             # then it ages out, 90 days after the last tap
UNDO_HOURS = 24 * 7
NEW_HERE_KIND = "new_here_text"   # new_here.KIND
WORDS = {
    REAL: "Marked a real person",
    NOT_A_GUEST: "Marked not a guest",
    SCAM: "Marked a scam",
}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    try:
        rows = sb_clients.sb_get_as_service(path)
    except Exception:  # noqa: BLE001
        return None
    return rows if isinstance(rows, list) else None


def check_id(receipt: str) -> str:
    return str(uuid.uuid5(uuid.UUID(str(receipt)), "inbound-check"))


def _uuid(v: Any) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(404, "That person isn't here.")


# ─── A card comes in ──────────────────────────────────────────────────

def mark_of(verdict: Dict[str, Any], cid: str) -> Dict[str, Any]:
    """The "held" mark on the contact (metadata.inbound_hold)."""
    return {"state": "needs_look", "door": verdict.get("door") or "", "score": int(verdict.get("score") or 0),
            "reasons": risk.words_of(verdict)[:6], "at": _iso(_now()), "check_id": cid}


def begin(business_id: str, receipt: str, verdict: Optional[Dict[str, Any]], *,
          pending: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Record a door's verdict. Returns the contact's held mark when this card
    waits for a look, else None (nothing waits). A card holds only where the
    switch is on, never a prayer request, and only once its row is saved."""
    if not verdict or not receipt:
        return None
    door = verdict.get("door") or ""
    holding = bool(verdict.get("enforce") and verdict.get("hold") and door != "prayer_request")
    if verdict.get("enforce") and verdict.get("hold") and door == "prayer_request":
        state = FLAGGED
    elif holding:
        state = HELD
    elif verdict.get("enforce"):
        state = CLEAR
    else:
        state = WATCHED
    try:
        cid = check_id(receipt)
    except ValueError:
        return None
    prints = verdict.get("prints") or {}
    row = {
        "id": cid, "business_id": str(business_id), "receipt": str(receipt), "door": door[:40],
        "verdict": verdict.get("verdict") or risk.CLEAR, "score": int(verdict.get("score") or 0),
        "reasons": [{"code": r.get("code"), "points": int(r.get("points") or 0), "words": r.get("words")}
                    for r in verdict.get("reasons") or []][:20],
        "second_opinion": verdict.get("second_opinion"),
        "email_hash": prints.get("email"), "domain_hash": prints.get("domain"),
        "phone_hash": prints.get("phone"), "text_hash": prints.get("text"),
        "state": state, "pending": dict(pending or {}, receipt=str(receipt)) if holding else {},
    }
    try:
        saved = sb_clients.sb_post_as_service(
            "/inbound_checks", row, prefer="resolution=ignore-duplicates,return=representation")
    except Exception:  # noqa: BLE001
        saved = None
    if saved == []:   # a retried card: the first row stands
        again = _rows(f"/inbound_checks?id=eq.{_q(cid)}&business_id=eq.{_q(business_id)}&select=state&limit=1")
        saved = again if again else None
        holding = holding and bool(again) and again[0].get("state") == HELD
    if not (isinstance(saved, list) and saved):
        if holding:
            print(f"[inbound_hold] {str(business_id)[:8]}: the hold couldn't be recorded; the card runs as before",
                  flush=True)
        return None
    return mark_of(verdict, cid) if holding else None


def attach(business_id: str, receipt: str, contact_id: Optional[str]) -> None:
    """The contact a checked card became. Best effort."""
    if not contact_id or not receipt:
        return
    try:
        sb_clients.sb_patch_as_service(
            f"/inbound_checks?id=eq.{_q(check_id(receipt))}&business_id=eq.{_q(business_id)}&contact_id=is.null",
            {"contact_id": str(contact_id)})
    except Exception:  # noqa: BLE001
        pass


def prayer_flag(verdict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The mark a prayer request carries when it scores: delivered as always."""
    if not verdict or not verdict.get("enforce") or not verdict.get("hold"):
        return None
    return {"label": "May not be genuine", "reasons": risk.words_of(verdict)[:4], "score": verdict.get("score")}


def held_count(business_id: str) -> Optional[int]:
    rows = _rows(f"/inbound_checks?business_id=eq.{_q(business_id)}&state=eq.{HELD}"
                 "&select=contact_id&limit=500")
    if rows is None:
        return None
    return len({str(r.get("contact_id") or r.get("id")) for r in rows})


def signal_words(n: int, church: bool = True) -> Tuple[str, str]:
    what = "card" if church else "message"
    title = f"1 {what} needs a look" if n == 1 else f"{n} {what}s need a look"
    body = (f"{'It' if n == 1 else 'They'} may not be from {'a guest' if church else 'a real customer'}, so nothing "
            "went out automatically. Open Members to read it and tap Real person, Not a guest or Scam.")
    return title, body


async def signal(business_id: str, *, church: bool = True) -> None:
    """One quiet line for the office in place of every guest alert. Never the
    sender's name: the line says a card waits, and Members says whose."""
    try:
        n = await asyncio.to_thread(held_count, business_id) or 1
        title, body = signal_words(n, church)
        import httpx
        from notification_engine import create_urgent_alert
        async with httpx.AsyncClient() as client:
            await create_urgent_alert(
                client, business_id, title, body, dedup_key="inbound:needs_look", dedup_hours=12,
                priority="normal", suggested_action="Open Members",
                action_payload={"type": "navigate", "tab": "operate", "sub": "contacts", "filter": "needs_look"})
    except Exception as e:  # noqa: BLE001 — the card is saved and marked whatever happens here
        print(f"[inbound_hold] signal failed biz={str(business_id)[:8]}: {type(e).__name__}", flush=True)


# ─── Who is waiting ───────────────────────────────────────────────────

def _previews(biz: str, receipts: List[str]) -> Dict[str, str]:
    if not receipts:
        return {}
    rows = _rows(f"/events?business_id=eq.{_q(biz)}&id=in.({','.join(_q(r) for r in receipts)})"
                 "&select=id,data") or []
    out = {}
    for r in rows:
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        words = risk.card_text(d.get("message"), d.get("fields") if isinstance(d.get("fields"), dict) else {})
        out[str(r.get("id"))] = _plain(words)[:280]
    return out


def held(business_id: str, *, limit: int = 100, previews: bool = True) -> Optional[List[Dict[str, Any]]]:
    """Everyone waiting for a look, newest first: one row a person.
    {contact_id, name, door, score, reasons, at, cards, preview}."""
    biz = str(business_id)
    rows = _rows(f"/inbound_checks?business_id=eq.{_q(biz)}&state=eq.{HELD}"
                 "&select=id,contact_id,door,score,reasons,created_at,receipt,second_opinion"
                 f"&order=created_at.desc&limit={int(limit) * 3}")
    if rows is None:
        return None
    people: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = str(r.get("contact_id") or "")
        if not cid:
            continue
        p = people.get(cid)
        if p is None:
            p = people[cid] = {"contact_id": cid, "name": "", "door": r.get("door") or "",
                               "score": int(r.get("score") or 0), "reasons": [], "at": r.get("created_at"),
                               "cards": 0, "preview": "", "_receipt": r.get("receipt")}
        p["cards"] += 1
        p["score"] = max(p["score"], int(r.get("score") or 0))
        for w in risk.words_of({"reasons": r.get("reasons") or []}):
            if w not in p["reasons"]:
                p["reasons"].append(w)
    ids = list(people)[:limit]
    if ids:
        names = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})"
                      "&select=id,name,email,phone") or []
        for n in names:
            p = people.get(str(n.get("id")))
            if p:
                p.update(name=_plain(n.get("name")) or "Someone", email=n.get("email") or "",
                         phone=n.get("phone") or "")
    if previews:
        got = _previews(biz, [str(people[i]["_receipt"]) for i in ids if people[i].get("_receipt")])
        for i in ids:
            people[i]["preview"] = got.get(str(people[i].get("_receipt")), "")
    out = []
    for i in ids:
        p = people[i]
        p.pop("_receipt", None)
        p["reasons"] = p["reasons"][:6]
        out.append(p)
    return out


def held_ids(business_id: str) -> Optional[set]:
    rows = _rows(f"/inbound_checks?business_id=eq.{_q(business_id)}&state=eq.{HELD}&select=contact_id&limit=500")
    if rows is None:
        return None
    return {str(r["contact_id"]) for r in rows if r.get("contact_id")}


def without_held(rows: Optional[List[Dict[str, Any]]], ids: Optional[set]) -> List[Dict[str, Any]]:
    """A list of contacts with the people waiting for a look taken out."""
    if not rows:
        return rows or []
    if not ids:
        return rows
    return [r for r in rows if str(r.get("id") or r.get("contact_id") or "") not in ids]


# ─── The decisions ────────────────────────────────────────────────────

def _contact(biz: str, cid: str) -> Dict[str, Any]:
    rows = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=eq.{_q(cid)}"
                 "&select=id,name,email,phone,status,metadata,updated_at&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't be read just now. Nothing changed. Try again in a minute.")
    if not rows:
        raise HTTPException(404, "That person isn't here.")
    return rows[0]


def _patch_contact(biz: str, cid: str, change) -> Dict[str, Any]:
    """Change one contact under its updated_at guard (a card arriving at the
    same moment is never lost). `change(row)` -> (metadata, extra columns)."""
    now = _iso(_now())
    for _ in range(3):
        row = _contact(biz, cid)
        meta, extra = change(row)
        stamp = row.get("updated_at")
        guard = ("eq." + _q(stamp)) if stamp else "is.null"
        saved = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&updated_at={guard}",
            dict(extra or {}, metadata=meta, updated_at=now))
        if isinstance(saved, list) and saved:
            return saved[0]
        if saved != []:
            break
    raise HTTPException(503, "That didn't save. Nothing changed. Try again in a minute.")


def _checks_of(biz: str, cid: str, states: Tuple[str, ...]) -> List[Dict[str, Any]]:
    rows = _rows(f"/inbound_checks?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                 f"&state=in.({','.join(states)})&select=id,door,receipt,pending,state,email_hash,domain_hash,"
                 "phone_hash,text_hash,created_at&order=created_at.asc&limit=50")
    if rows is None:
        raise HTTPException(503, "That couldn't be read just now. Nothing changed. Try again in a minute.")
    return rows


def _set_checks(biz: str, ids: List[str], state: str) -> None:
    if ids:
        sb_clients.sb_patch_as_service(
            f"/inbound_checks?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})",
            {"state": state, "decided_at": _iso(_now())})


def prints_of(contact: Dict[str, Any], checks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Every fingerprint that names this sender: their cards' and their record's."""
    out: Dict[str, List[str]] = {}
    for c in checks:
        for kind in ("email", "domain", "phone", "text"):
            h = c.get(f"{kind}_hash")
            if h and h not in out.setdefault(kind, []):
                out[kind].append(h)
    card = risk.Card(door="", name=contact.get("name") or "", email=contact.get("email") or "",
                     phone=contact.get("phone") or "")
    for kind, h in risk.fingerprints(card).items():
        if h not in out.setdefault(kind, []):
            out[kind].append(h)
    return {k: v for k, v in out.items() if v}


def _remember(biz: str, prints: Dict[str, List[str]], verdict: str, decision_id: str) -> List[Dict[str, Any]]:
    """This church's memory of the sender, replacing whatever it said before.
    Returns the rows it replaced, for undo. A Real never names the domain: one
    real person at gmail-like or company mail says nothing about the rest."""
    hashes = [(k, h) for k, hs in prints.items() for h in hs if not (verdict == REAL and k == "domain")]
    if not hashes:
        return []
    before = _rows(f"/inbound_senders?business_id=eq.{_q(biz)}&hash=in.({','.join(_q(h) for _, h in hashes)})"
                   "&select=kind,hash,verdict,at,decision_id") or []
    sb_clients.sb_post_as_service(
        "/inbound_senders?on_conflict=business_id,kind,hash",
        [{"business_id": biz, "kind": k, "hash": h, "verdict": verdict, "at": _iso(_now()),
          "decision_id": decision_id} for k, h in hashes],
        prefer="resolution=merge-duplicates,return=minimal")
    return before


def _forget(biz: str, decision_id: str, before: List[Dict[str, Any]]) -> None:
    sb_clients.sb_delete_as_service(f"/inbound_senders?business_id=eq.{_q(biz)}&decision_id=eq.{_q(decision_id)}")
    if before:
        sb_clients.sb_post_as_service(
            "/inbound_senders?on_conflict=business_id,kind,hash",
            [dict(b, business_id=biz) for b in before], prefer="resolution=merge-duplicates,return=minimal")


def shared_list_review(prints: Dict[str, List[str]], *, now: Optional[datetime] = None,
                       by_platform: bool = False) -> int:
    """Put a sender on the shared list when two different churches said Scam
    within 30 days (or the platform owner did), and take an entry off that no
    longer has two. Returns how many hashes are on the list after."""
    now = now or _now()
    since = _iso(now - timedelta(days=SHARED_WINDOW_DAYS))
    listed = 0
    for kind, hashes in prints.items():
        for h in hashes:
            taps = _rows(f"/inbound_senders?kind=eq.{_q(kind)}&hash=eq.{_q(h)}&verdict=eq.scam&at=gte.{since}"
                         "&select=business_id&limit=200")
            if taps is None:
                continue
            churches = len({str(t.get("business_id")) for t in taps})
            current = _rows(f"/inbound_shared_list?kind=eq.{_q(kind)}&hash=eq.{_q(h)}&select=source&limit=1") or []
            platform = by_platform or (current and current[0].get("source") == "platform")
            if churches >= 2 or platform:
                sb_clients.sb_post_as_service("/inbound_shared_list?on_conflict=kind,hash", {
                    "kind": kind, "hash": h, "source": "platform" if platform else "churches",
                    "churches": churches, "last_tap_at": _iso(now),
                    "expires_at": _iso(now + timedelta(days=SHARED_KEEP_DAYS)),
                }, prefer="resolution=merge-duplicates,return=minimal")
                listed += 1
            elif current:
                sb_clients.sb_delete_as_service(
                    f"/inbound_shared_list?kind=eq.{_q(kind)}&hash=eq.{_q(h)}&source=eq.churches")
    return listed


def _close_follow_ups(biz: str, cid: str, by_user: str, by_name: str) -> List[str]:
    """Close every open follow-up for this person (the volunteer call and its
    "still waiting" alerts stop). The closed ones' ids, for undo."""
    import church_follow_up as cfu
    shared = getattr(cfu, "close_for_contact", None)
    if callable(shared):
        # The step-1 Fix's one helper (church-office: marking someone inactive
        # closes their follow-ups); it also takes them off the Welcome Path.
        got = shared(biz, cid, by_user=by_user, by_name=by_name, why="Not a guest: closed by the office.")
        if got is None:
            raise HTTPException(503, "Their follow-ups couldn't be read just now. Nothing changed. Try again.")
        return [str(i) for i in got]
    rows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                 "&status=in.(open,handed_back)&select=id&limit=50")
    if rows is None:
        raise HTTPException(503, "Their follow-ups couldn't be read just now. Nothing changed. Try again.")
    closed = []
    for r in rows:
        try:
            cfu.close(biz, str(r["id"]), by_user=by_user, by_name=by_name)
            closed.append(str(r["id"]))
        except HTTPException as e:
            if e.status_code != 400:      # 400: already finished
                raise
    return closed


def _cancel_welcome_texts(biz: str, cid: str) -> List[str]:
    """Take them off the Welcome Path: every queued text for them cancelled."""
    rows = sb_clients.sb_patch_as_service(
        f"/chief_scheduled_actions?business_id=eq.{_q(biz)}&status=eq.queued"
        f"&action->>type=eq.{NEW_HERE_KIND}&action->>contact_id=eq.{_q(cid)}",
        {"status": "cancelled"})
    return [str(r["id"]) for r in rows if r.get("id")] if isinstance(rows, list) else []


def _event_data(biz: str, receipt: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/events?business_id=eq.{_q(biz)}&id=eq.{_q(receipt)}&select=data&limit=1")
    if not rows:
        return None
    return rows[0].get("data") if isinstance(rows[0].get("data"), dict) else None


def _release(biz: str, cid: str, contact: Dict[str, Any], checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run what each held card would have run, oldest first."""
    opened: List[str] = []
    nudge = False
    for c in checks:
        pending = c.get("pending") if isinstance(c.get("pending"), dict) else {}
        receipt = str(pending.get("receipt") or c.get("receipt") or "")
        data = _event_data(biz, receipt) if receipt else None
        if data is None:
            continue
        if c.get("door") == "connect_card":
            import church_follow_up
            row = church_follow_up.on_connect_card(biz, cid, data, receipt,
                                                   texts_ok=bool(pending.get("texts_ok")))
            if row and row.get("id"):
                opened.append(str(row["id"]))
        elif c.get("door") == "contact_form":
            try:
                import lead_scoring
                email = str(data.get("email") or contact.get("email") or "").strip().lower()
                lead_scoring.score_in_background(
                    biz, cid, {"name": data.get("name"), "email": email, "phone": data.get("phone"),
                               "message": data.get("message")},
                    source="website_contact_form", email=email, phone=contact.get("phone"))
            except Exception as e:  # noqa: BLE001
                print(f"[inbound_hold] lead scoring after release skipped: {type(e).__name__}", flush=True)
            nudge = True
    return {"opened": opened, "nudge": nudge}


def decide(business_id: str, contact_id: str, verdict: str, *, by_user: str, by_name: str = "",
           via: str = "app", share: bool = False) -> Dict[str, Any]:
    """Real person, Not a guest or Scam for one person. Sync. Raises
    HTTPException with words a person reads."""
    if verdict not in DECISIONS:
        raise HTTPException(400, "Choose Real person, Not a guest or Scam.")
    biz, cid = str(business_id), _uuid(contact_id)
    contact = _contact(biz, cid)
    name = _plain(contact.get("name")) or "Someone"
    meta0 = contact.get("metadata") if isinstance(contact.get("metadata"), dict) else {}
    checks = _checks_of(biz, cid, (HELD,))
    all_checks = _checks_of(biz, cid, (HELD, CLEAR, WATCHED, RELEASED, CLOSED))
    did = str(uuid.uuid4())
    before: Dict[str, Any] = {"status": contact.get("status"), "mark": meta0.get("inbound_hold"),
                              "decision": meta0.get("inbound_decision"), "checks": [c["id"] for c in checks]}
    prints = prints_of(contact, all_checks)
    stamp = {"verdict": verdict, "at": _iso(_now()), "by": by_name or "the office", "decision_id": did}

    if verdict == REAL:
        def change(row):
            meta = dict(row.get("metadata") or {})
            meta.pop("inbound_hold", None)
            meta["inbound_decision"] = stamp
            return meta, {}
        _patch_contact(biz, cid, change)
        _set_checks(biz, before["checks"], RELEASED)
        before["senders"] = _remember(biz, prints, "real", did)
        ran = _release(biz, cid, contact, checks)
        before["opened"] = ran["opened"]
        done = {"released": len(checks), "follow_ups_opened": len(ran["opened"]), "nudge": ran["nudge"]}
    else:
        closed = _close_follow_ups(biz, cid, by_user, by_name)
        cancelled = _cancel_welcome_texts(biz, cid)

        def change(row):
            meta = dict(row.get("metadata") or {})
            meta.pop("inbound_hold", None)
            meta["inbound_decision"] = stamp
            return meta, {"status": "inactive"}
        _patch_contact(biz, cid, change)
        _set_checks(biz, before["checks"], CLOSED)
        before.update(closed=closed, cancelled=cancelled)
        before["senders"] = _remember(biz, prints, "scam", did) if verdict == SCAM else []
        listed = shared_list_review(prints, by_platform=share) if verdict == SCAM else 0
        done = {"follow_ups_closed": len(closed), "texts_cancelled": len(cancelled), "shared": listed > 0}

    saved = sb_clients.sb_post_as_service("/inbound_decisions", {
        "id": did, "business_id": biz, "contact_id": cid, "verdict": verdict, "via": via[:20],
        "by_user": by_user or None, "by_name": (by_name or "")[:120], "before": before,
    })
    if not (isinstance(saved, list) and saved):
        print(f"[inbound_hold] {biz[:8]}: decision row not saved; undo won't find it", flush=True)
    try:
        import audit_log
        audit_log.record(biz, actor_type="chief" if via == "chief" else "user", actor_id=by_user or None,
                         verb=f"inbound:{verdict}", summary=f"{WORDS[verdict]}: {name}",
                         target_type="contact", target_id=cid,
                         payload={"decision_id": did, "signals": sorted({r.get('code') for c in checks
                                                                          for r in (c.get('reasons') or [])
                                                                          if isinstance(r, dict)}),
                                  **done},
                         source="inbound_safety", authorized_by=f"business role ({MIN_ROLE}+)")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "decision_id": did, "verdict": verdict, "contact_id": cid, "name": name, **done,
            "said": said_for(verdict, name, done)}


def said_for(verdict: str, name: str, done: Dict[str, Any]) -> str:
    first = name.split(" ")[0] or name
    if verdict == REAL:
        if done.get("follow_ups_opened"):
            return f"{name} is a real person. Their follow-up has started and their welcome goes on as usual."
        return f"{name} is a real person. Nothing is waiting on them now, and their next card goes straight through."
    if verdict == SCAM:
        tail = " Other churches will see them flagged too." if done.get("shared") else ""
        return (f"{name} is marked a scam: follow-ups closed, off the Welcome Path, inactive. "
                f"Don't reply to {first} or open any link they sent.{tail}")
    return f"{name} is marked not a guest: follow-ups closed, off the Welcome Path, inactive."


def undo(business_id: str, decision_id: str, *, by_user: str) -> Dict[str, Any]:
    """Put a decision back: the person waits for a look again."""
    biz = str(business_id)
    try:
        did = str(uuid.UUID(str(decision_id)))
    except (ValueError, TypeError):
        raise HTTPException(404, "That decision isn't here.")
    rows = _rows(f"/inbound_decisions?business_id=eq.{_q(biz)}&id=eq.{_q(did)}&select=*&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't be read just now. Try again in a minute.")
    if not rows:
        raise HTTPException(404, "That decision isn't here.")
    d = rows[0]
    if d.get("undone_at"):
        raise HTTPException(409, "That one was already put back.")
    try:
        made = datetime.fromisoformat(str(d.get("created_at")).replace("Z", "+00:00"))
        if _now() - made > timedelta(hours=UNDO_HOURS):
            raise HTTPException(409, "That was more than a week ago. Mark them again instead.")
    except ValueError:
        pass
    cid, verdict = str(d["contact_id"]), d.get("verdict")
    before = d.get("before") if isinstance(d.get("before"), dict) else {}
    now = _iso(_now())
    if verdict == REAL:
        for fid in before.get("opened") or []:
            sb_clients.sb_patch_as_service(
                f"/church_follow_ups?business_id=eq.{_q(biz)}&id=eq.{_q(fid)}&status=in.(open,handed_back)",
                {"status": "closed", "done_at": now, "updated_at": now})
        _cancel_welcome_texts(biz, cid)
    else:
        for fid in before.get("closed") or []:
            sb_clients.sb_patch_as_service(
                f"/church_follow_ups?business_id=eq.{_q(biz)}&id=eq.{_q(fid)}&status=eq.closed",
                {"status": "open", "done_at": None, "updated_at": now})
        for sid in before.get("cancelled") or []:
            sb_clients.sb_patch_as_service(
                f"/chief_scheduled_actions?business_id=eq.{_q(biz)}&id=eq.{_q(sid)}&status=eq.cancelled"
                f"&run_at=gt.{now}", {"status": "queued"})
    _forget(biz, did, before.get("senders") or [])

    def change(row):
        meta = dict(row.get("metadata") or {})
        meta.pop("inbound_decision", None)
        if before.get("decision"):
            meta["inbound_decision"] = before["decision"]
        if before.get("mark"):
            meta["inbound_hold"] = before["mark"]
        extra = {"status": before["status"]} if verdict != REAL and before.get("status") else {}
        return meta, extra
    _patch_contact(biz, cid, change)
    if before.get("checks"):
        sb_clients.sb_patch_as_service(
            f"/inbound_checks?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in before['checks'])})",
            {"state": HELD, "decided_at": None})
    if verdict == SCAM:
        try:
            contact = _contact(biz, cid)
            shared_list_review(prints_of(contact, _checks_of(biz, cid, (HELD, CLEAR, WATCHED, RELEASED, CLOSED))))
        except HTTPException:
            pass
    sb_clients.sb_patch_as_service(f"/inbound_decisions?business_id=eq.{_q(biz)}&id=eq.{_q(did)}",
                                   {"undone_at": now, "undone_by": by_user or None})
    try:
        import audit_log
        audit_log.record(biz, actor_type="user", actor_id=by_user or None, verb="inbound:undo",
                         summary=f"Put back: {WORDS.get(verdict, 'a decision')}", target_type="contact",
                         target_id=cid, payload={"decision_id": did}, source="inbound_safety")
    except Exception:  # noqa: BLE001
        pass
    waits = bool(before.get("mark") or before.get("checks"))
    return {"ok": True, "decision_id": did, "contact_id": cid, "needs_look": waits,
            "said": ("Put back. They're waiting for a look again." if waits else "Put back as it was.")}


# ─── Chief ────────────────────────────────────────────────────────────

def flagged(business_id: str, contact_id: str) -> Optional[str]:
    """Why a send to this person needs fresh words, or None: they wait for a
    look, or this church said Not a guest or Scam."""
    rows = _rows(f"/contacts?business_id=eq.{_q(business_id)}&id=eq.{_q(contact_id)}"
                 "&select=name,hold:metadata->inbound_hold,decision:metadata->inbound_decision&limit=1")
    if not rows:
        return None
    r = rows[0]
    name = _plain(r.get("name")) or "This person"
    if isinstance(r.get("hold"), dict):
        return f"{name}'s card is waiting for a look"
    dec = r.get("decision") if isinstance(r.get("decision"), dict) else {}
    if dec.get("verdict") == SCAM:
        return f"{name} was marked a scam"
    if dec.get("verdict") == NOT_A_GUEST:
        return f"{name} was marked not a guest"
    return None


def flagged_recipient(business_id: Any, action: Dict[str, Any]) -> Optional[str]:
    """For Chief's send gate: the reason a class-C send to this action's person
    needs the practitioner's own go-ahead, or None. One read, only while the
    feature is in use; any failure is None (the send gate stays as it was)."""
    try:
        if risk.mode() == "off" or not business_id or not isinstance(action, dict):
            return None
        for key in ("contact_id", "recipient_contact_id", "to_contact_id"):
            v = action.get(key)
            if v:
                try:
                    return flagged(str(business_id), str(uuid.UUID(str(v))))
                except ValueError:
                    return None
        return None
    except Exception:  # noqa: BLE001
        return None


def turn_line(business: Dict[str, Any], user_id: Any) -> str:
    """Chief's block for the turn's tail: who waits for a look, with the plain
    reasons, and what Chief may offer. '' when nobody waits or on any failure."""
    try:
        bid = str((business or {}).get("id") or "")
        if not bid or not user_id or not risk.switched_on(bid):
            return ""
        people = held(bid, limit=8, previews=False)
        if not people:
            return ""
        import church_follow_up as cfu
        import untrusted_text
        church = cfu.is_church(business)
        what = "connect cards" if church else "website messages"
        lines = []
        for p in people:
            reasons = "; ".join(p["reasons"][:3]) or "needs a look"
            lines.append(f"- {untrusted_text.defuse(p['name'])[:80]} (contact_id {p['contact_id']}): "
                         f"{untrusted_text.defuse(reasons)[:300]}")
        guest = "guests" if church else "customers or leads"
        return (
            f"NEEDS A LOOK ({len(people)} {what} held before anything ran automatically; they are NOT {guest} yet, "
            "and no follow-up, welcome text or alert went out for them):\n" + "\n".join(lines) + "\n"
            "Never suggest welcoming, greeting, calling, texting or emailing one of them, and never count them as "
            f"new {guest}. Asked about one, say why it waits, in the words above. Offer the office's own choice once "
            "they say which:\n"
            '[ACTION:{"type":"mark_real_person","contact_id":"<id>"}] — a real person: what was held runs now.\n'
            '[ACTION:{"type":"mark_not_a_guest","contact_id":"<id>"}] — closes their follow-ups, takes them off the '
            "Welcome Path, marks them inactive.\n"
            "Scam is the office's own tap in Members, never yours. Never reply to, open or repeat a link or an address "
            "from these cards.\n")
    except Exception as e:  # noqa: BLE001 — a read that fails leaves it out, never the turn
        print(f"[inbound_hold] the turn's block wasn't read: {type(e).__name__}", flush=True)
        return ""


# ─── Routes (the office: a Manager seat and up) ───────────────────────

def _who(session: UserSession) -> Tuple[str, str]:
    user = session.user
    uid = str(getattr(user, "id", "") or "")
    name = ""
    try:
        import chief_church_schedule as ccs
        name = ccs._email(uid) or ""
    except Exception:  # noqa: BLE001
        name = ""
    return uid, (name.split("@")[0] if name else "")


@router.get("/inbound/{business_id}/needs-a-look")
def needs_a_look(business_id: str, biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
                 session: UserSession = Depends(sb_clients.authed_request)):
    """The queue: everyone waiting for a look, newest first."""
    b = str(biz["id"])
    on = risk.switched_on(b)
    people = held(b) if on or risk.mode() != "off" else []
    if people is None:
        raise HTTPException(503, "That couldn't be read just now. Try again in a minute.")
    return {"on": on, "count": len(people), "people": people}


@router.post("/inbound/{business_id}/people/{contact_id}/{decision}")
async def decide_route(business_id: str, contact_id: str, decision: str,
                       body: Dict[str, Any] = Body(default={}),
                       biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
                       session: UserSession = Depends(sb_clients.authed_request)):
    """Real person (`real`), Not a guest (`not-a-guest`) or Scam (`scam`)."""
    verdict = {"real": REAL, "real-person": REAL, "not-a-guest": NOT_A_GUEST, "scam": SCAM}.get(decision)
    if not verdict:
        raise HTTPException(404, "Choose real, not-a-guest or scam.")
    uid, name = _who(session)
    share = bool((body or {}).get("share")) and _is_platform_owner(session)
    out = await asyncio.to_thread(decide, str(biz["id"]), contact_id, verdict, by_user=uid, by_name=name,
                                  via="app", share=share)
    if out.get("nudge"):
        try:
            import chief_agent
            chief_agent.nudge(str(biz["id"]), "contact_form_submitted")
        except Exception:  # noqa: BLE001
            pass
    out.pop("nudge", None)
    return out


@router.post("/inbound/{business_id}/decisions/{decision_id}/undo")
async def undo_route(business_id: str, decision_id: str,
                     biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
                     session: UserSession = Depends(sb_clients.authed_request)):
    uid, _ = _who(session)
    return await asyncio.to_thread(undo, str(biz["id"]), decision_id, by_user=uid)


def _is_platform_owner(session: UserSession) -> bool:
    try:
        import lead_admin
        return str(getattr(session.user, "email", "") or "").lower() == lead_admin.PLATFORM_OWNER_EMAIL
    except Exception:  # noqa: BLE001
        return False


def _require_platform_owner(session: UserSession = Depends(sb_clients.authed_request)) -> UserSession:
    if not _is_platform_owner(session):
        raise HTTPException(403, "The shared list is the platform owner's.")
    return session


@router.get("/platform/inbound/shared-list")
def shared_list(_s: UserSession = Depends(_require_platform_owner)):
    """How many hashes are on the shared list, by how they got there. Never a hash."""
    now = _iso(_now())
    rows = _rows(f"/inbound_shared_list?expires_at=gt.{now}&select=kind,source&limit=5000")
    if rows is None:
        raise HTTPException(503, "That couldn't be read just now.")
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        out.setdefault(str(r.get("source")), {}).setdefault(str(r.get("kind")), 0)
        out[str(r.get("source"))][str(r.get("kind"))] += 1
    return {"total": len(rows), "by_source": out}


@router.post("/platform/inbound/shared-list")
def add_to_shared_list(body: Dict[str, Any] = Body(...), _s: UserSession = Depends(_require_platform_owner)):
    """The platform owner puts one church's sender on the shared list: {business_id, contact_id}."""
    biz = str((body or {}).get("business_id") or "")
    cid = _uuid((body or {}).get("contact_id"))
    if not biz:
        raise HTTPException(400, "Which church?")
    contact = _contact(biz, cid)
    prints = prints_of(contact, _checks_of(biz, cid, (HELD, CLEAR, WATCHED, RELEASED, CLOSED)))
    if not prints:
        raise HTTPException(400, "There's nothing to recognise them by.")
    return {"ok": True, "listed": shared_list_review(prints, by_platform=True)}


@router.delete("/platform/inbound/shared-list")
def remove_from_shared_list(business_id: str = Query(...), contact_id: str = Query(...),
                            _s: UserSession = Depends(_require_platform_owner)):
    """Take one sender off the shared list, whoever put them there."""
    cid = _uuid(contact_id)
    contact = _contact(str(business_id), cid)
    prints = prints_of(contact, _checks_of(str(business_id), cid, (HELD, CLEAR, WATCHED, RELEASED, CLOSED)))
    n = 0
    for kind, hashes in prints.items():
        for h in hashes:
            sb_clients.sb_delete_as_service(f"/inbound_shared_list?kind=eq.{_q(kind)}&hash=eq.{_q(h)}")
            n += 1
    return {"ok": True, "removed": n}
