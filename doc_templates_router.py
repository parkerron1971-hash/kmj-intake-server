"""
doc_templates_router.py — generate documents from the template library.

The surface behind "New Document" in the Documents room:

  GET  /doctemplates/list?biz=   — the nine templates, suggested-for-
                                   this-vertical first (ranking, never
                                   a lockout).
  POST /doctemplates/generate    — {business_id, contact_id,
                                   template_id, params} → the finished
                                   document, landed as an agent_queue
                                   draft (agent='contract',
                                   action_type='document') so the
                                   EXISTING chain executes it: review →
                                   edit → approve/send → branded PDF →
                                   BoldSign e-sign → contract_signed on
                                   the spine. This router produces
                                   paper; it deliberately owns no
                                   sending machinery.

How a document is built (doc_templates.py owns the content):
  fixed clauses render verbatim with {variables} substituted; drafted
  sections get ONE model call in the practitioner's voice — and every
  drafted section has a fallback, so generation succeeds with the
  model down (units are only charged when the model actually ran).
  Variables come from the records: business name, practitioner name,
  the client's name from contacts, today's date, plus the dialog
  fields.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import billing_limits
import doc_templates
import llm_call
import sb_clients
from api_usage_logger import log_api_usage
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("doc_templates_router")

router = APIRouter(prefix="/doctemplates", tags=["doctemplates"])

# Short personalization paragraphs with explicit briefs — a small model
# is plenty, and the fallbacks make failure invisible anyway.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)


def _model() -> str:
    return (os.environ.get("DOCTEMPLATES_MODEL") or "").strip() or DEFAULT_MODEL


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}"
        "&select=id,name,owner_id,type,settings,voice_profile&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _today() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%B')} {now.day}, {now.year}"


# ─── Learned defaults — the first contract teaches the system ────────
# settings.doc_defaults holds the business's standard terms, keyed by
# STICKY field keys only (fee, state, cancel_window…). Populated
# automatically the first time a document is generated with them filled;
# merged under explicit params on every generation after — both doors
# (the dialog pre-fills via /list; Chief's verb merges before asking).

def get_doc_defaults(business: Dict[str, Any]) -> Dict[str, str]:
    d = (business.get("settings") or {}).get("doc_defaults")
    return {k: str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def merge_defaults(business: Dict[str, Any], template: Dict[str, Any],
                   params: Dict[str, str]) -> tuple:
    """(merged_params, used_defaults). Explicit params always win; a
    saved default only fills a STICKY field the caller left blank."""
    saved = get_doc_defaults(business)
    merged = dict(params or {})
    used: Dict[str, str] = {}
    for f in template["fields"]:
        if not f.get("sticky"):
            continue
        if (merged.get(f["key"]) or "").strip():
            continue
        if (saved.get(f["key"]) or "").strip():
            merged[f["key"]] = saved[f["key"]]
            used[f["key"]] = saved[f["key"]]
    return merged, used


def save_sticky_terms(business: Dict[str, Any], template: Dict[str, Any],
                      explicit_params: Dict[str, str]) -> List[str]:
    """Persist sticky terms the practitioner EXPLICITLY gave this time
    (never values that came from the defaults themselves). Returns the
    saved keys. Best-effort — a failed save must not fail the document."""
    saved = get_doc_defaults(business)
    sticky_keys = {f["key"] for f in template["fields"] if f.get("sticky")}
    changed: Dict[str, str] = {}
    for k in sticky_keys:
        v = (explicit_params.get(k) or "").strip()
        if v and saved.get(k) != v:
            changed[k] = v
    if not changed:
        return []
    try:
        settings = dict(business.get("settings") or {})
        settings["doc_defaults"] = {**saved, **changed}
        sb_clients.sb_patch_as_service(
            f"/businesses?id=eq.{business['id']}", {"settings": settings})
        business["settings"] = settings  # keep the in-hand row honest
    except Exception as e:
        logger.warning(f"doc_defaults save failed (non-fatal): {e}")
        return []
    return sorted(changed.keys())


# ─── List ────────────────────────────────────────────────────────────

@router.get("/list")
async def doctemplates_list(biz: str,
                            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    btype = (b.get("type") or "").lower()
    saved = get_doc_defaults(b)
    out = []
    # Learned templates lead — a business's own paper outranks the
    # library's. Same card shape; category 'custom' labels them "Yours".
    for t in load_custom_templates(biz) + doc_templates.TEMPLATES:
        # Overlay the business's learned terms onto sticky fields so the
        # New Document form arrives pre-filled with THEIR standards.
        fields = []
        for f in t["fields"]:
            f2 = dict(f)
            if f.get("sticky") and (saved.get(f["key"]) or "").strip():
                f2["default"] = saved[f["key"]]
            fields.append(f2)
        # The paper itself rides along — the picker renders a real
        # mini-document and the fill step previews it live. Drafted
        # sections ship their fallback text; {placeholders} stay intact
        # for the frontend to substitute as the form fills.
        sections = [{
            "heading": s.get("heading"),
            "text": s["text"] if s["kind"] == "fixed" else s.get("fallback", ""),
            "requires": s.get("requires"),
        } for s in t["sections"]]
        chars = sum(len(s["text"]) for s in sections)
        pages = max(1, round(chars / 2600))
        is_custom = str(t["id"]).startswith("custom:")
        out.append({
            "id": t["id"], "title": t["title"],
            "subtitle": t.get("subtitle") or "",
            "description": t["description"], "category": t["category"],
            "fields": fields,
            "sections": sections,
            "page_estimate": f"≈{pages} page{'s' if pages != 1 else ''}",
            "suggested": is_custom or btype in t.get("suggested_for", []),
            "custom": is_custom,
        })
    # A business's own templates first, then suggested, then the rest
    # in curated library order.
    out.sort(key=lambda t: 0 if t.get("custom") else (1 if t["suggested"] else 2))
    return {"ok": True, "templates": out}


# ─── Drafted sections — one voice-matched call ───────────────────────

def _substitute_brief(brief: str, variables: Dict[str, str]) -> str:
    return brief.format_map(doc_templates._SafeMap(variables))


async def _draft_sections(business: Dict[str, Any], template: Dict[str, Any],
                          variables: Dict[str, str], *, user_id: str,
                          ) -> Dict[int, str]:
    """One call fills every drafted section. Any failure → {} and the
    fallbacks carry the document; a template layer must never be down."""
    todo = [(i, s) for i, s in enumerate(template["sections"])
            if s["kind"] == "drafted"
            and not (s.get("requires")
                     and not (variables.get(s["requires"]) or "").strip())]
    if not todo or not llm_call.api_key():
        return {}

    voice = ""
    try:
        from practitioner_voice import compose_voice_directive
        voice = compose_voice_directive(business) or ""
    except Exception:
        pass

    briefs = "\n\n".join(
        f'Section {i}: {_substitute_brief(s["brief"], variables)}'
        for i, s in todo)
    system = (
        f"You draft short sections of business documents for "
        f"{variables['business_name']}. {voice}\n"
        "Write plainly and professionally — no headings, no placeholders, "
        "no invented facts beyond what the briefs give you. Respond with "
        "ONLY a JSON object mapping each section number to its text, e.g. "
        '{"0": "..."}.')
    payload = {
        "model": _model(), "max_tokens": 1000, "system": system,
        "messages": [{"role": "user", "content":
                      f'Document: {template["title"]}, dated {variables["date"]}, '
                      f'from {variables["business_name"]} to {variables["client_name"]}.'
                      f"\n\n{briefs}"}],
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await llm_call.apost(client, payload, task="doctemplates")
        if resp.status_code >= 400:
            logger.warning(f"doctemplates draft {resp.status_code}: {resp.text[:200]}")
            return {}
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
        usage = data.get("usage") or {}
        try:
            await log_api_usage(
                endpoint="/doctemplates", model=data.get("model") or _model(),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                business_id=business["id"], user_id=user_id,
                task_type=f"doctemplate_{template['id']}",
                duration_ms=int((time.monotonic() - started) * 1000))
        except Exception:
            pass
        m = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
        return {int(k): str(v) for k, v in parsed.items()
                if str(k).isdigit() and isinstance(v, str)}
    except Exception as e:
        logger.warning(f"doctemplates draft failed, using fallbacks: {e}")
        return {}


# ─── Generate ────────────────────────────────────────────────────────

class GenerateBody(BaseModel):
    business_id: str
    contact_id: str
    template_id: str
    params: Dict[str, str] = {}


class GenerationError(Exception):
    """A generation failure with a practitioner-readable message.
    The endpoint maps it to an HTTP status; Chief's handler maps it to
    a failed-action result."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


