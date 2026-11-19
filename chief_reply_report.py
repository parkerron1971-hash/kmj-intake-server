"""
chief_reply_report.py — "Report" on a Chief reply, from inside the app (2026-11-19).

Why it exists: Google Play's policy on AI-generated content asks that an app
which generates content with AI lets people report or flag offensive output
without leaving the app. Chief's replies are that content, and until today
there was no way to flag one. Kevin asked for it on 2026-11-19.

    POST /agents/chief/reply-report
      { business_id, reason, note?, reply, asked?, conversation_id?, surface? }

WHERE A REPORT GOES: a support ticket. No new table. support_tickets is the
queue Mission Control already reads (Support Tickets, and Today's list of
open tickets), it carries a business, a person, a subject, a message and a
free `context` object, and its triage, replies and "tell them" email all
work on a report the same way they work on any other ticket. The ticket's
`context.kind` is "chief_reply_report", so a report can be told apart from a
question at a glance and in a query.

"Offensive or harmful" is triaged HIGH on arrival (a support_triage row,
best effort): the queue's keyword guess would rank it "normal", and a report
under that policy should be read first. If that row can't be written the
queue seeds its own guess the first time it reads the ticket, as it always
has; the report itself is never lost over it. Either way a report has NO
problem_key (support_queue.stands_alone): every report has the same subject
for its reason, so a key would count unrelated replies as one repeated
problem and rank them up.

WHO MAY REPORT: whoever may talk to Chief in the business. The chat turn
authorizes by reading the business under the caller's own token, and the
businesses policies let three kinds of login read it: the owner
(businesses.owner_id), an active seat of any role (business_users,
is_business_member) and an active collaborator such as an accountant
(business_collaborators, is_business_collaborator). This route writes as the
service role, so it asks the same question explicitly, and fails CLOSED: a
read that fails (sb_get_as_service's None) is a 503 the app can retry, never
a "not found" for a real team member, and a stranger gets the same 404 as a
business that doesn't exist.

What a ticket holds is readable by the business's owner (tickets_tenant_select),
so it carries nothing the owner can't already see: the reply, the message
before it, the reason and the note.

A SAMPLE CHURCH (sample_church.py) has its own Chief, and its replies are AI
output too, so a report from one is let through both write guards (the app's
sampleChurch.ts and sample_church_guard.EXEMPT_PATHS) and filed under the
visitor's HOME church: a sample is deleted when the church starts for real,
and support_tickets cascades on delete, so a report filed on the sample
would vanish with it.

Rate limited per login (rate_limit "chief_reply_report"); fails open like
every practitioner bucket.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("chief_reply_report")

router = APIRouter(tags=["chief"])

KIND = "chief_reply_report"

# The reasons the app offers, and the words a ticket uses for each. The
# category is support_tickets' own (its CHECK allows bug, question, billing,
# feature, general): a wrong or made-up answer is a fault to fix, so "bug".
REASONS: Dict[str, Dict[str, str]] = {
    "offensive": {"label": "Offensive or harmful", "category": "general", "severity": "high"},
    "wrong":     {"label": "Wrong or made up",     "category": "bug",     "severity": "normal"},
    "other":     {"label": "Something else",       "category": "general", "severity": "normal"},
}

# How much of each piece a ticket keeps. support_tickets.message is CHECKed
# at 5000 characters and the subject at 200, so the whole message is cut to
# fit after it is put together; these keep any one piece from crowding out
# the rest.
REPLY_MAX = 3000
ASKED_MAX = 1000
NOTE_MAX = 800
MESSAGE_MAX = 5000
SUBJECT_MAX = 200
SURFACE_MAX = 40
CONVERSATION_MAX = 80

THANKS = "Thanks — we'll look at it."
NOT_SENT = "That report didn't send. Try again in a moment."


class ReplyReport(BaseModel):
    business_id: str
    reason: str
    reply: str
    note: Optional[str] = None
    asked: Optional[str] = None             # the message the reply answered, when the app has it
    conversation_id: Optional[str] = None
    surface: Optional[str] = None           # where in the app: "chief", "phone", "stage", "voice" …


def _clip(text: Any, limit: int) -> str:
    """Trimmed, and cut to `limit` characters with an ellipsis when longer."""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "…"


class _Unreadable(RuntimeError):
    """A read the access check needed came back as no answer at all."""


def _rows(path: str) -> list:
    """sb_get_as_service, where None means the read FAILED. It answers None
    on any error and a list (maybe empty) on success, so `or []` here would
    turn "the database didn't answer" into "you have no seat"."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise _Unreadable(path.split("?", 1)[0])
    return rows


def _role_of_caller(business_id: str, user_id: str) -> Optional[str]:
    """'owner', the active seat's role, 'collaborator', or None (no standing,
    or no such business). Raises _Unreadable when a read fails.

    The same questions as business_users_router.role_of plus
    is_business_collaborator, read here rather than through role_of because
    role_of folds a failed read into "no role", and a team member must not
    hear "business not found" because the database blinked."""
    from business_users_router import safe_id
    if not safe_id(str(business_id or "")) or not safe_id(str(user_id or "")):
        return None
    b, u = quote(str(business_id), safe=""), quote(str(user_id), safe="")
    biz = _rows(f"/businesses?id=eq.{b}&select=id,owner_id&limit=1")
    if not biz:
        return None
    if str(biz[0].get("owner_id")) == str(user_id):
        return "owner"
    seat = _rows(f"/business_users?business_id=eq.{b}&user_id=eq.{u}"
                 f"&status=eq.active&select=role&limit=1")
    if seat:
        return str(seat[0].get("role") or "member")
    collab = _rows(f"/business_collaborators?business_id=eq.{b}&user_id=eq.{u}"
                   f"&status=eq.active&select=id&limit=1")
    return "collaborator" if collab else None


