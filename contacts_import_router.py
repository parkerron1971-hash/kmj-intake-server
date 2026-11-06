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
    # 2026-11-06 — a church's file (contact_fields CHURCH_FIELDS). People
    # who share a household become one family: households +
    # household_adults + children, what Kids check-in reads. Ignored for
    # a business. `birthdate` is the birthday as a full date, or "".
    household: str = ""
    household_role: str = ""   # 'adult' | 'child' | ''
    birthdate: str = ""


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
        f"/businesses?id=eq.{biz_id}&select=id,name,owner_id,type&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz_id, str(user.id), min_role)
    return rows[0]


def _is_church(biz: Dict[str, Any]) -> bool:
    import vertical_registry
    return vertical_registry.resolve(str(biz.get("type") or "")) == "ministry"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _families_line(families: List[Dict[str, Any]]) -> str:
    """The household column's line in the preview."""
    if not families:
        return "No families: nobody here shares a household with someone else"
    kids = sum(len(f["children"]) for f in families)
    line = f"Makes {_plural(len(families), 'family', 'families')}"
    return line + (f", with {_plural(kids, 'child', 'children')} for Kids check-in" if kids else "")


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm_phone(raw: str) -> str:
    """E.164 or ''. Same key the SMS rail sends and checks STOP on, after
    the formatting a phone's own export adds ('+1 (555) 010-2233')."""
    return contact_fields.phone_key(raw)


def _same_keys(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PostgREST refuses a bulk insert whose rows don't share their keys
    (PGRST102, "All object keys must match"), which loses the whole chunk.
    role, birthdate and first_response_at are on only some rows, so every
    row carries every key, null where it has none."""
    keys = sorted({k for r in rows for k in r})
    return [{k: r.get(k) for k in keys} for r in rows]


def _name_key(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


def _preload_existing(biz_id: str, by_name: Optional[Dict[str, List[Tuple[str, str]]]] = None
                      ) -> Tuple[Dict[str, str], Dict[str, str], bool]:
    """(email -> id, phone match key -> id, complete?).

    `by_name`, when given, is filled with name -> [(id, birthdate)]: a
    church's children come with no email or phone, and a second import
    of the same file must not add them twice.

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
            + (",name,birthdate" if by_name is not None else "")
            + f"&order=created_at.asc&limit={PAGE}&offset={offset}") or []
        for r in rows:
            em = (r.get("email") or "").strip().lower()
            ph = contact_fields.phone_match_key(r.get("phone") or "")
            if by_name is not None and _name_key(r.get("name")):
                by_name.setdefault(_name_key(r.get("name")), []).append(
                    (r["id"], str(r.get("birthdate") or "")[:10]))
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
    church = _is_church(_gate(business_id, user, "member"))
    if len(body.headers) > contact_fields.MAX_COLUMNS:
        raise HTTPException(400, f"{len(body.headers)} columns is over the "
                                 f"{contact_fields.MAX_COLUMNS}-column limit")
    headers = [str(h or "")[:200] for h in body.headers]
    sample = [[str(v if v is not None else "")[:300] for v in (r or [])[:len(headers)]]
              for r in body.sample_rows[:25]]
    return {"ok": True, "church": church,
            "fields": contact_fields.fields_for(church),
            "columns": contact_fields.guess_columns(headers, sample, body.filled, church=church)}


