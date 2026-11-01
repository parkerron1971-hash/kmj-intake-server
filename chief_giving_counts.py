"""
chief_giving_counts.py: Chief and giving by service (Kevin, 2026-11-01).

  giving_counts          read: the counts (open first) with their totals, what
                         is coming up, and online gifts in no service.
  record_service_gifts   write: gifts the person names, into one service's
                         open count, dated its day ("record Sunday's: Grace
                         $100 check 1042, Marcus $50 cash, $83.50 loose").
                         Every name must be one of the church's people, or
                         loose / anonymous. If one isn't, nothing is
                         recorded and Chief asks.
  undo_service_gifts     takes one batch back while its count is still open
                         (the gifts are deleted; the books follow).

The same gate as the screen (giving_services._gate): finance people, behind
the giving keeper, where GIVING_SERVICES is on. Closing a count stays a
person's job: two counters sign for what they counted.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import sb_clients

NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "giving"}
MAX_GIFTS = 50
UNDO_DAYS = 7
LOOSE = {"loose", "loose offering", "loose cash", "plate", "plate cash"}
ANON = {"anonymous", "anon", "no name", "unknown", ""}


TOOL = {
    "name": "giving_counts",
    "description": (
        "Giving by service: this church's service counts, each service day's giving recorded together (open or "
        "closed, with its count_id), with its cash, checks, online gifts (already placed in the week's service) "
        "and apps; the services coming up; and online gifts in no service. Use it for 'what came in Sunday', "
        "'record Sunday's offering' (look first), 'is Sunday counted'. Quote its figures."),
    "input_schema": {"type": "object", "properties": {}},
}


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _chief(biz: Dict[str, Any], atype: str) -> Tuple[Optional[Dict[str, Any]], Any]:
    import giving_services as gs
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return _fail(atype, "giving by service is only for a signed-in person who keeps the giving records"), None
    user = SimpleNamespace(id=uid)
    try:
        gs._gate(str(biz["id"]), user)
    except HTTPException as e:
        if e.status_code == 404:
            return _fail(atype, "giving by service isn't switched on for this church yet"), None
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return _fail(atype, str(detail or "this login can't see the giving records")), None
    return None, user


def _day(iso: str) -> str:
    try:
        d = datetime.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


# ─── Reading ──────────────────────────────────────────────────────────

def counts_sync(biz_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import giving_services as gs
    atype = "giving_counts"
    fail, user = _chief({"id": biz_id}, atype)
    if fail:
        return fail
    try:
        data = gs.list_counts(biz_id, user)
    except HTTPException as e:
        return _fail(atype, str(e.detail.get("message") if isinstance(e.detail, dict) else e.detail))
    if not data["has_services"]:
        return {"type": atype, "result": "No services are set up for giving yet. In Bookkeeping, Giving, Giving by "
                                         "service, add them (for example every Sunday at 11:00 AM).",
                "label": "No services yet", "nav": NAV, "counts": []}
    lines = []
    for c in sorted(data["counts"], key=lambda c: (c["status"] != "open", c["date"]), reverse=False)[:12]:
        t = c["totals"]
        lines.append(f"- {c['name']}, {_day(c['date'])} [{c['status']}] count_id {c['id']}: {_money(t['all'])} in "
                     f"{t['gifts']} gift(s) (cash {_money(t['cash'])}, checks {_money(t['check'])}, "
                     f"online {_money(t['online'])}, apps and other {_money(t['other'])})")
    coming = "; ".join(f"{c['name']} {_day(c['date'])}" for c in data["coming"][:4]) or "none in the next two weeks"
    unplaced = data["unplaced"]
    tail = ("Online gifts in no service: couldn't be read just now." if unplaced is None
            else f"Online gifts in no service: {unplaced}." if unplaced else "")
    text = ("Service counts (open ones take gifts; a closed one is locked):\n" + "\n".join(lines)
            + f"\nComing up: {coming}." + (f"\n{tail}" if tail else ""))
    return {"type": atype, "result": text, "label": f"{len(data['counts'])} service counts", "nav": NAV,
            "counts": [{"id": c["id"], "name": c["name"], "date": c["date"], "status": c["status"],
                        "totals": c["totals"]} for c in data["counts"]]}


# ─── Recording ────────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(s or "").lower()).split())


def _people(contacts: List[Dict[str, Any]]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    full: Dict[str, List[str]] = {}
    ends: Dict[str, List[str]] = {}
    for c in contacts:
        n = _norm(c.get("name"))
        if not n:
            continue
        full.setdefault(n, []).append(str(c["id"]))
        p = n.split()
        if len(p) >= 2:
            ends.setdefault(f"{p[0]} {p[-1]}", []).append(str(c["id"]))
    return full, ends


def who(name: Any, full: Dict[str, List[str]], ends: Dict[str, List[str]]) -> Tuple[str, Optional[str]]:
    """('loose'|'anonymous'|'one'|'several'|'none', contact id)."""
    n = _norm(name)
    if n in LOOSE:
        return "loose", None
    if n in ANON:
        return "anonymous", None
    ids = full.get(n) or []
    if not ids and len(n.split()) >= 2:
        p = n.split()
        ids = ends.get(f"{p[0]} {p[-1]}") or []
    ids = sorted(set(ids))
    if len(ids) == 1:
        return "one", ids[0]
    return ("several" if ids else "none"), None


def _method(raw: Any, menu: List[Dict[str, str]]) -> Optional[str]:
    """A menu id from the person's word: the id or the label, any case."""
    t = " ".join(str(raw or "cash").split()).lower()
    for m in menu:
        if t in (m["id"].lower(), m["label"].lower()):
            return m["id"]
    if t in ("cheque", "checks"):
        return "check"
    if t in ("cash app", "cashapp"):
        return "cashapp" if any(m["id"] == "cashapp" for m in menu) else None
    return None


