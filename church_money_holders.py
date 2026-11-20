"""church_money_holders.py — who holds the giving tick, as the server reads it.

Kevin, 2026-11-18 ("One sheet per person", step three): giving becomes its
own tick on a person's sheet, and a holder asks while the owner taps yes
("yes build with C"). The rows live in two server-only tables
(supabase/APPLY-2026-11-18-church-money-holders.sql):

    church_money_holders   one row a login a church: level see | work | lead,
                           who_gave, bank, and the seat it was given to
    church_money_asks      a request for a tick, waiting for the owner

THIS FILE DECIDES NOTHING. It is the two reads the money gate will make
(church_money_gate, the next PR, behind a switch), and nothing calls them
from a door yet. They are written first, and closed, so the gate has no way
to read a tick loosely:

    money_holder(business_id, user_id)   the tick this login holds on its
                                         ACTIVE seat, or None
    open_ask(business_id, user_id)       the ask waiting for the owner about
                                         this login, or None

A READ THAT FAILS IS "NO". Before the migration is applied the tables are
not there and PostgREST answers an error: that is None. A read that times
out is None. An id that is not a uuid is None without a read. Neither
function raises into a route, and neither ever answers for the owner, an
Admin or the accountant: those pass the gate on their own standing, with or
without a row here.

money_holder says exactly what the database's own church_money_tick says:
the row counts only on the seat it was given to (seat_id), while that seat
is active, and Work or Lead is read as See on a Viewer seat.

ONE SPELLING OF AN ID (2026-11-20). Postgres reads a uuid written with or
without hyphens, in upper or lower case, or in braces, as the same uuid, so
a door handed any of those spellings finds the same row. _id() turns each
of them into the one spelling these tables are filtered by (lower case,
hyphenated), and anything else into None, never a different id.

WHETHER THE TABLES ARE THERE (_READY, kept here because these reads see it
first): a read that PostgREST answers "no such table" (404, PGRST205,
42P01: the rollback dropped them) marks them gone at once
(tables_gone()); church_money_ticks.tables_ready() keeps a yes for ten
minutes at most.
"""
from __future__ import annotations

import datetime as _dt
import re
import time
import uuid
from typing import Any, Dict, Optional
from urllib.parse import quote

import sb_clients

HOLDERS = "church_money_holders"
ASKS = "church_money_asks"

LEVELS = ("see", "work", "lead")
WRITES = ("work", "lead")
# A seat that may change rows at all (tenant_writer_write, 2026-07-31): a
# Viewer never does, whatever its tick says.
WORKING_SEATS = ("member", "manager", "admin")

# The spellings Postgres's uuid type reads: 32 hex digits, a hyphen allowed
# after any group of four, the whole in braces or not, any case.
_UUID = re.compile(r"\{?[0-9a-f]{4}(?:-?[0-9a-f]{4}){7}\}?", re.I)

# Whether the two tables answer (church_money_ticks.tables_ready): `yes`,
# and the monotonic time that answer is kept until.
_READY: Dict[str, Any] = {"yes": False, "until": 0.0}
KEEP_YES_S = 600          # a yes is asked again after ten minutes
KEEP_NO_S = 300           # a no, after five
# What PostgREST says for a table that isn't there: 404 with PGRST205 (v12
# and later), or Postgres's own "relation does not exist".
MISSING_CODES = ("PGRST205", "42P01")


def _id(value: Any) -> Optional[str]:
    """The id in its one spelling (lower case, hyphenated), whichever of
    Postgres's spellings it came in; None for anything that isn't a uuid."""
    if isinstance(value, uuid.UUID):
        return str(value)
    text = "" if value is None else str(value).strip()
    if not _UUID.fullmatch(text):
        return None
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return None


def relation_missing(err: Any) -> bool:
    """Whether a PostgREST refusal (sb_clients.last_error()) says the table
    isn't there."""
    if not isinstance(err, dict):
        return False
    return str(err.get("code") or "") in MISSING_CODES or err.get("status") == 404


def tables_gone() -> None:
    """A read or write to either table was answered "no such table": no from
    now, asked again in five minutes."""
    _READY.update(yes=False, until=time.monotonic() + KEEP_NO_S)


def _q(value: str) -> str:
    return quote(value, safe="")