@router.post("/{business_id}")
def import_contacts(business_id: str, body: ImportBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _gate(business_id, user, "member")
    church = _is_church(biz)

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
        fields = [("detail" if f in contact_fields.CHURCH_FIELDS and not church else f) for f in t.fields]
        rows_in = [ImportRow(**r) for r in contact_fields.rows_from_table(t.headers, t.rows, fields)]
        columns = contact_fields.column_report(t.headers, t.rows, fields)
    if not church:
        rows_in = [r.model_copy(update={"household": "", "household_role": "", "birthdate": ""})
                   for r in rows_in]

    if not rows_in:
        raise HTTPException(400, "no rows supplied")
    if len(rows_in) > MAX_ROWS:
        raise HTTPException(
            400, f"{len(rows_in)} rows is over the {MAX_ROWS}-row limit for one "
                 f"import — split the file and run it again")
    if body.on_duplicate not in ("skip", "fill"):
        raise HTTPException(400, "on_duplicate must be 'skip' or 'fill'")

    by_name: Optional[Dict[str, List[Tuple[str, str]]]] = {} if church else None
    by_email, by_phone, complete = _preload_existing(business_id, by_name)
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
    # A church's file: one entry per person it brings or matches, for the
    # families (church_families.plan_from_file). Rows with no status of
    # their own ("Child") take their family's.
    people: List[Dict[str, Any]] = []
    no_status: set = set()

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
        if not existing_id and by_name is not None and not email and not phone_key:
            # A church's child, with no email or phone: the same name, and
            # no birthdate that says otherwise, is the same person.
            born = contact_fields.iso_birthdate(raw.birthdate)
            same = [cid for cid, b in by_name.get(_name_key(name), []) if not b or not born or b == born]
            if len(same) == 1:
                existing_id = same[0]

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
            if church and (raw.household or "").strip():
                people.append(_person(i, existing_id, name, raw, now_iso, source))
            continue

        status = contact_fields.normalize_status(raw.status or "")
        if not (raw.status or "").strip():
            no_status.add(i)
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
        if church and status == "lead":
            # Brought over, not waiting on a reply: an imported guest never
            # sits in "nobody has replied" (subsplash_import does the same).
            payload["first_response_at"] = now_iso
        born = contact_fields.iso_birthdate(raw.birthdate) if church else ""
        if born:
            payload["birthdate"] = born
        to_create.append((i, payload))
        owner[i] = ("create", payload)
        row_out = {"row": i, "name": name, "action": "create"}
        if note_bits:
            row_out["reason"] = "; ".join(note_bits)
        if email_out or sms_out:
            row_out["opt_out"] = [c for c, v in (("email", email_out), ("sms", sms_out)) if v]
        results.append(row_out)
        if church and (raw.household or "").strip():
            people.append({**_person(i, None, name, raw, now_iso, source), "payload": payload})

    # Families, from the church's own Household column.
    families, families_not_made = _plan_families(business_id, people, to_create, no_status, results)

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
    if church:
        summary["families"] = len(families)
        summary["family_children"] = sum(len(f["children"]) for f in families)
        if columns is not None:
            for c in columns:
                if c["field"] == "household":
                    c["lands"] = _families_line(families)

    def family_list() -> List[Dict[str, Any]]:
        return [{"name": f["name"], "adults": len(f["adults"]), "children": len(f["children"]),
                 "joins": bool(f.get("household_id"))} for f in families]

    if body.dry_run:
        out = {"ok": True, "dry_run": True, "summary": summary, "results": results}
        if columns is not None:
            out["columns"] = columns
        if church:
            out["families"] = family_list()
            out["families_not_made"] = families_not_made
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
                "/contacts", _same_keys([p for _, p in chunk]))
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

    families_made = 0
    if church and families:
        families_made, more_not_made = _make_families(business_id, families, results)
        families_not_made = families_not_made + more_not_made
        summary["families"] = families_made
        summary["family_children"] = sum(len(f["children"]) for f in families if f.get("made"))
        summary["families_failed"] = len(more_not_made)

    n = len(created_ids)
    line = f"Imported {n} contact{'' if n == 1 else 's'} from {'phone contacts' if source == 'phone' else 'a file'}"
    if summary["matched"]:
        line += f", {summary['matched']} already known"
    if families_made:
        line += f", {_plural(families_made, 'family', 'families')} made"
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
    if church:
        out["families"] = [f for f, fam in zip(family_list(), families) if fam.get("made")]
        out["families_not_made"] = families_not_made
    return out


