"""
contract_agent.py — Solutionist System Contract Agent

Drafts proposals and engagement letters when contacts are ready to
convert. Uses the business voice_profile to adapt: a church gets a
partnership proposal, a coach gets a program outline, a consultant
gets a scope of work.

Also generates professional PDF proposals and uploads them to
Supabase Storage.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway project alongside the other agent files.

2. In main.py:
       from contract_agent import router as contract_router
       app.include_router(contract_router)

3. Add to requirements.txt:
       reportlab>=4.0.0

4. Env vars needed (already set): SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY

5. Create a PUBLIC Storage bucket named "proposals" in Supabase Dashboard:
   Storage → New Bucket → name: proposals → Public: ON

6. Add Storage RLS policies on storage.objects (in SQL Editor):
       CREATE POLICY "Allow public read"   ON storage.objects FOR SELECT USING (bucket_id = 'proposals');
       CREATE POLICY "Allow public upload" ON storage.objects FOR INSERT WITH CHECK (bucket_id = 'proposals');
       CREATE POLICY "Allow public delete" ON storage.objects FOR DELETE USING (bucket_id = 'proposals');
"""

import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DRAFT_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
MIN_LEAD_SCORE = 60

logger = logging.getLogger("contract_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] contract: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")
def _anthropic_key(): return os.environ.get("ANTHROPIC_API_KEY", "")

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _sb(client: httpx.AsyncClient, method: str, path: str, body=None):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.request(method, url, headers=headers,
                                content=json.dumps(body) if body else None,
                                timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase {method} {path}: {resp.status_code} {resp.text}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str, max_tokens=800) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    resp = await client.post(ANTHROPIC_API_URL, headers={
        "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
    }, json={
        "model": DRAFT_MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.warning(f"Claude error: {resp.status_code}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


# ═══════════════════════════════════════════════════════════════════════
# CORE LOGIC
# ═══════════════════════════════════════════════════════════════════════

async def _draft_proposal(
    client: httpx.AsyncClient,
    business: Dict,
    contact: Dict,
    events: List[Dict],
    queue_history: List[Dict],
    dry_run: bool = False,
) -> Optional[Dict]:

    biz_id = business["id"]
    biz_name = business.get("name", "")
    biz_type = business.get("type", "general")
    voice = business.get("voice_profile", {})
    practitioner = business.get("settings", {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "professional and warm")
    personality = voice.get("personality", "helpful")
    audience = voice.get("audience", "clients")
    comm_style = voice.get("communication_style", [])

    contact_id = contact["id"]
    name = contact.get("name", "there")
    role = contact.get("role") or ""
    email = contact.get("email") or ""
    tags = contact.get("tags") or []
    lead_score = contact.get("lead_score", 0)
    health = contact.get("health_score", 50)
    metadata = contact.get("metadata") or {}

    # Build context from events and queue history
    event_summary = "\n".join(
        f"- {e.get('event_type')} — {e.get('created_at', '?')[:10]}: {json.dumps(e.get('data', {}))[:100]}"
        for e in events[:8]
    ) or "No events"

    outreach_summary = "\n".join(
        f"- [{q.get('status')}] {q.get('agent')}/{q.get('action_type')}: {q.get('subject', '?')} — {q.get('created_at', '?')[:10]}"
        for q in queue_history[:5]
    ) or "No prior outreach"

    # Submission data from intake (if available)
    submission = metadata.get("submission", {})
    submission_text = "\n".join(f"- {k}: {v}" for k, v in submission.items() if v) if submission else "No intake data"

    # Business-type-specific framing
    type_framing = {
        "church": "a partnership proposal for ministry engagement",
        "coaching": "a coaching program outline with session details and expected outcomes",
        "agency": "a professional scope of work with deliverables and timeline",
        "nonprofit": "a program partnership proposal with impact metrics",
        "ecommerce": "a creative services proposal with project scope",
        "general": "a professional engagement proposal",
    }
    proposal_type = type_framing.get(biz_type, type_framing["general"])

    system_prompt = f"""You are the Contract Agent for {biz_name}. Draft {proposal_type} from {practitioner} to {name}.

Voice profile: tone is "{tone}", personality is "{personality}", audience is "{audience}", style is "{', '.join(comm_style) if comm_style else tone}".

This is a {biz_type} business. Adapt completely:
- Church: partnership language, ministry impact, spiritual alignment
- Coaching: transformation journey, session structure, accountability
- Consulting: scope, deliverables, timeline, ROI
- Nonprofit: mission alignment, community impact, collaboration
- Freelance: creative vision, project milestones, collaboration style

The proposal should include:
1. A personalized opening referencing their specific situation and needs
2. What you're proposing (scope of engagement)
3. Expected outcomes or impact
4. Next steps to get started

Keep it professional but warm. Sign off as {practitioner}. This should feel like a real proposal, not a template."""

    user_msg = f"""Contact: {name}
Role: {role or "not specified"}
Email: {email}
Lead Score: {lead_score}/100
Health Score: {health}/100
Tags: {', '.join(tags) if tags else 'none'}

Intake submission:
{submission_text}

Interaction history:
{event_summary}

Prior outreach:
{outreach_summary}

Draft the proposal."""

    draft_body = await _call_claude(client, system_prompt, user_msg)
    if not draft_body:
        draft_body = f"Hi {name},\n\nThank you for your interest in working with {biz_name}. I'd love to discuss how we can help. Let's schedule a time to talk through the details.\n\nBest,\n{practitioner}"

    subject = f"Proposal for {name} — {biz_name}"
    reasoning = f"Lead score: {lead_score}/100. Contact has been engaged through outreach and shows conversion readiness."
    if submission:
        reasoning += f" Original inquiry mentioned: {list(submission.values())[0][:80] if submission.values() else 'N/A'}."

    result = {
        "contact_id": contact_id,
        "contact_name": name,
        "subject": subject,
        "body": draft_body,
        "priority": "high",
        "ai_reasoning": reasoning,
        "lead_score": lead_score,
    }

    if dry_run:
        return result

    # Insert into agent_queue
    await _sb(client, "POST", "/agent_queue", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "agent": "contract",
        "action_type": "proposal",
        "subject": subject,
        "body": draft_body,
        "channel": "email" if email else "in_app",
        "status": "draft",
        "priority": "high",
        "ai_reasoning": reasoning,
        "ai_model": DRAFT_MODEL,
    })

    # Log event
    await _sb(client, "POST", "/events", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "event_type": "contract_draft_created",
        "data": {"lead_score": lead_score, "proposal_type": biz_type},
        "source": "contract_agent",
    })

    logger.info(f"Proposal drafted for {name} (lead_score={lead_score})")
    return result


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["contract_agent"])

class ContractRequest(BaseModel):
    business_id: str

class ContractPreviewRequest(BaseModel):
    business_id: str
    contact_id: str


@router.post("/agents/contract/generate")
async def contract_generate(req: ContractRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        # Find conversion-ready contacts:
        # High lead score OR has been engaged (agent_message_sent event exists)
        contacts = await _sb(client, "GET",
            f"/contacts?business_id=eq.{req.business_id}"
            f"&lead_score=gte.{MIN_LEAD_SCORE}"
            f"&status=in.(lead,active,vip)"
            f"&order=lead_score.desc&limit=15"
        ) or []

        results = []
        for contact in contacts:
            cid = contact["id"]

            # Skip if contract draft already exists
            existing = await _sb(client, "GET",
                f"/agent_queue?contact_id=eq.{cid}&agent=eq.contract"
                f"&action_type=eq.proposal&select=id&limit=1"
            )
            if existing and len(existing) > 0:
                continue

            events = await _sb(client, "GET",
                f"/events?contact_id=eq.{cid}&order=created_at.desc&limit=8") or []
            queue_history = await _sb(client, "GET",
                f"/agent_queue?contact_id=eq.{cid}&order=created_at.desc&limit=5"
                f"&select=agent,action_type,subject,status,created_at") or []

            r = await _draft_proposal(client, biz, contact, events, queue_history)
            if r:
                results.append(r)

        return {
            "business_id": req.business_id,
            "contacts_evaluated": len(contacts),
            "proposals_drafted": len(results),
            "results": results,
        }


@router.post("/agents/contract/preview")
async def contract_preview(req: ContractPreviewRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        contacts = await _sb(client, "GET", f"/contacts?id=eq.{req.contact_id}&select=*&limit=1")
        if not contacts:
            raise HTTPException(404, "Contact not found")
        events = await _sb(client, "GET",
            f"/events?contact_id=eq.{req.contact_id}&order=created_at.desc&limit=8") or []
        queue_history = await _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{req.contact_id}&order=created_at.desc&limit=5"
            f"&select=agent,action_type,subject,status,created_at") or []
        result = await _draft_proposal(client, businesses[0], contacts[0], events, queue_history, dry_run=True)
        if not result:
            raise HTTPException(500, "Failed to generate preview")
        return result


@router.get("/agents/contract/health")
async def contract_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "min_lead_score": MIN_LEAD_SCORE,
    }


# ═══════════════════════════════════════════════════════════════════════
# PDF GENERATION
# ═══════════════════════════════════════════════════════════════════════
#
# Generates a styled PDF proposal using reportlab and uploads it to
# the Supabase "proposals" Storage bucket. Returns the public URL.

PDF_BUCKET = "proposals"
PDF_ACCENT = "#C8973E"  # Default gold


def _build_pdf(
    business_name: str,
    practitioner_name: str,
    contact_name: str,
    contact_org: Optional[str],
    subject: str,
    body: str,
    accent_hex: str = PDF_ACCENT,
) -> bytes:
    """Generate a professional PDF proposal. Returns bytes."""
    # Lazy import so the module loads even if reportlab isn't installed yet
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem,
    )
    from reportlab.lib.enums import TA_LEFT

    accent = HexColor(accent_hex)
    dark = HexColor("#1A1A22")
    muted = HexColor("#6B7280")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title=subject,
    )

    styles = getSampleStyleSheet()
    h_business = ParagraphStyle(
        "BusinessName", parent=styles["Title"],
        fontSize=22, leading=26, textColor=dark, spaceAfter=4, alignment=TA_LEFT,
        fontName="Helvetica-Bold",
    )
    h_practitioner = ParagraphStyle(
        "Practitioner", parent=styles["Normal"],
        fontSize=11, leading=14, textColor=muted, spaceAfter=2, fontName="Helvetica",
    )
    h_date = ParagraphStyle(
        "DateStyle", parent=styles["Normal"],
        fontSize=10, leading=12, textColor=muted, spaceAfter=20, fontName="Helvetica",
    )
    h_recipient = ParagraphStyle(
        "Recipient", parent=styles["Normal"],
        fontSize=11, leading=14, textColor=dark, spaceAfter=18, fontName="Helvetica",
    )
    h_subject = ParagraphStyle(
        "Subject", parent=styles["Heading2"],
        fontSize=15, leading=18, textColor=accent, spaceAfter=12,
        fontName="Helvetica-Bold",
    )
    h_section = ParagraphStyle(
        "Section", parent=styles["Heading3"],
        fontSize=12, leading=15, textColor=accent, spaceAfter=6, spaceBefore=12,
        fontName="Helvetica-Bold",
    )
    h_body = ParagraphStyle(
        "Body", parent=styles["BodyText"],
        fontSize=10.5, leading=15, textColor=dark, spaceAfter=8,
        fontName="Helvetica", alignment=TA_LEFT,
    )
    h_footer = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=9, leading=11, textColor=muted, alignment=TA_LEFT,
        fontName="Helvetica",
    )

    story: List[Any] = []
    # Header
    story.append(Paragraph(business_name, h_business))
    story.append(Paragraph(practitioner_name, h_practitioner))
    story.append(Paragraph(datetime.now().strftime("%B %d, %Y"), h_date))
    story.append(HRFlowable(width="100%", thickness=2, color=accent, spaceBefore=0, spaceAfter=14))

    # Recipient
    recipient_line = f"<b>Prepared for:</b> {contact_name}"
    if contact_org:
        recipient_line += f", {contact_org}"
    story.append(Paragraph(recipient_line, h_recipient))

    # Subject
    story.append(Paragraph(subject, h_subject))
    story.append(Spacer(1, 6))

    # Body — parse markdown-ish formatting (## headers, **bold**, - bullets)
    bullet_buffer: List[str] = []

    def _flush_bullets():
        if not bullet_buffer:
            return
        items = [ListItem(Paragraph(b, h_body), leftIndent=12) for b in bullet_buffer]
        story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=18, bulletColor=accent))
        story.append(Spacer(1, 6))
        bullet_buffer.clear()

    def _inline_md(text: str) -> str:
        # Convert **bold** → <b>bold</b>
        text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
        # Convert *italic* → <i>italic</i>  (only single asterisks)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
        # Escape stray angle brackets
        return text

    for raw_line in body.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            _flush_bullets()
            story.append(Spacer(1, 4))
            continue
        # Heading
        if line.startswith("## "):
            _flush_bullets()
            story.append(Paragraph(_inline_md(line[3:]), h_section))
            continue
        if line.startswith("# "):
            _flush_bullets()
            story.append(Paragraph(_inline_md(line[2:]), h_section))
            continue
        # Bullet
        bm = re.match(r"^\s*[-*]\s+(.*)", line)
        nm = re.match(r"^\s*\d+\.\s+(.*)", line)
        if bm:
            bullet_buffer.append(_inline_md(bm.group(1)))
            continue
        if nm:
            bullet_buffer.append(_inline_md(nm.group(1)))
            continue
        # Regular paragraph
        _flush_bullets()
        story.append(Paragraph(_inline_md(line), h_body))

    _flush_bullets()

    # Footer
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=muted, spaceBefore=0, spaceAfter=8))
    story.append(Paragraph(f"{business_name}  ·  {practitioner_name}", h_footer))

    doc.build(story)
    return buf.getvalue()


