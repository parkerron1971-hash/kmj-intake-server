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

EVERYTHING THE FILE CARRIES (2026-09-26)
The dialog sends the file as a mapped TABLE and contact_fields turns it
into rows — the same function the Structure Import uses. First + last
names are joined; company, birthday and address land in named metadata
keys; job title lands in `role`; every other column is kept under its own
heading in metadata.imported. Nothing is dropped unless the practitioner
leaves it out.

OPT-OUTS CARRY; CONSENT NEVER DOES
A column that says someone unsubscribed, was cleaned, bounced or said no
to marketing is honoured on the way in:
  • email → contacts.metadata.email_opt_out, which campaigns skip. NOT
    email_suppressions: that list is platform-wide and blocks receipts
    too, and a file upload must never be able to silence an address for
    every other business on the platform.
  • texts → a row in sms_opt_outs scoped to this business — the STOP
    ledger every text path already checks — plus metadata.sms_opt_out.
It is carried onto people who are ALREADY in contacts too, whatever
on_duplicate says. Nothing here ever writes sms_consents or
sms_bindings, or clears an opt-out: an import only takes permission away.

TRUST-LAYER DISCIPLINE (feedback_chief_trust_layer_discipline):
  • What changes? Rows in /contacts, plus sms_opt_outs rows for people
    the file says must not be texted. No email, no SMS, no money.
    Importing someone does NOT enrol them in anything — that is the
    whole reason this is separate from campaigns.
  • Can the practitioner see it first? Yes. dry_run=true returns the exact
    per-row verdict (create / match / skip, with the reason) and writes
    nothing. The UI runs that before it runs the real thing.
  • Is it reversible? Each created contact is an ordinary contact and can
    be deleted. The response returns every created id so a caller could
    undo the batch wholesale.
  • Is there an audit trail? One audit_log row per import naming the
    counts, including the opt-outs carried.
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
import contact_fields
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
    # 2026-09-26 — everything a real export carries. See contact_fields.
    first_name: str = ""
    last_name: str = ""
    company: str = ""          # → metadata.organization (contract_agent reads it)
    title: str = ""            # → contacts.role ("Role / Title" in the app)
    birthday: str = ""         # → metadata.birthday
    address: str = ""          # → metadata.address, one line
    details: Dict[str, str] = Field(default_factory=dict)   # → metadata.imported
    # Non-empty = this person must not be marketed to on that channel,
    # and the text is the plain reason. There is deliberately NO field
    # that means "they agreed": an import can only take permission away.
    email_opt_out: str = ""
    sms_opt_out: str = ""


class ImportTable(BaseModel):
    """The file as the practitioner mapped it: headers, rows, and one
    contact_fields field id per column. The server turns it into rows
    with the same function the Structure Import uses."""
    headers: List[str]
    rows: List[List[Any]] = Field(default_factory=list)
    fields: List[str]


class ImportBody(BaseModel):
    rows: List[ImportRow] = Field(default_factory=list)
    # Either `rows` (already shaped) or `table` (mapped columns). The
    # dialog sends `table`, so the column meaning lives server-side.
    table: Optional[ImportTable] = None
    # True = compute and report, write nothing. The UI always runs this
    # first so the practitioner sees what is about to happen.
    dry_run: bool = False
    # What to do with a row that matches an existing contact.
    #   'skip'   — leave the existing row alone (default) — EXCEPT that an
    #              opt-out in the file is always carried onto them
    #   'fill'   — only fill fields that are currently empty
    on_duplicate: str = "skip"
    # Where the list came from, for the record: 'file' | 'phone'.
    source: str = "file"


class ColumnsBody(BaseModel):
    headers: List[str]
    sample_rows: List[List[Any]] = Field(default_factory=list)
    # Rows with a value, per column, across the whole file — so a column
    # filled only far down the file is not mistaken for an empty one.
    filled: Optional[List[int]] = None


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
    """E.164 or ''. Same key the SMS rail sends and checks STOP on, after
    the formatting a phone's own export adds ('+1 (555) 010-2233')."""
    return contact_fields.phone_key(raw)


