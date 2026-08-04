"""
doc_intelligence_router.py — Document Intelligence, pass 1.

The gap this closes: business-documents was dumb storage. A lawyer's
engagement letters, a contractor's subcontracts, a coach's vendor
agreements sat in per-client folders and the system never read one of
them. Competitors' entire product ("summarize any agreement in
seconds") is one endpoint away when the file already lives next to the
client it belongs to — so the analysis here is CONTEXT-AWARE where
theirs is an orphan-PDF trick: the business's vertical voice frames the
read, and a contact-scoped document logs its analysis onto that
contact's timeline.

Surface (all owner-gated, all metered as AI actions):

  POST /docintel/analyze   {business_id, path, mode, question?}
       mode = "summary"  → plain-language summary + parties + key
                           points + dates + obligations + red flags
              "dates"    → every date/deadline with its consequence
              "ask"      → answer a practitioner question, with the
                           exact supporting quotes
  POST /docintel/compare   {business_id, path_a, path_b}
       → verdict + per-topic differences with significance, plus
         clauses present in only one document.

Mechanics that carry weight:

  - Files go to Claude NATIVELY: PDFs as `document` blocks (vision
    handles scanned pages — the OCR gap closes for free), images as
    `image` blocks, plain text inlined. No local pdf-parsing library,
    nothing new in requirements.txt.
  - `path` MUST start with "{business_id}/" — the storage bucket nests
    every business under its own prefix, and the check keeps a crafted
    path from reading another tenant's files (same topology
    account_lifecycle.py relies on for erasure).
  - billing_limits.require_units() gates every call (dormant until
    BILLING_ENFORCE, like compose/director/Chief) and every successful
    call logs to api_usage with the business_id.
  - The model answers ONLY as JSON; _parse_json tolerates code fences.
    Kill switch: no ANTHROPIC_API_KEY → 503, never a hang.
  - This is practitioner-facing analysis, not client-facing advice —
    the system prompt addresses the OWNER about their own document.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import billing_limits
import llm_call
import sb_clients
from api_usage_logger import log_api_usage
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("doc_intelligence")

router = APIRouter(prefix="/docintel", tags=["docintel"])

DOCS_BUCKET = "business-documents"

# 20MB raw → ~27MB base64, safely under the Messages API's 32MB request
# cap. (The bucket's own upload cap is 50MB; the tail between the two
# gets a friendly 413 instead of an opaque Anthropic error.)
MAX_FILE_BYTES = 20 * 1024 * 1024

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2000

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

_MODES = ("summary", "dates", "ask")

# Extension → how the file rides in the message. Anthropic accepts
# jpeg/png/gif/webp image blocks and PDF document blocks; everything
# text-shaped is inlined as text.
_IMAGE_MEDIA = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}
_TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".rtf"}


def _model() -> str:
    return (os.environ.get("DOCINTEL_MODEL") or "").strip() or DEFAULT_MODEL


def _supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,business_type&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _check_path(business_id: str, path: str) -> str:
    """A storage path is only valid inside the caller's own prefix."""
    p = (path or "").strip().lstrip("/")
    if ".." in p or not p.startswith(f"{business_id}/"):
        raise HTTPException(403, "path outside this business's documents")
    return p


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _filename(path: str) -> str:
    """Display name — the stored name minus the upload timestamp prefix
    (mirrors documentStorage.ts on the frontend)."""
    name = path.rsplit("/", 1)[-1]
    return re.sub(r"^\d{10,}-", "", name)


def _contact_id_from_path(business_id: str, path: str) -> Optional[str]:
    m = re.match(rf"^{re.escape(business_id)}/contacts/([^/]+)/", path)
    return m.group(1) if m else None


async def _download(client: httpx.AsyncClient, path: str) -> bytes:
    """Fetch the file through the authenticated storage endpoint (works
    whether the bucket stays public or ever goes private)."""
    url = f"{_supabase_url()}/storage/v1/object/{DOCS_BUCKET}/{path}"
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
           or os.environ.get("SUPABASE_ANON") or "")
    r = await client.get(url, headers={
        "apikey": key, "Authorization": f"Bearer {key}"})
    if r.status_code >= 400 or not r.content:
        raise HTTPException(404, "couldn't fetch that document from storage")
    if len(r.content) > MAX_FILE_BYTES:
        raise HTTPException(413, "That file is over 20MB — too large to analyze.")
    return r.content


