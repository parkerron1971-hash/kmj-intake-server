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

# Document drafting rides the `draft` lane, like every other set of
# words that reaches a client.
#
# It used to be a hardcoded Haiku constant, on the reasoning that these
# are "short personalization paragraphs" and "a small model is plenty".
# chief_models had already settled the question the other way for every
# other drafter — the `draft` lane exists because of Kevin's 2026-07-03
# ruling that "drafts ride the conversational tier, so quality of the
# words that reach clients never drops" — and a signed agreement is the
# most client-facing paper the system produces. It was exempt from that
# ruling by accident, not by decision.
#
# Still env-overridable two ways: DOCTEMPLATES_MODEL pins this call
# alone, CHIEF_MODEL_DRAFT moves every drafter together.
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

# One drafted section is a paragraph; the whole set used to share a
# single 1000-token ceiling, so a template with several of them was
# rationing tokens across sections that had nothing to do with each
# other — and the last one in the JSON object was the one that got
# truncated. Budget per section, with a floor and a ceiling.
TOKENS_PER_DRAFTED_SECTION = 700
MIN_DRAFT_TOKENS = 1200
MAX_DRAFT_TOKENS = 4000


def _model() -> str:
    pinned = (os.environ.get("DOCTEMPLATES_MODEL") or "").strip()
    if pinned:
        return pinned
    try:
        import chief_models
        return chief_models.model_for("draft")
    except Exception:
        # chief_models is the source of truth; this is only so a broken
        # import cannot take document generation down with it.
        return "claude-sonnet-5"


def _draft_budget(section_count: int) -> int:
    return max(MIN_DRAFT_TOKENS,
               min(MAX_DRAFT_TOKENS,
                   TOKENS_PER_DRAFTED_SECTION * max(1, section_count)))


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
    # CANONICALIZED. suggested_for lists canonical verticals, and
    # businesses.type legitimately holds aliases — a business stamped
    # "church" resolves to ministry, and without this it matched nothing
    # and was shown a library with no suggestions at all, including the
    # six governance templates written for it.
    import vertical_registry
    btype = vertical_registry.resolve((b.get("type") or "").lower())
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
            "requires_value": s.get("requires_value"),
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
            # Whether this paper belongs in THIS vertical's list at all.
            # The library returned all sixteen to everyone, so a nonprofit
            # was shown a demand letter and a barber an engagement letter.
            # Hidden, never gated: the frontend shows the relevant set and
            # keeps the rest behind "Show all", so an over-hide costs one
            # click while an under-hide can cost a professional-ethics
            # violation. A business's own learned templates are always
            # relevant — they made them.
            "relevant": is_custom or not doc_templates.is_irrelevant(t["id"], btype),
            "irrelevance_reason": (
                None if is_custom
                else doc_templates.irrelevance_reason(t["id"], btype)),
            "custom": is_custom,
            # the live preview numbers headed sections exactly like
            # assemble() does, so what you watch is what you sign
            "numbered": bool(t.get("numbered")),
        })
    # A business's own templates first, then suggested, then the rest
    # in curated library order.
    # Own paper, then this vertical's suggested paper, then the rest of
    # what belongs here, then everything else.
    out.sort(key=lambda t: (
        0 if t.get("custom") else 1 if t["suggested"] else 2 if t["relevant"] else 3))
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
            and doc_templates.section_renders(s, variables)]
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
        "model": _model(), "max_tokens": _draft_budget(len(todo)), "system": system,
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