def _preload_existing(biz_id: str) -> Tuple[Dict[str, str], Dict[str, str], bool]:
    """(email -> id, phone match key -> id, complete?).

    `complete` is False when the business has more contacts than
    PRELOAD_CAP, which tells the caller it must fall back to per-row
    lookups rather than trusting a miss.

    Existing phones are keyed with the SAME function as the file's, so a
    number typed by hand as "(555) 010-2233" matches a phone export's
    "+1 555-010-2233" — the re-import that used to duplicate everyone.
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
            ph = contact_fields.phone_match_key(r.get("phone") or "")
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
    if phone and phone.startswith("+"):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{biz_id}"
            f"&phone=eq.{urllib.parse.quote(phone, safe='')}"
            f"&select=id&limit=1") or []
        if rows:
            return rows[0]["id"]
    return None


def _optout_record(reason: str, now_iso: str, source: str) -> Dict[str, Any]:
    return {"reason": reason[:60], "at": now_iso, "source": f"import:{source}"}


def _metadata_for(raw: ImportRow, now_iso: str, source: str,
                  extra_details: Dict[str, str]) -> Dict[str, Any]:
    """Everything a row carries that has no contacts COLUMN, under named
    keys. There is no `notes` column on contacts — free text belongs in
    metadata, the way every public writer already does it (writing a
    `notes` key into the row would 400 the whole batch, PGRST204)."""
    md: Dict[str, Any] = {}
    note = (raw.note or "").strip()
    if note:
        md["import_note"] = note[:2000]
    if (raw.first_name or "").strip() and (raw.last_name or "").strip():
        md["first_name"] = raw.first_name.strip()[:80]
        md["last_name"] = raw.last_name.strip()[:80]
    if (raw.company or "").strip():
        md["organization"] = raw.company.strip()[:200]
    if (raw.birthday or "").strip():
        md["birthday"] = raw.birthday.strip()[:40]
    if (raw.address or "").strip():
        md["address"] = raw.address.strip()[:400]
    details = {str(k).strip()[:80]: str(v).strip()[:contact_fields.MAX_DETAIL_CHARS]
               for k, v in list((raw.details or {}).items())[:contact_fields.MAX_DETAILS]
               if str(k).strip() and str(v).strip()}
    details.update(extra_details)
    if details:
        md["imported"] = details
    if (raw.email_opt_out or "").strip():
        md["email_opt_out"] = _optout_record(raw.email_opt_out.strip(), now_iso, source)
    if (raw.sms_opt_out or "").strip():
        md["sms_opt_out"] = _optout_record(raw.sms_opt_out.strip(), now_iso, source)
    if md:
        md["imported_at"] = now_iso
        md["imported_from"] = source
    return md


def _opt_out_words(email_out: str, sms_out: str) -> str:
    if email_out and sms_out:
        return "no marketing email or texts"
    if email_out:
        return "no marketing email"
    if sms_out:
        return "no texts"
    return ""


@router.post("/{business_id}/columns")
def guess_columns(business_id: str, body: ColumnsBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Headers (+ a sample) in → what each column probably is, out. Reads
    and writes nothing; it is here so the dialog and the Structure Import
    read a Square or Google export the same way (contact_fields)."""
    _gate(business_id, user, "member")
    if len(body.headers) > contact_fields.MAX_COLUMNS:
        raise HTTPException(400, f"{len(body.headers)} columns is over the "
                                 f"{contact_fields.MAX_COLUMNS}-column limit")
    headers = [str(h or "")[:200] for h in body.headers]
    sample = [[str(v if v is not None else "")[:300] for v in (r or [])[:len(headers)]]
              for r in body.sample_rows[:25]]
    return {"ok": True,
            "fields": [dict(f) for f in contact_fields.FIELDS],
            "columns": contact_fields.guess_columns(headers, sample, body.filled)}