def _content_block(path: str, data: bytes) -> Dict[str, Any]:
    """The file as an Anthropic content block, chosen by extension."""
    ext = _ext(path)
    if ext == ".pdf":
        return {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode("ascii")}}
    if ext in _IMAGE_MEDIA:
        return {"type": "image", "source": {
            "type": "base64", "media_type": _IMAGE_MEDIA[ext],
            "data": base64.standard_b64encode(data).decode("ascii")}}
    if ext in _TEXT_EXT:
        text = data.decode("utf-8", errors="replace")[:200_000]
        return {"type": "text",
                "text": f"--- DOCUMENT: {_filename(path)} ---\n{text}"}
    raise HTTPException(
        415, "Only PDF, image, and plain-text documents can be analyzed for now.")


def analyzable(path: str) -> bool:
    ext = _ext(path)
    return ext == ".pdf" or ext in _IMAGE_MEDIA or ext in _TEXT_EXT


# ─── Prompts ─────────────────────────────────────────────────────────

def _voice(business_type: Optional[str]) -> str:
    """Vertical framing — a lawyer's read is precise about obligations,
    a contractor's about scope and payment terms. Reuses Chief's voice
    fragment so the vertical speaks with one voice everywhere."""
    try:
        import chief_llm
        return chief_llm.voice_fragment(business_type) or ""
    except Exception:
        return ""


def _system(biz: Dict[str, Any], contact_name: Optional[str]) -> str:
    parts = [
        f"You are the document analyst for {biz.get('name') or 'this business'}"
        + (f", a {biz.get('business_type')}" if biz.get("business_type") else "")
        + ". You are advising the business OWNER about a document in their "
          "own files — not giving advice to their client.",
    ]
    v = _voice(biz.get("business_type"))
    if v:
        parts.append(v)
    if contact_name:
        parts.append(f"This document is filed under the client record: {contact_name}.")
    parts.append(
        "Read the attached document carefully. Quote dates, names and "
        "amounts exactly as written. If something is ambiguous, unusual, "
        "or risky for the owner, say so plainly. Respond with ONLY the "
        "requested JSON — no prose before or after it.")
    return "\n\n".join(parts)


_MODE_INSTRUCTIONS: Dict[str, str] = {
    "summary": (
        'Return JSON: {"document_type": "what kind of document this is", '
        '"summary": "2-4 plain-language sentences", '
        '"parties": ["who is involved"], '
        '"key_points": ["the points that matter most, each one sentence"], '
        '"dates": [{"date": "as written", "label": "what it is"}], '
        '"obligations": ["who must do what, by when"], '
        '"red_flags": ["anything unusual, one-sided, or risky — empty if none"]}'
    ),
    "dates": (
        'Extract EVERY date, deadline, term length and renewal/notice window. '
        'Return JSON: {"dates": [{"date": "as written", "label": "what it is", '
        '"consequence": "what happens if missed, or null"}], '
        '"notes": "one sentence on the overall timeline, or null"}'
    ),
    "ask": (
        'Answer the owner\'s question using ONLY this document. '
        'Return JSON: {"answer": "direct answer in plain language", '
        '"quotes": ["the exact passages that support it"], '
        '"not_in_document": false — set true (with your best reading in '
        '"answer") if the document does not actually address the question}'
    ),
}

_COMPARE_INSTRUCTION = (
    'Compare DOCUMENT A and DOCUMENT B. Return JSON: '
    '{"verdict": "1-2 sentences on how the documents differ overall", '
    '"differences": [{"topic": "the clause/term", "doc_a": "what A says", '
    '"doc_b": "what B says", "significance": "low|medium|high"}], '
    '"only_in_a": ["provisions present only in A"], '
    '"only_in_b": ["provisions present only in B"]}'
)


def _parse_json(raw: str) -> Dict[str, Any]:
    """The model is told JSON-only, but tolerate a fenced block or stray
    prose around the object rather than 500ing the practitioner."""
    s = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.DOTALL)
    if fence:
        s = fence.group(1)
    else:
        start, end = s.find("{"), s.rfind("}")
        if start >= 0 and end > start:
            s = s[start:end + 1]
    try:
        out = json.loads(s)
        if isinstance(out, dict):
            return out
    except Exception:
        pass
    raise HTTPException(502, "The analysis came back malformed — try again.")


