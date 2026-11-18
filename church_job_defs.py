"""church_job_defs.py — a church's own jobs, who may set them up, and the record.

Kevin, 2026-11-17, on "One sheet per person" (artifact WE3jy89EXadQSjz9t8A2FV):
"yes to all and build it. also allow for custom roles to be set that way, it
becomes easy for other churches to set there own leadership flow", then "also
allow for permission to be given to a person to create roles like how my wife
over administration team, she should be able to alter roles and or things if
needed."

    a JOB ......... a starting point for a person's sheet: a title, one line
                    of what it does, a description, the login level, the
                    areas it works and the duties it does. The five presets
                    are the office's lanes (church_areas.LANES, with each
                    lane's starter duties); a church adds its own beside
                    them (church_jobs). A job is a label and a starting
                    point: saving or changing one never changes anyone who
                    already holds it
    the GRANT ..... "Sets up jobs and people's sheets" (GRANT). Only the
                    owner or an Admin gives it or takes it away, and only to
                    a Manager login. A holder makes, changes and removes the
                    church's own jobs (never an Admin job) and changes the
                    sheet of a Manager login or below (church_sheet); never
                    their own, an Admin's or the owner's, never Giving &
                    money or a money duty, and never the grant itself. It is
                    kept in the duties' own holder table under a key that is
                    not one of the duties (church_duties._moved leaves it out
                    of every duty reading), so who gave it, when, and every
                    change are in church_duty_changes with the duties'
    the RECORD .... church_sheet_changes: who changed whose sheet or which
                    job, when, in one sentence. A change made by a holder
                    (not the owner, not an Admin) is also told to the owner:
                    a phone alert and an email

Server-only tables (supabase/APPLY-2026-11-17-church-jobs.sql). Before the
file is applied every read answers "no custom jobs" and never fails a page; a
write answers 503 with NOT_READY. The record is best effort: a change is never
refused because its record didn't save.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger(__name__)

TABLE = "church_jobs"
LOG = "church_sheet_changes"
COLS = "id,business_id,key,label,does,description,role,areas,duties,created_by,updated_by,created_at,updated_at,deleted_at"
ROLES = ("viewer", "member", "manager", "admin")
GRANT = "jobs_and_sheets"
GRANT_LABEL = "Sets up jobs and people's sheets"
GRANT_DOES = ("Makes and changes the church's own jobs, and changes the sheet of a Manager login or below. "
              "Never an Admin job, Giving & money, or their own sheet.")
NOT_READY = "Custom jobs are being switched on. Try again shortly."
UNSAVED = "That didn't save. Try again."
PRESET = "That is one of the five starting jobs, so it can't be changed here. Make your own job from it instead."
OWNER_ONLY_ADMIN = "Only the owner can make or change a job that is an Admin login."
LABEL_MAX, DOES_MAX, DESCRIPTION_MAX = 60, 240, 8000
MAX_JOBS = 60
# Words a job's key may never be: the presets, the Executive Pastor's lane,
# the grant, and the fixed paths under /church/jobs (the job descriptions').
_FIXED = ("person", "whose", "draft", "list", "new", "none", "jobs", "sheet", "undo")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reserved() -> Set[str]:
    import church_areas
    import church_duties as cd
    return set(church_areas.LANES) | set(cd.PSEUDO_LANES) | {GRANT} | set(_FIXED)


# ─── Reading ──────────────────────────────────────────────────────────

def _rows(business_id: Any) -> Optional[List[Dict[str, Any]]]:
    """Every job row this church ever made, the removed ones too. None when
    the table couldn't be read (before its file is applied, or a read that
    failed): every reader then shows the presets alone."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/{TABLE}?business_id=eq.{_q(business_id)}&select={COLS}&order=created_at.asc&limit=500")
    except Exception:  # noqa: BLE001 — a job list never fails a page
        logger.warning("church jobs: read failed (business %s)", str(business_id)[:8], exc_info=True)
        return None
    if not isinstance(rows, list):
        return None
    return [r for r in rows if str(r.get("business_id")) == str(business_id)]