async def _state_notes(business: Dict[str, Any], template: Dict[str, Any],
                       variables: Dict[str, str], *, user_id: str) -> Optional[str]:
    """State awareness, the legal-judgment half. Mechanical differences
    (parish vs county) adjust the paper deterministically in
    doc_templates; differences that ARE state law — late-fee caps,
    required notices, cancellation rights — come back as short advisory
    notes for the PRACTITIONER. Deliberately not auto-applied and never
    printed on the document: a model-invented 'state rule' silently
    entering a contract is the failure mode this design refuses.
    Fail-soft: any error → None, generation proceeds."""
    state = (variables.get("state_full") or "").strip()
    if not state or not llm_call.api_key():
        return None
    headings = [s.get("heading") for s in template["sections"] if s.get("heading")]
    payload = {
        "model": _learn_model(), "max_tokens": 500,
        "system": ("You are a cautious contracts-practice assistant writing "
                   "advisory notes for a business OWNER about their own "
                   "document. Not legal advice; never addressed to their "
                   "client. Only well-established, widely-known rules — "
                   "when unsure, stay silent rather than guess."),
        "messages": [{"role": "user", "content":
                      f"Business: {business.get('name')}, a "
                      f"{business.get('type') or 'small business'}. Document: "
                      f"{template['title']}, governed by {state} law. Its "
                      f"clauses cover: {', '.join(headings[:16])}.\n\n"
                      f"In 2-4 short plain-language bullets, note where "
                      f"{state} law commonly differs or needs attention for "
                      f"a document like this (late-fee caps, required "
                      f"notices, cancellation rights, enforceability limits, "
                      f"licensing). If nothing is notable, say the document "
                      f"is broadly standard for {state}. End with: 'Confirm "
                      f"anything load-bearing with a {state} attorney.'"}],
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await llm_call.apost(client, payload, task="doctemplates_state")
        if resp.status_code >= 400:
            return None
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()
        usage = data.get("usage") or {}
        try:
            await log_api_usage(
                endpoint="/doctemplates/state_notes",
                model=data.get("model") or _learn_model(),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                business_id=business["id"], user_id=user_id,
                task_type="doctemplate_state_notes",
                duration_ms=int((time.monotonic() - started) * 1000))
        except Exception:
            pass
        return text or None
    except Exception as e:
        logger.warning(f"state notes failed soft: {e}")
        return None


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
        client_name=contact.get("name") or "Client", date_str=_today(),
        # The document speaks the business's trade — expense examples,
        # outcome factors, and file-vs-work-product language all derive
        # from the vertical (doc_templates.VERTICAL_LANGUAGE).
        business_type=business.get("type"))

    drafted = await _draft_sections(business, template, variables,
                                    user_id=user_id)

    # The attorney-review note is an INTERNAL acknowledgment — it shows
    # in the app (dialog, queue, Chief's reply) and never prints on the
    # client's document. Lawyers see none (they are the counsel).
    is_lawyer = (business.get("type") or "").lower() == "lawyer"
    # Rendered ONCE, and both the body and the audit are built from it.
    # The auditor used to be handed template["sections"] — the raw
    # source — so it was reading clauses that still said {fee} when it
    # looked for conflicting amounts, and drafted sections, which have
    # no "text" key at all, arrived as empty strings. The money rule
    # could not fire on a real document and the model's own paragraphs,
    # the least constrained prose in the system, were never scanned.
    rendered = doc_templates.render_sections(template, variables, drafted)
    doc_body = doc_templates.assemble(
        template, variables, drafted, include_review_note=False)

    # Read the finished text before the client does.
    #
    # Deterministic only: no model call, no network, no metering, and no
    # veto HERE — audit_document never raises, and a document with
    # findings still generates, because a practitioner has to see the
    # draft to fix it. The teeth are on the way out (doc_guard).
    import doc_audit
    import doc_guard
    audit = doc_audit.audit_document(
        doc_body, sections=rendered,
        numbered=bool(template.get("numbered")),
        contract=template.get("contract"), variables=variables)

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
        # The verdict rides with the document. /doctemplates/history reads
        # it back without recomputing, and doc_guard re-audits against the
        # contract and field values stashed here when the body reaches a
        # door — which is how an edit made in the approval queue gets
        # caught. Existing jsonb column; no migration.
        "data": {doc_guard.DATA_KEY: doc_guard.stash(
            template, variables, audit, rendered)},
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

    # State counsel notes — advisory, practitioner-facing, off-paper.
    state_notes = await _state_notes(business, template, variables,
                                     user_id=user_id)

    return {"ok": True, "queue_id": queue_id, "subject": subject,
            "title": template["title"], "body": doc_body,
            "drafted_sections_used": bool(drafted),
            "used_defaults": used_defaults,
            "saved_defaults": saved_defaults,
            "state_notes": state_notes,
            "audit": audit,
            "review_note": None if is_lawyer else doc_templates._REVIEW_NOTE}


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


