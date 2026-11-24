"""chief_turns_by_login.py — whether Chief's saved turns keep who asked, and whose a read is.

A saved turn (public.chief_conversations) keeps the login that asked once
supabase/APPLY-2026-11-24-chief-conversations-by-login.sql is applied. Three
places have to agree on whether that is so: the save (chief_of_staff._archive_turn),
the recall (chief_of_staff._recall_whose) and the nightly pass
(chief_brain_pass.gather). Two of them read as the server, where no row rule
holds anyone back, so "couldn't tell" must never be read as "no login is kept":
that would hand an outside surface the team's conversations unnamed, and teach
Chief from an office login's words as if they were the owner's.

    keeps_login() .. True: the column answers (remembered for good: a column
                     doesn't go away). False: the table answers and the
                     column doesn't (kept ABSENT_SECONDS, then asked again).
                     None: couldn't tell just now.
    on() ........... CHIEF_TURNS_BY_LOGIN: on (the default) | off. Off, the
                     server stops saving turns itself and a turn is saved as
                     the person again (the owner's lands, an office login's
                     is refused, as before 2026-11-24). It only stops the
                     SAVE: every read keeps to whose it is for as long as
                     the column is there.
    owners_own() ... the filter for the owner's own rows: the owner's, and
                     the ones with no login (saved before a login was kept,
                     or by the owner's own app).
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional
from urllib.parse import quote

ABSENT_SECONDS = 600
_STATE = {"seen": False, "absent_at": 0.0}


def on() -> bool:
    return (os.environ.get("CHIEF_TURNS_BY_LOGIN") or "on").strip().lower() != "off"


def forget() -> None:
    """Tests only."""
    _STATE.update(seen=False, absent_at=0.0)


def keeps_login() -> Optional[bool]:
    """Whether chief_conversations keeps who asked: True, False or None
    (couldn't tell). With no database configured (a test, a local run), False:
    everything is as it always was."""
    if _STATE["seen"]:
        return True
    if not os.environ.get("SUPABASE_URL"):
        return False
    if _STATE["absent_at"] and time.monotonic() - _STATE["absent_at"] < ABSENT_SECONDS:
        return False
    import sb_clients
    try:
        col = sb_clients.sb_get_as_service("/chief_conversations?select=user_id&limit=1")
    except Exception:  # noqa: BLE001
        col = None
    if isinstance(col, list):
        _STATE["seen"] = True
        return True
    # The column didn't answer. Is it not there, or did the read fail? The table's own id says.
    try:
        base = sb_clients.sb_get_as_service("/chief_conversations?select=id&limit=1")
    except Exception:  # noqa: BLE001
        base = None
    if isinstance(base, list):
        _STATE["absent_at"] = time.monotonic()
        return False
    return None


def owners_own(owner_id: Any) -> str:
    """The query filter for the owner's own rows."""
    owner = str(owner_id or "")
    return f"&or=(user_id.is.null,user_id.eq.{quote(owner, safe='')})" if owner else "&user_id=is.null"