@router.post("/{business_id}")
def import_contacts(business_id: str, body: ImportBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _gate(business_id, user, "member")

    source = body.source if body.source in ("file", "phone", "structure_import") else "file"
    columns: Optional[List[Dict[str, Any]]] = None
    rows_in: List[ImportRow] = list(body.rows)
    if body.table is not None:
        t = body.table
        if len(t.rows) > MAX_ROWS:
            raise HTTPException(
                400, f"{len(t.rows)} rows is over the {MAX_ROWS}-row limit for one "
                     f"import — split the file and run it again")
        problem = contact_fields.validate_fields(t.headers, t.fields)
        if problem:
            raise HTTPException(400, problem)
        rows_in = [ImportRow(**r) for r in contact_fields.rows_from_table(t.headers, t.rows, t.fields)]
        columns = contact_fields.column_report(t.headers, t.rows, t.fields)

    if not rows_in:
        raise HTTPException(400, "no rows supplied")
    if len(rows_in) > MAX_ROWS:
        raise HTTPException(
            400, f"{len(rows_in)} rows is over the {MAX_ROWS}-row limit for one "
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
    to_fill: List[Tuple[int, str, Dict[str, Any], Dict[str, Any]]] = []
    # Within-batch dedupe — a CSV repeats people far more often than a
    # web form does. Keys → the row that owns that person.
    seen_email: Dict[str, int] = {}
    seen_phone: Dict[str, int] = {}
    # Where each accepted row's person lives: ('create', payload) or
    # ('existing', contact_id). A later duplicate's opt-out follows it.
    owner: Dict[int, Tuple[str, Any]] = {}
    # Opt-outs for people ALREADY in contacts: contact_id → {email, sms}.
    existing_outs: Dict[str, Dict[str, str]] = {}
    # Every phone the file says must not be texted: E.164 → reason. Kept
    # even when the row itself is skipped — a STOP is never dropped.
    sms_phones: Dict[str, str] = {}

    def carry(target: Tuple[str, Any], email_out: str, sms_out: str) -> None:
        kind, ref = target
        if kind == "create":
            md = ref.setdefault("metadata", {})
            if email_out and "email_opt_out" not in md:
                md["email_opt_out"] = _optout_record(email_out, now_iso, source)
            if sms_out and "sms_opt_out" not in md:
                md["sms_opt_out"] = _optout_record(sms_out, now_iso, source)
        else:
            cur = existing_outs.setdefault(ref, {})
            if email_out:
                cur.setdefault("email", email_out)
            if sms_out:
                cur.setdefault("sms", sms_out)

    for i, raw in enumerate(rows_in):
        name = (raw.name or "").strip()
        if not name:
            name = " ".join(x for x in ((raw.first_name or "").strip(),
                                        (raw.last_name or "").strip()) if x)
        email = (raw.email or "").strip().lower()
        raw_phone = (raw.phone or "").strip()
        phone = _norm_phone(raw_phone)
        phone_key = contact_fields.phone_match_key(raw_phone)
        email_out = (raw.email_opt_out or "").strip()[:60]
        sms_out = (raw.sms_opt_out or "").strip()[:60]
        if sms_out and phone:
            sms_phones.setdefault(phone, sms_out)
        extra: Dict[str, str] = {}
        note_bits: List[str] = []

        # A phone we cannot put in E.164 is still kept — as written, in
        # the phone column when it has enough digits to be a number, as a
        # detail when it does not.
        phone_store = phone
        if raw_phone and not phone:
            if phone_key:
                phone_store = raw_phone[:40]
            else:
                extra["Phone (as written)"] = raw_phone[:80]

        # An email that is not an address no longer throws the person
        # away: they come in without it, and it is kept as written.
        if email and "@" not in email:
            extra["Email (as written)"] = (raw.email or "").strip()[:120]
            note_bits.append(f"'{(raw.email or '').strip()[:60]}' is not an email address — kept as a detail")
            email = ""

        # name is NOT NULL on contacts. Rather than reject a row that has a
        # perfectly good email, fall back to the local-part — a contact
        # called "marcus" beats a failed row, and the practitioner can see
        # what happened in the report.
        if not name:
            if email:
                name = email.split("@", 1)[0]
            elif phone_store:
                name = phone_store
            else:
                results.append({"row": i, "action": "skipped",
                                "reason": "no name, email or phone"})
                continue

        # Duplicate inside this file?
        dup_of = None
        if email and email in seen_email:
            dup_of = seen_email[email]
        elif phone_key and phone_key in seen_phone:
            dup_of = seen_phone[phone_key]
        if dup_of is not None:
            outs = _opt_out_words(email_out, sms_out)
            if (email_out or sms_out) and dup_of in owner:
                carry(owner[dup_of], email_out, sms_out)
            results.append({"row": i, "name": name, "action": "skipped",
                            "reason": f"same person as row {dup_of + 1} in this file"
                                      + (f" — their {outs} carries over" if outs else "")})
            continue

        existing_id = by_email.get(email) if email else None
        if not existing_id and phone_key:
            existing_id = by_phone.get(phone_key)
        if not existing_id and not complete:
            existing_id = _lookup_one(business_id, email, phone)

        if email:
            seen_email[email] = i
        if phone_key:
            seen_phone[phone_key] = i

        if existing_id:
            owner[i] = ("existing", existing_id)
            carry(owner[i], email_out, sms_out)
            outs = _opt_out_words(email_out, sms_out)
            reason = "already in your contacts"
            if body.on_duplicate == "fill":
                patch: Dict[str, Any] = {}
                if email:
                    patch["email"] = email
                if phone_store:
                    patch["phone"] = phone_store
                if (raw.title or "").strip():
                    patch["role"] = raw.title.strip()[:120]
                meta = _metadata_for(raw.model_copy(update={"email_opt_out": "", "sms_opt_out": ""}),
                                     now_iso, source, extra)
                to_fill.append((i, existing_id, patch, meta))
                reason += " — filling blanks"
            if outs:
                reason += f" — marked for {outs}"
            row_out = {"row": i, "name": name, "action": "matched",
                       "reason": reason, "contact_id": existing_id}
            if email_out or sms_out:
                row_out["opt_out"] = [c for c, v in (("email", email_out), ("sms", sms_out)) if v]
            results.append(row_out)
            continue

        status = contact_fields.normalize_status(raw.status or "")
        if status not in VALID_STATUSES:
            status = "lead"
        tags = [str(t).strip()[:40] for t in (raw.tags or []) if str(t).strip()][:20]

        payload: Dict[str, Any] = {
            "business_id": business_id,
            "name": name[:200],
            "email": email or None,
            "phone": phone_store or None,
            "status": status,
            "source": "csv_import",
            "tags": tags,
            "metadata": _metadata_for(raw, now_iso, source, extra),
        }
        if (raw.title or "").strip():
            payload["role"] = raw.title.strip()[:120]
        to_create.append((i, payload))
        owner[i] = ("create", payload)
        row_out = {"row": i, "name": name, "action": "create"}
        if note_bits:
            row_out["reason"] = "; ".join(note_bits)
        if email_out or sms_out:
            row_out["opt_out"] = [c for c, v in (("email", email_out), ("sms", sms_out)) if v]
        results.append(row_out)

    # Opted-out people, counted once each whatever path brought them in.
    email_out_n = sum(1 for _, p in to_create if (p.get("metadata") or {}).get("email_opt_out")) \
        + sum(1 for v in existing_outs.values() if v.get("email"))
    sms_out_n = sum(1 for _, p in to_create if (p.get("metadata") or {}).get("sms_opt_out")) \
        + sum(1 for v in existing_outs.values() if v.get("sms"))

    summary = {
        "to_create": len(to_create),
        "matched": sum(1 for r in results if r["action"] == "matched"),
        "skipped": sum(1 for r in results if r["action"] == "skipped"),
        "total": len(rows_in),
        "email_opt_outs": email_out_n,
        "sms_opt_outs": sms_out_n,
    }

    if body.dry_run:
        out = {"ok": True, "dry_run": True, "summary": summary, "results": results}
        if columns is not None:
            out["columns"] = columns
        return out

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
            if len(made) != len(chunk):
                raise RuntimeError(f"{len(made)} of {len(chunk)} rows came back")
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
    for idx, cid, patch, meta in to_fill:
        try:
            # Only fill what is actually blank — an import must never
            # overwrite a number someone corrected by hand.
            cur = sb_clients.sb_get_as_service(
                f"/contacts?id=eq.{cid}&business_id=eq.{business_id}"
                f"&select=email,phone,role,metadata&limit=1") or []
            if not cur:
                continue
            gap = {k: v for k, v in patch.items()
                   if v and not str(cur[0].get(k) or "").strip()}
            cur_md = cur[0].get("metadata") if isinstance(cur[0].get("metadata"), dict) else {}
            md_gap = {k: v for k, v in meta.items() if k not in cur_md}
            if isinstance(meta.get("imported"), dict) and isinstance(cur_md.get("imported"), dict):
                merged = {**meta["imported"], **cur_md["imported"]}
                if merged != cur_md["imported"]:
                    md_gap["imported"] = merged
            if md_gap and set(md_gap) - {"imported_at", "imported_from"}:
                gap["metadata"] = {**cur_md, **md_gap}
            if gap:
                gap["last_interaction"] = now_iso
                sb_clients.sb_patch_as_service(
                    f"/contacts?id=eq.{cid}&business_id=eq.{business_id}", gap)
                filled += 1
        except Exception as e:
            logger.warning(f"[import] fill failed contact={cid}: {e}")

    # Opt-outs onto people who were already here — ALWAYS, whatever
    # on_duplicate says. "Leave them alone" means don't overwrite what
    # they have; it never means "keep mailing someone who unsubscribed".
    opt_out_failed = 0
    for cid, outs in existing_outs.items():
        try:
            cur = sb_clients.sb_get_as_service(
                f"/contacts?id=eq.{cid}&business_id=eq.{business_id}"
                f"&select=id,phone,metadata&limit=1") or []
            if not cur:
                continue
            md = dict(cur[0].get("metadata") or {}) if isinstance(cur[0].get("metadata"), dict) else {}
            changed = False
            if outs.get("email") and not md.get("email_opt_out"):
                md["email_opt_out"] = _optout_record(outs["email"], now_iso, source)
                changed = True
            if outs.get("sms"):
                if not md.get("sms_opt_out"):
                    md["sms_opt_out"] = _optout_record(outs["sms"], now_iso, source)
                    changed = True
                ph = _norm_phone(cur[0].get("phone") or "")
                if ph:
                    sms_phones.setdefault(ph, outs["sms"])
            if changed:
                sb_clients.sb_patch_as_service(
                    f"/contacts?id=eq.{cid}&business_id=eq.{business_id}", {"metadata": md})
        except Exception as e:
            opt_out_failed += 1
            logger.warning(f"[import] opt-out carry failed contact={cid}: {e}")

    # The SMS STOP ledger every text path already checks
    # (sms_service.is_opted_out, scoped to this business). One upsert;
    # a duplicate is not an error — they were already opted out.
    sms_recorded = 0
    if sms_phones:
        written = sb_clients.sb_post_as_service(
            "/sms_opt_outs?on_conflict=phone,business_id",
            [{"phone": p, "business_id": business_id} for p in sms_phones],
            prefer="resolution=ignore-duplicates,return=representation")
        if written is None:
            opt_out_failed += len(sms_phones)
            logger.error(f"[import] sms_opt_outs write FAILED biz={business_id[:8]} "
                         f"n={len(sms_phones)} — these numbers are marked on the contact only")
        else:
            sms_recorded = len(sms_phones)

    summary.update({"created": len(created_ids), "failed": failed, "filled": filled,
                    "sms_numbers_opted_out": sms_recorded, "opt_out_failed": opt_out_failed})
    summary.pop("to_create", None)

    n = len(created_ids)
    line = f"Imported {n} contact{'' if n == 1 else 's'} from {'phone contacts' if source == 'phone' else 'a file'}"
    if summary["matched"]:
        line += f", {summary['matched']} already known"
    if email_out_n or sms_out_n:
        line += f", opt-outs carried (email {email_out_n}, texts {sms_out_n})"
    if failed:
        line += f", {failed} failed"

    audit_log.record(
        business_id, actor_type="user", actor_id=str(user.id),
        verb="import_contacts", ok=(failed == 0 and opt_out_failed == 0),
        summary=line,
        target_type="contacts",
        payload={"summary": summary, "on_duplicate": body.on_duplicate, "source": source},
        source="contacts_import",
        authorized_by="member+",
    )

    out = {"ok": True, "dry_run": False, "summary": summary,
           "results": results, "created_ids": created_ids}
    if columns is not None:
        out["columns"] = columns
    return out
