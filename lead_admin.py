"""
lead_admin.py — Marketing-leads admin endpoints (Phase 4 of AUTH_PLAN).

Lets the platform owner (Kevin) triage `marketing_leads` rows from the
Settings → Leads panel in the app:

    GET    /admin/leads?status=new            → list leads
    POST   /admin/leads/{lead_id}/contacted   → mark contacted
    POST   /admin/leads/{lead_id}/approve     → mint Supabase auth user
                                                + send invite email
                                                + bump status to onboarded
    POST   /admin/leads/{lead_id}/decline     → mark declined (+ note)
    POST   /admin/leads/{lead_id}/notes       → append a note

All endpoints require a Supabase-issued JWT (Bearer header) AND the
caller's email must match PLATFORM_OWNER_EMAIL — anyone else gets 403.

═══════════════════════════════════════════════════════════════════════
ENV VARS REQUIRED
═══════════════════════════════════════════════════════════════════════

    SUPABASE_URL                — https://<ref>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY   — service-role key from Supabase dashboard
                                  → Settings → API. Bypasses RLS, can mint
                                  auth users. NEVER exposed to the client.
    SUPABASE_JWT_SECRET         — already required by auth_supabase.py
    PLATFORM_OWNER_EMAIL        — defaults to kmjcreativesolution@gmail.com
    APP_REDIRECT_URL            — where the invite email's "Accept Invite"
                                  link sends the user. Defaults to
                                  https://mysolutionist.app/welcome.

═══════════════════════════════════════════════════════════════════════
NOTES
═══════════════════════════════════════════════════════════════════════

  • The invite email is sent by Supabase Auth itself using the templates
    in dashboard → Authentication → Email Templates → "Invite User".
    Customize that template before public launch.
  • If the email already has an auth row (e.g. Kevin already signed
    them up manually), the Admin API returns 422 and we surface it as
    a 409 to the client so it can offer "resend invite" instead.
  • Lead → user linkage is recorded on the lead row in
    metadata.auth_user_id for later reconciliation.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth_supabase import AuthedUser, require_user


logger = logging.getLogger("lead_admin")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] leads: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


router = APIRouter(prefix="/admin/leads", tags=["lead-admin"])

# Diagnostic router — public, no auth. Reports WHICH env vars the
# running process sees (presence only — never the values). Lets us
# debug "I set the var on Railway, why isn't it working?" without
# guessing.
diag_router = APIRouter(prefix="/_diag", tags=["diag"])


@diag_router.get("/env")
def diag_env(_user: AuthedUser = Depends(require_user)):
    """Report presence of the env vars the auth + service-role paths
    depend on. Values are NEVER returned — only whether they're set
    and (for the URL) a redacted preview so you can confirm the
    project. LOCKED (Fork #3): authenticated callers only — no longer
    public. Tighten to require_owner if practitioner-level access is too broad."""
    su_url = os.environ.get("SUPABASE_URL", "")
    su_role = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    su_jwt = os.environ.get("SUPABASE_JWT_SECRET", "")
    owner = os.environ.get("PLATFORM_OWNER_EMAIL", "(default)")
    return {
        "SUPABASE_URL": {
            "set": bool(su_url),
            "preview": (su_url[:32] + "…") if su_url else "",
        },
        "SUPABASE_SERVICE_ROLE_KEY": {
            "set": bool(su_role),
            "length": len(su_role) if su_role else 0,
            "starts_with": (su_role[:8] + "…") if su_role else "",
        },
        "SUPABASE_JWT_SECRET": {
            "set": bool(su_jwt),
            "length": len(su_jwt) if su_jwt else 0,
        },
        "PLATFORM_OWNER_EMAIL": owner,
        "STRIPE_SECRET_KEY_set": bool(os.environ.get("STRIPE_SECRET_KEY")),
    }


SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
PLATFORM_OWNER_EMAIL = os.environ.get("PLATFORM_OWNER_EMAIL", "kmjcreativesolution@gmail.com").lower()
APP_REDIRECT_URL = os.environ.get("APP_REDIRECT_URL", "https://mysolutionist.app/welcome")

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)


def require_owner(user: AuthedUser = Depends(require_user)) -> AuthedUser:
    """Allow only the platform owner through. Surface as 403 (not 401)
    so the client can distinguish 'not signed in' from 'signed in but
    not allowed'."""
    email = (user.email or "").lower()
    if email != PLATFORM_OWNER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lead admin access is restricted to the platform owner.",
        )
    return user