# ─── A church's families ─────────────────────────────────────────────

def _person(i: int, contact_id: Optional[str], name: str, raw: ImportRow,
            now_iso: str, source: str) -> Dict[str, Any]:
    """One person in the file, the shape church_families reads."""
    md = _metadata_for(raw.model_copy(update={"email_opt_out": "", "sms_opt_out": ""}), now_iso, source, {})
    return {"ref": i, "id": contact_id, "name": name, "metadata": md,
            "birthdate": contact_fields.iso_birthdate(raw.birthdate) or None,
            "household": (raw.household or "").strip()[:120],
            "role": raw.household_role if raw.household_role in ("adult", "child") else ""}


def _plan_families(business_id: str, people: List[Dict[str, Any]],
                   to_create: List[Tuple[int, Dict[str, Any]]], no_status: set,
                   results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Who becomes a family, before anything is written. A child the file
    gave no status of its own takes the family's, so a member family's
    children are members on the roll and a visiting family's are guests."""
    if not people:
        return [], []
    import church_families
    homes = church_families.family_of(business_id)
    if homes is None:
        return [], [{"name": "Families", "why": "families couldn't be read just now, so none were made"}]
    families, not_made = church_families.plan_from_file(people, homes)
    existing = [p["id"] for f in families for p in f["adults"] if p.get("id")]         + [i for f in families for i in f.get("already") or []]
    status_of: Dict[str, str] = {}
    if existing:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}&id=in.({','.join(existing)})&select=id,status") or []
        status_of = {str(r["id"]): str(r.get("status") or "") for r in rows}
    by_row = {r["row"]: r for r in results}
    for f in families:
        said = [p["payload"]["status"] if p.get("payload") else status_of.get(str(p["id"]), "")
                for p in f["adults"] if p["ref"] not in no_status]             + [status_of.get(i, "") for i in f.get("already") or []]
        said = [x for x in said if x]
        family_status = "active" if any(s in ("active", "vip") for s in said) else (said[0] if said else "")
        for p in f["adults"] + f["children"]:
            row = by_row.get(p["ref"])
            if row is not None:
                row["family"] = f["name"]
                row["family_as"] = "child" if p in f["children"] else "adult"
        for p in f["children"]:
            if p.get("payload") and p["ref"] in no_status and family_status in VALID_STATUSES:
                p["payload"]["status"] = family_status
                if family_status != "lead":
                    p["payload"].pop("first_response_at", None)
    return families, not_made


def _make_families(business_id: str, families: List[Dict[str, Any]],
                   results: List[Dict[str, Any]]) -> Tuple[int, List[Dict[str, str]]]:
    """Write the planned families once their people exist. Someone whose
    record didn't save leaves the family; a family left with fewer than
    two people, or no adult, isn't made."""
    import church_families
    made_id = {r["row"]: r.get("contact_id") for r in results if r.get("action") in ("created", "matched")}
    made = 0
    not_made: List[Dict[str, str]] = []
    for f in families:
        def ready(people: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            out = []
            for p in people:
                cid = p.get("id") or made_id.get(p["ref"])
                if cid:
                    out.append({**p, "id": cid})
            return out
        adults, kids = ready(f["adults"]), ready(f["children"])
        hid = f.get("household_id")
        if not hid and (not adults or len(adults) + len(kids) < 2):
            if f["adults"] or f["children"]:
                not_made.append({"name": f["name"], "why": "some of them didn't save"})
            continue
        if hid:
            ok = church_families.join_family(business_id, hid, adults, kids) if (adults or kids) else False
        else:
            ok = bool(church_families.make_family(business_id, f["name"], adults, kids))
        if ok:
            f["made"] = True
            made += 1
        else:
            not_made.append({"name": f["name"], "why": "it didn't save; make it on the Families page"})
    return made, not_made