def require_reporter(business_id: str, user: AuthedUser) -> str:
    """The caller's standing in the business, or a refusal.

    'owner', their active seat's role (any role, as is_business_member
    allows), or 'collaborator' for an active business_collaborators row (as
    is_business_collaborator allows). Anyone else gets 404, the same answer
    as a business that doesn't exist (business_access's rule). Fails
    CLOSED and retryable: a read that fails or doesn't answer is a 503,
    never a yes and never a "not found"."""
    try:
        role = _role_of_caller(business_id, str(user.id))
    except Exception as e:  # noqa: BLE001 - _Unreadable, or a read that raised
        logger.error("[reply-report] access check failed for %s: %s", business_id, e)
        raise HTTPException(status_code=503, detail="access check unavailable") from e
    if not role:
        raise HTTPException(status_code=404, detail="business not found")
    return role


def _ticket_business(business_id: str) -> Dict[str, Any]:
    """The business the ticket is filed under, and whether the report came
    from a sample church. A sample's report goes to its home church; a sample
    whose home is gone (or a read that fails) keeps its own id."""
    out: Dict[str, Any] = {"id": business_id, "sample_id": None}
    try:
        import sample_church
        if sample_church.is_sample(business_id):
            home = sample_church.home_of(business_id)
            out["sample_id"] = business_id
            if home:
                out["id"] = home
    except Exception as e:  # noqa: BLE001 - fail open: file it where it was asked
        logger.warning("[reply-report] sample check failed open: %s", type(e).__name__)
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(out['id']), safe='')}&select=id,name&limit=1") or []
    out["name"] = (rows[0].get("name") if rows else None) or None
    return out


def compose(reason_key: str, reply: str, asked: str, note: str,
            surface: str) -> Dict[str, str]:
    """The ticket's subject and message, in plain words, inside the
    table's limits."""
    label = REASONS[reason_key]["label"]
    subject = _clip(f"Chief reply reported: {label}", SUBJECT_MAX)
    parts = [f"Reason: {label}"]
    if note:
        parts.append(f"Their note: {note}")
    if surface:
        parts.append(f"Where: {surface}")
    if asked:
        parts.append(f"They asked:\n{asked}")
    parts.append(f"Chief replied:\n{reply}")
    return {"subject": subject, "message": _clip("\n\n".join(parts), MESSAGE_MAX)}


def _seed_triage(ticket: Dict[str, Any], reason_key: str) -> None:
    """Best effort: rank the ticket by its reason, not the keyword guess.

    No problem_key: every report stands alone. The key the queue would work
    out comes from the subject, which is the same for every report with one
    reason, so two unrelated replies would count as one repeated problem and
    rank each other up. support_queue.stands_alone tells the queue's own
    seeding (support_router._seed_triage) the same thing when this write
    doesn't land."""
    try:
        sb_clients.sb_post_as_service("/support_triage", {
            "ticket_id": ticket["id"],
            "severity": REASONS[reason_key]["severity"],
            "fix_state": "new",
            "problem_key": None,
            "triaged_by": "auto",
        }, prefer="return=minimal", redact=True)
    except Exception as e:  # noqa: BLE001 - the queue seeds its own guess on read
        logger.warning("[reply-report] triage seed skipped: %s", type(e).__name__)


@router.post("/agents/chief/reply-report")
def report_chief_reply(body: ReplyReport,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    reason_key = str(body.reason or "").strip().lower()
    if reason_key not in REASONS:
        raise HTTPException(status_code=400, detail="Pick a reason for the report.")
    reply = _clip(body.reply, REPLY_MAX)
    if not reply:
        raise HTTPException(status_code=400, detail="There's no reply to report.")

    try:
        import rate_limit
        if not rate_limit.allow("chief_reply_report", str(user.id)):
            raise HTTPException(
                status_code=429,
                detail="You've sent a lot of reports just now. Try again in a little while.",
                headers={"Retry-After": str(rate_limit.retry_after("chief_reply_report"))})
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - the limiter fails open
        pass

    business_id = str(body.business_id or "").strip()
    role = require_reporter(business_id, user)

    asked = _clip(body.asked, ASKED_MAX)
    note = _clip(body.note, NOTE_MAX)
    surface = _clip(body.surface, SURFACE_MAX)
    where = _ticket_business(business_id)
    words = compose(reason_key, reply, asked, note, surface)
    context: Dict[str, Any] = {
        "kind": KIND,
        "reason": reason_key,
        "screen": "chief",
        "surface": surface or None,
        "conversation_id": _clip(body.conversation_id, CONVERSATION_MAX) or None,
        "reporter_role": role,
        "reply_chars": len(str(body.reply or "").strip()),
    }
    if where["sample_id"]:
        context["sample_church"] = where["sample_id"]
    row = {
        "business_id": where["id"],
        "user_id": str(user.id),            # NOT NULL, defaulting to auth.uid(): null for the service role
        "category": REASONS[reason_key]["category"],
        "subject": words["subject"],
        "message": words["message"],
        "context": context,
    }
    if where.get("name"):
        row["business_name"] = where["name"]

    saved = sb_clients.sb_post_as_service("/support_tickets", row)
    ticket = saved[0] if isinstance(saved, list) and saved else (
        saved if isinstance(saved, dict) else None)
    if not ticket or not ticket.get("id"):
        logger.error("[reply-report] ticket insert failed for %s", where["id"])
        raise HTTPException(status_code=503, detail=NOT_SENT)

    _seed_triage({**row, "id": ticket["id"]}, reason_key)
    return {"ok": True, "message": THANKS}