async def generate_document_core(business: Dict[str, Any],
                                 contact: Dict[str, Any],
                                 template: Dict[str, Any],
                                 params: Dict[str, str], *,
                                 user_id: str) -> Dict[str, Any]:
    """The one generation path — the /doctemplates endpoint and Chief's
    generate_document verb both land here, so the document a practitioner
    gets is identical whichever door they came through. Caller has
    already authorized (owner gate / Chief's turn) and validated the
    template + contact belong to the business."""
    explicit = dict(params or {})
    merged, used_defaults = merge_defaults(business, template, explicit)
    err = doc_templates.validate_params(template, merged)
    if err:
        raise GenerationError(err, 400)
    params = merged

    business_name = business.get("name") or "this business"
    practitioner = ((business.get("settings") or {}).get("practitioner_name")
                    or business_name)
    variables = doc_templates.build_vars(
        template, params or {},
        business_name=business_name, practitioner_name=practitioner,
        client_name=contact.get("name") or "Client", date_str=_today())

    drafted = await _draft_sections(business, template, variables,
                                    user_id=user_id)

    # The attorney-review note rides on everyone's paper except the
    # lawyer's own — they ARE the counsel.
    is_lawyer = (business.get("type") or "").lower() == "lawyer"
    doc_body = doc_templates.assemble(
        template, variables, drafted, include_review_note=not is_lawyer)

    subject = f"{template['title']} — {business_name}"
    queue_id: Optional[str] = None
    queued = sb_clients.sb_post_as_service("/agent_queue", {
        "business_id": business["id"],
        "contact_id": contact["id"],
        "agent": "contract",
        "action_type": "document",
        "subject": subject,
        "body": doc_body,
        "channel": "email" if contact.get("email") else "in_app",
        "status": "draft",
        "priority": "high",
        "ai_reasoning": (f"Generated from the {template['title']} template "
                         f"for {contact.get('name')}."),
        "ai_model": _model() if drafted else None,
    })
    if isinstance(queued, list) and queued:
        queue_id = queued[0].get("id")
    if not queue_id:
        # The document exists but has nowhere to be approved from —
        # surface that honestly instead of a dead 'ok'.
        raise GenerationError(
            "couldn't queue the document for review — try again", 502)

    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": business["id"], "contact_id": contact["id"],
            "event_type": "document_generated",
            "data": {"template_id": template["id"], "title": template["title"],
                     "queue_id": queue_id},
            "source": "doc_templates"})
    except Exception:
        pass

    # The first filled contract teaches the system: explicitly-given
    # sticky terms become the business's standard, pre-filling next time.
    saved_defaults = save_sticky_terms(business, template, explicit)

    return {"ok": True, "queue_id": queue_id, "subject": subject,
            "title": template["title"], "body": doc_body,
            "drafted_sections_used": bool(drafted),
            "used_defaults": used_defaults,
            "saved_defaults": saved_defaults}