def _target(data: Dict[str, Any], action: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """The count to record into: count_id; else by date and/or service name;
    else the newest open count. Only an open count."""
    counts = data["counts"]
    cid = str(action.get("count_id") or "")
    if cid:
        hit = next((c for c in counts if c["id"] == cid), None)
        return (hit, "") if hit else (None, "that service count isn't among the last nine weeks")
    day = str(action.get("date") or "")[:10]
    name = _norm(action.get("service"))
    pool = [c for c in counts if (not day or c["date"] == day) and (not name or name in _norm(c["name"]))]
    open_ = [c for c in pool if c["status"] == "open"]
    if not pool:
        return None, "no service count matches that" + (f" ({day})" if day else "")
    if not open_:
        return None, "that service's count is closed; reopen it on the screen first"
    if len(open_) > 1:
        # Money never goes to a guessed service: ask, whatever was said.
        choices = ", ".join(f"{c['name']} {_day(c['date'])}" for c in open_[:6])
        return None, f"more than one open service count fits ({choices}). Say which service and date"
    return open_[0], ""


def record_sync(biz_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import giving_services as gs
    import giving_ways
    from giving_router import giving_settings
    atype = "record_service_gifts"
    fail, user = _chief({"id": biz_id}, atype)
    if fail:
        return fail
    gifts = action.get("gifts")
    if not isinstance(gifts, list) or not gifts:
        return _fail(atype, "say the gifts: each one's giver (or loose / anonymous), amount and how it was given")
    if len(gifts) > MAX_GIFTS:
        return _fail(atype, f"record up to {MAX_GIFTS} gifts at a time")
    try:
        data = gs.list_counts(biz_id, user)
        contacts = gs._need(f"/contacts?business_id=eq.{gs._q(biz_id)}&select=id,name&limit=10000")
        biz = gs._business(biz_id)
    except HTTPException as e:
        return _fail(atype, str(e.detail.get("message") if isinstance(e.detail, dict) else e.detail))
    count, why = _target(data, action)
    if not count:
        return _fail(atype, why)
    menu = giving_ways.method_menu(giving_ways.stored_ways(giving_settings(biz.get("settings"))))
    full, ends = _people(contacts)
    rows, unknown, several, bad = [], [], [], []
    for g in gifts:
        if not isinstance(g, dict):
            bad.append("a gift with no amount")
            continue
        try:
            cents = round(float(g.get("amount")) * 100)
        except (TypeError, ValueError):
            cents = 0
        kind, cid = who(g.get("name"), full, ends)
        method = _method(g.get("method"), menu)
        label = str(g.get("name") or "anonymous")
        if cents <= 0:
            bad.append(f"{label}: no amount")
        elif not method:
            bad.append(f"{label}: '{g.get('method')}' isn't one of your ways to give "
                       f"({', '.join(m['label'] for m in menu)})")
        if kind == "none":
            unknown.append(label)
        elif kind == "several":
            several.append(label)
        rows.append({"request_id": str(uuid.uuid4()), "amount_cents": cents, "fund": str(g.get("fund") or "General")[:40],
                     "method": method or "cash", "contact_id": cid, "loose": kind == "loose",
                     "check_number": str(g.get("check_number") or "") or None, "_label": label})
    problems = []
    if unknown:
        problems.append(f"I can't find {', '.join(unknown)} among your people (add them first, or say anonymous)")
    if several:
        problems.append(f"more than one person is named {', '.join(several)} (say the full name)")
    problems += bad
    if problems:
        return _fail(atype, "nothing was recorded: " + "; ".join(problems))
    labels = {r["request_id"]: r.pop("_label") for r in rows}
    try:
        out = gs.record_gifts(biz_id, count["id"], {"rows": rows}, user)
    except HTTPException as e:
        return _fail(atype, str(e.detail.get("message") if isinstance(e.detail, dict) else e.detail))
    saved = [r for r in out["results"] if r["ok"] and not r.get("already")]
    failed = [f"{labels.get(r['request_id'])}: {r.get('error')}" for r in out["results"] if not r["ok"]]
    total = sum(r["amount_cents"] for r in rows if any(s["request_id"] == r["request_id"] for s in saved))
    batch = str(uuid.uuid4())
    undo_ok = _log(biz_id, user.id, action, {"batch_id": batch, "count_id": count["id"],
                                             "gift_ids": [r["id"] for r in saved if r.get("id")]}) if saved else False
    text = f"Recorded {len(saved)} gift{'' if len(saved) == 1 else 's'} ({_money(total)}) to {count['name']}, {_day(count['date'])}."
    if failed:
        text += " Not recorded: " + "; ".join(failed) + "."
    if saved and not undo_ok:
        text += " (The record that lets me undo this couldn't be saved; correct a gift on the Giving screen if needed.)"
    res = {"type": atype, "result": text, "label": f"✓ {len(saved)} gifts to {count['name']}", "nav": NAV,
           "count_id": count["id"]}
    if saved and undo_ok:
        res["batch_id"] = batch
    if failed and not saved:
        res["failed"] = True
    return res


def _log(biz_id: str, user_id: Any, action: Dict[str, Any], out: Dict[str, Any]) -> bool:
    try:
        res = sb_clients.sb_post_as_service("/chief_undo_log", {
            "business_id": biz_id, "user_id": str(user_id), "action_type": "record_service_gifts",
            "action_json": action, "result_json": out, "status": "undoable"})
    except Exception as e:  # noqa: BLE001 — the gifts stand; only their undo is lost
        print(f"[chief_giving_counts] undo log write failed: {e}", flush=True)
        return False
    return bool(res)


def undo_sync(biz_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import giving_services as gs
    import period_lock
    atype = "undo_service_gifts"
    fail, user = _chief({"id": biz_id}, atype)
    if fail:
        return fail
    since = (datetime.now(timezone.utc) - timedelta(days=UNDO_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    logs = sb_clients.sb_get_as_service(
        f"/chief_undo_log?business_id=eq.{gs._q(biz_id)}&action_type=eq.record_service_gifts&status=eq.undoable"
        f"&created_at=gte.{since}&order=created_at.desc&limit=20&select=id,result_json")
    if logs is None:
        return _fail(atype, "the record of those gifts couldn't be read just now; nothing changed")
    want = str(action.get("batch_id") or "")
    log = next((r for r in logs if not want or (r.get("result_json") or {}).get("batch_id") == want), None)
    if not log:
        return _fail(atype, f"there are no gifts I recorded in the last {UNDO_DAYS} days left to take back")
    res = log["result_json"] or {}
    count_id, ids = str(res.get("count_id") or ""), [str(i) for i in res.get("gift_ids") or []]
    try:
        count = gs._count(biz_id, count_id)
    except HTTPException:
        return _fail(atype, "that service count can't be found")
    if count.get("status") != "open":
        return _fail(atype, f"{count.get('name')}'s count is closed; reopen it on the screen to take gifts out")
    try:
        period_lock.guard(biz_id, str(count.get("service_date"))[:10], source_type="giving_count", source_id=count_id,
                          reason=None, override_by=str(user.id))
    except HTTPException:
        return _fail(atype, "that day is in a closed period of the books; correct the gifts on the screen instead")
    try:
        if gs._count(biz_id, count_id).get("status") != "open":
            return _fail(atype, f"{count.get('name')}'s count was just closed; reopen it on the screen to take gifts out")
    except HTTPException:
        return _fail(atype, "that service count can't be read just now; nothing changed")
    if ids:
        ok = sb_clients.sb_delete_as_service(
            f"/invoices?business_id=eq.{gs._q(biz_id)}&giving_count_id=eq.{gs._q(count_id)}"
            f"&invoice_number=like.GIVE-manual-*&id=in.({','.join(gs._q(i) for i in ids)})")
        if not ok:
            return _fail(atype, "the gifts couldn't be taken back just now; nothing changed")
    marked = sb_clients.sb_patch_as_service(f"/chief_undo_log?id=eq.{log['id']}", {
        "status": "undone", "undone_at": datetime.now(timezone.utc).isoformat()})
    text = f"Took back {len(ids)} gift{'' if len(ids) == 1 else 's'} from {count.get('name')}."
    if not marked:
        # The gifts are gone; a second undo of this batch finds nothing to delete.
        print(f"[chief_giving_counts] undo log {log['id']} not marked undone", flush=True)
    return {"type": atype, "result": text, "label": f"↩ {len(ids)} gifts", "nav": NAV}


async def handle_giving_counts(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(counts_sync, str(biz["id"]), action or {})


async def handle_record_service_gifts(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(record_sync, str(biz["id"]), action or {})


async def handle_undo_service_gifts(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo_sync, str(biz["id"]), action or {})
