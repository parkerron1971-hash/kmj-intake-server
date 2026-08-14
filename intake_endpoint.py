"""
intake_endpoint.py — Solutionist System Intake Agent

Self-contained FastAPI router that receives form submissions from
embeddable intake forms on client websites, scores the lead using AI,
drafts a personalized response, and queues it for Kevin's approval.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop this file into your Railway project alongside ai_proxy.py.

2. In your existing main.py, add:

       from intake_endpoint import router as intake_router
       app.include_router(intake_router)

3. Set these environment variables in the Railway dashboard:

       SUPABASE_URL=https://brqjgbpzackdihgjsorf.supabase.co
       SUPABASE_ANON=<your anon key>
       ANTHROPIC_API_KEY=<already set from Step 2>

4. CORS: embeddable forms will POST from any client website.
   Make sure your CORSMiddleware includes allow_origins=["*"] or
   at least allows the origins where intake forms are embedded.

═══════════════════════════════════════════════════════════════════════
ENDPOINT
═══════════════════════════════════════════════════════════════════════

POST /intake/submit

Request:
    {
      "form_id":     "uuid",
      "business_id": "uuid",
      "data":        { "name": "...", "email": "...", ... }
    }

Response:
    { "success": true, "contact_id": "uuid" }

Pipeline:
    1. Validate submission against form config
    2. Create contact in contacts table
    3. Log event in events table
    4. Score the lead 0-100 via lead_scoring — the SHARED rubric, the
       same one the composed-site contact form, the site concierge and
       the booking widget now run. This module used to be the only
       writer of contacts.lead_score in the whole backend, which is why
       every reader gated on that column went quiet for leads arriving
       through any other door.
    5. AI drafts a personalized response
    6. Insert draft into agent_queue for approval
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

import lead_scoring
import llm_call
import rate_limit
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

# Arc 29 — abuse gate for the anon intake endpoint. Each submission
# creates a contact + fires an AI scoring + draft, so unthrottled spam
# is both a data-pollution and an AI-cost vector. Per-IP sliding window,
# in-process (matches public_site._check_rate; resets on redeploy —
# acceptable for a spam speed-bump, not a security boundary).
_INTAKE_RATE_MAX = int(os.environ.get("INTAKE_RATE_PER_MIN", "6"))
_INTAKE_WINDOW_SEC = 60
_intake_buckets: Dict[str, Dict[str, float]] = {}


def _intake_rate_ok(ip: str) -> bool:
    now = time.time()
    b = _intake_buckets.get(ip)
    if not b or now - b["start"] > _INTAKE_WINDOW_SEC:
        _intake_buckets[ip] = {"start": now, "count": 1}
        return True
    if b["count"] >= _INTAKE_RATE_MAX:
        return False
    b["count"] += 1
    return True

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_VERSION = "2023-06-01"

# Scoring moved to lead_scoring (one rubric, every door) and runs on a
# cheap model there. What is left here is the draft.
DRAFT_MODEL = "claude-sonnet-4-5-20250929"

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

logger = logging.getLogger("intake_endpoint")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] intake: %(message)s"
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "")


def get_supabase_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "")


def get_anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def supabase_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: Optional[Dict] = None,
) -> Any:
    """Make a request to the Supabase REST API."""
    url = f"{get_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": get_supabase_anon(),
        "Authorization": f"Bearer {get_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.request(
        method, url, headers=headers,
        content=json.dumps(body) if body else None,
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code >= 400:
        logger.error(f"Supabase {method} {path} failed: {resp.status_code} {resp.text}")
        raise HTTPException(status_code=502, detail=f"Database error: {resp.text}")
    text = resp.text
    return json.loads(text) if text else None


# ═══════════════════════════════════════════════════════════════════════
# AI HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def call_claude(
    client: httpx.AsyncClient,
    system: str,
    user_msg: str,
    model: str,
    max_tokens: int = 1500,
) -> str:
    """Call Anthropic directly (we're already server-side)."""
    api_key = get_anthropic_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    resp = await llm_call.apost(
        client,
        {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=HTTP_TIMEOUT,
        key=api_key,
    )

    if resp.status_code >= 400:
        logger.error(f"Anthropic error: {resp.status_code} {resp.text}")
        # Don't fail the whole submission — degrade gracefully
        return ""

    data = resp.json()
    content = data.get("content", [])
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    ).strip()


def parse_json_from_ai(raw: str) -> Dict:
    """Extract JSON from AI response, handling markdown fencing."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(clean[start:end])
            except json.JSONDecodeError:
                pass
    return {}


# ═══════════════════════════════════════════════════════════════════════
# REQUEST MODEL
# ═══════════════════════════════════════════════════════════════════════

class IntakeSubmission(BaseModel):
    form_id: str
    business_id: str
    data: Dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["intake"])


# ═══════════════════════════════════════════════════════════════════════
# MODULE ROUTING HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _render_template(template, submission, contact_id=None):
    """Substitute {{key}} with submission[key]. Unmatched placeholders stay put.
    Non-string values pass through unchanged."""
    if not isinstance(template, str) or "{{" not in template:
        return template
    out = template
    for k, v in (submission or {}).items():
        out = out.replace("{{" + str(k) + "}}", "" if v is None else str(v))
    if contact_id:
        out = out.replace("{{contact_id}}", str(contact_id))
    return out


def _map_submission_to_module_data(submission, field_map, module_schema, contact_id=None):
    """Build module_entries.data from an intake submission.

    Order of precedence for each module field:
      1. explicit entry in field_map (literal value or {{template}})
      2. direct name match between module field and submission key
      3. skipped

    field_map format:
      {"title": "name"}                 → copy submission["name"] to data["title"]
      {"title": "Interest from {{name}}"} → template substitution
      {"status": "new"}                  → literal (no {{ }} and key not in submission)
    """
    data = {}
    field_map = field_map or {}
    schema_fields = (module_schema or {}).get("fields") or []
    schema_field_names = {f.get("name"): f for f in schema_fields if isinstance(f, dict)}

    for module_field_name in schema_field_names.keys():
        if module_field_name in field_map:
            raw = field_map[module_field_name]
            if isinstance(raw, str) and "{{" in raw:
                data[module_field_name] = _render_template(raw, submission, contact_id)
            elif isinstance(raw, str) and raw in (submission or {}):
                # raw is a pointer to a submission key
                data[module_field_name] = submission[raw]
            else:
                data[module_field_name] = raw
        elif module_field_name in (submission or {}):
            data[module_field_name] = submission[module_field_name]

    # Always attach contact_id if the module has a contact_link field
    for f in schema_fields:
        if isinstance(f, dict) and f.get("type") == "contact_link" and contact_id:
            data[f["name"]] = contact_id
            break

    return data


async def _create_module_entry_from_submission(
    client, business_id, module_id, submission, form_id, contact_id, field_map
):
    """Create a module_entries row from an intake submission. Returns entry id or None."""
    modules = await supabase_request(
        client, "GET",
        f"/custom_modules?id=eq.{module_id}&limit=1&select=*",
    )
    if not modules:
        logger.warning(f"linked_module_id {module_id} not found for form {form_id}")
        return None
    module = modules[0]
    if not module.get("is_active", True):
        logger.info(f"Skipping inactive module {module_id}")
        return None

    data = _map_submission_to_module_data(
        submission, field_map, module.get("schema"), contact_id=contact_id,
    )

    inserted = await supabase_request(client, "POST", "/module_entries", {
        "module_id": module_id,
        "business_id": business_id,
        "data": data,
        "status": "active",
        "created_by": "intake_form",
        "source": "intake_form",
        "source_form_id": form_id,
    })
    entry_id = inserted[0]["id"] if (inserted and isinstance(inserted, list)) else None
    if entry_id:
        await supabase_request(client, "POST", "/events", {
            "business_id": business_id,
            "contact_id": contact_id,
            "event_type": "module_entry_from_intake",
            "data": {
                "module_id": module_id,
                "entry_id": entry_id,
                "form_id": form_id,
            },
            "source": "intake_form",
        })
        logger.info(f"Created module_entry {entry_id} in module {module_id} from form {form_id}")
    return entry_id


def _route_condition_matches(route, submission):
    """A route fires when submission[route.field] == route.value (stringified)."""
    field = route.get("field")
    want = route.get("value")
    if not field:
        return False
    got = (submission or {}).get(field)
    # Support booleans, strings, and numbers — compare as strings
    return str(got).lower() == str(want).lower() if got is not None else False


@router.post("/intake/submit")
async def submit_intake(req: IntakeSubmission, request: Request):
    """
    Receive a form submission, create a contact, score with AI,
    draft a response, and queue it for approval.
    """
    if not get_supabase_url() or not get_supabase_anon():
        raise HTTPException(status_code=500, detail="SUPABASE_URL and SUPABASE_ANON must be set")

    # Arc 29 — abuse gates (anon endpoint; runs before any AI/DB write).
    #
    # The LAST X-Forwarded-For hop, not the first. Railway appends the
    # peer it actually observed, so the last entry is the one nobody
    # upstream chose; the first is whatever the caller put in the header.
    # This is an anonymous endpoint that spends money on AI, so the
    # limiter has to be a control rather than a courtesy — and a control
    # keyed on an attacker-supplied string is neither.
    client_ip = rate_limit.trusted_client_ip(request)
    if not _intake_rate_ok(client_ip):
        logger.warning(f"[intake] rate-limited ip={client_ip}")
        raise HTTPException(status_code=429, detail="Too many submissions — please wait a minute and try again.")

    submission_data = req.data
    # Honeypot: a hidden field bots fill and humans never see. Forms may
    # include any of these names; if one arrives non-empty, drop silently
    # (200 so the bot gets no signal) without creating a contact or
    # spending an AI call.
    for hp in ("_hp", "website_url", "company_url", "fax"):
        if str(submission_data.get(hp) or "").strip():
            logger.info(f"[intake] honeypot tripped ({hp}) ip={client_ip} — dropped")
            return {"status": "ok", "contact_id": None, "queued": False}

    name = submission_data.get("name", "").strip()
    email = submission_data.get("email", "").strip()
    phone = submission_data.get("phone", "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    async with httpx.AsyncClient() as client:

        # ── 1. Fetch form config ──────────────────────────────────────
        forms = await supabase_request(
            client, "GET",
            f"/intake_forms?id=eq.{req.form_id}&select=*&limit=1",
        )
        form_config = forms[0] if forms else None
        if not form_config:
            raise HTTPException(status_code=404, detail="Form not found")

        # Validate required fields
        fields = form_config.get("fields", [])
        for field in fields:
            if field.get("required") and not submission_data.get(field["name"]):
                raise HTTPException(
                    status_code=400,
                    detail=f"Required field missing: {field.get('label', field['name'])}",
                )

        # ── 2. Fetch business for voice profile ───────────────────────
        businesses = await supabase_request(
            client, "GET",
            f"/businesses?id=eq.{req.business_id}&select=*&limit=1",
        )
        business = businesses[0] if businesses else None
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")

        voice_profile = business.get("voice_profile", {})
        business_type = business.get("type", "general")
        business_name = business.get("name", "")

        # ── 3. Create contact ─────────────────────────────────────────
        contact_payload = {
            "business_id": req.business_id,
            "name": name,
            "email": email or None,
            "phone": phone or None,
            "role": submission_data.get("role") or submission_data.get("organization") or None,
            "status": "lead",
            "source": "intake_form",
            "metadata": {
                "form_id": req.form_id,
                "form_type": form_config.get("form_type", "general"),
                "submission": submission_data,
            },
            "last_interaction": "now()",
        }
        # Remove the now() hack — Supabase REST doesn't support SQL functions in values
        contact_payload.pop("last_interaction")

        contacts = await supabase_request(client, "POST", "/contacts", contact_payload)
        contact = contacts[0] if contacts else None
        if not contact:
            raise HTTPException(status_code=500, detail="Failed to create contact")

        contact_id = contact["id"]
        logger.info(f"Created contact {contact_id}: {name} ({email})")

        # ── 4. Log event ──────────────────────────────────────────────
        await supabase_request(client, "POST", "/events", {
            "business_id": req.business_id,
            "contact_id": contact_id,
            "event_type": "form_submit",
            "data": {
                "form_id": req.form_id,
                "form_name": form_config.get("name", ""),
                "form_type": form_config.get("form_type", ""),
                "submission": submission_data,
            },
            "source": "intake_form",
        })

        # ── 4b. Route to custom module(s) ─────────────────────────────
        # Two paths:
        #   settings.linked_module_id  → every submission creates one module entry
        #   settings.field_routes      → per-rule routing based on field values
        module_entries_created = []
        settings = form_config.get("settings") or {}

        linked_module_id = settings.get("linked_module_id")
        if linked_module_id:
            try:
                entry_id = await _create_module_entry_from_submission(
                    client, req.business_id, linked_module_id,
                    submission_data, req.form_id, contact_id,
                    settings.get("field_map") or {},
                )
                if entry_id:
                    module_entries_created.append({"module_id": linked_module_id, "entry_id": entry_id})
            except Exception as e:
                logger.exception(f"linked_module routing failed: {e}")

        for route in (settings.get("field_routes") or []):
            try:
                if not _route_condition_matches(route, submission_data):
                    continue
                target_module_id = route.get("create_module_entry")
                if not target_module_id:
                    continue
                entry_id = await _create_module_entry_from_submission(
                    client, req.business_id, target_module_id,
                    submission_data, req.form_id, contact_id,
                    route.get("map_fields") or {},
                )
                if entry_id:
                    module_entries_created.append({"module_id": target_module_id, "entry_id": entry_id})
            except Exception as e:
                logger.exception(f"field_routes rule failed: {e}")

        # ── 5. Score the lead ─────────────────────────────────────────
        # One rubric, shared with every other capture door (lead_scoring).
        # This used to be a bespoke prompt here — the only place in the
        # backend that ever wrote contacts.lead_score, which is why the
        # hot-lead alert, the Hot Leads list, Chief's briefing and the
        # proposal agent could only ever see intake-form leads.
        #
        # Awaited rather than backgrounded HERE, unlike the other doors:
        # the draft below reads the score, and this endpoint is already
        # blocking on an LLM call for that draft.
        submission_summary = "\n".join(
            f"- {k}: {v}" for k, v in submission_data.items() if v
        )
        scored = await asyncio.to_thread(
            lead_scoring.score_and_store,
            req.business_id, contact_id, submission_data,
            source="intake_form", email=email, phone=phone,
            business_name=business_name, business_type=business_type,
        )
        lead_score = scored.score
        score_reasoning = scored.reasoning
        response_type = scored.response_type
        priority = scored.priority
        logger.info(f"Scored contact {contact_id}: {lead_score} ({priority})")

        # ── 7. AI: Draft response ─────────────────────────────────────
        draft_subject = f"Thanks for reaching out, {name}!"
        draft_body = f"Hi {name},\n\nThank you for your interest. We'll be in touch soon.\n\nBest regards,\n{business_name}"
        draft_reasoning = score_reasoning

        if get_anthropic_key():
            tone = voice_profile.get("tone", "professional and warm")
            personality = voice_profile.get("personality", "helpful")
            audience = voice_profile.get("audience", "clients")

            draft_system = f"""You are the Intake Agent for {business_name}.
Write a personalized email response to a new form submission.

Business voice: tone is "{tone}", personality is "{personality}", audience is "{audience}".
Business type: {business_type}
Response type: {response_type}

Guidelines by response_type — the shape of the reply, not the trade.
A church visitor and a new gym member both want `welcome`; a consulting
prospect and a roofing estimate both want `book_time`:
- welcome: Warm, inviting. Thank them for connecting. Name the next step
  (a visit, a call, an event) in their words, not in industry language.
- book_time: Direct and glad to hear from them. Propose a specific time
  to talk, and say what you will cover.
- answer_then_offer: They asked something concrete. Answer that first,
  in the first two lines. Only then offer the next step.
- nurture: Light touch. Acknowledge interest. No hard sell.

RESPOND ONLY WITH VALID JSON:
{{
  "subject": "Email subject line",
  "body": "Full email body with greeting and sign-off. Use the business owner's name at the end."
}}"""

            draft_msg = f"Submission from {name} ({email or 'no email'}):\n{submission_summary}\n\nLead score: {lead_score}\nResponse type: {response_type}"

            draft_raw = await call_claude(client, draft_system, draft_msg, DRAFT_MODEL, 1000)
            if draft_raw:
                draft_json = parse_json_from_ai(draft_raw)
                draft_subject = draft_json.get("subject", draft_subject)
                draft_body = draft_json.get("body", draft_body)

        # ── 8. Insert into agent_queue ────────────────────────────────
        await supabase_request(client, "POST", "/agent_queue", {
            "business_id": req.business_id,
            "contact_id": contact_id,
            "agent": "intake",
            "action_type": "email" if email else "follow_up",
            "subject": draft_subject,
            "body": draft_body,
            "channel": "email" if email else "in_app",
            "status": "draft",
            "priority": priority,
            "ai_reasoning": f"Lead score: {lead_score}/100. {score_reasoning}",
            "ai_model": DRAFT_MODEL,
        })

        logger.info(
            f"Intake complete: contact={contact_id} score={lead_score} "
            f"priority={priority} response_type={response_type}"
        )

        return {
            "success": True,
            "contact_id": contact_id,
            "lead_score": lead_score,
            "priority": priority,
            "module_entries_created": module_entries_created,
        }


@router.get("/intake/health")
async def intake_health():
    """Liveness probe."""
    return {
        "status": "ok",
        "supabase_configured": bool(get_supabase_url()),
        "anthropic_configured": bool(get_anthropic_key()),
    }