def _service_headers() -> Dict[str, str]:
    """Auth headers for PostgREST + Admin API calls. The service-role
    key bypasses RLS so we can read + write any row."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing)",
        )
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


# ─── Pydantic models ────────────────────────────────────────────────────

class Lead(BaseModel):
    id: str
    name: str
    email: str  # validated by Supabase + Auth Admin API; plain str avoids the email-validator pip dep
    role: Optional[str] = None
    what_you_do: Optional[str] = None
    source: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    contacted_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class DeclineBody(BaseModel):
    reason: Optional[str] = None


class NoteBody(BaseModel):
    note: str


class ApproveResponse(BaseModel):
    ok: bool
    auth_user_id: Optional[str] = None
    invited: bool = False
    message: str


# ─── Endpoints ──────────────────────────────────────────────────────────

@router.get("", response_model=List[Lead])
async def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    _owner: AuthedUser = Depends(require_owner),
):
    """List leads, newest first, optionally filtered by status."""
    headers = _service_headers()
    params = {
        "select": "*",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if status_filter:
        params["status"] = f"eq.{status_filter}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/marketing_leads", headers=headers, params=params)
    if r.status_code >= 400:
        logger.error(f"list_leads PostgREST {r.status_code}: {r.text[:300]}")
        raise HTTPException(status_code=r.status_code, detail="Failed to fetch leads")
    return r.json()


async def _patch_lead(lead_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """PATCH the lead row, return the updated representation."""
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/marketing_leads",
            headers=headers,
            params={"id": f"eq.{lead_id}"},
            json=body,
        )
    if r.status_code >= 400:
        logger.error(f"patch_lead PostgREST {r.status_code}: {r.text[:300]}")
        raise HTTPException(status_code=r.status_code, detail="Failed to update lead")
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Lead not found")
    return rows[0]


@router.post("/{lead_id}/contacted", response_model=Lead)
async def mark_contacted(lead_id: str, _owner: AuthedUser = Depends(require_owner)):
    """Bump status to 'contacted' + stamp contacted_at."""
    from datetime import datetime, timezone
    return await _patch_lead(lead_id, {
        "status": "contacted",
        "contacted_at": datetime.now(timezone.utc).isoformat(),
    })


@router.post("/{lead_id}/decline", response_model=Lead)
async def decline_lead(
    lead_id: str,
    body: DeclineBody,
    _owner: AuthedUser = Depends(require_owner),
):
    """Bump status to 'declined'. Reason (if any) prepended to notes."""
    # Fetch the existing note so we can append rather than overwrite
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/marketing_leads",
            headers=headers,
            params={"id": f"eq.{lead_id}", "select": "notes"},
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="Failed to fetch lead")
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Lead not found")

    existing_notes = (rows[0] or {}).get("notes") or ""
    new_notes = existing_notes
    if body.reason:
        prefix = f"[Declined] {body.reason.strip()}"
        new_notes = f"{prefix}\n\n{existing_notes}" if existing_notes else prefix

    return await _patch_lead(lead_id, {
        "status": "declined",
        "notes": new_notes,
    })


@router.post("/{lead_id}/notes", response_model=Lead)
async def add_note(
    lead_id: str,
    body: NoteBody,
    _owner: AuthedUser = Depends(require_owner),
):
    """Append a free-text note to the lead, preserving existing notes."""
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="Note is empty")
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/marketing_leads",
            headers=headers,
            params={"id": f"eq.{lead_id}", "select": "notes"},
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="Failed to fetch lead")
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Lead not found")

    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    existing = (rows[0] or {}).get("notes") or ""
    new_line = f"[{stamp}] {body.note.strip()}"
    new_notes = f"{new_line}\n\n{existing}" if existing else new_line
    return await _patch_lead(lead_id, {"notes": new_notes})


@router.post("/{lead_id}/approve", response_model=ApproveResponse)
async def approve_lead(
    lead_id: str,
    _owner: AuthedUser = Depends(require_owner),
):
    """The headline action. Mints an auth.users row for the lead, sends
    the Supabase-templated invite email, and bumps status to 'onboarded'.

    Failure modes:
      • Service role not configured → 500
      • Lead not found → 404
      • Lead already onboarded → 409 (return existing auth_user_id so UI
        can offer "resend invite" without creating a duplicate user)
      • Supabase Auth Admin returns 422 because the email already exists
        in auth.users → 409 (same)
    """
    headers = _service_headers()

    # 1. Load the lead
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/marketing_leads",
            headers=headers,
            params={"id": f"eq.{lead_id}", "select": "*"},
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="Failed to fetch lead")
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = rows[0]

    if lead.get("status") == "onboarded":
        existing_uid = (lead.get("metadata") or {}).get("auth_user_id")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Lead already onboarded (auth_user_id={existing_uid or 'unknown'})",
        )

    email = lead.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Lead has no email")

    # 2. Send the Supabase invite (creates the auth user if needed).
    #    POST /auth/v1/invite returns { user: { id, email, ... } }.
    invite_headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    invite_body: Dict[str, Any] = {
        "email": email,
        "data": {
            "lead_id": lead_id,
            "name": lead.get("name"),
            "role": lead.get("role"),
            "source": lead.get("source"),
        },
    }
    if APP_REDIRECT_URL:
        invite_body["redirect_to"] = APP_REDIRECT_URL

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        ir = await c.post(
            f"{SUPABASE_URL}/auth/v1/invite",
            headers=invite_headers,
            json=invite_body,
        )

    if ir.status_code in (400, 422):
        # Most common cause: email already exists in auth.users
        msg = ir.text[:300]
        logger.warning(f"invite for {email} rejected {ir.status_code}: {msg}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Supabase rejected invite (likely user already exists): {msg}",
        )
    if ir.status_code >= 400:
        logger.error(f"invite for {email} failed {ir.status_code}: {ir.text[:300]}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Supabase invite failed: {ir.text[:200]}",
        )

    invite_payload = ir.json() if ir.text else {}
    user_obj = (invite_payload.get("user") or invite_payload) if isinstance(invite_payload, dict) else {}
    auth_user_id = user_obj.get("id")

    # 3. Bump the lead: status=onboarded, stamp auth_user_id in metadata
    new_metadata = dict(lead.get("metadata") or {})
    if auth_user_id:
        new_metadata["auth_user_id"] = auth_user_id
    await _patch_lead(lead_id, {
        "status": "onboarded",
        "metadata": new_metadata,
    })

    logger.info(f"Lead {lead_id} approved → invite sent to {email} (auth_user_id={auth_user_id})")
    return ApproveResponse(
        ok=True,
        auth_user_id=auth_user_id,
        invited=True,
        message=f"Invite sent to {email}.",
    )