def resolve_template(query: str, business_id: Optional[str] = None) -> Any:
    """Loose template lookup for conversational callers: exact id, then
    title/keyword containment. With a business_id, the business's own
    learned templates join the pool — and win exact-title matches, since
    "the consulting agreement" usually means THEIRS once one exists.
    Returns the template, a list (ambiguous), or None (no match)."""
    q = (query or "").strip().lower().replace("-", "_")
    if not q:
        return None
    customs: List[Dict[str, Any]] = []
    if business_id:
        try:
            customs = load_custom_templates(business_id)
        except Exception:
            customs = []
        if q.startswith("custom:"):
            hit = next((t for t in customs if t["id"].lower() == q), None)
            if hit:
                return hit
    pool = customs + doc_templates.TEMPLATES
    exact = doc_templates.TEMPLATE_INDEX.get(q)
    exact_custom = next((t for t in customs if t["title"].lower() == q.replace("_", " ")), None)
    if exact_custom:
        return exact_custom
    if exact:
        return exact
    q_words = q.replace("_", " ")
    hits = [t for t in pool
            if q_words in t["title"].lower() or q in str(t["id"])]
    if not hits:
        # token overlap: "nda" → Mutual Nondisclosure, "demand" → Demand Letter
        hits = [t for t in pool
                if any(w and (w in str(t["id"]) or w in t["title"].lower())
                       for w in q_words.split())]
    if len(hits) == 1:
        return hits[0]
    return hits or None


