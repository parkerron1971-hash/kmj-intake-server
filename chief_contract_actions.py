"""
chief_contract_actions.py — P0.3, the contract verbs.

THE GAP THIS CLOSES: contract_agent.py drafts engagement letters and
proposals in the practitioner's own voice, and renders them as branded PDFs
into Supabase Storage. It was reachable only through its own router
(/agents/contract/generate | preview | pdf), and `generate` is a BULK sweep —
it walks every contact over MIN_LEAD_SCORE and drafts for all of them. There
was no way to say "draft the engagement letter for Marcus." The lawyer and
consultant archetypes both talk about engagement letters and scopes of work
that Chief could describe and could not produce.

These verbs add no drafting logic of their own. Both are thin wrappers over
functions that already exist in contract_agent — the proposal voice, the PDF
styling, and the storage upload all keep exactly one home, and it is not
here. Same principle as P0.2.

═══════════════════════════════════════════════════════════════════════
WHY THERE IS NO `send_for_signature`
═══════════════════════════════════════════════════════════════════════
The build list named `draft_contract` / `send_for_signature`. The first is
here. The second is NOT, deliberately: there is no e-signature provider in
this service. No DocuSign, Dropbox Sign, PandaDoc or equivalent — no client,
no account, no callback route, nothing that could receive a signing event. A
verb called `send_for_signature` would promise the practitioner a legally
signed document and deliver an email, which is the precise failure the
dead-weight rule exists to prevent, and worse here because the practitioner
would believe a contract was executed when it was not.

What ships instead is the honest half of that arc, and it is a complete
loop today:

    draft_contract  → an agent_queue draft the practitioner reads
    contract_pdf    → the branded PDF, public URL, ready to attach
    approve_draft   → the EXISTING verb that sends it (chief_of_staff)

`draft_contract` returns `queue_id`, and `approve_draft` accepts it (or
"latest"), so "draft the engagement letter for Marcus and send it" already
chains in one turn through verbs that all do what their names say.

Real e-signature is a provider integration — an account, a webhook, a
signed-document store, and a status model on the contract itself. That is
its own arc, not a verb. When it lands, `send_for_signature` belongs next to
these.

TRUST-LAYER DISCIPLINE (feedback_chief_trust_layer_discipline):
  • What changes? draft_contract writes ONE agent_queue row with
    status='draft' — the same row shape /agents/contract/generate already
    writes — plus a contract_draft_created event. Nothing is sent. Nothing
    reaches the contact. contract_pdf writes no database row at all; it
    renders bytes and uploads an object.
  • Can the practitioner see it first? Yes, and that is the whole design.
    A draft sits in the queue until a human approves it, and the result
    names the contact and the subject line so the reply can't be vague
    about who it is for.
  • Is it reversible? A draft can be edited or deleted before it is sent,
    and it is inert until then. A PDF is an additive object — regenerating
    writes a new one.
  • Is there an audit trail? agent_queue carries agent='contract',
    ai_model and ai_reasoning; /events gets contract_draft_created.
  • Deflection / substitution: the model can return nothing, in which case
    contract_agent substitutes a short generic body. That substitution is
    invisible in the row, so `used_fallback_language` rides on the action
    result and the label says so — the second-pass reply must not call a
    stub "your engagement letter" as though the voice work happened.
  • Ambiguity is refused, not guessed. A contract names a counterparty, so
    an unmatched or multi-match name returns a question rather than
    drafting for whoever sorted first. This is stricter than
    chief_booking_actions, where a nameless walk-in is legitimate.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("chief_contract_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    logger.info(f"Action {action_type} failed: {msg}")
    return {"type": action_type, "result": msg, "label": action_type, "nav": None}


def _nav_queue() -> Dict[str, Any]:
    return {"tab": "operate", "sub": "queue"}


# ─── shared resolution ────────────────────────────────────────────────

def _resolve_contact(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """contact_id wins; else fuzzy name. Returns {"contact": row} or
    {"error": msg}.

    Unlike a booking, a contract REQUIRES a counterparty — so unlike
    chief_booking_actions._resolve_contact, a miss here is fatal and a
    multi-match asks rather than picking. Drafting an engagement letter for
    the wrong Marcus is not a recoverable mistake."""
    contact_id = (action.get("contact_id") or "").strip()
    if contact_id:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}"
            f"&select=*&limit=1") or []
        if not rows:
            return {"error": "I couldn't find that contact."}
        return {"contact": rows[0]}

    name = (action.get("contact_name") or action.get("client_name")
            or action.get("name") or "").strip()
    if not name:
        return {"error": "Who is the contract for?"}

    safe = name.replace("*", "").replace(",", " ")
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&name=ilike.*{safe}*"
        f"&select=*&limit=3") or []
    if len(rows) == 1:
        return {"contact": rows[0]}
    if len(rows) > 1:
        return {"error": f"Multiple contacts match '{name}': "
                         + ", ".join(r.get("name") or "" for r in rows)
                         + ". Which one?"}
    return {"error": f"I couldn't find a contact named '{name}'."}


def _find_contract_draft(business_id: str, action: Dict[str, Any],
                         contact: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Locate the contract draft to render. queue_id wins ("latest" resolves
    to the most recent contract draft); otherwise the newest one for the
    resolved contact. Returns {"row": row} or {"error": msg}."""
    qid = (action.get("queue_id") or action.get("draft_id") or "").strip()
    if qid and qid != "latest":
        rows = sb_clients.sb_get_as_service(
            f"/agent_queue?id=eq.{qid}&business_id=eq.{business_id}"
            f"&select=id,subject,body,contact_id&limit=1") or []
        if not rows:
            return {"error": "I couldn't find that draft."}
        return {"row": rows[0]}

    q = (f"/agent_queue?business_id=eq.{business_id}&agent=eq.contract"
         f"&action_type=eq.proposal&order=created_at.desc&limit=1"
         f"&select=id,subject,body,contact_id")
    if contact:
        q += f"&contact_id=eq.{contact['id']}"
    rows = sb_clients.sb_get_as_service(q) or []
    if not rows:
        who = f" for {contact.get('name')}" if contact else ""
        return {"error": f"There's no contract draft{who} yet — I can draft one first."}
    return {"row": rows[0]}


