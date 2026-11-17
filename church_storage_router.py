"""
church_storage_router.py — the church's storage: how much is used, and
deleting a recording (church_storage.py has the meter and the rules).

A manager or the owner (the stream relay's check, kids_router.require):

  GET     /church/storage?business_id=
          {"enabled": false} while CHURCH_STORAGE is off for this church,
          or it isn't on a church plan (no allowance). Otherwise:
          {enabled, allowance_bytes, extra_bytes, used_bytes,
           parts: {recordings, classes, files}, files_counted, percent,
           state ("ok" | "near" at 80% | "full" at 100%), bytes_per_sunday,
           sundays_left, can_delete, can_download (false until downloads
           ship), recordings: [{session_id, started_at, duration_s, bytes,
           published, sermon_id, keep_until}] (ended, not removed, newest
           first, at most 50),
           extra_offer: {gb, cents, every, blocks, can_buy, trial}} (2026-11-17:
           more room is bought in blocks of `gb` (100) for `cents` each time
           the plan bills, `every` month, quarter or year; `blocks` is what
           the church bought, null when that can't be read; `can_buy` only
           for the owner, with the price set, on a paid church plan. The
           purchase itself is POST /billing/church/extra-storage).
  DELETE  /church/storage/recordings/{session_id}?business_id=
          404 while switched off or when the recording isn't this church's;
          409 while it is still being recorded, or when a published sermon
          carries it; 503 without the key that may delete, or when deleting
          its files didn't finish (nothing is marked; try again). Otherwise
          its files are deleted, it is marked removed, an unpublished
          sermon draft that carried it loses the link, and the answer is
          {"removed": true, "freed_bytes": n}. Deleting one already gone
          answers the same with 0.

Practitioner words only: no bucket, provider or database names.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

import church_storage as cs
import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import _uuid, require

router = APIRouter(tags=["church-storage"])

_METER = ("allowance_bytes", "extra_bytes", "used_bytes", "parts", "files_counted", "percent", "state",
          "bytes_per_sunday", "sundays_left")


def _unavailable() -> HTTPException:
    return HTTPException(503, "Storage couldn't load just now. Please try again.")


@router.get("/church/storage")
def storage_overview(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    role = require(biz, user, "manager")
    if not cs.switched_on(biz):
        return {"enabled": False}
    row, sessions = cs.business_row(biz), cs.sessions_of(biz)
    if row is None or sessions is None:
        raise _unavailable()
    if cs.allowance_bytes(row) is None:
        return {"enabled": False}
    meter = cs.measure(biz, sessions, row)
    shown = cs.recordings_of(sessions)
    published = cs.published_sessions(biz) if shown else set()
    if published is None:
        raise _unavailable()
    out: Dict[str, Any] = {"enabled": True, **{k: meter[k] for k in _METER},
                           "can_delete": cs.can_delete(), "can_download": False}
    out["recordings"] = [{
        "session_id": str(s["id"]),
        "started_at": s.get("started_at"),
        "duration_s": cs._int(s.get("duration_s")),
        "bytes": cs._int(s.get("bytes")),
        "published": str(s["id"]).lower() in published,
        "sermon_id": s.get("sermon_id"),
        "keep_until": s.get("keep_until"),
    } for s in shown]
    out["extra_offer"] = cs.extra_offer(row, owner=role == "owner")
    return out


@router.delete("/church/storage/recordings/{session_id}")
def storage_delete_recording(session_id: str, business_id: str = Query(...),
                             user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    sid = _uuid(session_id, "recording")
    require(biz, user, "manager")
    if not cs.switched_on(biz):
        raise HTTPException(404, "Not Found")
    rows = sb_clients.sb_get_as_service(
        f"/stream_sessions?id=eq.{sid}&business_id=eq.{biz}&select={cs.SESSION_COLS}&limit=1")
    if not isinstance(rows, list):
        raise _unavailable()
    if not rows:
        raise HTTPException(404, "That recording isn't here any more.")
    s = rows[0]
    if s.get("removed_at"):
        return {"removed": True, "freed_bytes": 0}
    if s.get("status") != "ended":
        raise HTTPException(409, "This service is still being recorded. Delete it once it has ended.")
    import stream_relay_router as sr
    published = sr._published(biz, sid)
    if published is None:
        raise _unavailable()
    if published:
        raise HTTPException(409, "This recording is a published sermon. Unpublish it first, then delete it.")
    if not cs.can_delete():
        raise HTTPException(503, "Deleting recordings isn't switched on yet.")
    done = cs.remove_recording(biz, s)
    if done is None:
        raise HTTPException(503, "That recording couldn't be deleted just now. Please try again.")
    print(f"[church_storage] recording {sid[:8]} deleted by {str(user.id)[:8]}", flush=True)
    return {"removed": True, "freed_bytes": int(done["freed_bytes"])}