@router.post("/generate")
async def doctemplates_generate(body: GenerateBody,
                                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    business = _owner(body.business_id, user)
    if body.template_id.startswith("custom:"):
        template = load_custom_template(body.business_id, body.template_id)
    else:
        template = doc_templates.TEMPLATE_INDEX.get(body.template_id)
    if not template:
        raise HTTPException(404, "unknown template")

    contacts = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{body.contact_id}"
        f"&business_id=eq.{body.business_id}&select=id,name,email&limit=1") or []
    if not contacts:
        raise HTTPException(404, "contact not found")
    contact = contacts[0]

    billing_limits.require_units(body.business_id)  # drafting is an AI action

    try:
        return await generate_document_core(
            business, contact, template, body.params or {}, user_id=user.id)
    except GenerationError as e:
        raise HTTPException(e.status, e.message)


# ─── Learn from upload — their own paper becomes a template ──────────
# A practitioner's proven contract, uploaded to business-documents,
# converted ONCE into a reusable template: parties → {client_name},
# amounts/scopes → declared fields, business-standard terms marked
# sticky. Clause wording is preserved — it's their paper, not ours.
# Stored per-business in business_doc_templates; from then on it lists,
# previews, generates, and resolves through Chief exactly like the nine
# built-ins.

_STANDARD_VARS = {"business_name", "practitioner_name", "client_name", "date"}
_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

LEARN_MODEL_DEFAULT = "claude-sonnet-4-5"


def _learn_model() -> str:
    return (os.environ.get("DOCTEMPLATES_LEARN_MODEL") or "").strip() or LEARN_MODEL_DEFAULT