# ─── draft_contract ───────────────────────────────────────────────────

async def handle_draft_contract(client, biz, action) -> Dict[str, Any]:
    """Draft an engagement letter / proposal for ONE named contact.

    The bulk endpoint skips a contact who already has a contract draft; here
    the practitioner asked by name, so a second draft is allowed and the
    result says an earlier one exists rather than silently no-op'ing."""
    import contract_agent as ca

    business_id = biz["id"]
    found = _resolve_contact(business_id, action)
    if found.get("error"):
        return _fail("draft_contract", found["error"])
    contact = found["contact"]

    prior = sb_clients.sb_get_as_service(
        f"/agent_queue?business_id=eq.{business_id}&contact_id=eq.{contact['id']}"
        f"&agent=eq.contract&action_type=eq.proposal&select=id&limit=1") or []

    events = sb_clients.sb_get_as_service(
        f"/events?contact_id=eq.{contact['id']}&order=created_at.desc&limit=8") or []
    history = sb_clients.sb_get_as_service(
        f"/agent_queue?contact_id=eq.{contact['id']}&order=created_at.desc&limit=5"
        f"&select=agent,action_type,subject,status,created_at") or []

    try:
        drafted = await ca._draft_proposal(client, biz, contact, events, history)
    except Exception as e:
        logger.exception(f"draft_contract failed: {e}")
        return _fail("draft_contract", f"I couldn't draft that contract: {str(e)[:160]}")

    if not drafted:
        return _fail("draft_contract", "I couldn't draft that contract.")

    who = contact.get("name") or "your client"
    subject = drafted.get("subject") or "Proposal"

    # contract_agent falls back to a short generic body when the model
    # returns nothing. The row looks identical either way, so surface it —
    # the second-pass reply must not present a stub as finished voice work.
    body = drafted.get("body") or ""
    used_fallback = "I'd love to discuss how we can help" in body

    label = f"{subject} — {who}"
    if used_fallback:
        label += " (generic wording)"

    result = (f"drafted for {who}" if not used_fallback
              else f"drafted for {who}, but the model returned nothing so it's "
                   f"generic placeholder wording — worth a read before it goes out")
    if prior:
        result += ". There was already a contract draft for them"

    return {
        "type": "draft_contract",
        "result": result,
        "label": label,
        "queue_id": drafted.get("queue_id"),
        "contact_id": contact.get("id"),
        "contact_name": who,
        "subject": subject,
        "used_fallback_language": used_fallback,
        "nav": _nav_queue(),
    }


