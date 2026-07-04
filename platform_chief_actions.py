"""
platform_chief_actions.py — Action handlers for the Platform Chief.

The Platform Chief can embed [ACTION:{...}] tags in its replies (same
pattern as the practitioner Chief). This module:

  1. Extracts every tag from a Chief reply.
  2. Dispatches each one to a handler.
  3. Logs every dispatch to chief_actions (success + error paths).
  4. Returns a list of typed result rows the frontend renders as cards.

═══════════════════════════════════════════════════════════════════════
ACTION VOCABULARY (this pass)
═══════════════════════════════════════════════════════════════════════

  extend_trial
      {"type":"extend_trial", "business_id":"...", "days":14, "reason":"..."}

  resend_invite
      {"type":"resend_invite", "lead_id":"...", "reason":"..."}

  send_practitioner_email
      {"type":"send_practitioner_email",
       "business_id":"...", "subject":"...", "body":"...",
       "reason":"..."}

  mark_lead_status
      {"type":"mark_lead_status", "lead_id":"...",
       "status":"contacted"|"qualified"|"declined"|"archived",
       "note":"..."}

Every handler returns a dict with at minimum:
    {"ok": bool, "label": "human-friendly one-liner", ...}

The "label" is what the frontend shows on the action card.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL


logger = logging.getLogger("platform_chief_actions")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] chief-action: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)

# Greedy "[ACTION:" then capture everything up to the matching closing
# bracket. Chief's JSON payloads can contain nested objects + escaped
# quotes; we lean on json.loads to tell us if a candidate is well-formed
# rather than counting braces in regex.
_ACTION_RE = re.compile(r"\[ACTION:\s*(\{.*?\})\s*\]", re.DOTALL)


def extract_actions(text: str) -> List[Dict[str, Any]]:
    """Pull every [ACTION:{...}] tag out of a Chief reply. Tolerates
    malformed JSON by skipping (with a log) rather than failing the
    whole turn."""
    out: List[Dict[str, Any]] = []
    if not text:
        return out
    for match in _ACTION_RE.finditer(text):
        raw = match.group(1)
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("type"):
                out.append(obj)
            else:
                logger.warning(f"Action tag missing 'type' field; skipping: {raw[:100]}")
        except json.JSONDecodeError as e:
            logger.warning(f"Malformed action JSON; skipping: {e} | {raw[:120]}")
    return out


def strip_action_tags(text: str) -> str:
    """Remove every [ACTION:...] tag so the reply Chief presents to the
    operator doesn't show the raw JSON."""
    return _ACTION_RE.sub("", text or "").strip()


# ─── Logging ───────────────────────────────────────────────────────────