def normalize_custom(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a model-extracted template into the exact shape the
    generation core runs. Placeholder integrity is enforced HERE, at
    learn time: any placeholder the model used without declaring a
    field gets a field auto-declared — a template can never ship with
    a hole that nothing fills."""
    title = str(raw.get("title") or "").strip()[:80] or "Custom Document"
    fields_in = raw.get("fields") if isinstance(raw.get("fields"), list) else []
    sections_in = raw.get("sections") if isinstance(raw.get("sections"), list) else []
    if not sections_in:
        raise GenerationError("I couldn't extract any sections from that document.", 422)

    fields: List[Dict[str, Any]] = []
    seen = set()
    for f in fields_in[:12]:
        if not isinstance(f, dict):
            continue
        key = re.sub(r"[^a-z0-9_]", "_", str(f.get("key") or "").strip().lower())[:40]
        if not key or key in seen or key in _STANDARD_VARS:
            continue
        seen.add(key)
        fields.append({
            "key": key,
            "label": str(f.get("label") or key.replace("_", " ").title())[:80],
            "type": "textarea" if str(f.get("type")) == "textarea" else "text",
            "required": bool(f.get("required")),
            "placeholder": str(f.get("placeholder") or "")[:160],
            "default": "",
            "sticky": bool(f.get("sticky")),
        })

    sections: List[Dict[str, Any]] = []
    for s in sections_in[:24]:
        if not isinstance(s, dict):
            continue
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        heading = (str(s.get("heading")).strip()[:100]
                   if s.get("heading") else None)
        sections.append({"kind": "fixed", "heading": heading,
                         "text": text[:6000]})

    # Auto-declare any undeclared placeholder as an optional text field.
    for s in sections:
        for var in _PLACEHOLDER_RE.findall(s["text"]):
            if var in _STANDARD_VARS or var in seen:
                continue
            seen.add(var)
            fields.append({
                "key": var, "label": var.replace("_", " ").title()[:80],
                "type": "text", "required": False, "placeholder": "",
                "default": "", "sticky": False,
            })

    return {
        "id": "",  # stamped by the caller as custom:{row_id}
        "title": title,
        "subtitle": str(raw.get("subtitle") or "From your own document")[:90],
        "description": str(raw.get("description") or "Learned from an uploaded document.")[:160],
        "category": "custom",
        "suggested_for": [],
        "fields": fields,
        "sections": sections,
    }


_LEARN_INSTRUCTION = (
    "Convert this document into a reusable template for the business that "
    "wrote it. Respond with ONLY JSON:\n"
    '{"title": "short document name", '
    '"subtitle": "the 2-4 key things it covers, like: Fees, Term & Renewal", '
    '"description": "one sentence on when to use it", '
    '"fields": [{"key": "snake_case", "label": "Human label", '
    '"type": "text" or "textarea", "required": true/false, '
    '"sticky": true/false, "placeholder": "example value from the original"}], '
    '"sections": [{"heading": "SECTION HEADING or null", "text": "the clause text"}]}\n\n'
    "Rules:\n"
    "- Replace the counterparty/client's name everywhere with {client_name}, "
    "the business's own name with {business_name}, the signer's personal name "
    "with {practitioner_name}, and the execution/effective date with {date}.\n"
    "- Every OTHER engagement-specific value (amounts, rates, scopes, "
    "addresses, deadlines, durations) becomes a {snake_case} placeholder with "
    "a matching entry in fields. required=true when the document is "
    "meaningless without it. sticky=true ONLY for business-standard terms "
    "(their rate, their state, their notice window) - never for facts about "
    "one client.\n"
    "- Otherwise preserve the clause wording EXACTLY, including numbering. "
    "This is their proven paper - do not improve, summarize, or reorder it.\n"
    "- Skip signature blocks; one is appended automatically at generation.")


class LearnBody(BaseModel):
    business_id: str
    path: str


@router.post("/learn")
async def doctemplates_learn(body: LearnBody,
                             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    import doc_intelligence_router as di
    _owner(body.business_id, user)
    path = di._check_path(body.business_id, body.path)
    billing_limits.require_units(body.business_id)

    if not llm_call.api_key():
        raise HTTPException(503, "Template learning isn't configured (no API key).")

    async with httpx.AsyncClient(timeout=di.HTTP_TIMEOUT) as client:
        blob = await di._download(client, path)
    block = di._content_block(path, blob)

    payload = {
        "model": _learn_model(), "max_tokens": 4000,
        "system": ("You convert real business documents into reusable "
                   "templates, preserving their wording faithfully. "
                   "Respond with ONLY the requested JSON."),
        "messages": [{"role": "user",
                      "content": [block, {"type": "text", "text": _LEARN_INSTRUCTION}]}],
    }
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=di.HTTP_TIMEOUT) as client:
        resp = await llm_call.apost(client, payload, task="doctemplates_learn")
    if resp.status_code >= 400:
        logger.error(f"doctemplates learn {resp.status_code}: {resp.text[:300]}")
        raise HTTPException(502, "I couldn't read that document into a template — try again.")
    data = resp.json()
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    usage = data.get("usage") or {}
    try:
        await log_api_usage(
            endpoint="/doctemplates/learn", model=data.get("model") or _learn_model(),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            business_id=body.business_id, user_id=user.id,
            task_type="doctemplate_learn",
            duration_ms=int((time.monotonic() - started) * 1000))
    except Exception:
        pass

    try:
        raw = di._parse_json(text)
    except HTTPException:
        raise HTTPException(502, "The extraction came back malformed — try again.")
    try:
        template = normalize_custom(raw)
    except GenerationError as e:
        raise HTTPException(e.status, e.message)

    rows = sb_clients.sb_post_as_service("/business_doc_templates", {
        "business_id": body.business_id,
        "template": template,
        "source_path": path,
    })
    if not (isinstance(rows, list) and rows):
        raise HTTPException(502, "The template was extracted but couldn't be saved — try again.")
    row_id = rows[0].get("id")
    template["id"] = f"custom:{row_id}"

    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": body.business_id,
            "event_type": "document_template_learned",
            "data": {"title": template["title"], "source_path": path,
                     "template_row": row_id},
            "source": "doc_templates"})
    except Exception:
        pass

    return {"ok": True, "template_id": template["id"],
            "title": template["title"],
            "fields": template["fields"], "sections": template["sections"]}


# ─── Custom-template plumbing (list / load / delete) ─────────────────

def load_custom_templates(business_id: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/business_doc_templates?business_id=eq.{business_id}"
        "&select=id,template,created_at&order=created_at.desc&limit=50") or []
    out = []
    for r in rows:
        t = r.get("template")
        if not isinstance(t, dict) or not t.get("sections"):
            continue
        t = dict(t)
        t["id"] = f"custom:{r['id']}"
        out.append(t)
    return out


def load_custom_template(business_id: str, template_id: str) -> Optional[Dict[str, Any]]:
    row_id = template_id.split(":", 1)[1] if ":" in template_id else template_id
    rows = sb_clients.sb_get_as_service(
        f"/business_doc_templates?id=eq.{row_id}"
        f"&business_id=eq.{business_id}&select=id,template&limit=1") or []
    if not rows:
        return None
    t = rows[0].get("template")
    if not isinstance(t, dict):
        return None
    t = dict(t)
    t["id"] = f"custom:{rows[0]['id']}"
    return t


@router.delete("/custom/{row_id}")
async def doctemplates_delete_custom(row_id: str, biz: str,
                                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    sb_clients.sb_delete_as_service(
        f"/business_doc_templates?id=eq.{row_id}&business_id=eq.{biz}")
    return {"ok": True}