def _areas(v: Any) -> Optional[List[str]]:
    import church_areas
    if not isinstance(v, list):
        return None
    return [a for a in church_areas.AREA_ORDER if a in v]


def _shape(row: Dict[str, Any]) -> Dict[str, Any]:
    import church_duties as cd
    role = row.get("role") if row.get("role") in ROLES else "manager"
    return {"key": str(row.get("key") or ""), "label": _plain(row.get("label")), "does": _plain(row.get("does")),
            "description": (str(row.get("description") or "").strip() or None), "role": role,
            "areas": None if role == "admin" else (_areas(row.get("areas")) or []),
            "duties": [k for k in cd.CATALOG if k in (row.get("duties") or [])], "custom": True}


def presets() -> List[Dict[str, Any]]:
    """The five starting jobs: the office's lanes and each lane's starter duties."""
    import church_areas
    import church_duties as cd
    return [{"key": k, "label": v["label"], "does": v["does"], "description": None, "role": v["role"],
             "areas": list(v["areas"]) if v["areas"] else None, "duties": list(cd.STARTER.get(k, ())),
             "custom": False} for k, v in church_areas.LANES.items()]


def customs(business_id: Any) -> List[Dict[str, Any]]:
    """This church's own jobs that are still there; [] when none, or unread."""
    return [_shape(r) for r in (_rows(business_id) or []) if not r.get("deleted_at")]


def jobs(business_id: Any) -> List[Dict[str, Any]]:
    """The presets, then this church's own. Never raises."""
    return presets() + customs(business_id)


def find(business_id: Any, key: Any, *, gone: bool = False) -> Optional[Dict[str, Any]]:
    """One job by its key: a preset, or one of the church's own. With `gone`,
    a removed one too (a login that held it keeps its title)."""
    key = str(key or "")
    if not key:
        return None
    hit = next((j for j in presets() if j["key"] == key), None)
    if hit:
        return hit
    rows = [r for r in (_rows(business_id) or []) if str(r.get("key")) == key]
    live = [r for r in rows if not r.get("deleted_at")]
    pick = live[0] if live else (rows[-1] if rows and gone else None)
    return _shape(pick) if pick else None


def label_of(business_id: Any, key: Any) -> Optional[str]:
    """A job's title by its key, a removed one's too; None for no job."""
    j = find(business_id, key, gone=True)
    return j["label"] if j else None


# ─── Who may set jobs and sheets up ───────────────────────────────────

def grant_holders(business_id: Any) -> Optional[Set[str]]:
    """The logins the owner or an Admin gave the grant to. None when it
    couldn't be read: never a yes."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/church_duty_holders?business_id=eq.{_q(business_id)}&duty=eq.{GRANT}&select=user_id&limit=50")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(rows, list):
        return None
    return {str(r["user_id"]) for r in rows if r.get("user_id")}


def holds_grant(business_id: Any, user_id: Any, role: Optional[str]) -> bool:
    """A Manager login the grant was given to. The owner and the Admins set
    everything up already and are never "holders"; a login that was moved
    down to Member or Viewer no longer holds it."""
    if role != "manager":
        return False
    return str(user_id) in (grant_holders(business_id) or set())


def editor(business_id: Any, user_id: Any, role: Optional[str]) -> Optional[str]:
    """What this login is for jobs and sheets: 'owner', 'admin', 'holder', or
    None (it changes neither)."""
    if role in ("owner", "admin"):
        return role
    return "holder" if holds_grant(business_id, user_id, role) else None


def set_grant(business: Dict[str, Any], target: str, give: bool, by: str) -> bool:
    """Give the grant to one Manager login, or take it away, as the duties'
    own write does it (church_duty_set: the holders and its log row in one
    transaction). The caller checked who may (the owner or an Admin). True
    when something changed. A read or a save that fails is a 503."""
    import church_duties as cd
    biz = str(business["id"])
    have = grant_holders(biz)
    if have is None:
        raise HTTPException(503, "Who sets up jobs couldn't be read just now. Try again.")
    want = (have | {str(target)}) if give else (have - {str(target)})
    if want == have:
        return False
    cd._write(biz, GRANT, sorted(want), str(by))
    return True


def drop_grant(business_id: Any, user_id: Any) -> Optional[bool]:
    """Take the grant away from a login that is leaving the team or has just
    joined it again (business_users_router: revoke, accept), so it never
    comes back with the same person. True when a row went, None when they
    held none, False when it couldn't be read or saved. Logged by the
    duties' own write with no one named as the changer."""
    have = grant_holders(business_id)
    if have is None:
        return False
    if str(user_id) not in have:
        return None
    try:
        saved = sb_clients.sb_post_as_service("/rpc/church_duty_set", {
            "p_business_id": str(business_id), "p_duty": GRANT, "p_user_ids": sorted(have - {str(user_id)}),
            "p_by": None, "p_undoes": None})
    except Exception:  # noqa: BLE001
        return False
    if isinstance(saved, list):
        saved = saved[0] if saved else None
    return bool(isinstance(saved, dict) and saved.get("id"))