async def _log_action(
    *,
    action_type: str,
    payload: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    ok: bool = True,
    error: Optional[str] = None,
    business_id: Optional[str] = None,
    user_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    triggered_by_message: Optional[str] = None,
    chief_reply_excerpt: Optional[str] = None,
) -> None:
    """Insert one row into chief_actions. Never raises — losing an
    audit row beats failing a Chief turn."""
    headers = _service_headers()
    body: Dict[str, Any] = {
        "action_type":           action_type,
        "payload":               payload,
        "ok":                    ok,
        "result":                result or {},
    }
    if business_id: body["business_id"] = business_id
    if user_id:     body["user_id"] = user_id
    if lead_id:     body["lead_id"] = lead_id
    if error:       body["error"] = str(error)[:500]
    if triggered_by_message:  body["triggered_by_message"] = triggered_by_message[:1000]
    if chief_reply_excerpt:   body["chief_reply_excerpt"] = chief_reply_excerpt[:500]
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(
                f"{SUPABASE_URL}/rest/v1/chief_actions",
                headers={**headers, "Prefer": "return=minimal"},
                json=body,
            )
        if r.status_code >= 400:
            logger.warning(f"chief_actions insert {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"chief_actions insert failed: {e}")


# ─── Handlers ──────────────────────────────────────────────────────────

async def _handler_extend_trial(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Push businesses.trial_ends_at out by `days` days from NOW (or from
    the existing trial_ends_at if it's in the future). Sets subscription_status
    to 'trialing' if not already on a paid plan."""
    biz_id = payload.get("business_id")
    days = int(payload.get("days") or 14)
    if not biz_id:
        return {"ok": False, "label": "Missing business_id", "error": "business_id required"}

    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        # Load current state
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={"id": f"eq.{biz_id}", "select": "id,name,trial_ends_at,subscription_status"},
        )
        if r.status_code >= 400 or not r.json():
            return {"ok": False, "label": "Business not found", "error": r.text[:200]}
        biz = r.json()[0]

        # Anchor: max(now, current trial end)
        now = datetime.now(timezone.utc)
        current = biz.get("trial_ends_at")
        anchor = now
        if current:
            try:
                anchor_dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
                if anchor_dt > now:
                    anchor = anchor_dt
            except Exception:
                pass
        new_end = anchor + timedelta(days=days)

        patch: Dict[str, Any] = {"trial_ends_at": new_end.isoformat()}
        # Don't override an active/paid sub
        if (biz.get("subscription_status") or "") not in ("active", "past_due"):
            patch["subscription_status"] = "trialing"

        pr = await c.patch(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={"id": f"eq.{biz_id}"},
            json=patch,
        )
        if pr.status_code >= 400:
            return {"ok": False, "label": "Failed to extend trial", "error": pr.text[:200]}

    return {
        "ok": True,
        "label": f"Extended {biz.get('name','business')}'s trial by {days} days (now ends {new_end.date()})",
        "business_id": biz_id,
        "business_name": biz.get("name"),
        "new_trial_ends_at": new_end.isoformat(),
    }


async def _handler_resend_invite(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Re-trigger the Supabase Auth invite for a marketing_lead row.
    Reuses /auth/v1/invite (same as lead_admin.approve_lead)."""
    lead_id = payload.get("lead_id")
    if not lead_id:
        return {"ok": False, "label": "Missing lead_id", "error": "lead_id required"}

    headers = _service_headers()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        # Load lead
        lr = await c.get(
            f"{SUPABASE_URL}/rest/v1/marketing_leads",
            headers=headers,
            params={"id": f"eq.{lead_id}", "select": "*"},
        )
        if lr.status_code >= 400 or not lr.json():
            return {"ok": False, "label": "Lead not found", "error": lr.text[:200]}
        lead = lr.json()[0]
        email = lead.get("email")
        if not email:
            return {"ok": False, "label": "Lead has no email"}

        # Send invite via Supabase Auth Admin
        invite_body = {
            "email": email,
            "data": {
                "lead_id": lead_id,
                "name": lead.get("name"),
                "resent": True,
            },
        }
        redirect = os.environ.get("APP_REDIRECT_URL", "https://mysolutionist.app/welcome")
        if redirect:
            invite_body["redirect_to"] = redirect

        ir = await c.post(
            f"{SUPABASE_URL}/auth/v1/invite",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json=invite_body,
        )
        if ir.status_code >= 400:
            return {
                "ok": False,
                "label": f"Supabase invite rejected ({ir.status_code})",
                "error": ir.text[:200],
            }

    return {
        "ok": True,
        "label": f"Re-sent invite to {email}",
        "lead_id": lead_id,
        "email": email,
    }


async def _handler_send_practitioner_email(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a transactional email to a business's practitioner via Resend.
    Looks up the practitioner email via business.owner_id → auth.users."""
    biz_id = payload.get("business_id")
    subject = payload.get("subject")
    body = payload.get("body")
    if not biz_id or not subject or not body:
        return {"ok": False, "label": "Missing business_id / subject / body"}

    headers = _service_headers()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        # Find business + owner
        br = await c.get(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={"id": f"eq.{biz_id}", "select": "id,name,owner_id"},
        )
        if br.status_code >= 400 or not br.json():
            return {"ok": False, "label": "Business not found"}
        biz = br.json()[0]
        owner_id = biz.get("owner_id")
        if not owner_id:
            return {"ok": False, "label": "Business has no owner_id"}

        # Look up owner email via Auth Admin
        ur = await c.get(
            f"{SUPABASE_URL}/auth/v1/admin/users/{owner_id}",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
        )
        if ur.status_code >= 400:
            return {"ok": False, "label": "Owner not found in auth.users"}
        owner_email = ur.json().get("email")
        if not owner_email:
            return {"ok": False, "label": "Owner has no email"}

    # Send via the email_sender router we already deploy
    try:
        from email_sender import send_via_resend
        await send_via_resend(
            to_email=owner_email,
            to_name=biz.get("name"),
            from_email=os.environ.get("RESEND_FROM_EMAIL", "noreply@mysolutionist.app"),
            from_name="Solutionist System",
            subject=subject,
            body=body,
            reply_to=os.environ.get("PLATFORM_OWNER_EMAIL", "kmjcreativesolution@gmail.com"),
        )
    except Exception as e:
        return {"ok": False, "label": "Resend send failed", "error": str(e)[:200]}

    return {
        "ok": True,
        "label": f"Emailed {owner_email} — \"{subject[:60]}\"",
        "business_id": biz_id,
        "business_name": biz.get("name"),
        "email": owner_email,
        "subject": subject,
    }


async def _handler_mark_lead_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bump a marketing_leads.status. Optionally appends a note."""
    lead_id = payload.get("lead_id")
    new_status = payload.get("status")
    note = payload.get("note")
    valid = {"new", "contacted", "qualified", "onboarded", "declined", "archived"}
    if not lead_id or new_status not in valid:
        return {"ok": False, "label": f"Invalid status (must be one of {sorted(valid)})"}

    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        # Fetch existing note so we can append
        existing_notes = ""
        if note:
            lr = await c.get(
                f"{SUPABASE_URL}/rest/v1/marketing_leads",
                headers=headers,
                params={"id": f"eq.{lead_id}", "select": "notes,name"},
            )
            if lr.status_code < 400 and lr.json():
                existing_notes = (lr.json()[0] or {}).get("notes") or ""
                lead_name = lr.json()[0].get("name", "(unnamed)")
            else:
                lead_name = "(unknown)"
        else:
            lead_name = "(unnamed)"

        patch: Dict[str, Any] = {"status": new_status}
        if note:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            line = f"[{stamp}] (Chief) {note.strip()}"
            patch["notes"] = f"{line}\n\n{existing_notes}" if existing_notes else line

        pr = await c.patch(
            f"{SUPABASE_URL}/rest/v1/marketing_leads",
            headers=headers,
            params={"id": f"eq.{lead_id}"},
            json=patch,
        )
        if pr.status_code >= 400:
            return {"ok": False, "label": "Update failed", "error": pr.text[:200]}

    return {
        "ok": True,
        "label": f"Marked {lead_name} as {new_status}" + (f" — \"{note[:60]}\"" if note else ""),
        "lead_id": lead_id,
        "new_status": new_status,
    }


# ─── Operator log (the Business Chief's memory of the business) ───────
# Kevin's ruling 2026-07-04: he WILL forget changes — Chief is the
# keeper of record. These two actions let Chief write/resolve entries
# in platform_changelog; every snapshot reads the log back.

_VALID_LOG_CATEGORIES = {"shipped", "config", "decision", "pending", "note"}


async def _handler_log_platform_note(action: Dict[str, Any]) -> Dict[str, Any]:
    title = (action.get("title") or "").strip()
    if not title:
        return {"ok": False, "label": "Log entry needs a title", "error": "missing title"}
    category = (action.get("category") or "note").strip().lower()
    if category not in _VALID_LOG_CATEGORIES:
        category = "note"
    status = "pending" if category == "pending" else \
             ("pending" if (action.get("status") or "").lower() == "pending" else "done")
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(
            f"{SUPABASE_URL}/rest/v1/platform_changelog",
            headers=headers,
            json={
                "category": category,
                "title": title[:300],
                "detail": (action.get("detail") or "").strip()[:2000] or None,
                "status": status,
            },
        )
        if r.status_code >= 400:
            return {"ok": False, "label": "Log write failed — is the platform-changelog migration applied?",
                    "error": r.text[:200]}
        rows = r.json() if r.text else []
        note_id = (rows[0].get("id") if isinstance(rows, list) and rows else None)
    return {"ok": True,
            "label": f"Logged [{category}] {title[:80]}" + (" (pending)" if status == "pending" else ""),
            "note_id": note_id}


async def _handler_resolve_platform_note(action: Dict[str, Any]) -> Dict[str, Any]:
    note_id = action.get("note_id")
    if not note_id:
        return {"ok": False, "label": "Which entry? note_id required", "error": "missing note_id"}
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/platform_changelog",
            headers=headers,
            params={"id": f"eq.{note_id}"},
            json={"status": "done",
                  "resolved_at": datetime.now(timezone.utc).isoformat()},
        )
        if r.status_code >= 400:
            return {"ok": False, "label": "Resolve failed", "error": r.text[:200]}
    return {"ok": True, "label": f"Marked entry #{note_id} done"}


# ─── Dispatcher ────────────────────────────────────────────────────────

HANDLERS = {
    "extend_trial":            _handler_extend_trial,
    "resend_invite":           _handler_resend_invite,
    "send_practitioner_email": _handler_send_practitioner_email,
    "mark_lead_status":        _handler_mark_lead_status,
    "log_platform_note":       _handler_log_platform_note,
    "resolve_platform_note":   _handler_resolve_platform_note,
}


async def dispatch_actions(
    actions: List[Dict[str, Any]],
    *,
    triggered_by_message: Optional[str] = None,
    chief_reply_excerpt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run every action sequentially. Each result is logged. Returns
    the list of result dicts (same length as input)."""
    results: List[Dict[str, Any]] = []
    for action in actions:
        act_type = action.get("type", "")
        handler = HANDLERS.get(act_type)
        if not handler:
            res = {"ok": False, "label": f"Unknown action: {act_type}", "type": act_type}
            results.append(res)
            await _log_action(
                action_type=act_type or "unknown", payload=action, result=res,
                ok=False, error=f"unknown handler: {act_type}",
                triggered_by_message=triggered_by_message,
                chief_reply_excerpt=chief_reply_excerpt,
            )
            continue
        try:
            res = await handler(action)
        except Exception as e:
            logger.exception(f"Handler {act_type} crashed")
            res = {"ok": False, "label": f"Handler crashed: {e}", "type": act_type, "error": str(e)}
        res["type"] = act_type
        results.append(res)
        await _log_action(
            action_type=act_type,
            payload=action,
            result=res,
            ok=bool(res.get("ok")),
            error=res.get("error") if not res.get("ok") else None,
            business_id=action.get("business_id"),
            lead_id=action.get("lead_id"),
            user_id=action.get("user_id"),
            triggered_by_message=triggered_by_message,
            chief_reply_excerpt=chief_reply_excerpt,
        )
    return results