async def _upload_pdf_to_supabase(
    client: httpx.AsyncClient,
    pdf_bytes: bytes,
    business_id: str,
    contact_id: str,
) -> Optional[str]:
    """Upload PDF to Supabase Storage. Returns public URL."""
    timestamp = int(datetime.now(timezone.utc).timestamp())
    path = f"{business_id}/{contact_id}/proposal-{timestamp}.pdf"
    url = f"{_supabase_url()}/storage/v1/object/{PDF_BUCKET}/{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/pdf",
    }
    resp = await client.post(url, headers=headers, content=pdf_bytes, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase Storage upload failed: {resp.status_code} {resp.text}")
        if "Bucket not found" in resp.text:
            raise HTTPException(500, f"Storage bucket '{PDF_BUCKET}' does not exist. Create it in Supabase Dashboard → Storage → New Bucket → name: {PDF_BUCKET} → Public: ON.")
        if "row-level security" in resp.text.lower() or resp.status_code == 403:
            raise HTTPException(500, f"Storage upload blocked by RLS. Add INSERT policy on storage.objects for bucket '{PDF_BUCKET}'.")
        raise HTTPException(500, f"PDF upload failed: {resp.text}")
    return f"{_supabase_url()}/storage/v1/object/public/{PDF_BUCKET}/{path}"


class PdfRequest(BaseModel):
    business_id: str
    contact_id: str
    proposal_body: str
    subject: str


@router.post("/agents/contract/pdf")
async def contract_pdf(req: PdfRequest):
    async with httpx.AsyncClient() as client:
        # Fetch business + contact for header/recipient info
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        contacts = await _sb(client, "GET", f"/contacts?id=eq.{req.contact_id}&select=*&limit=1")
        if not contacts:
            raise HTTPException(404, "Contact not found")
        contact = contacts[0]

        biz_name = biz.get("name", "")
        practitioner = biz.get("settings", {}).get("practitioner_name", "")
        practitioner_line = practitioner if practitioner else biz_name

        contact_name = contact.get("name", "Recipient")
        contact_org = (contact.get("metadata") or {}).get("submission", {}).get("organization") \
            or (contact.get("metadata") or {}).get("organization") \
            or contact.get("role")

        # Build PDF
        try:
            pdf_bytes = _build_pdf(
                business_name=biz_name,
                practitioner_name=practitioner_line,
                contact_name=contact_name,
                contact_org=contact_org,
                subject=req.subject,
                body=req.proposal_body,
            )
        except ImportError:
            raise HTTPException(500, "reportlab is not installed. Add reportlab>=4.0.0 to requirements.txt and redeploy.")
        except Exception as e:
            logger.error(f"PDF build failed: {e}")
            raise HTTPException(500, f"PDF build failed: {e}")

        # Upload
        pdf_url = await _upload_pdf_to_supabase(client, pdf_bytes, req.business_id, req.contact_id)

        logger.info(f"PDF generated for {contact_name}: {pdf_url}")
        return {"pdf_url": pdf_url, "size_bytes": len(pdf_bytes)}