def _rows(path: str) -> Optional[list]:
    """The rows, or None when the read did not answer with a list. A read of
    either table answered "no such table" marks the tables gone."""
    try:
        got = sb_clients.sb_get_as_service(path)
    except Exception:  # noqa: BLE001 — a read that raised is a read that failed
        return None
    if isinstance(got, list):
        return got
    if path.startswith((f"/{HOLDERS}?", f"/{ASKS}?")) and relation_missing(sb_clients.last_error()):
        tables_gone()
    return None


def money_holder(business_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
    """The giving tick this login holds at this church, or None.

    None when there is no row, when either read fails, when the seat the tick
    was given to is no longer that person's active seat, or when the row says
    something this file does not know. The answer:

        level      "see" | "work" | "lead" as the owner gave it
        can_work   True when the level writes AND the seat is not a Viewer
        who_gave   may see who gave
        bank       may see the bank
        seat_role  the seat's role now
        granted_by, granted_at, ask_id   as stored
    """
    biz, uid = _id(business_id), _id(user_id)
    if not biz or not uid:
        return None
    held = _rows(f"/{HOLDERS}?business_id=eq.{_q(biz)}&user_id=eq.{_q(uid)}"
                 "&select=business_id,user_id,seat_id,level,who_gave,bank,granted_by,granted_at,ask_id&limit=1")
    if not held:
        return None
    row = held[0] if isinstance(held[0], dict) else {}
    seat_id, level = _id(row.get("seat_id")), row.get("level")
    if not seat_id or level not in LEVELS:
        return None
    if _id(row.get("business_id")) != biz or _id(row.get("user_id")) != uid:
        return None
    seats = _rows(f"/business_users?id=eq.{_q(seat_id)}&business_id=eq.{_q(biz)}&user_id=eq.{_q(uid)}"
                  "&status=eq.active&select=id,role,status&limit=1")
    if not seats or not isinstance(seats[0], dict):
        return None
    seat = seats[0]
    if _id(seat.get("id")) != seat_id or seat.get("status") != "active":
        return None
    role = seat.get("role")
    return {
        "level": level,
        "can_work": level in WRITES and role in WORKING_SEATS,
        "who_gave": row.get("who_gave") is True,
        "bank": row.get("bank") is True,
        "seat_role": role,
        "granted_by": row.get("granted_by"),
        "granted_at": row.get("granted_at"),
        "ask_id": row.get("ask_id"),
    }


def _when(value: Any) -> Optional[_dt.datetime]:
    try:
        at = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=_dt.timezone.utc)


def open_ask(business_id: Any, user_id: Any, now: Optional[_dt.datetime] = None) -> Optional[Dict[str, Any]]:
    """The ask waiting for the owner about this login, or None.

    None when there is none, when the read fails, or when the one found has
    run out (its status still says "asked" until the server marks it). An ask
    opens nothing: this is for showing "waiting for the pastor's yes", never
    for a decision.
    """
    biz, uid = _id(business_id), _id(user_id)
    if not biz or not uid:
        return None
    asks = _rows(f"/{ASKS}?business_id=eq.{_q(biz)}&user_id=eq.{_q(uid)}&status=eq.asked"
                 "&select=id,business_id,user_id,asked_by,wants,status,asked_at,expires_at,reminded_at"
                 "&order=asked_at.desc&limit=1")
    if not asks or not isinstance(asks[0], dict):
        return None
    ask = asks[0]
    if ask.get("status") != "asked" or _id(ask.get("business_id")) != biz or _id(ask.get("user_id")) != uid:
        return None
    ends = _when(ask.get("expires_at"))
    if ends is None or ends <= (now or _dt.datetime.now(_dt.timezone.utc)):
        return None
    wants = ask.get("wants") if isinstance(ask.get("wants"), dict) else {}
    if wants.get("level") not in LEVELS:
        return None
    return {
        "id": ask.get("id"),
        "asked_by": ask.get("asked_by"),
        "wants": {"level": wants["level"], "who_gave": wants.get("who_gave") is True,
                  "bank": wants.get("bank") is True},
        "asked_at": ask.get("asked_at"),
        "expires_at": ask.get("expires_at"),
        "reminded_at": ask.get("reminded_at"),
    }