# ─── The record, and telling the owner ────────────────────────────────

def record(business_id: Any, kind: str, by: Any, summary: str, *, subject: Any = None, job_key: Any = None,
           detail: Optional[Dict[str, Any]] = None) -> bool:
    """One line of who changed what. Best effort: a change is never refused
    because its record didn't save (the table may not be there yet)."""
    try:
        saved = sb_clients.sb_post_as_service(f"/{LOG}", {
            "business_id": str(business_id), "kind": kind, "subject_user_id": str(subject) if subject else None,
            "job_key": str(job_key) if job_key else None, "changed_by": str(by) if by else None,
            "changed_at": _now(), "summary": summary[:500], "detail": detail or {}})
        return isinstance(saved, list) and bool(saved)
    except Exception:  # noqa: BLE001
        logger.warning("church jobs: a change's record didn't save (business %s)", str(business_id)[:8])
        return False


def _later(fn: Callable[[], None]) -> None:
    """Alerts go off the request: a slow email never holds up an answer."""
    threading.Thread(target=fn, daemon=True).start()


def tell_owner(business: Dict[str, Any], title: str, body: str, tag: str) -> None:
    """A phone alert and an email to the church's owner, off the request;
    one that fails never stops the other, and neither stops the change."""
    owner = str(business.get("owner_id") or "")
    if not owner:
        return

    def run() -> None:
        biz = str(business["id"])
        try:
            import push_notifications
            push_notifications.send_to_user(owner, title=title, body=body[:160], nav="operate:areas", tag=tag,
                                            business_id=biz)
        except Exception:
            logger.warning("church jobs: the owner's phone alert failed", exc_info=True)
        try:
            import asyncio
            import app_base
            import email_sender
            import messaging_router
            email = (messaging_router.owner_email_read(owner) or "").strip()
            if "@" not in email:
                return
            asyncio.run(email_sender.send_via_resend(
                to_email=email, to_name=None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                from_name=business.get("name") or "Your church", subject=title[:150], reply_to=None,
                business_id=biz, idempotency_key=tag,
                body=f"{title}\n\n{body}\n\nSee it on Logins & areas:\n{app_base.app_base_url()}/?nav=operate:areas\n"))
        except Exception:
            logger.warning("church jobs: the owner's email failed", exc_info=True)
    _later(run)


def changed(business: Dict[str, Any], kind: str, by: str, by_role: str, by_name: str, summary: str, *,
            subject: Any = None, job_key: Any = None, detail: Optional[Dict[str, Any]] = None) -> None:
    """Record a change, and tell the owner when a holder made it (never when
    the owner or an Admin did)."""
    record(business["id"], kind, by, summary, subject=subject, job_key=job_key, detail=detail)
    if by_role == "holder":
        tell_owner(business, f"{by_name} {summary}"[:150],
                   f"{by_name} sets up jobs and people's sheets at {business.get('name') or 'your church'}. "
                   f"They {summary}.", tag=f"sheet-{kind}-{subject or job_key or ''}-{_now()[:19]}")


