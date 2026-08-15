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

import business_identity
import llm_call
import storage_links
from fastapi import APIRouter, HTTPException, Depends
from auth_supabase import require_user, AuthedUser
from business_users_router import require_business_admin
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

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

async def _sb(client, method: str, path: str, body=None):
    """RLS-readiness migration: delegates to sb_clients.sb_as_current_context.
    User JWT bound by the handler (via sb_clients.set_user_jwt) is forwarded.
    Falls back to service-role for server-initiated paths."""
    import sb_clients
    return await sb_clients.sb_as_current_context(
        client, method, path, body, allow_service_fallback=True,
    )




async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str, max_tokens=800) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    resp = await llm_call.apost(client, {
        "model": DRAFT_MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }, timeout=HTTP_TIMEOUT, key=key)
    if resp.status_code >= 400:
        logger.warning(f"Claude error: {resp.status_code}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


# ═══════════════════════════════════════════════════════════════════════
# VERTICAL FRAMING
# ═══════════════════════════════════════════════════════════════════════

# What KIND of document each vertical's "contract" actually is. A church does
# not sign a scope of work and a law firm does not sign a program outline, so
# this decides the shape before the model writes a word.
#
# Keys are canonical vertical_registry keys. GENERIC covers 'custom' and any
# type that predates the registry.
_GENERIC_FRAMING = "a professional engagement proposal"

PROPOSAL_FRAMING: Dict[str, str] = {
    "coach":              "a coaching program outline with session structure, "
                          "package terms, and the outcomes the client is working toward",
    "consultant":         "a scope of work with deliverables, milestones, timeline, "
                          "and the terms of the engagement",
    "creative":           "a creative services proposal with project scope, "
                          "revision rounds, deliverables, and timeline",
    "course_creator":     "a program enrollment agreement covering curriculum, "
                          "cohort dates, access terms, and what the student receives",
    "financial_educator": "an educational program agreement — explicitly education, "
                          "NOT personalized financial advice",
    "fitness_wellness":   "a training or wellness program agreement with session "
                          "structure, and no clinical or medical claims",
    "contractor":         "a WORK AGREEMENT / job bid — scope of work, materials "
                          "and labor broken out, deposit, payment schedule, and "
                          "how change orders are handled and priced",
    "therapist":          "a PRACTICE AGREEMENT / informed-consent and policies "
                          "document — fees, session length, cancellation window "
                          "and fee, contact between sessions, and the limits of "
                          "confidentiality. NOT a treatment plan and NOT clinical",
    "service_provider":   "a service agreement with scope, schedule, and pricing",
    "personal_services":  "a service agreement covering the services booked, "
                          "pricing, and cancellation terms",
    "lawyer":             "an ENGAGEMENT LETTER — scope of representation, fee "
                          "structure, retainer and trust-account terms, and the "
                          "limits of the engagement. Never predict an outcome",
    "ministry":           "a partnership proposal for ministry engagement — "
                          "covenant language, shared mission, and how the "
                          "partnership serves the congregation",
    "nonprofit":          "a program partnership proposal with mission alignment, "
                          "impact metrics, and reporting commitments",
    "custom":             _GENERIC_FRAMING,
}

# Per-vertical drafting guidance injected alongside the framing. Replaces the
# old hardcoded prose list, which named legacy types the system no longer
# stamps ('Church', 'Coaching', 'Freelance') and silently omitted lawyers.
PROPOSAL_GUIDANCE: Dict[str, str] = {
    "coach":              "Transformation journey, session cadence, accountability. "
                          "Outcome-focused without promising specific results.",
    "consultant":         "Scope, deliverables, milestones, ROI. Crisp and "
                          "executive — no filler.",
    "creative":           "Creative vision, project milestones, revision rounds, "
                          "collaboration style.",
    "course_creator":     "Curriculum is the product. Be concrete about what is "
                          "taught, in what order, and over what period.",
    "financial_educator": "Education, not personalized financial advice. Say so "
                          "plainly in the document.",
    "fitness_wellness":   "Program structure and progression. No clinical claims, "
                          "no diagnosis, no treatment language.",
    "contractor":         "Scope of work in plain terms. Materials and labor "
                          "separated. Deposit, progress payments, and final "
                          "balance stated as amounts and dates. Say explicitly "
                          "what is NOT included, and that changes to the scope "
                          "are priced as a change order before the work is done.",
    "therapist":          "Plain, calm, and administrative. Fees, session "
                          "length, cancellation window and fee, how to reach "
                          "you between sessions, and the limits of "
                          "confidentiality stated factually. Say nothing "
                          "clinical: no diagnosis, no treatment approach, no "
                          "predicted outcome. This is a business agreement, "
                          "not a clinical document.",
    "service_provider":   "Plain talk about scope, schedule, and price.",
    "personal_services":  "Plain talk about price, time, and cancellation. Short "
                          "and transactional — this is not a legal brief.",
    "lawyer":             "Formal. Scope of representation and its LIMITS, fee "
                          "structure, retainer handling. Trust funds stay separate "
                          "from operating funds. Never speculate on outcomes and "
                          "never state a legal conclusion.",
    "ministry":           "Partnership language, ministry impact, spiritual "
                          "alignment. Pastoral, never salesy.",
    "nonprofit":          "Mission alignment, community impact, collaboration, "
                          "and how impact will be reported.",
    "custom":             "Professional and clear. Scope, terms, next steps.",
}


def _canonical_type(business_type: Optional[str]) -> str:
    """Canonical vertical key for a raw businesses.type value.

    Falls back to 'custom' when vertical_registry is unavailable rather than
    raising — a contract that drafts with generic framing is a worse document,
    but a contract that fails to draft at all is a broken feature.
    """
    try:
        import vertical_registry
        return vertical_registry.resolve(business_type)
    except Exception:
        return "custom"


def _proposal_framing(business_type: Optional[str]) -> str:
    return PROPOSAL_FRAMING.get(_canonical_type(business_type), _GENERIC_FRAMING)


def _proposal_guidance(business_type: Optional[str]) -> str:
    return PROPOSAL_GUIDANCE.get(_canonical_type(business_type),
                                 PROPOSAL_GUIDANCE["custom"])


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
    # Phase 2 (LGS): one consistent voice directive composed from voice_profile
    # + brand_kit tone_words + creative_expression. Additive — augments the
    # explicit voice line below so every artifact sounds like the same person.
    try:
        from practitioner_voice import compose_voice_directive
        _voice_directive = compose_voice_directive(business)
    except Exception:
        _voice_directive = ""

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

    # Business-type-specific framing.
    #
    # Keyed on CANONICAL vertical keys (vertical_registry.CANONICAL), never on
    # raw businesses.type. The two are not the same string: intake stamps the
    # canonical value ('ministry', 'coach', 'creative') while this map was
    # historically keyed on the legacy aliases ('church', 'coaching', 'agency').
    # Every canonical vertical fell through to the generic framing as a result,
    # and lawyer/consultant had no entry at all — the exact two verticals whose
    # archetypes are built around engagement letters. resolve() collapses the
    # alias table so both spellings land on the same framing.
    #
    # test_contract_vertical_framing.py asserts this map covers every canonical
    # key, so a new vertical cannot be added without a framing decision.
    proposal_type = _proposal_framing(biz_type)

    system_prompt = f"""You are the Contract Agent for {biz_name}. Draft {proposal_type} from {practitioner} to {name}.

Voice profile: tone is "{tone}", personality is "{personality}", audience is "{audience}", style is "{', '.join(comm_style) if comm_style else tone}".
{_voice_directive}

This is a {_canonical_type(biz_type)} business. Adapt completely:
{_proposal_guidance(biz_type)}

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

    # Insert into agent_queue. The returned row id is surfaced on the result
    # as `queue_id` so a caller can act on THIS draft specifically — Chief's
    # draft_contract → approve_draft chain needs the id, and before this the
    # only way to find it again was "the most recent draft", which is wrong
    # the moment two drafts exist.
    queued = await _sb(client, "POST", "/agent_queue", {
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
    if isinstance(queued, list) and queued:
        result["queue_id"] = queued[0].get("id")

    # Log event
    await _sb(client, "POST", "/events", {
        "business_id": biz_id,
        "contact_id": contact_id,
        "event_type": "contract_draft_created",
        # proposal_type has always recorded the raw businesses.type here; kept
        # as-is for any existing consumer, with the canonical key alongside it
        # so downstream reads can group by vertical without re-resolving.
        "data": {
            "lead_score": lead_score,
            "proposal_type": biz_type,
            "business_type": _canonical_type(biz_type),
        },
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


async def run_contract_generate(business_id: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        # Find conversion-ready contacts:
        # High lead score OR has been engaged (agent_message_sent event exists)
        contacts = await _sb(client, "GET",
            f"/contacts?business_id=eq.{business_id}"
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
            "business_id": business_id,
            "contacts_evaluated": len(contacts),
            "proposals_drafted": len(results),
            "results": results,
        }


async def run_contract_preview(business_id: str, contact_id: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        contacts = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=*&limit=1")
        if not contacts:
            raise HTTPException(404, "Contact not found")
        events = await _sb(client, "GET",
            f"/events?contact_id=eq.{contact_id}&order=created_at.desc&limit=8") or []
        queue_history = await _sb(client, "GET",
            f"/agent_queue?contact_id=eq.{contact_id}&order=created_at.desc&limit=5"
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

# Brand Studio → the paper (8/05). The kit at settings.brand_kit already
# carries colors.primary, font_pair, and logo_url — the PDF just never
# read it. brand_from_business() extracts what reportlab can honor
# (accent color, serif/sans lean, the logo), and both callers pass it.

_SERIF_HINTS = ("playfair", "georgia", "merriweather", "lora", "times",
                "garamond", "baskerville", "libre caslon", "cormorant",
                "crimson", "spectral", "serif")


def brand_from_business(business: Dict[str, Any]) -> Dict[str, Any]:
    """{accent, serif, logo_url} from settings.brand_kit — with the
    shipped defaults when a business hasn't built a kit yet."""
    kit = ((business or {}).get("settings") or {}).get("brand_kit") or {}
    colors = kit.get("colors") or {}
    raw = (colors.get("primary") or kit.get("primary_color") or "").strip()
    accent = PDF_ACCENT
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", raw):
        accent = raw if raw.startswith("#") else f"#{raw}"
    font_pair = kit.get("font_pair") or {}
    heading_font = str(font_pair.get("heading")
                       or kit.get("font_heading") or "").lower()
    serif = any(h in heading_font for h in _SERIF_HINTS)
    logo_url = kit.get("logo_url") or (kit.get("assets") or {}).get("primary")
    return {"accent": accent, "serif": serif, "logo_url": logo_url or None}


def letterhead_lines(business: Dict[str, Any],
                     identity: Optional[Dict[str, Any]] = None) -> List[str]:
    """The contact block for the top-right of the letterhead.

    Reads the filed identity first (business_profiles — the legal record
    a practitioner fills in during Foundation) and falls back to the
    business row's settings. Returns [] when a business has told us
    nothing, so the header simply keeps its old shape rather than
    printing an empty box or the word "None".

    A suite or unit keeps its own line. Joined onto the street it reads
    as part of the road name ("412 Grand River Avenue Suite 3"), and in
    a two-inch column it is also the thing that pushes the street into
    an ugly wrap.
    """
    ident = identity or {}
    settings = (business or {}).get("settings") or {}

    street = ident.get("address_line1") or ""
    unit = ident.get("address_line2") or ""
    city = ident.get("address_city") or ""
    state = ident.get("address_state") or ""
    zip_ = ident.get("address_zip") or ""
    locality = ", ".join(x for x in (city, " ".join(y for y in (state, zip_) if y)) if x)

    phone = ident.get("phone") or settings.get("phone") or ""
    email = settings.get("contact_email") or (business or {}).get("email") or ""
    site = settings.get("site_url") or settings.get("website") or ""
    # A bare domain reads as part of an address block; the scheme reads
    # as a URL someone pasted.
    site = re.sub(r"^https?://", "", str(site)).rstrip("/")

    return [str(x).strip() for x in (street, unit, locality, phone, email, site)
            if x and str(x).strip()]


async def fetch_logo_bytes(client: httpx.AsyncClient,
                           logo_url: Optional[str]) -> Optional[bytes]:
    """Best-effort logo download for the letterhead. SVG is skipped
    (reportlab can't raster it); any failure means no logo, never a
    failed PDF."""
    if not logo_url or logo_url.lower().split("?")[0].endswith(".svg"):
        return None
    try:
        r = await client.get(logo_url, timeout=HTTP_TIMEOUT)
        if r.status_code >= 400 or not r.content or len(r.content) > 3_000_000:
            return None
        return r.content
    except Exception:
        return None


# ── Line classification for the body renderer ────────────────────────
# Generated documents carry clause headings like "1. SCOPE OF
# ENGAGEMENT" and letters carry bare ones like "THE BALANCE". The old
# renderer's numbered-list regex swallowed the former as BULLETS. A
# line is a clause heading when its text reads as a title (all-caps,
# short); numbered lines with sentence text stay list items.

def _classify_line(line: str) -> tuple:
    s = line.rstrip()
    if not s.strip():
        return ("blank", "")
    if s.startswith("## "):
        return ("heading", s[3:])
    if s.startswith("# "):
        return ("heading", s[2:])
    m = re.match(r"^(\d+)\.\s+(.+)$", s.strip())
    if m:
        rest = m.group(2).strip()
        if rest == rest.upper() and any(c.isalpha() for c in rest) and len(rest) <= 70:
            return ("heading", s.strip())          # "1. SCOPE OF ENGAGEMENT"
        return ("numbered", rest)                   # a real numbered list item
    bare = s.strip()
    if (bare == bare.upper() and any(c.isalpha() for c in bare)
            and len(bare) <= 70 and not bare.endswith((".", ":", ","))):
        return ("heading", bare)                    # "GENERAL TERMS", "ACCEPTED AND AGREED"
    if re.match(r"^\([a-z]\)\s+", bare):
        return ("subclause", bare)                  # "(a) Entire agreement. …"
    bm = re.match(r"^\s*[-*]\s+(.*)", s)
    if bm:
        return ("bullet", bm.group(1))
    return ("para", s.strip())


def _build_pdf(
    business_name: str,
    practitioner_name: str,
    contact_name: str,
    contact_org: Optional[str],
    subject: str,
    body: str,
    accent_hex: str = PDF_ACCENT,
    serif: bool = False,
    logo_bytes: Optional[bytes] = None,
    letterhead: Optional[List[str]] = None,
) -> bytes:
    """Generate a professional PDF proposal. Returns bytes.

    `letterhead` is the pre-formatted right-hand contact block — address,
    phone, email, site — one entry per line. Build it with
    `letterhead_lines()` rather than assembling it at each call site.
    """
    # Lazy import so the module loads even if reportlab isn't installed yet
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem,
        Image, Table, TableStyle,
    )
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.pdfgen import canvas

    accent = HexColor(accent_hex)
    dark = HexColor("#1A1A22")
    muted = HexColor("#6B7280")

    # Brand Studio font lean: a serif kit reads as Times, a sans kit as
    # Helvetica — the closest reportlab's built-ins get to the site's
    # typography without shipping font files.
    f_regular = "Times-Roman" if serif else "Helvetica"
    f_bold = "Times-Bold" if serif else "Helvetica-Bold"

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
        fontSize=17, leading=21, textColor=dark, spaceAfter=3, alignment=TA_LEFT,
        fontName=f_bold,
    )
    h_practitioner = ParagraphStyle(
        "Practitioner", parent=styles["Normal"],
        fontSize=9.5, leading=13, textColor=muted, spaceAfter=0, fontName=f_regular,
    )
    h_recipient = ParagraphStyle(
        "Recipient", parent=styles["Normal"],
        fontSize=10.5, leading=14, textColor=muted, spaceAfter=16, fontName=f_regular,
    )
    h_subject = ParagraphStyle(
        "Subject", parent=styles["Heading2"],
        fontSize=15, leading=18, textColor=accent, spaceAfter=12,
        fontName=f_bold,
    )
    h_section = ParagraphStyle(
        "Section", parent=styles["Heading3"],
        fontSize=12, leading=15, textColor=accent, spaceAfter=6, spaceBefore=12,
        fontName=f_bold,
    )
    h_body = ParagraphStyle(
        "Body", parent=styles["BodyText"],
        fontSize=10.5, leading=15, textColor=dark, spaceAfter=8,
        fontName=f_regular, alignment=TA_LEFT,
    )
    h_footer = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=9, leading=11, textColor=muted, alignment=TA_LEFT,
        fontName=f_regular,
    )
    h_letterhead = ParagraphStyle(
        "Letterhead", parent=styles["Normal"],
        fontSize=8.5, leading=11.5, textColor=muted, alignment=TA_RIGHT,
        fontName=f_regular,
    )

    def _xml(s: str) -> str:
        # Names travel through Paragraph's inline-markup parser too — an
        # "&" in "A & B Law" must never crash the letterhead.
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story: List[Any] = []
    # Header — a tight letterhead lockup. The logo column is sized to
    # the LOGO (the old fixed 2.1in column left a dead gap that made
    # the header read as two things fighting); the name block sits
    # immediately beside it, vertically centered, with practitioner and
    # date on one quiet line instead of a three-line stack.
    meta_line = _xml(practitioner_name)
    meta_line += f"  ·  {datetime.now().strftime('%B %d, %Y')}"
    name_block = [
        Paragraph(_xml(business_name), h_business),
        Paragraph(meta_line, h_practitioner),
    ]
    logo_flowable = None
    logo_w = 0.0
    if logo_bytes:
        try:
            reader = ImageReader(io.BytesIO(logo_bytes))
            iw, ih = reader.getSize()
            if iw > 0 and ih > 0:
                target_h = 0.6 * inch
                logo_w = min(target_h * (iw / ih), 1.7 * inch)
                logo_flowable = Image(io.BytesIO(logo_bytes),
                                      width=logo_w, height=target_h)
        except Exception:
            logo_flowable = None  # a bad image never breaks the paper
    # Where the business can be reached, right-aligned opposite the name
    # — the half of a letterhead that was missing. A document that a
    # board files, a client signs, or a funder keeps on record needs to
    # carry the sender's address and phone; without them the paper looks
    # generated rather than issued, and a printed copy has no way back
    # to the business at all.
    #
    # Deliberately NOT the EIN. It belongs on the documents that need it
    # (a §170(f)(8) donation acknowledgment states it in the body, where
    # a donor's accountant looks for it) and nowhere near a proposal
    # emailed to a prospect.
    lh_lines = [_xml(x) for x in (letterhead or []) if x and str(x).strip()]
    contact_block = ([Paragraph("<br/>".join(lh_lines), h_letterhead)]
                     if lh_lines else None)

    if logo_flowable is not None or contact_block is not None:
        row: List[Any] = []
        widths: List[Any] = []
        if logo_flowable is not None:
            row.append(logo_flowable)
            widths.append(logo_w + 14)
        row.append(name_block)
        widths.append(None)
        if contact_block is not None:
            row.append(contact_block)
            # A fixed right column: the name is the flexible one, so a
            # long business name wraps instead of squeezing the address
            # into one word per line.
            widths.append(2.0 * inch)
        name_col = len(row) - (2 if contact_block is not None else 1)
        head = Table([row], colWidths=widths)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]
        if logo_flowable is not None:
            style.append(("RIGHTPADDING", (0, 0), (0, 0), 14))
        if contact_block is not None:
            style.append(("RIGHTPADDING", (name_col, 0), (name_col, 0), 14))
            style.append(("VALIGN", (name_col + 1, 0), (name_col + 1, 0), "TOP"))
        head.setStyle(TableStyle(style))
        story.append(head)
    else:
        story.extend(name_block)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=2, color=accent, spaceBefore=0, spaceAfter=16))

    # Title first, then who it's for — the document leads with what it
    # IS; the recipient line reads as a quiet label under it.
    story.append(Paragraph(_xml(subject), h_subject))
    recipient_line = f'Prepared for <font color="#1A1A22"><b>{_xml(contact_name)}</b></font>'
    if contact_org:
        recipient_line += f", {_xml(contact_org)}"
    story.append(Paragraph(recipient_line, h_recipient))
    story.append(Spacer(1, 2))

    # Body — parse markdown-ish formatting (## headers, **bold**, - bullets)
    bullet_buffer: List[str] = []

    def _flush_bullets():
        if not bullet_buffer:
            return
        items = [ListItem(Paragraph(b, h_body), leftIndent=12) for b in bullet_buffer]
        story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=18, bulletColor=accent))
        story.append(Spacer(1, 6))
        bullet_buffer.clear()

    h_subclause = ParagraphStyle(
        "Subclause", parent=h_body, leftIndent=14, spaceAfter=5,
    )

    def _inline_md(text: str) -> str:
        # Escape XML first — a stray & or < in a clause must never crash
        # reportlab's Paragraph parser (it reads inline HTML-ish markup).
        text = (text.replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))
        # Convert **bold** → <b>bold</b>
        text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
        # Convert *italic* → <i>italic</i>  (only single asterisks)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
        return text

    # The classifier knows a clause heading ("1. SCOPE OF ENGAGEMENT",
    # "GENERAL TERMS") from a list item — the old numbered-list regex
    # rendered every contract clause as a bullet point.
    for raw_line in body.split("\n"):
        kind, text = _classify_line(raw_line)
        if kind == "blank":
            _flush_bullets()
            story.append(Spacer(1, 4))
        elif kind == "heading":
            _flush_bullets()
            story.append(Paragraph(_inline_md(text), h_section))
        elif kind in ("bullet", "numbered"):
            bullet_buffer.append(_inline_md(text))
        elif kind == "subclause":
            _flush_bullets()
            story.append(Paragraph(_inline_md(text), h_subclause))
        else:
            _flush_bullets()
            story.append(Paragraph(_inline_md(text), h_body))

    _flush_bullets()

    # Footer
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=muted, spaceBefore=0, spaceAfter=8))
    story.append(Paragraph(f"{_xml(business_name)}  ·  {_xml(practitioner_name)}", h_footer))

    # "Page 2 of 6" on every page. A conflict-of-interest policy or a
    # retention schedule runs to several pages, gets printed, signed and
    # filed — and a stack with no pagination has no way to show a page
    # went missing. multiBuild runs the story twice so the total is
    # known; the first pass only counts pages.
    class _Paginated(canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                if total > 1:
                    self.setFont(f_regular, 8.5)
                    self.setFillColor(muted)
                    self.drawRightString(
                        LETTER[0] - 0.75 * inch, 0.5 * inch,
                        f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    doc.multiBuild(story, canvasmaker=_Paginated)
    return buf.getvalue()


def build_document_pdf(
    *,
    business_name: str,
    practitioner_name: str,
    prepared_for: str,
    subject: str,
    body: str,
    prepared_for_org: Optional[str] = None,
    accent_hex: str = PDF_ACCENT,
    serif: bool = False,
    logo_bytes: Optional[bytes] = None,
    letterhead: Optional[List[str]] = None,
) -> bytes:
    """Public seam over _build_pdf for documents that are not client proposals.

    Foundation Track's Operating Agreement, Privacy Policy and Terms of Service
    are governance documents about the business itself. They want the same
    paper as a proposal: the Brand Studio accent, the font lean, the logo, the
    contact block, and the clause classifier that keeps numbered sections from
    rendering as bullets.

    (/agents/contract/pdf now takes an optional contact and reaches the same
    renderer, so this is a convenience over that door rather than a way round
    a restriction — it was the latter until 2026-08-15.)

    `prepared_for` is the party the document is FOR. For a governance document
    that is the business's own legal name, which reads correctly in the
    "Prepared for …" line without needing a special case.

    Exists so callers need not depend on the private _build_pdf name.
    """
    return _build_pdf(
        business_name=business_name,
        practitioner_name=practitioner_name,
        contact_name=prepared_for,
        contact_org=prepared_for_org,
        subject=subject,
        body=body,
        accent_hex=accent_hex,
        serif=serif,
        logo_bytes=logo_bytes,
        letterhead=letterhead,
    )


async def _upload_pdf_to_supabase(
    client: httpx.AsyncClient,
    pdf_bytes: bytes,
    business_id: str,
    contact_id: str,
    download_as: Optional[str] = None,
) -> Optional[str]:
    """Upload the PDF to the private `proposals` bucket and return a
    signed URL for it.

    Both halves of this used to be wrong, and had been since the vault
    migration closed the bucket on 2026-08-10:

      * the upload went out under the ANON key, which the bucket's
        insert policy (`authenticated` + business scope) refuses —
        "new row violates row-level security policy", so nothing was
        ever stored; and
      * the returned URL was `/object/public/...`, which a private
        bucket answers with "Bucket not found".

    Every Download PDF button in the app went through here, so all of
    them had been dead for five days without anything logging louder
    than a 500.
    """
    timestamp = int(datetime.now(timezone.utc).timestamp())
    path = f"{business_id}/{contact_id}/proposal-{timestamp}.pdf"
    url = f"{_supabase_url()}/storage/v1/object/{PDF_BUCKET}/{path}"
    headers = {**storage_links.service_headers(), "Content-Type": "application/pdf"}
    resp = await client.post(url, headers=headers, content=pdf_bytes, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase Storage upload failed: {resp.status_code} {resp.text}")
        if "Bucket not found" in resp.text:
            raise HTTPException(500, f"Storage bucket '{PDF_BUCKET}' does not exist. Create it in Supabase Dashboard → Storage → New Bucket → name: {PDF_BUCKET} → Public: OFF (it holds client records).")
        if "row-level security" in resp.text.lower() or resp.status_code == 403:
            raise HTTPException(500, f"Storage upload blocked by RLS on bucket '{PDF_BUCKET}'. Check SUPABASE_SERVICE_ROLE_KEY is set on this service.")
        raise HTTPException(500, f"PDF upload failed: {resp.text}")

    signed = await storage_links.signed_url(
        client, PDF_BUCKET, path, download_as=download_as)
    if not signed:
        # The bytes are filed; only the link failed. Say which, so this
        # never again reads as "the document was never generated".
        raise HTTPException(
            500, "The PDF was saved but the download link couldn't be signed. "
                 "Try again in a moment.")
    return signed


class PdfRequest(BaseModel):
    business_id: str
    # OPTIONAL. A proposal has a counterparty; a governance document does
    # not. A board list, a whistleblower policy, a mission narrative and
    # an operating agreement are all about the business itself — and
    # while this was required, none of them could be downloaded at all.
    # The button was hidden on the queue row AND the endpoint 404'd, so a
    # practitioner could generate one of those documents, approve it, and
    # have no way to get the file.
    contact_id: Optional[str] = None
    proposal_body: str
    subject: str


@router.post("/agents/contract/pdf")
async def contract_pdf(req: PdfRequest, user: AuthedUser = Depends(require_user)):
    # Reads a whole business row (settings included) and a whole contact
    # row, then renders both into a PDF. Authenticated-then-discarded
    # meant any signed-in caller could do that for ANY business and ANY
    # contact — this is a disclosure endpoint, not just a render one.
    import business_access
    business_access.assert_access(str(req.business_id), user, "member")
    async with httpx.AsyncClient() as client:
        # Fetch business + contact for header/recipient info
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        contact = None
        if req.contact_id:
            contacts = await _sb(
                client, "GET",
                f"/contacts?id=eq.{req.contact_id}&select=*&limit=1")
            if not contacts:
                raise HTTPException(404, "Contact not found")
            contact = contacts[0]

        biz_name = biz.get("name", "")
        practitioner = biz.get("settings", {}).get("practitioner_name", "")
        practitioner_line = practitioner if practitioner else biz_name

        # The filed identity feeds both the letterhead's contact block and,
        # when there is no counterparty, the "Prepared for" line.
        try:
            ident = business_identity.get_identity(req.business_id, biz)
        except Exception as e:  # noqa: BLE001 — identity must not 500 a download
            logger.warning(f"identity lookup failed for {req.business_id}: {e}")
            ident = {}

        if contact:
            contact_name = contact.get("name", "Recipient")
            contact_org = (contact.get("metadata") or {}).get("submission", {}).get("organization") \
                or (contact.get("metadata") or {}).get("organization") \
                or contact.get("role")
        else:
            # No counterparty: the document is FOR the business, so its own
            # legal name reads correctly on the "Prepared for" line.
            contact_name = (ident.get("legal_name") or "").strip() or biz_name or "Prepared internally"
            contact_org = None

        # Build PDF — dressed by the Brand Studio kit (accent, font
        # lean, logo) when one exists.
        brand = brand_from_business(biz)
        logo = await fetch_logo_bytes(client, brand["logo_url"])
        try:
            pdf_bytes = _build_pdf(
                business_name=biz_name,
                practitioner_name=practitioner_line,
                contact_name=contact_name,
                contact_org=contact_org,
                subject=req.subject,
                body=req.proposal_body,
                accent_hex=brand["accent"],
                serif=brand["serif"],
                logo_bytes=logo,
                letterhead=letterhead_lines(biz, ident),
            )
        except ImportError:
            raise HTTPException(500, "reportlab is not installed. Add reportlab>=4.0.0 to requirements.txt and redeploy.")
        except Exception as e:
            logger.error(f"PDF build failed: {e}")
            raise HTTPException(500, f"PDF build failed: {e}")

        # Upload
        # "general" rather than a contact folder, so a governance document
        # still lands under the business prefix the storage policies key on
        # — the same segment foundation_agent already uses for its own.
        safe = re.sub(r"[^\w\- ]+", "", (req.subject or "Document")).strip() or "Document"
        pdf_url = await _upload_pdf_to_supabase(
            client, pdf_bytes, req.business_id, req.contact_id or "general",
            download_as=f"{safe}.pdf")

        logger.info(f"PDF generated for {contact_name}: {pdf_url}")
        return {"pdf_url": pdf_url, "size_bytes": len(pdf_bytes)}


# ── The doors ─────────────────────────────────────────────────────────


@router.post("/agents/contract/generate")
async def contract_generate(req: ContractRequest, user: AuthedUser = Depends(require_user)):
    """Owner/admin only. This makes the business ACT — drafts client
    messages and spends model budget — so a caller proves who they are
    rather than merely knowing a uuid. Chief calls run_contract_generate() in-process."""
    require_business_admin(req.business_id, user)
    return await run_contract_generate(req.business_id)

@router.post("/agents/contract/preview")
async def contract_preview(req: ContractPreviewRequest, user: AuthedUser = Depends(require_user)):
    """Admin only. Drafts against a named contact; Chief calls
    run_contract_preview() in-process."""
    require_business_admin(req.business_id, user)
    return await run_contract_preview(req.business_id, req.contact_id)
