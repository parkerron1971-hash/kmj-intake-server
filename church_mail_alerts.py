"""church_mail_alerts.py — new church mail lets the person know.

Kevin, 2026-11-14, on the mock (artifact 1fGHqCVMe9fxwceAbjbaJZ): "I love the
design. lets build it". He had asked for it once copies to people's own
email can be off: then nothing told them mail had come.

What it does:
  * When a message lands in a church box (church_mail.deliver), its row gets
    alert_at. Outside the church's quiet hours (member_push.quiet_hour, the
    hours the church set under Text) the alert goes out at once; inside them
    it waits, and the sweep sends it when they end, several from one box as
    one ("Office · 3 new").
  * Who hears: whoever the box reaches right now (church_mail.reach), each by
    their own choice (church_mail_people): all (default), mine (their own box
    only) or off; and phone alerts on or off. Nobody hears about a message
    they've already opened, archived or that was deleted.
  * Never alerts: held mail, prayer@ (the Prayer list has its own), replies
    to a copy that went out as the box (church_mail.relay_reply), anything
    from before this existed (alert_at null).
  * The bell isn't a second copy that could drift: GET /church-mail/alerts
    (church_mail_room) lists the person's recent new mail straight from
    church_mail, so an answer clears it for everyone on a shared box.
  * Trash: rows deleted more than 30 days ago are deleted for good.

Every write claims first (alerted_at is null), so the at-once path and the
sweep can't both send the same alert. Push is best effort: no keys, no
devices, a failed send, and the mail is still there in Email.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import church_mail as cm
import sb_clients

logger = logging.getLogger(__name__)

MODES = ("all", "mine", "off")
STALE_HOURS = 24
TRASH_DAYS = 30
SWEEP_ROWS = 300
_ALERT_ROW = "id,business_id,mailbox_id,to_address,from_email,from_name,subject,body_text,read_by,archived_by,deleted_at,alert_at,alerted_at,outcome,direction"


def _q(v: Any) -> str:
    return cm._q(v)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


# ─── A person's choice ───────────────────────────────────────────────

def clean_mode(v: Any) -> str:
    return v if v in MODES else "all"


def prefs(church_id: str, uids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """uid → {mode, push, bell}. A read that fails is everyone's default
    (all, on, on): an alert too many, never mail nobody hears about."""
    ids = sorted({str(u) for u in uids if u})
    out = {u: {"mode": "all", "push": True, "bell": True} for u in ids}
    if not ids:
        return out
    rows = sb_clients.sb_get_as_service(
        f"/church_mail_people?business_id=eq.{_q(church_id)}&user_id=in.({','.join(_q(u) for u in ids)})"
        "&select=user_id,alerts,alert_push,alert_bell&limit=200")
    if isinstance(rows, list):
        for r in rows:
            uid = str(r.get("user_id") or "")
            if uid in out:
                out[uid] = {"mode": clean_mode(r.get("alerts")), "push": r.get("alert_push") is not False,
                            "bell": r.get("alert_bell") is not False}
    return out


def quiet_words(biz: Dict[str, Any]) -> str:
    """'9 PM to 7 AM': the church's quiet hours, as the alert settings say them."""
    try:
        import texting_hours as th
        h = th.of(biz)
        return f"{th.hour_words(h['quiet_from'])} to {th.hour_words(h['quiet_until'])}"
    except Exception:  # noqa: BLE001
        return "9 PM to 7 AM"


def quiet_now(biz: Dict[str, Any]) -> bool:
    try:
        import member_push
        return bool(member_push.quiet_hour(biz))
    except Exception:  # noqa: BLE001 — a clock nobody can read never holds mail back
        return False


# ─── Where a message sits, and who it reaches ────────────────────────