# ─── Writing a job ────────────────────────────────────────────────────

def _live(business_id: Any) -> List[Dict[str, Any]]:
    """Every row, for a write: a table that isn't there yet is a 503."""
    rows = _rows(business_id)
    if rows is None:
        raise HTTPException(503, NOT_READY)
    return rows


def _slug(label: str, taken: Set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:34]
    if not base or not base[0].isalpha():
        base = ("job_" + base)[:34].strip("_")
    if len(base) < 2:
        base = "job"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}_{n}"
    return key


def clean(body: Dict[str, Any], by_role: str) -> Dict[str, Any]:
    """A job's fields as they are saved, or a 400 that says what to fix.
    `by_role` is the editor's (owner, admin or holder): an Admin job is the
    owner's alone; Giving & money and the money duties go only with an Admin
    job; the lanes' oversight (the monthly report, Over the lanes) only from
    the owner or an Admin; the grant is never part of a job."""
    import church_areas
    import church_duties as cd
    body = body if isinstance(body, dict) else {}
    label = _plain(body.get("label"))
    if not 2 <= len(label) <= LABEL_MAX:
        raise HTTPException(400, f"Give the job a title, {LABEL_MAX} letters at most.")
    does = _plain(body.get("does"))
    if len(does) > DOES_MAX:
        raise HTTPException(400, f"Say what the job does in one line, {DOES_MAX} letters at most.")
    description = str(body.get("description") or "").replace("\r\n", "\n").strip()
    if len(description) > DESCRIPTION_MAX:
        raise HTTPException(400, f"A job's description is {DESCRIPTION_MAX:,} letters at most.")
    try:
        import church_job_descriptions as cjd
        if cjd.has_pay(label, does, description):
            raise HTTPException(400, "Pay stays out of a job: say what the job does, not what it pays.")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — the pay check is the descriptions'; unread, the job still saves
        pass
    role = body.get("role")
    role = "manager" if role in (None, "") else role
    if not isinstance(role, str) or role not in ROLES:
        raise HTTPException(400, "A job's login is a Viewer, a Member, a Manager or an Admin.")
    if role == "admin" and by_role != "owner":
        raise HTTPException(403, OWNER_ONLY_ADMIN)
    areas = body.get("areas")
    if areas is not None and (not isinstance(areas, list)
                              or any(not isinstance(a, str) or a not in church_areas.AREAS for a in areas)):
        raise HTTPException(400, "Pick the job's areas from the church's eight.")
    areas = [a for a in church_areas.AREA_ORDER if a in (areas or [])]
    if role == "admin":
        areas = []                      # an Admin login sees the whole church
    elif church_areas.FINANCE_ONLY in areas:
        raise HTTPException(400, "Giving & money opens only for an Admin login, so it can't be part of this job. "
                                 "Only the owner makes an Admin job.")
    duties = body.get("duties")
    if duties is not None and (not isinstance(duties, list)
                               or any(not isinstance(d, str) or d not in cd.CATALOG for d in duties)):
        raise HTTPException(400, "One of those isn't a duty here. Pick the job's duties from the church's list.")
    duties = [k for k in cd.CATALOG if k in (duties or [])]
    if role != "admin" and any(cd.CATALOG[k]["money"] for k in duties):
        raise HTTPException(400, "A money job goes only with an Admin login, so it can't be part of this job.")
    if role not in ("admin", "manager") and duties:
        raise HTTPException(400, "A Member or Viewer login doesn't do office jobs: leave the duties out, or make "
                                 "the job a Manager login.")
    if by_role == "holder" and any(k in cd.OVERSIGHT for k in duties):
        raise HTTPException(403, "Only the owner or an Admin puts the monthly report or Over the lanes in a job.")
    return {"label": label, "does": does, "description": description or None, "role": role, "areas": areas,
            "duties": duties}


