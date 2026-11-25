"""
messaging_everyone.py — one switch: every adult with a birthday on their
record can use member messaging.

Kevin, 2026-11-24: "can you create a simple toggle that would work to turn
on all member messaging. this would be for numbers that filled out date of
birth." His answers: automatic (now, and as birthdays are added later),
adults only (teens stay one by one, so the office links their parents
first), and only the birthday on their record (contacts.birthdate, which the
office enters or checks; a birthday typed in the app never opens messaging:
member_posts, 2026-11-20).

  settings.messaging.adults_with_birthday   True while the switch is on

HOW. The per-person switch (msg_members.enabled) stays the one thing every
reader checks (member_messaging_rules.can_message, the directory, alerts,
the office's People list), so this module only writes those switches:

  * on: every contact 18 or over by contacts.birthdate WITHOUT a msg_members
    row gets one, enabled, marked enabled_by=BY_SWITCH. A row that exists is
    never touched, so someone the office switched off, or the Safety room
    paused, stays off. Rows this switch turned off before (enabled_by
    BY_SWITCH_OFF) come back on.
  * the sweep (sweep_tick, every 15 minutes) does the same for each church
    with the switch on, so a birthday added later, or a teen turning 18,
    opens messaging without anyone pressing anything.
  * off: only what the switch turned on goes off (enabled_by BY_SWITCH and
    still on), marked BY_SWITCH_OFF. Anyone the office turned on by hand
    stays on.

The server's own writes carry no signed-in user, so the database's grant
guard (APPLY-2026-10-02-messaging.sql: turning messaging ON is a manager's
call) doesn't apply to them; the switch itself is changed only by the chat
rules' keeper (messaging_router._chat_rules_keeper: the owner, an admin, or
whoever has the chat rules). Messaging still opens only once the church
turns it on with its two safety officers, and teens are never added.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("messaging_everyone")

KEY = "adults_with_birthday"
# enabled_by markers (msg_members.enabled_by is a plain uuid, no reference):
BY_SWITCH = "00000000-0000-0000-0000-00000000a0a1"       # turned on by this switch
BY_SWITCH_OFF = "00000000-0000-0000-0000-00000000a0a0"   # turned off by this switch going off
PAGE = 1000
WRITE_CHUNK = 200


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def on(business: Dict[str, Any]) -> bool:
    s = (business or {}).get("settings")
    m = s.get("messaging") if isinstance(s, dict) else None
    return isinstance(m, dict) and m.get(KEY) is True


def _adults(business_id: str, today: Optional[date] = None) -> Optional[List[str]]:
    """Contacts 18 or over by the birthday on their record. None on a failed read."""
    import member_messaging_rules as rules
    out: List[str] = []
    offset = 0
    while True:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&birthdate=not.is.null&select=id,birthdate"
            f"&order=id.asc&limit={PAGE}&offset={offset}")
        if rows is None:
            return None
        for r in rows:
            a = rules.age(r.get("birthdate"), today)
            if a is not None and a >= rules.ADULT_AGE:
                out.append(str(r["id"]))
        if len(rows) < PAGE:
            return out
        offset += PAGE


def _rows(business_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Any]] = {}
    offset = 0
    while True:
        rows = sb_clients.sb_get_as_service(
            f"/msg_members?business_id=eq.{_q(business_id)}&select=contact_id,enabled,enabled_by"
            f"&order=contact_id.asc&limit={PAGE}&offset={offset}")
        if rows is None:
            return None
        out.update({str(r["contact_id"]): r for r in rows})
        if len(rows) < PAGE:
            return out
        offset += PAGE


def _ids(ids: List[str]) -> str:
    return ",".join(_q(i) for i in ids)


def open_for_adults(business_id: str, today: Optional[date] = None) -> Optional[int]:
    """Turn messaging on for every adult with a birthday on record who has no
    switch yet, and back on for those this switch turned off. How many were
    turned on; None when a read or write failed."""
    adults = _adults(business_id, today)
    rows = _rows(business_id) if adults is not None else None
    if adults is None or rows is None:
        return None
    now = _now()
    new = [c for c in adults if c not in rows]
    back = [c for c in adults if c in rows and not rows[c].get("enabled")
            and str(rows[c].get("enabled_by") or "") == BY_SWITCH_OFF]
    n = 0
    for i in range(0, len(new), WRITE_CHUNK):
        part = new[i:i + WRITE_CHUNK]
        # Every row carries the same keys (a bulk write with mixed keys loses
        # the chunk). ignore-duplicates: a switch someone set meanwhile wins.
        got = sb_clients.sb_post_as_service(
            "/msg_members?on_conflict=contact_id",
            [{"contact_id": c, "business_id": business_id, "enabled": True, "enabled_by": BY_SWITCH,
              "enabled_at": now, "updated_at": now} for c in part],
            prefer="resolution=ignore-duplicates,return=representation")
        if got is None:
            return None
        n += len(got)
    for i in range(0, len(back), WRITE_CHUNK):
        part = back[i:i + WRITE_CHUNK]
        got = sb_clients.sb_patch_as_service(
            f"/msg_members?business_id=eq.{_q(business_id)}&contact_id=in.({_ids(part)})"
            f"&enabled=eq.false&enabled_by=eq.{BY_SWITCH_OFF}",
            {"enabled": True, "enabled_by": BY_SWITCH, "enabled_at": now, "updated_at": now})
        if got is None:
            return None
        n += len(got)
    return n


def close_what_it_opened(business_id: str) -> Optional[int]:
    """The switch goes off: only the people it turned on go off. How many;
    None when the write failed."""
    got = sb_clients.sb_patch_as_service(
        f"/msg_members?business_id=eq.{_q(business_id)}&enabled=eq.true&enabled_by=eq.{BY_SWITCH}",
        {"enabled": False, "enabled_by": BY_SWITCH_OFF, "updated_at": _now()})
    return None if got is None else len(got)


def counts(business_id: str, today: Optional[date] = None) -> Optional[Dict[str, int]]:
    """For the office: adults with a birthday on record, and how many of them
    can message. None on a failed read."""
    adults = _adults(business_id, today)
    rows = _rows(business_id) if adults is not None else None
    if adults is None or rows is None:
        return None
    on_ = sum(1 for c in adults if (rows.get(c) or {}).get("enabled"))
    return {"adults": len(adults), "adults_on": on_}


def sweep_tick() -> int:
    """Every church with the switch on: anyone who has become an adult with a
    birthday on record since the last pass is turned on. How many in all."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?settings->messaging->>{KEY}=eq.true&select=id&limit=2000")
    if not rows:
        return 0
    total = 0
    for b in rows:
        try:
            n = open_for_adults(str(b["id"]))
        except Exception:  # noqa: BLE001 — one church never stops the rest
            logger.warning("messaging everyone sweep failed", exc_info=True)
            continue
        if n:
            logger.info("messaging opened for adults with a birthday", extra={"business_id": b["id"], "n": n})
            total += n
    return total