# ─── contract_pdf ─────────────────────────────────────────────────────

async def handle_contract_pdf(client, biz, action) -> Dict[str, Any]:
    """Render a drafted contract as the branded PDF and return its URL.

    Reads the draft rather than taking body text as an argument: the thing
    the practitioner means by "make that a PDF" is the draft they just read,
    and re-passing the body through the model risks rendering something they
    never saw."""
    import contract_agent as ca

    business_id = biz["id"]

    contact = None
    if any(action.get(k) for k in ("contact_id", "contact_name", "client_name", "name")):
        found = _resolve_contact(business_id, action)
        if found.get("error"):
            return _fail("contract_pdf", found["error"])
        contact = found["contact"]

    located = _find_contract_draft(business_id, action, contact)
    if located.get("error"):
        return _fail("contract_pdf", located["error"])
    row = located["row"]

    if contact is None and row.get("contact_id"):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{row['contact_id']}&business_id=eq.{business_id}"
            f"&select=*&limit=1") or []
        contact = rows[0] if rows else None
    if contact is None:
        return _fail("contract_pdf", "I couldn't tell who that contract is for.")

    body = row.get("body") or ""
    if not body.strip():
        return _fail("contract_pdf", "That draft is empty — nothing to render.")

    settings = biz.get("settings") or {}
    metadata = contact.get("metadata") or {}
    contact_org = ((metadata.get("submission") or {}).get("organization")
                   or metadata.get("organization")
                   or contact.get("role"))

    try:
        pdf_bytes = ca._build_pdf(
            business_name=biz.get("name", ""),
            practitioner_name=settings.get("practitioner_name") or biz.get("name", ""),
            contact_name=contact.get("name", "Recipient"),
            contact_org=contact_org,
            subject=row.get("subject") or "Proposal",
            body=body,
        )
    except ImportError:
        # reportlab ships in requirements.txt; if it is genuinely missing the
        # practitioner needs a real answer, not a stack trace in the chat.
        return _fail("contract_pdf",
                     "PDF rendering isn't available on the server right now.")
    except Exception as e:
        logger.exception(f"contract_pdf build failed: {e}")
        return _fail("contract_pdf", f"I couldn't build that PDF: {str(e)[:160]}")

    try:
        pdf_url = await ca._upload_pdf_to_supabase(
            client, pdf_bytes, business_id, contact["id"])
    except Exception as e:
        logger.exception(f"contract_pdf upload failed: {e}")
        return _fail("contract_pdf", f"I built the PDF but couldn't store it: {str(e)[:160]}")

    if not pdf_url:
        return _fail("contract_pdf", "I built the PDF but couldn't store it.")

    who = contact.get("name") or "your client"
    return {
        "type": "contract_pdf",
        "result": f"PDF ready for {who}",
        "label": f"{row.get('subject') or 'Proposal'} — PDF",
        "pdf_url": pdf_url,
        "size_bytes": len(pdf_bytes),
        "queue_id": row.get("id"),
        "contact_id": contact.get("id"),
        "nav": _nav_queue(),
    }
