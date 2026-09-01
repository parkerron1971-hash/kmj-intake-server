"""
structure_import_router.py — Stage 0 of the Structure Import arc, the wire.

  POST /structure-import/propose/{business_id}
      headers + sample rows in → a PROPOSAL out (never a built thing)
  POST /structure-import/run/{business_id}
      the confirmed (possibly edited) proposal + full rows → dry run, or
      build the module(s) and land the rows

The rubric lives in structure_import.py and reads nothing from the
database; this file does the reads, the gates, the caps, the writes and
the audit row. Spec: STRUCTURE_IMPORT_ARC_SPEC.md §3, §6, §7.

THE ORDER OF A REAL RUN IS THE WHOLE SAFETY STORY
  Create the module → READ IT BACK → only then insert entries. A
  half-built import that landed 400 orphan rows against a module whose
  insert 4xx'd is the worst outcome this endpoint can produce, and
  sb_post_as_service returns None on a 4xx rather than raising — so the
  read-back is what proves the module exists before a single row goes in.

THE CLIENT'S PROPOSAL IS UNTRUSTED
  The practitioner edits the proposal in the browser before confirming.
  A `select` handed back with no options, a `module_ref` with no target,
  a `file` field an import could never fill — all rejected here with the
  validator's own strings, before the dry run says a word.

PEOPLE SHEETS REUSE THE CONTACTS IMPORT
  A sheet routed to contacts is handed to contacts_import_router's
  import_contacts — same dedupe, same dry run, same audit verb — so there
  is one way people enter the system, not two.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import audit_log
import sb_clients
import structure_import as si
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("structure_import")

router = APIRouter(prefix="/structure-import", tags=["structure-import"])

MAX_ROWS_PER_SHEET = 2000
MAX_COLUMNS = 60
CONTACTS_PRELOAD = 5000
CHUNK = 100


# ─── Bodies ──────────────────────────────────────────────────────────

class SheetIn(BaseModel):
    name: str = "Sheet"
    headers: List[str]
    sample_rows: List[List[Any]] = Field(default_factory=list)
    total_rows: int = 0


class ProposeBody(BaseModel):
    source_name: str = ""
    sheets: List[SheetIn]


class RunSheet(BaseModel):
    sheet: str
    verdict: str                                  # existing_surface | new_module | ignore
    headers: List[str] = Field(default_factory=list)
    target: Optional[Dict[str, Any]] = None
    columns: List[Dict[str, Any]] = Field(default_factory=list)
    import_hints: Dict[str, Any] = Field(default_factory=dict)


class RunBody(BaseModel):
    proposal_id: str = ""
    sheets: List[RunSheet]
    rows: Dict[str, List[List[Any]]] = Field(default_factory=dict)
    dry_run: bool = True
    on_duplicate: str = "skip"


# ─── Gate ────────────────────────────────────────────────────────────

def _gate(biz_id: str, user: AuthedUser, min_role: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}&select=id,name,owner_id,type&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz_id, str(user.id), min_role)
    return rows[0]


def _known_contacts(biz_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    while offset < CONTACTS_PRELOAD:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{biz_id}&select=name,email"
            f"&order=created_at.asc&limit=1000&offset={offset}") or []
        out.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000
    return out


# ─── Propose ─────────────────────────────────────────────────────────

@router.post("/propose/{business_id}")
def propose(business_id: str, body: ProposeBody,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(business_id, user, "member")
    if not body.sheets:
        raise HTTPException(400, "no sheets supplied")
    if len(body.sheets) > si.MAX_SHEETS:
        raise HTTPException(400, f"{len(body.sheets)} sheets is over the {si.MAX_SHEETS}-sheet "
                                 f"limit for one pass — split the upload")
    sheets = []
    for s in body.sheets:
        if not s.headers:
            raise HTTPException(400, f"sheet “{s.name}” has no header row")
        if len(s.headers) > MAX_COLUMNS:
            raise HTTPException(400, f"sheet “{s.name}” has {len(s.headers)} columns — "
                                     f"the limit is {MAX_COLUMNS}")
        sheets.append({
            "name": (s.name or "Sheet")[:80],
            "headers": [str(h or "")[:si.MAX_CELL_CHARS] for h in s.headers],
            "sample_rows": [[str(v if v is not None else "")[:si.MAX_CELL_CHARS] for v in (r or [])]
                            for r in s.sample_rows[:si.MAX_SAMPLE_ROWS]],
            "total_rows": max(0, int(s.total_rows or 0)),
        })
    contacts = _known_contacts(business_id)
    proposal = si.propose(sheets, contacts)
    for entry in proposal["sheets"]:
        target = entry.get("target") or {}
        spec = target.get("spec")
        if spec and spec.get("archetype") == "event_roster":
            # The run needs to know which column names the person — an
            # archetype param does not carry that, so it rides as a hint.
            person = next((c for c in entry["columns"]
                           if c.get("field") and c["field"].get("type") in ("contact_link", "text")
                           and si._header_has(c["header"], si._NAME_HEADERS)), None)
            entry["import_hints"] = {"person_field": person["field"]["name"]} if person else {}
    return {
        "ok": True,
        "proposal_id": str(uuid.uuid4()),
        "source_name": (body.source_name or "")[:160],
        # The rubric is deterministic — no model call, no credits.
        "credits_spent": 0,
        **proposal,
    }


# ─── Run ─────────────────────────────────────────────────────────────

def _validate_spec(spec: Dict[str, Any]) -> List[str]:
    """Vocabulary validator first (plain strings), then the ModuleSpec
    model for the archetype rules it already enforces."""
    errors = si.validate_module_schema(spec.get("schema"))
    if errors:
        return errors
    try:
        from module_spec_generator import ModuleSpec
        ModuleSpec.model_validate({
            "slug": spec.get("slug") or "imported",
            "name": spec.get("name") or "Imported",
            "icon": spec.get("icon") or "Table",
            "description": spec.get("description") or "Imported from a file.",
            "intake_excerpt": "structure import",
            "schema": spec.get("schema"),
            "reasoning": "structure import proposal",
            "archetype": spec.get("archetype") or "fallback_generic",
            "archetype_params": spec.get("archetype_params") or {},
            "archetype_fallback_reason": spec.get("archetype_fallback_reason"),
        })
    except Exception as e:  # pydantic ValidationError or ValueError
        return [str(e)[:400]]
    return []


def _contacts_rows(sheet: RunSheet, rows: List[List[Any]]) -> List[Dict[str, Any]]:
    idx = {str(h or "").strip(): i for i, h in enumerate(sheet.headers)}
    plan: Dict[str, int] = {}
    for col in sheet.columns:
        if col.get("decision") != "map" or not col.get("field"):
            continue
        target = col["field"].get("name")
        i = idx.get(str(col.get("header") or "").strip())
        if target in ("name", "email", "phone", "status", "tags", "note") and i is not None:
            plan.setdefault(target, i)
    out = []
    for r in rows:
        def get(k: str) -> str:
            i = plan.get(k)
            return str(r[i] if i is not None and i < len(r) and r[i] is not None else "").strip()
        tags = [t.strip() for t in get("tags").replace("|", ";").split(";") if t.strip()]
        out.append({"name": get("name"), "email": get("email"), "phone": get("phone"),
                    "status": get("status").lower(), "tags": tags, "note": get("note")})
    return out


def _run_contacts(business_id: str, user: AuthedUser, sheet: RunSheet,
                  rows: List[List[Any]], dry_run: bool, on_duplicate: str) -> Dict[str, Any]:
    from contacts_import_router import ImportBody, ImportRow, import_contacts
    payload = [ImportRow(**r) for r in _contacts_rows(sheet, rows)]
    if not payload:
        return {"sheet": sheet.sheet, "module_action": "n/a", "module_slug": "contacts",
                "summary": {"to_create": 0, "matched": 0, "skipped": 0, "total": 0}, "results": []}
    res = import_contacts(business_id, ImportBody(rows=payload, dry_run=dry_run,
                                                   on_duplicate=on_duplicate), user)
    return {"sheet": sheet.sheet, "module_action": "n/a", "module_slug": "contacts",
            "summary": res.get("summary") or {}, "results": res.get("results") or []}


def _group_roster(entries: List[Dict[str, Any]], params: Dict[str, Any],
                  person_field: Optional[str]) -> List[Dict[str, Any]]:
    """event_roster: many rows share one occasion → one entry per occasion
    with a signups[] array. Without a person column every row is its own
    occasion, which is honest if unhelpful."""
    title_f = params.get("title_field") or "title"
    date_f = params.get("date_field")
    signups_f = params.get("signups_field") or "signups"
    if not person_field:
        return entries
    grouped: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for e in entries:
        d = dict(e["data"])
        who = d.pop(person_field, None)
        key = f"{d.get(title_f)}|{d.get(date_f) if date_f else ''}"
        if key not in grouped:
            grouped[key] = {"row": e["row"], "data": {**d, signups_f: []}}
            order.append(key)
        if who:
            grouped[key]["data"][signups_f].append({"name": str(who), "status": "yes"})
    return [grouped[k] for k in order]


def _run_module(business_id: str, user: AuthedUser, sheet: RunSheet,
                rows: List[List[Any]], dry_run: bool) -> Dict[str, Any]:
    spec = (sheet.target or {}).get("spec") or {}
    errors = _validate_spec(spec)
    if errors:
        raise HTTPException(422, {"error": "invalid_spec", "sheet": sheet.sheet, "errors": errors})
    fields = (spec.get("schema") or {}).get("fields") or []
    entries, problems = si.rows_to_entries(sheet.headers, rows, sheet.columns, fields)
    archetype = spec.get("archetype") or "fallback_generic"
    params = spec.get("archetype_params") or {}
    if archetype == "event_roster":
        entries = _group_roster(entries, params, (sheet.import_hints or {}).get("person_field"))
    slug = spec.get("slug") or si.slugify(spec.get("name") or sheet.sheet)

    existing = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}&slug=eq.{slug}&select=id,slug&limit=1") or []
    summary = {"to_create": len(entries), "matched": 0, "skipped": len(problems), "total": len(rows)}
    if dry_run:
        return {"sheet": sheet.sheet, "module_action": "reused" if existing else "would_create",
                "module_slug": slug, "module_id": existing[0]["id"] if existing else None,
                "summary": summary, "results": problems}

    # 1. The module — create, then PROVE it exists.
    if existing:
        module_id = existing[0]["id"]
        module_action = "reused"
    else:
        payload = {
            "business_id": business_id, "sort_order": 0,
            "name": spec.get("name") or slug, "slug": slug,
            "description": spec.get("description"), "icon": spec.get("icon") or "Table",
            "schema": spec.get("schema"), "agent_config": {"enabled": True, "triggers": []},
            "is_active": True,
            "archetype": archetype, "archetype_params": params,
            "archetype_fallback_reason": spec.get("archetype_fallback_reason"),
        }
        created = sb_clients.sb_post_as_service("/custom_modules", payload)
        module_id = created[0].get("id") if isinstance(created, list) and created else None
        if not module_id:
            raise HTTPException(500, {"error": "module_create_failed", "sheet": sheet.sheet,
                                      "detail": "the module was not created — no rows were written"})
        module_action = "created"
    check = sb_clients.sb_get_as_service(
        f"/custom_modules?id=eq.{module_id}&business_id=eq.{business_id}&select=id&limit=1") or []
    if not check:
        raise HTTPException(500, {"error": "module_missing_after_create", "sheet": sheet.sheet,
                                  "detail": "the module could not be read back — no rows were written"})

    # 2. The rows, in chunks. A failed chunk is reported, never hidden.
    created_n, failed_n = 0, 0
    results = list(problems)
    for start in range(0, len(entries), CHUNK):
        chunk = entries[start:start + CHUNK]
        body = [{"module_id": module_id, "business_id": business_id, "data": e["data"],
                 "status": "active", "created_by": str(user.id), "source": "structure_import"}
                for e in chunk]
        res = sb_clients.sb_post_as_service("/module_entries", body)
        if isinstance(res, list) and len(res) == len(chunk):
            created_n += len(chunk)
        else:
            failed_n += len(chunk)
            results.extend({"row": e["row"], "action": "failed", "reason": "the database refused this batch"}
                           for e in chunk)
    summary = {"created": created_n, "failed": failed_n, "matched": 0,
               "skipped": len(problems), "total": len(rows)}
    return {"sheet": sheet.sheet, "module_action": module_action, "module_slug": slug,
            "module_id": module_id, "summary": summary, "results": results}


@router.post("/run/{business_id}")
def run(business_id: str, body: RunBody,
        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _gate(business_id, user, "manager")
    if not body.sheets:
        raise HTTPException(400, "no sheets supplied")
    if body.on_duplicate not in ("skip", "fill"):
        raise HTTPException(400, "on_duplicate must be 'skip' or 'fill'")
    for s in body.sheets:
        n = len(body.rows.get(s.sheet) or [])
        if n > MAX_ROWS_PER_SHEET:
            raise HTTPException(400, f"sheet “{s.sheet}” has {n} rows — the limit is "
                                     f"{MAX_ROWS_PER_SHEET} per import; split it and run again")

    # Validate EVERY module sheet before touching any — a run must not
    # build sheet 1 and then refuse sheet 2.
    for s in body.sheets:
        if s.verdict == "new_module":
            errors = _validate_spec((s.target or {}).get("spec") or {})
            if errors:
                raise HTTPException(422, {"error": "invalid_spec", "sheet": s.sheet, "errors": errors})

    out: List[Dict[str, Any]] = []
    for s in body.sheets:
        rows = body.rows.get(s.sheet) or []
        if s.verdict == "ignore":
            out.append({"sheet": s.sheet, "module_action": "n/a", "module_slug": None,
                        "summary": {"to_create": 0, "matched": 0, "skipped": len(rows), "total": len(rows)},
                        "results": []})
        elif s.verdict == "existing_surface":
            out.append(_run_contacts(business_id, user, s, rows, body.dry_run, body.on_duplicate))
        elif s.verdict == "new_module":
            out.append(_run_module(business_id, user, s, rows, body.dry_run))
        else:
            raise HTTPException(400, f"sheet “{s.sheet}” has an unknown verdict {s.verdict!r}")

    if not body.dry_run:
        built = [o for o in out if o.get("module_action") in ("created", "reused")]
        landed = sum(int((o.get("summary") or {}).get("created") or 0) for o in out)
        audit_log.record(
            business_id, actor_type="user", actor_id=str(user.id), verb="structure_import",
            ok=True,
            summary=f"Imported {landed} rows across {len(out)} sheet(s); "
                    f"{len(built)} module(s) built or reused",
            target_type="custom_modules",
            payload={"proposal_id": body.proposal_id[:80],
                     "sheets": [{"sheet": o["sheet"], "module_slug": o.get("module_slug"),
                                 "module_action": o.get("module_action"),
                                 "summary": o.get("summary")} for o in out]},
            source="structure_import", authorized_by="manager+")
    return {"ok": True, "dry_run": body.dry_run, "proposal_id": body.proposal_id, "sheets": out}