def _box_of(church: cm.Church, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mid = str(row.get("mailbox_id") or "")
    boxes = church.boxes()
    box = next((b for b in boxes if str(b["id"]) == mid), None) if mid else None
    return box or church.catch_all()


def tray_id(box: Optional[Dict[str, Any]]) -> str:
    return f"box:{box['id']}" if box else "other"


def owns(church: cm.Church, box: Optional[Dict[str, Any]], uid: str) -> bool:
    if not box or box.get("kind") != "person":
        return False
    if str(box.get("user_id") or "") == uid:
        return True
    contact = str((church.seats().get(uid) or {}).get("contact_id") or "")
    return bool(contact and str(box.get("contact_id") or "") == contact)


def box_label(box: Optional[Dict[str, Any]]) -> str:
    return str(box["local"]).capitalize() if box else "Other addresses"


def readers(church: cm.Church, box: Optional[Dict[str, Any]]) -> List[str]:
    where = cm.reach(church, box)
    if where.get("prayer"):
        return []
    return sorted({str(t["user_id"]) for t in where.get("to") or [] if t.get("user_id")})


# ─── Sending ─────────────────────────────────────────────────────────

def _claim(row_id: str) -> bool:
    got = sb_clients.sb_patch_as_service(f"/church_mail?id=eq.{_q(row_id)}&alerted_at=is.null",
                                         {"alerted_at": _iso(_now())})
    return isinstance(got, list) and len(got) > 0


def _who(row: Dict[str, Any]) -> str:
    return cm._plain(row.get("from_name"), 80) or cm._plain(row.get("from_email"), 120) or "Someone"


def _snippet(row: Dict[str, Any], n: int = 110) -> str:
    """The first words they wrote: the quoted email under a reply left out,
    on one line, cut at a word."""
    text = str(row.get("body_text") or "")
    try:
        import email_sender
        text = email_sender._strip_quoted_reply(text) or text
    except Exception:  # noqa: BLE001
        pass
    one = " ".join(text.split())
    if len(one) <= n:
        return one
    cut = one[:n].rsplit(" ", 1)[0] or one[:n]
    return cut.rstrip(",.;:-") + "…"


def words(rows: List[Dict[str, Any]], label: str, own: bool) -> Tuple[str, str]:
    """The alert as a phone shows it (Kevin, 2026-11-14: "make sure the
    notification briefly looks right"). One message reads like any mail
    app's: who it's from (and the shared box, when it's not their own), then
    the subject, then the first line they wrote. Several from one box (after
    quiet hours) list who and what, three at most."""
    first = rows[0]
    if len(rows) == 1:
        subject = cm._plain(first.get("subject"), 120) or "(no subject)"
        title = _who(first) if own else f"{_who(first)} · {label}"
        snip = _snippet(first)
        return title, f"{subject}\n{snip}" if snip else subject
    lines = [f"{_who(r)}: {cm._plain(r.get('subject'), 80) or '(no subject)'}" for r in rows[:3]]
    if len(rows) > 3:
        lines.append(f"and {len(rows) - 3} more")
    return f"{label} · {len(rows)} new emails", "\n".join(lines)


def send(church: cm.Church, rows: List[Dict[str, Any]]) -> int:
    """Alert whoever each message reaches now, by their choice. Returns how
    many alerts went to a device."""
    import push_notifications
    claimed: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("deleted_at") or r.get("outcome") not in ("copied", "stored", "failed") \
                or (r.get("direction") or "in") != "in":
            _claim(str(r["id"]))  # never alerts; settle it so it isn't read again
            continue
        if _claim(str(r["id"])):
            claimed.append(r)
    if not claimed:
        return 0
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in claimed:
        box = _box_of(church, r)
        try:
            who = readers(church, box)
        except cm.Unavailable:
            continue
        read = {str(u) for u in r.get("read_by") or []}
        put_away = {str(u) for u in r.get("archived_by") or []}
        for uid in who:
            if uid in read or uid in put_away:
                continue
            g = groups.setdefault((uid, tray_id(box)), {"box": box, "rows": []})
            g["rows"].append(r)
    if not groups:
        return 0
    choice = prefs(church.id, {u for u, _ in groups})
    sent = 0
    for (uid, tray), g in groups.items():
        p = choice.get(uid) or {"mode": "all", "push": True}
        own = owns(church, g["box"], uid)
        if p["mode"] == "off" or not p["push"] or (p["mode"] == "mine" and not own):
            continue
        rs = sorted(g["rows"], key=lambda x: str(x.get("alert_at") or ""), reverse=True)
        title, body = words(rs, box_label(g["box"]), own)
        # One email, one alert (each makes its sound); several at once share
        # the box's, and a newer group replaces it.
        tag = f"church-mail-{rs[0]['id']}" if len(rs) == 1 else f"church-mail-{tray}"
        # The church it's from rides along: a tap opens that church's Email on
        # the message, whichever business the device was last signed up from.
        data = {"tray": tray, "biz": church.id}
        if len(rs) == 1:
            data["mail"] = str(rs[0]["id"])
        try:
            # Every device the person turned alerts on for, whatever business
            # it was signed up from (a device keeps one business, and an
            # owner of two would otherwise hear one church's mail on none of
            # them: Kevin, 2026-11-14, "it didn't pop up on my phone").
            sent += push_notifications.send_to_user(uid, title=title, body=body, nav="operate:email",
                                                    tag=tag, data=data)
        except Exception as e:  # noqa: BLE001 — the mail is in Email either way
            logger.warning("church mail alert to %s failed: %s", uid[:8], e)
    return sent


def on_new(church: cm.Church, row_id: str) -> None:
    """A message just landed in a box: make its alert due, and send it now
    unless it's the church's quiet hours (then the sweep sends it after)."""
    due = sb_clients.sb_patch_as_service(f"/church_mail?id=eq.{_q(row_id)}&alert_at=is.null",
                                         {"alert_at": _iso(_now())})
    if not isinstance(due, list) or not due or quiet_now(church.biz):
        return
    rows = sb_clients.sb_get_as_service(f"/church_mail?id=eq.{_q(row_id)}&select={_ALERT_ROW}&limit=1")
    if isinstance(rows, list) and rows:
        send(church, rows)


# ─── The sweeps (worker) ─────────────────────────────────────────────

def sweep() -> Dict[str, Any]:
    """Every few minutes: alerts that waited out quiet hours (or missed the
    at-once send), grouped by church. Never raises."""
    now = _now()
    rows = sb_clients.sb_get_as_service(
        f"/church_mail?alerted_at=is.null&alert_at=lte.{_q(_iso(now))}&select={_ALERT_ROW}"
        f"&order=alert_at.asc&limit={SWEEP_ROWS}")
    if not isinstance(rows, list) or not rows:
        return {"due": 0}
    stale_before = _iso(now - timedelta(hours=STALE_HOURS))
    by_church: Dict[str, List[Dict[str, Any]]] = {}
    stale = 0
    for r in rows:
        if str(r.get("alert_at") or "") < stale_before:
            _claim(str(r["id"]))  # a day late is no alert at all
            stale += 1
            continue
        by_church.setdefault(str(r["business_id"]), []).append(r)
    sent = held = 0
    for church_id, rs in by_church.items():
        try:
            got = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{_q(church_id)}&select=id,name,type,owner_id,settings&limit=1")
            if not isinstance(got, list) or not got:
                continue
            church = cm.Church(got[0])
            if quiet_now(church.biz):
                held += len(rs)
                continue
            sent += send(church, rs)
        except Exception as e:  # noqa: BLE001 — one church never stops the rest
            logger.warning("church mail alert sweep for %s failed: %s", church_id[:8], e)
    return {"due": len(rows), "sent": sent, "waiting": held, "stale": stale}


def trash_sweep() -> Dict[str, Any]:
    """Deleted more than 30 days ago: gone for good."""
    cutoff = _iso(_now() - timedelta(days=TRASH_DAYS))
    got = sb_clients.sb_delete_as_service(f"/church_mail?deleted_at=lt.{_q(cutoff)}")
    return {"ok": bool(got)}
