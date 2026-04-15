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
    4. AI scores the lead (0-100)
    5. AI drafts a personalized response
    6. Insert draft into agent_queue for approval
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Models — same as ai_proxy.py
SCORE_MODEL = "claude-sonnet-4-5-20250929"
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

    resp = await client.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=HTTP_TIMEOUT,
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
async def submit_intake(req: IntakeSubmission):
    """
    Receive a form submission, create a contact, score with AI,
    draft a response, and queue it for approval.
    """
    if not get_supabase_url() or not get_supabase_anon():
        raise HTTPException(status_code=500, detail="SUPABASE_URL and SUPABASE_ANON must be set")

    submission_data = req.data
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

        # ── 5. AI: Score the lead ─────────────────────────────────────
        lead_score = 50  # default if AI fails
        score_reasoning = "Default score — AI scoring unavailable"
        response_type = "general"
        priority = "medium"

        if get_anthropic_key():
            score_system = f"""You are a lead scoring agent for {business_name}, a {business_type} business.

Score this intake form submission from 0-100 based on:
- Completeness: how many fields did they fill out vs leave blank?
- Engagement signals: did they write detailed responses or minimal ones?
- Match: does this person match the target audience? (Voice profile: {json.dumps(voice_profile)})
- Intent: are they ready to engage or just browsing?

Also determine:
- response_type: "warm_welcome" (church/ministry visitor), "discovery_invite" (coaching/consulting prospect ready to talk), "info_send" (early-stage, send capabilities overview), "nurture" (low intent, add to drip)
- priority: "high" (score 70+), "medium" (40-69), "low" (under 40)

RESPOND ONLY WITH VALID JSON:
{{
  "score": 75,
  "reasoning": "why you scored this way — be specific about the signals",
  "response_type": "discovery_invite",
  "priority": "high"
}}"""

            submission_summary = "\n".join(
                f"- {k}: {v}" for k, v in submission_data.items() if v
            )
            score_msg = f"Form type: {form_config.get('form_type', 'general')}\nSubmission:\n{submission_summary}"

            score_raw = await call_claude(client, score_system, score_msg, SCORE_MODEL, 500)
            if score_raw:
                score_json = parse_json_from_ai(score_raw)
                lead_score = max(0, min(100, int(score_json.get("score", 50))))
                score_reasoning = score_json.get("reasoning", score_reasoning)
                response_type = score_json.get("response_type", response_type)
                priority = score_json.get("priority", priority)

            logger.info(f"Scored contact {contact_id}: {lead_score} ({priority})")

        # ── 6. Update contact with score ──────────────────────────────
        await supabase_request(
            client, "PATCH",
            f"/contacts?id=eq.{contact_id}",
            {"lead_score": lead_score, "health_score": min(lead_score + 10, 100)},
        )

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

Guidelines by response_type:
- warm_welcome: Warm, inviting. Thank them for connecting. Mention next steps (visit, call, event).
- discovery_invite: Professional, enthusiastic. Propose a brief discovery call. Mention specific value.
- info_send: Informative, no pressure. Share what you do. Include a soft CTA.
- nurture: Light touch. Acknowledge interest. No hard sell. Offer a resource.

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
            "ai_model": SCORE_MODEL,
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