def _words(j: Dict[str, Any]) -> str:
    return f"“{j['label']}”"


def create(business: Dict[str, Any], body: Dict[str, Any], by: str, by_role: str) -> Dict[str, Any]:
    """A new job of the church's own. A title another of its jobs has is a
    409. Returns {job, created: True}."""
    biz = str(business["id"])
    rows = _live(biz)
    fields = clean(body, by_role)
    live = [r for r in rows if not r.get("deleted_at")]
    if len(live) >= MAX_JOBS:
        raise HTTPException(400, f"A church keeps up to {MAX_JOBS} jobs of its own. Remove one first.")
    names = {_plain(r.get("label")).casefold() for r in live} | {j["label"].casefold() for j in presets()}
    if fields["label"].casefold() in names:
        raise HTTPException(409, f"There is already a job called {fields['label']}. Change that one, or pick "
                                 "another title.")
    key = _slug(fields["label"], {str(r.get("key")) for r in rows} | _reserved())
    now = _now()
    saved = sb_clients.sb_post_as_service(f"/{TABLE}", {
        "business_id": biz, "key": key, **fields, "created_by": str(by), "updated_by": str(by),
        "created_at": now, "updated_at": now})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, UNSAVED)
    return {"job": _shape(saved[0]), "created": True, "before": None}


def _mine(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    if key in _reserved() and any(j["key"] == key for j in presets()):
        raise HTTPException(400, PRESET)
    row = next((r for r in rows if str(r.get("key")) == key and not r.get("deleted_at")), None)
    if not row:
        raise HTTPException(404, "That isn't one of this church's own jobs.")
    return row


def update(business: Dict[str, Any], key: str, body: Dict[str, Any], by: str, by_role: str) -> Dict[str, Any]:
    """Change one of the church's own jobs. Nobody who holds it changes:
    their areas and duties stay as they are. Returns {job, before}."""
    biz = str(business["id"])
    rows = _live(biz)
    row = _mine(rows, str(key or ""))
    if row.get("role") == "admin" and by_role != "owner":
        raise HTTPException(403, OWNER_ONLY_ADMIN)
    fields = clean(body, by_role)
    others = {_plain(r.get("label")).casefold() for r in rows if not r.get("deleted_at") and r is not row}
    if fields["label"].casefold() in others | {j["label"].casefold() for j in presets()}:
        raise HTTPException(409, f"There is already a job called {fields['label']}. Pick another title.")
    saved = sb_clients.sb_patch_as_service(
        f"/{TABLE}?business_id=eq.{_q(biz)}&key=eq.{_q(row['key'])}&deleted_at=is.null",
        {**fields, "updated_by": str(by), "updated_at": _now()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, UNSAVED)
    return {"job": _shape(saved[0]), "created": False, "before": _shape(row)}


def remove(business: Dict[str, Any], key: str, by: str, by_role: str) -> Dict[str, Any]:
    """Take one of the church's own jobs off the list. The logins that hold
    it keep their areas and their duties, and their job still reads as its
    title. Returns {job}: the job as it was."""
    biz = str(business["id"])
    rows = _live(biz)
    row = _mine(rows, str(key or ""))
    if row.get("role") == "admin" and by_role != "owner":
        raise HTTPException(403, OWNER_ONLY_ADMIN)
    saved = sb_clients.sb_patch_as_service(
        f"/{TABLE}?business_id=eq.{_q(biz)}&key=eq.{_q(row['key'])}&deleted_at=is.null",
        {"deleted_at": _now(), "updated_by": str(by), "updated_at": _now()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, UNSAVED)
    return {"job": _shape(row), "removed": True}


def summary_of(verb: str, job: Dict[str, Any]) -> str:
    """One sentence for the record ("added the job “Kids Director”")."""
    return {"create": "added the job ", "update": "changed the job ", "remove": "removed the job "}[verb] + _words(job)
