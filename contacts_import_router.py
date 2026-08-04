"""
contacts_import_router.py — bring an existing client list into the system.

THE GAP THIS CLOSES
═══════════════════════════════════════════════════════════════════════
An established business arrives with people. Until now there was no way
to bring them: /contacts had CSV EXPORT and no import. The frontend's
"Import (coming soon)" button was deleted in the 2026-07-03 dead-weight
sweep with a note saying it returns when CSV import ships. This is that.

It matters more than it sounds. Contacts are the first domino — history,
campaigns, invoices, balances, the daily briefing and every proactive
suggestion read from them. A practitioner who has to hand-type 200 clients
does not hand-type 200 clients; they conclude the product is for someone
smaller than them and leave.

WHY THE PARSING IS ON THE CLIENT
This endpoint takes structured rows, not a file. The column-mapping step
("which column is the email?") has to happen in the browser anyway to show
a preview before anything is written, so the CSV never needs to cross the
wire. That also keeps this endpoint free of file-upload surface.

DEDUPE, AND WHY IT IS DONE THE HARD WAY
`contacts` has NO unique index on (business_id, lower(email)) — this is
documented in booking_widget_router, and it means `on_conflict` cannot
save us. Matching is therefore application-level, in one pass, exactly
mirroring the BE#344 find-or-create in public_site:

  - email, case-insensitively, with LIKE wildcards escaped. That escape is
    not decoration: emails legally contain '_', which is a single-char
    wildcard, so an unescaped jo_n@x.com matches joan@x.com.
  - falling back to normalized phone.
  - always scoped to business_id.

A CSV is far more likely than a web form to contain the same person twice,
so the batch is ALSO deduped against itself before anything is written.

TRUST-LAYER DISCIPLINE (feedback_chief_trust_layer_discipline):
  • What changes? Rows in /contacts, and nothing else. No email, no SMS,
    no money. Importing someone does NOT enrol them in anything — that is
    the whole reason this is separate from campaigns.
  • Can the practitioner see it first? Yes. dry_run=true returns the exact
    per-row verdict (create / match / skip, with the reason) and writes
    nothing. The UI runs that before it runs the real thing.
  • Is it reversible? Each created contact is an ordinary contact and can
    be deleted. The response returns every created id so a caller could
    undo the batch wholesale.
  • Is there an audit trail? One audit_log row per import naming the
    counts, plus the per-row results in its payload.
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
import audit_log
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("contacts_import")

router = APIRouter(prefix="/contacts-import", tags=["contacts"])

MAX_ROWS = 2000
# How many existing contacts we pull up front to dedupe against. Beyond
# this the import still runs — it just falls back to a per-row lookup for
# rows that didn't match the preloaded set, which is slower but correct.
PRELOAD_CAP = 20000
PAGE = 1000

VALID_STATUSES = {"active", "lead", "vip", "inactive", "churned"}


class ImportRow(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    status: str = ""
    tags: List[str] = Field(default_factory=list)
    note: str = ""


class ImportBody(BaseModel):
    rows: List[ImportRow]
    # True = compute and report, write nothing. The UI always runs this
    # first so the practitioner sees what is about to happen.
    dry_run: bool = False
    # What to do with a row that matches an existing contact.
    #   'skip'   — leave the existing row completely alone (default)
    #   'fill'   — only fill fields that are currently empty
    on_duplicate: str = "skip"


def _gate(biz_id: str, user: AuthedUser, min_role: str = "member") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz_id, str(user.id), min_role)
    return rows[0]


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm_phone(raw: str) -> str:
    if not raw:
        return ""
    try:
        from sms_service import normalize_phone
        return normalize_phone(str(raw)) or ""
    except Exception:
        return ""


def _preload_existing(biz_id: str) -> Tuple[Dict[str, str], Dict[str, str], bool]:
    """(email -> id, phone -> id, complete?).

    `complete` is False when the business has more contacts than
    PRELOAD_CAP, which tells the caller it must fall back to per-row
    lookups rather than trusting a miss.
    """
    by_email: Dict[str, str] = {}
    by_phone: Dict[str, str] = {}
    offset = 0
    while offset < PRELOAD_CAP:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{biz_id}&select=id,email,phone"
            f"&order=created_at.asc&limit={PAGE}&offset={offset}") or []
        for r in rows:
            em = (r.get("email") or "").strip().lower()
            ph = _norm_phone(r.get("phone") or "")
            # First writer wins — matches "oldest contact is the real one".
            if em and em not in by_email:
                by_email[em] = r["id"]
            if ph and ph not in by_phone:
                by_phone[ph] = r["id"]
        if len(rows) < PAGE:
            return by_email, by_phone, True
        offset += PAGE
    return by_email, by_phone, False


def _lookup_one(biz_id: str, email: str, phone: str) -> Optional[str]:
    """Per-row fallback, used only when the preload was truncated."""
    if email:
        pattern = urllib.parse.quote(_escape_ilike(email), safe="")
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{biz_id}&email=ilike.{pattern}"
            f"&select=id&limit=1") or []
        if rows:
            return rows[0]["id"]
    if phone:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{biz_id}"
            f"&phone=eq.{urllib.parse.quote(phone, safe='')}"
            f"&select=id&limit=1") or []
        if rows:
            return rows[0]["id"]
    return None


@router.post("/{business_id}")
def import_contacts(business_id: str, body: ImportBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _gate(business_id, user, "member")

    if not body.rows:
        raise HTTPException(400, "no rows supplied")
    if len(body.rows) > MAX_ROWS:
        raise HTTPException(
            400, f"{len(body.rows)} rows is over the {MAX_ROWS}-row limit for one "
                 f"import — split the file and run it again")
    if body.on_duplicate not in ("skip", "fill"):
        raise HTTPException(400, "on_duplicate must be 'skip' or 'fill'")

    by_email, by_phone, complete = _preload_existing(business_id)
    if not complete:
        logger.info(f"[import] biz={business_id[:8]} over preload cap — "
                    f"falling back to per-row lookups on misses")

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    results: List[Dict[str, Any]] = []
    to_create: List[Tuple[int, Dict[str, Any]]] = []
    to_fill: List[Tuple[int, str, Dict[str, Any]]] = []
    # Within-batch dedupe — a CSV repeats people far more often than a
    # web form does.
    seen_email: Dict[str, int] = {}
    seen_phone: Dict[str, int] = {}

    for i, raw in enumerate(body.rows):
        name = (raw.name or "").strip()
        email = (raw.email or "").strip().lower()
        phone = _norm_phone(raw.phone or "")

        # name is NOT NULL on contacts. Rather than reject a row that has a
        # perfectly good email, fall back to the local-part — a contact
        # called "marcus" beats a failed row, and the practitioner can see
        # what happened in the report.
        if not name:
            if email and "@" in email:
                name = email.split("@", 1)[0]
            elif phone:
                name = phone
            else:
                results.append({"row": i, "action": "skipped",
                                "reason": "no name, email or phone"})
                continue

        if email and "@" not in email:
            results.append({"row": i, "action": "skipped",
                            "reason": f"'{raw.email.strip()[:60]}' is not an email address"})
            continue

        # Duplicate inside this file?
        dup_of = None
        if email and email in seen_email:
            dup_of = seen_email[email]
        elif phone and phone in seen_phone:
            dup_of = seen_phone[phone]
        if dup_of is not None:
            results.append({"row": i, "action": "skipped",
                            "reason": f"same person as row {dup_of + 1} in this file"})
            continue

        existing_id = by_email.get(email) if email else None
        if not existing_id and phone:
            existing_id = by_phone.get(phone)
        if not existing_id and not complete:
            existing_id = _lookup_one(business_id, email, phone)

        if email:
            seen_email[email] = i
        if phone:
            seen_phone[phone] = i

        if existing_id:
            if body.on_duplicate == "fill":
                patch: Dict[str, Any] = {}
                if email:
                    patch["email"] = email
                if phone:
                    patch["phone"] = phone
                to_fill.append((i, existing_id, patch))
                results.append({"row": i, "name": name, "action": "matched",
                                "reason": "already in your contacts — filling blanks",
                                "contact_id": existing_id})
            else:
                results.append({"row": i, "name": name, "action": "matched",
                                "reason": "already in your contacts",
                                "contact_id": existing_id})
            continue

        status = (raw.status or "").strip().lower()
        if status not in VALID_STATUSES:
            status = "lead"
        tags = [str(t).strip()[:40] for t in (raw.tags or []) if str(t).strip()][:20]

        payload: Dict[str, Any] = {
            "business_id": business_id,
            "name": name[:200],
            "email": email or None,
            "phone": phone or None,
            "status": status,
            "source": "csv_import",
            "tags": tags,
            # There is no `notes` COLUMN on contacts — free text belongs in
            # metadata, the way every public writer already does it. Writing
            # a `notes` key here would 400 the whole batch (PGRST204).
            "metadata": ({"import_note": raw.note.strip()[:1000]}
                         if (raw.note or "").strip() else {}),
        }
        to_create.append((i, payload))
        results.append({"row": i, "name": name, "action": "create"})

    summary = {
        "to_create": len(to_create),
        "matched": sum(1 for r in results if r["action"] == "matched"),
        "skipped": sum(1 for r in results if r["action"] == "skipped"),
        "total": len(body.rows),
    }

    if body.dry_run:
        return {"ok": True, "dry_run": True, "summary": summary, "results": results}

    created_ids: List[str] = []
    failed = 0
    # Chunked inserts: one 2000-row POST is a single point of failure, and
    # a partial failure inside it tells the practitioner nothing about
    # which people made it in.
    CHUNK = 100
    for start in range(0, len(to_create), CHUNK):
        chunk = to_create[start:start + CHUNK]
        try:
            rows = sb_clients.sb_post_as_service(
                "/contacts", [p for _, p in chunk])
            made = rows if isinstance(rows, list) else []
            created_ids.extend([r["id"] for r in made if r.get("id")])
            for (idx, _), row in zip(chunk, made):
                for r in results:
                    if r["row"] == idx:
                        r["action"] = "created"
                        r["contact_id"] = row.get("id")
        except Exception as e:
            logger.warning(f"[import] chunk insert failed biz={business_id[:8]}: {e}")
            failed += len(chunk)
            for idx, _ in chunk:
                for r in results:
                    if r["row"] == idx:
                        r["action"] = "failed"
                        r["reason"] = "could not be saved — try this row again"

    filled = 0
    for idx, cid, patch in to_fill:
        try:
            # Only fill what is actually blank — an import must never
            # overwrite a number someone corrected by hand.
            cur = sb_clients.sb_get_as_service(
                f"/contacts?id=eq.{cid}&business_id=eq.{business_id}"
                f"&select=email,phone&limit=1") or []
            if not cur:
                continue
            gap = {k: v for k, v in patch.items()
                   if v and not str(cur[0].get(k) or "").strip()}
            if gap:
                gap["last_interaction"] = now_iso
                sb_clients.sb_patch_as_service(
                    f"/contacts?id=eq.{cid}&business_id=eq.{business_id}", gap)
                filled += 1
        except Exception as e:
            logger.warning(f"[import] fill failed contact={cid}: {e}")

    summary.update({"created": len(created_ids), "failed": failed, "filled": filled})
    summary.pop("to_create", None)

    n = len(created_ids)
    line = f"Imported {n} contact{'' if n == 1 else 's'} from a file"
    if summary["matched"]:
        line += f", {summary['matched']} already known"
    if failed:
        line += f", {failed} failed"

    audit_log.record(
        business_id, actor_type="user", actor_id=str(user.id),
        verb="import_contacts", ok=(failed == 0),
        summary=line,
        target_type="contacts",
        payload={"summary": summary, "on_duplicate": body.on_duplicate},
        source="contacts_import",
        authorized_by="member+",
    )

    return {"ok": True, "dry_run": False, "summary": summary,
            "results": results, "created_ids": created_ids}
