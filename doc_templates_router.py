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
    for t in doc_templates.TEMPLATES:
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
            "text": s["text"] if s["kind"] == "fixed" else s["fallback"],
            "requires": s.get("requires"),
        } for s in t["sections"]]
        chars = sum(len(s["text"]) for s in sections)
        pages = max(1, round(chars / 2600))
        out.append({
            "id": t["id"], "title": t["title"],
            "subtitle": t.get("subtitle") or "",
            "description": t["description"], "category": t["category"],
            "fields": fields,
            "sections": sections,
            "page_estimate": f"≈{pages} page{'s' if pages != 1 else ''}",
            "suggested": btype in t["suggested_for"],
        })
    # Suggested templates first, library order otherwise (it's curated).
    out.sort(key=lambda t: 0 if t["suggested"] else 1)
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


def resolve_template(query: str) -> Any:
    """Loose template lookup for conversational callers: exact id, then
    title/keyword containment. Returns the template, a list (ambiguous),
    or None (no match)."""
    q = (query or "").strip().lower().replace("-", "_")
    if not q:
        return None
    exact = doc_templates.TEMPLATE_INDEX.get(q)
    if exact:
        return exact
    q_words = q.replace("_", " ")
    hits = [t for t in doc_templates.TEMPLATES
            if q_words in t["title"].lower() or q in t["id"]]
    if not hits:
        # token overlap: "nda" → Mutual Nondisclosure, "demand" → Demand Letter
        hits = [t for t in doc_templates.TEMPLATES
                if any(w and (w in t["id"] or w in t["title"].lower())
                       for w in q_words.split())]
    if len(hits) == 1:
        return hits[0]
    return hits or None


@router.post("/generate")
async def doctemplates_generate(body: GenerateBody,
                                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    business = _owner(body.business_id, user)
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