# ─── History — the documents this business has actually issued ───────
#
# There was no way to see them. A generated document lands in
# agent_queue as a draft and the dialog then navigates to the Approval
# Queue with no link back; /doctemplates/list returns TEMPLATES, not
# documents; and the two folders in the Documents room are Storage
# objects — things somebody UPLOADED. A document the system wrote had
# nowhere it could be looked at again.
#
# approvals_router says "There is no GET on purpose: seats already read
# the queue via RLS", and that is right for the approval queue, which is
# a worklist. This is not a worklist. It is the practitioner's record of
# their own paper, it needs the e-signature state joined onto it, and it
# needs the stored verdict — so it reads through the owner gate like
# every other /doctemplates route.
#
# Reads rows that already exist, so it works retroactively on every
# document ever generated. No migration.

HISTORY_PAGE = 50
_PREVIEW_CHARS = 240


def _esign_by_source(business_id: str, queue_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Signature state keyed by the queue row it came from. Best-effort:
    the history list is worth showing without it."""
    if not queue_ids:
        return {}
    try:
        ids = ",".join(f'"{q}"' for q in queue_ids if q)
        rows = sb_clients.sb_get_as_service(
            f"/esign_documents?business_id=eq.{business_id}"
            f"&source_ref=in.({ids})"
            "&select=source_ref,status,sent_at,completed_at,signer_name,signer_email"
            "&order=sent_at.desc") or []
    except Exception as e:
        logger.warning(f"esign join failed (non-fatal): {e}")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out.setdefault(str(r.get("source_ref")), r)   # newest wins
    return out


def _history_row(row: Dict[str, Any], contact_names: Dict[str, str],
                 esign: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    import doc_guard
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    stash = (data or {}).get(doc_guard.DATA_KEY) or {}
    body = row.get("body") or ""
    sig = esign.get(str(row.get("id"))) or None
    return {
        "id": row.get("id"),
        "title": row.get("subject") or "Document",
        "template_id": stash.get("template_id"),
        "contact_id": row.get("contact_id"),
        "contact_name": contact_names.get(str(row.get("contact_id") or "")) or None,
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "reviewed_at": row.get("reviewed_at"),
        "sent_at": row.get("sent_at"),
        "preview": " ".join(body[:_PREVIEW_CHARS].split()),
        "verification": doc_guard.summarize(stash.get("audit")),
        "esign": ({"status": sig.get("status"), "sent_at": sig.get("sent_at"),
                   "completed_at": sig.get("completed_at"),
                   "signer_name": sig.get("signer_name")} if sig else None),
    }


@router.get("/history")
async def doctemplates_history(biz: str, limit: int = HISTORY_PAGE,
                               offset: int = 0,
                               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Every document this business has issued, newest first."""
    _owner(biz, user)
    limit = max(1, min(int(limit or HISTORY_PAGE), 200))
    offset = max(0, int(offset or 0))
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?business_id=eq.{biz}&action_type=eq.document"
        "&select=id,contact_id,subject,body,status,data,created_at,reviewed_at,sent_at"
        f"&order=created_at.desc&limit={limit + 1}&offset={offset}") or []
    has_more = len(rows) > limit
    rows = rows[:limit]

    contact_ids = sorted({str(r.get("contact_id")) for r in rows if r.get("contact_id")})
    names: Dict[str, str] = {}
    if contact_ids:
        try:
            ids = ",".join(f'"{c}"' for c in contact_ids)
            for c in (sb_clients.sb_get_as_service(
                    f"/contacts?business_id=eq.{biz}&id=in.({ids})"
                    "&select=id,name") or []):
                names[str(c.get("id"))] = c.get("name") or ""
        except Exception as e:
            logger.warning(f"contact names failed (non-fatal): {e}")

    esign = _esign_by_source(biz, [str(r.get("id")) for r in rows])
    documents = [_history_row(r, names, esign) for r in rows]

    # Counters for the standing rail. Scoped to this page deliberately:
    # a count that disagrees with the list under it is worse than no
    # count, and the rail sits directly above the list it describes.
    needs = sum(1 for d in documents
                if (d["verification"] or {}).get("verdict") == "blocked")
    out_for_sig = sum(1 for d in documents
                      if (d.get("esign") or {}).get("status") == "sent")
    return {"ok": True, "documents": documents, "has_more": has_more,
            "offset": offset,
            "counts": {"listed": len(documents), "needs_attention": needs,
                       "out_for_signature": out_for_sig}}