async def _call_claude(system: str, content: List[Dict[str, Any]],
                       *, business_id: str, user_id: str,
                       task_type: str) -> Dict[str, Any]:
    if not llm_call.api_key():
        raise HTTPException(503, "Document analysis isn't configured (no API key).")
    payload = {
        "model": _model(),
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await llm_call.apost(client, payload, task="docintel")
    if resp.status_code >= 400:
        logger.error(f"docintel LLM {resp.status_code}: {resp.text[:300]}")
        raise HTTPException(502, "The document couldn't be analyzed right now.")
    data = resp.json()
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    usage = data.get("usage") or {}
    try:
        await log_api_usage(
            endpoint="/docintel", model=data.get("model") or _model(),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            business_id=business_id, user_id=user_id, task_type=task_type,
            duration_ms=int((time.monotonic() - started) * 1000))
    except Exception:
        pass  # fire-and-forget by contract
    return _parse_json(text)


def _log_event(business_id: str, contact_id: Optional[str],
               event_type: str, data: Dict[str, Any]) -> None:
    """Contact-scoped analyses land on the contact timeline (same events
    table the panel already writes upload/delete rows to). Best-effort."""
    if not contact_id:
        return
    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": business_id, "contact_id": contact_id,
            "event_type": event_type, "data": data,
            "source": "doc_intelligence"})
    except Exception:
        pass


def _contact_name(business_id: str, contact_id: Optional[str]) -> Optional[str]:
    if not contact_id:
        return None
    try:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
            "&select=name&limit=1") or []
        return (rows[0] or {}).get("name") if rows else None
    except Exception:
        return None


# ─── Endpoints ───────────────────────────────────────────────────────

class AnalyzeBody(BaseModel):
    business_id: str
    path: str
    mode: str = "summary"
    question: Optional[str] = None


@router.post("/analyze")
async def docintel_analyze(body: AnalyzeBody,
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _owner(body.business_id, user)
    mode = (body.mode or "summary").strip().lower()
    if mode not in _MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(_MODES)}")
    if mode == "ask" and not (body.question or "").strip():
        raise HTTPException(400, "ask mode needs a question")
    path = _check_path(body.business_id, body.path)
    billing_limits.require_units(body.business_id)  # AI action, metered

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        blob = await _download(client, path)
    block = _content_block(path, blob)

    contact_id = _contact_id_from_path(body.business_id, path)
    contact_name = _contact_name(body.business_id, contact_id)

    content: List[Dict[str, Any]] = [block]
    instruction = _MODE_INSTRUCTIONS[mode]
    if mode == "ask":
        instruction = (f'The owner\'s question: "{(body.question or "").strip()[:500]}"\n\n'
                       + instruction)
    content.append({"type": "text", "text": instruction})

    result = await _call_claude(
        _system(biz, contact_name), content,
        business_id=body.business_id, user_id=user.id, task_type=f"docintel_{mode}")

    _log_event(body.business_id, contact_id, "document_analyzed", {
        "filename": _filename(path), "path": path, "mode": mode,
        "summary": (result.get("summary") or result.get("answer") or "")[:400],
    })
    return {"ok": True, "mode": mode, "filename": _filename(path), "result": result}


class CompareBody(BaseModel):
    business_id: str
    path_a: str
    path_b: str


@router.post("/compare")
async def docintel_compare(body: CompareBody,
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _owner(body.business_id, user)
    path_a = _check_path(body.business_id, body.path_a)
    path_b = _check_path(body.business_id, body.path_b)
    if path_a == path_b:
        raise HTTPException(400, "pick two different documents to compare")
    billing_limits.require_units(body.business_id)

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        blob_a = await _download(client, path_a)
        blob_b = await _download(client, path_b)

    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"DOCUMENT A — {_filename(path_a)}:"},
        _content_block(path_a, blob_a),
        {"type": "text", "text": f"DOCUMENT B — {_filename(path_b)}:"},
        _content_block(path_b, blob_b),
        {"type": "text", "text": _COMPARE_INSTRUCTION},
    ]

    result = await _call_claude(
        _system(biz, None), content,
        business_id=body.business_id, user_id=user.id, task_type="docintel_compare")

    return {"ok": True, "mode": "compare",
            "filename_a": _filename(path_a), "filename_b": _filename(path_b),
            "result": result}