@router.get("/history/{queue_id}")
async def doctemplates_history_one(queue_id: str, biz: str,
                                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """One document, with its full body and every stored finding."""
    _owner(biz, user)
    import doc_guard
    row = doc_guard.load_document(queue_id, biz)
    if (row.get("action_type") or "") != "document":
        raise HTTPException(404, "document not found")
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    stash = (data or {}).get(doc_guard.DATA_KEY) or {}
    esign = _esign_by_source(biz, [str(row.get("id"))])
    doc = _history_row(row, {}, esign)
    doc["body"] = row.get("body") or ""
    doc["audit"] = stash.get("audit") or None
    doc["contract"] = stash.get("contract") or []
    if row.get("contact_id"):
        try:
            c = sb_clients.sb_get_as_service(
                f"/contacts?id=eq.{row['contact_id']}&business_id=eq.{biz}"
                "&select=id,name,email&limit=1") or []
            if c:
                doc["contact_name"] = c[0].get("name")
                doc["contact_email"] = c[0].get("email")
        except Exception:
            pass
    return {"ok": True, "document": doc}


@router.post("/history/{queue_id}/verify")
async def doctemplates_history_verify(queue_id: str, biz: str,
                                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Re-read the document as it stands NOW.

    The verdict stamped at generation describes the body as generated,
    and a practitioner can edit that body in the approval queue. This
    re-runs every rule against the current text and re-stamps the row,
    which is how an edit that deletes the signature block or renumbers
    past the end gets caught here rather than at the client's desk.

    Deterministic and free — no model call, so no units."""
    _owner(biz, user)
    import doc_guard
    row = doc_guard.load_document(queue_id, biz)
    if (row.get("action_type") or "") != "document":
        raise HTTPException(404, "document not found")
    audit = doc_guard.audit_stored_body(row)
    doc_guard.restash(row, audit)
    return {"ok": True, "audit": audit,
            "verification": doc_guard.summarize(audit)}


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


# ─── Compose — a contract that doesn't exist yet ─────────────────────
# The practitioner describes the agreement they need ("equipment rental
# with a damage deposit and pickup windows") and the model writes ONLY
# the deal-specific clauses, in our exact template structure. The
# armor is ours, deterministically: normalize_custom() sanitizes the
# shape and auto-declares placeholders, then the shared spine (dispute
# resolution, general terms, signature block) is spliced in server-side
# — a composed contract can never ship without severability or with a
# model-invented signature block. Saved to business_doc_templates, so
# it lists, previews, generates, and resolves through Chief like any
# learned template, reusable from then on.

_COMPOSE_INSTRUCTION = (
    "Draft the DEAL-SPECIFIC clauses of this agreement as a reusable "
    "template. Respond with ONLY JSON:\n"
    '{"title": "short document name", '
    '"subtitle": "the 2-4 key things it covers, like: Rental, Deposit & Return", '
    '"description": "one sentence on when to use it", '
    '"fields": [{"key": "snake_case", "label": "Human label", '
    '"type": "text" or "textarea", "required": true/false, '
    '"sticky": true/false, "placeholder": "a realistic example value"}], '
    '"sections": [{"heading": "SECTION HEADING", "text": "the clause text"}]}\n\n'
    "Rules:\n"
    "- Write plain, professional, complete clauses — no headings inside "
    "text, no markdown. Use {client_name}, {business_name}, "
    "{practitioner_name}, and {date} where the parties or date belong.\n"
    "- Every OTHER variable value (amounts, dates, quantities, windows, "
    "addresses) becomes a {snake_case} placeholder with a matching entry "
    "in fields. required=true when the agreement is meaningless without "
    "it. sticky=true ONLY for business-standard terms (their rate, their "
    "deposit policy, their notice window) — never facts about one client.\n"
    "- Cover the deal completely: what is provided, money and when it is "
    "due, each party's responsibilities, what happens when things go "
    "wrong (damage, cancellation, no-shows), and how it ends.\n"
    "- Do NOT write general boilerplate (entire agreement, severability, "
    "assignment, notices, force majeure, signatures, dispute resolution, "
    "governing law) — the system appends those itself.\n"
    "- Do not include legal-advice framing or disclaimers; write the "
    "practitioner's own document in a neutral professional voice.")


def _compose_spine() -> List[Dict[str, Any]]:
    """The non-negotiable tail of every composed contract."""
    import doc_templates as dt
    return [
        dt.fixed("GOVERNING LAW",
                 "This agreement is governed by the laws of "
                 "{state_full}.{venue_clause}",
                 requires="state"),
        dict(dt._DISPUTE),
        dict(dt._GENERAL_TERMS),
        dt.sig(dt._SIGNATURE_BLOCK),
    ]


async def compose_document_template(business: Dict[str, Any],
                                    description: str, *,
                                    user_id: str) -> Dict[str, Any]:
    """One composition path for the endpoint and Chief's verb. Returns
    the saved template (id stamped custom:{row_id}). Raises
    GenerationError with a practitioner-readable message."""
    import doc_intelligence_router as di
    import doc_templates as dt

    desc = (description or "").strip()
    if len(desc) < 12:
        raise GenerationError(
            "Describe the agreement you need in a sentence or two — what's "
            "being provided, and the terms that matter.", 400)
    if not llm_call.api_key():
        raise GenerationError("Contract composing isn't configured (no API key).", 503)

    btype = (business.get("type") or "").strip()
    lang = dt.vertical_language(btype)
    # Brief the drafting with the governing state when the business has
    # one on file — the model leans toward patterns valid there, and
    # the deterministic spine + state_notes still backstop it.
    gov_state = dt.us_state_full(get_doc_defaults(business).get("state", ""))
    payload = {
        "model": _learn_model(), "max_tokens": 4000,
        "system": ("You draft clean, professional business agreements as "
                   "reusable templates, in the exact JSON structure "
                   "requested. "
                   + (f"The business is a {btype}; " if btype else "")
                   + f"typical pass-through expenses for it are "
                     f"{lang['expense_examples']}."
                   + (f" Its agreements are typically governed by "
                      f"{gov_state} law; draft with that in mind."
                      if gov_state else "")),
        "messages": [{"role": "user", "content":
                      f"The business ({business.get('name') or 'this business'}) "
                      f"needs this agreement:\n\n{desc}\n\n{_COMPOSE_INSTRUCTION}"}],
    }
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=di.HTTP_TIMEOUT) as client:
        resp = await llm_call.apost(client, payload, task="doctemplates_compose")
    if resp.status_code >= 400:
        logger.error(f"compose {resp.status_code}: {resp.text[:300]}")
        raise GenerationError("I couldn't draft that agreement right now — try again.", 502)
    data = resp.json()
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    usage = data.get("usage") or {}
    try:
        await log_api_usage(
            endpoint="/doctemplates/compose",
            model=data.get("model") or _learn_model(),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            business_id=business["id"], user_id=user_id,
            task_type="doctemplate_compose",
            duration_ms=int((time.monotonic() - started) * 1000))
    except Exception:
        pass

    try:
        raw = di._parse_json(text)
    except HTTPException:
        raise GenerationError("The draft came back malformed — try again.", 502)
    template = normalize_custom(raw)

    # The armor is ours: state/venue fields + the shared spine, spliced
    # deterministically. Composed agreements auto-number like the
    # library's.
    keys = {f["key"] for f in template["fields"]}
    if "state" not in keys:
        template["fields"].append({
            "key": "state", "label": "Governing state (optional)",
            "type": "text", "required": False, "placeholder": "e.g. Michigan",
            "default": "", "sticky": True})
    if "venue_county" not in keys:
        template["fields"].append({
            "key": "venue_county", "label": "Venue county (optional)",
            "type": "text", "required": False, "placeholder": "e.g. Oakland",
            "default": "", "sticky": True})
    template["sections"].extend(_compose_spine())
    template["numbered"] = True

    rows = sb_clients.sb_post_as_service("/business_doc_templates", {
        "business_id": business["id"],
        "template": template,
        "source_path": None,
    })
    if not (isinstance(rows, list) and rows):
        raise GenerationError("The agreement was drafted but couldn't be saved — try again.", 502)
    template["id"] = f"custom:{rows[0].get('id')}"

    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": business["id"],
            "event_type": "document_template_composed",
            "data": {"title": template["title"],
                     "template_row": rows[0].get("id"),
                     "description": desc[:300]},
            "source": "doc_templates"})
    except Exception:
        pass
    return template


class ComposeBody(BaseModel):
    business_id: str
    description: str


@router.post("/compose")
async def doctemplates_compose(body: ComposeBody,
                               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    business = _owner(body.business_id, user)
    billing_limits.require_units(body.business_id)  # drafting is an AI action
    try:
        template = await compose_document_template(
            business, body.description, user_id=user.id)
    except GenerationError as e:
        raise HTTPException(e.status, e.message)
    return {"ok": True, "template_id": template["id"],
            "title": template["title"], "subtitle": template["subtitle"],
            "fields": template["fields"], "sections": [{
                "heading": s.get("heading"),
                "text": s.get("text") or s.get("fallback", ""),
                "requires": s.get("requires"),
                "requires_value": s.get("requires_value"),
            } for s in template["sections"]],
            "numbered": True}


# ─── Adjusting a template you own ────────────────────────────────────
#
# business_doc_templates had no update path at all — insert, select,
# delete. So "add an IP clause to that agreement" had exactly one honest
# answer: recompose the whole thing, which INSERTS a second near-identical
# row that then competes with the first in the picker and in
# resolve_template.
#
# Sections are already an addressable list of {heading, text}, so adding
# and removing one is list surgery on JSON. NO MODEL CALL, and none is
# wanted: a deterministic edit to a document the practitioner owns should
# not cost a credit or acquire a failure mode.
#
# The 16 built-ins are NOT adjustable this way. TEMPLATE_INDEX is a
# module-level dict shared by every business; a per-business edit to it
# would change one practitioner's paper for all of them. Customising a
# library template means forking it into business_doc_templates first,
# which is what /custom/fork below is for.

_ADJUST_OPS = ("add", "remove", "replace")


class AdjustBody(BaseModel):
    business_id: str
    operation: str
    heading: str
    text: Optional[str] = None
    # Where to put a new section. A heading that no longer exists puts it
    # at the end rather than failing — the practitioner asked for a
    # clause, and refusing over placement would be pedantry.
    after: Optional[str] = None


@router.patch("/custom/{row_id}")
async def doctemplates_adjust_custom(row_id: str, body: AdjustBody,
                                     user: AuthedUser = Depends(require_user)
                                     ) -> Dict[str, Any]:
    b = _owner(body.business_id, user)
    op = (body.operation or "").strip().lower()
    if op not in _ADJUST_OPS:
        raise HTTPException(400, f"operation must be one of {', '.join(_ADJUST_OPS)}")
    heading = (body.heading or "").strip()
    if not heading:
        raise HTTPException(400, "heading required")
    if op in ("add", "replace") and not (body.text or "").strip():
        raise HTTPException(400, f"{op} needs the clause text")

    rows = sb_clients.sb_get_as_service(
        f"/business_doc_templates?id=eq.{row_id}"
        f"&business_id=eq.{body.business_id}&select=id,template&limit=1") or []
    if not rows:
        raise HTTPException(404, "template not found")
    template = dict(rows[0].get("template") or {})
    sections = list(template.get("sections") or [])
    if not sections:
        raise HTTPException(409, "that template has no sections to adjust")

    def _find(h: str) -> int:
        want = h.strip().lower()
        for i, s in enumerate(sections):
            if (s.get("heading") or "").strip().lower() == want:
                return i
        return -1

    at = _find(heading)
    if op == "remove":
        if at < 0:
            raise HTTPException(404, f"no clause headed “{heading}”")
        # The signature block is what makes the paper signable. Removing
        # it turns an agreement into a memo, silently.
        if "ACCEPTED AND AGREED" in (sections[at].get("text") or "").upper():
            raise HTTPException(
                409, "that is the signature block — removing it would leave "
                     "nothing to sign")
        removed = sections.pop(at)
        changed = removed.get("heading")
    elif op == "replace":
        if at < 0:
            raise HTTPException(404, f"no clause headed “{heading}”")
        sections[at] = {**sections[at], "kind": "fixed", "text": body.text.strip()}
        changed = heading
    else:  # add
        if at >= 0:
            raise HTTPException(
                409, f"there is already a clause headed “{heading}” — replace it "
                     "instead of adding a second")
        new = {"kind": "fixed", "heading": heading, "text": body.text.strip()}
        anchor = _find(body.after) if body.after else -1
        # Default to just before the signature block, which is where a
        # clause belongs — appending after it would put terms below the
        # signatures.
        if anchor >= 0:
            sections.insert(anchor + 1, new)
        else:
            sig = next((i for i, s in enumerate(sections)
                        if "ACCEPTED AND AGREED" in (s.get("text") or "").upper()), -1)
            sections.insert(sig if sig >= 0 else len(sections), new)
        changed = heading

    template["sections"] = sections
    # Back through the SAME sanitizer a learned or composed template goes
    # through, so an added clause cannot introduce an undeclared
    # placeholder or blow the section cap.
    template = normalize_custom(template)

    sb_clients.sb_patch_as_service(
        f"/business_doc_templates?id=eq.{row_id}&business_id=eq.{body.business_id}",
        {"template": template})

    return {"ok": True, "operation": op, "heading": changed,
            "sections": len(template.get("sections") or []),
            "title": template.get("title")}


@router.post("/custom/fork")
async def doctemplates_fork_library(biz: str, template_id: str,
                                    user: AuthedUser = Depends(require_user)
                                    ) -> Dict[str, Any]:
    """Copy a library template into this business's own so it can be edited.

    TEMPLATE_INDEX is a module-level dict shared by every business, so a
    per-business edit to a built-in would change one practitioner's paper
    for all of them. Forking is the honest way to say yes to "change this
    one" without that.
    """
    _owner(biz, user)
    src = doc_templates.TEMPLATE_INDEX.get(template_id)
    if not src:
        raise HTTPException(404, f"no template {template_id!r}")
    copy = {
        "title": src["title"], "subtitle": src.get("subtitle") or "",
        "description": src.get("description") or "",
        "category": "custom",
        "suggested_for": [],
        "fields": [dict(f) for f in src.get("fields") or []],
        # Drafted sections are flattened to their fallback, matching what
        # learn and compose already do: a business's own template is
        # deterministic paper, not a model call waiting to happen.
        "sections": [
            {"kind": "fixed", "heading": s.get("heading"),
             "text": s["text"] if s["kind"] == "fixed" else s.get("fallback", ""),
             **({"requires": s["requires"]} if s.get("requires") else {})}
            for s in src["sections"]],
        "numbered": bool(src.get("numbered")),
    }
    copy = normalize_custom(copy)
    created = sb_clients.sb_post_as_service("/business_doc_templates", {
        "business_id": biz, "template": copy, "source_path": None})
    row = created[0] if isinstance(created, list) and created else None
    if not row:
        raise HTTPException(502, "couldn't save your copy — try again")
    return {"ok": True, "id": f"custom:{row['id']}", "title": copy["title"]}
