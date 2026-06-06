"""
terminology_overrides_router.py — Phase VABI v1.5.

Practitioner-facing CRUD for per-business terminology +
vertical_intelligence overrides. Backs:
  - BUILD → Settings → Terminology page (B3)
  - The lookup chain that promotes practitioner-authored terms above
    the vertical defaults (B2 + B3 share the same column)

Endpoints (owner-gated):
  GET   /terminology/overrides?business_id=...
        Returns the current overrides + the effective resolved
        dictionary the UI would render. Single source of truth.
  PATCH /terminology/overrides
        Body: { business_id, terminology?: {...}, vertical_intelligence?: {...} }
        Merges into the existing JSONB (NOT replace). Setting a key
        to null removes it (lookup falls back to vertical/BASE).
  POST  /terminology/overrides/reset
        Body: { business_id, scope: 'terminology' | 'vertical_intelligence' | 'all' }
        Clears overrides — falls back to vertical defaults.

Read path used by the frontend useTerm() hook is the existing
GET /intelligence/vertical?business_id=... + this override layer
applied. Frontend merges client-side.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
from vertical_terminology import BASE_TERMS, VERTICAL_TERMS

logger = logging.getLogger("terminology_overrides_router")

router = APIRouter(prefix="/terminology", tags=["terminology"])


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,type&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _get_or_create_profile(business_id: str) -> Dict[str, Any]:
    """Profile row lazy-creates if missing so override writes never
    fail on a not-yet-onboarded business."""
    rows = sb_clients.sb_get_as_service(
        f"/business_profiles?business_id=eq.{business_id}&limit=1"
    ) or []
    if rows:
        return rows[0]
    created = sb_clients.sb_post_as_service("/business_profiles", {
        "business_id": business_id,
        "terminology_overrides": {},
        "vertical_intelligence_overrides": {},
    })
    if isinstance(created, list) and created:
        return created[0]
    # Surface the failure but don't 500; downstream GETs will see
    # the empty default.
    return {
        "business_id": business_id,
        "terminology_overrides": {},
        "vertical_intelligence_overrides": {},
    }


# ─── Read ────────────────────────────────────────────────────────────


@router.get("/overrides")
def get_overrides(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz = _require_owner(business_id, user)
    profile = _get_or_create_profile(business_id)
    overrides = profile.get("terminology_overrides") or {}
    vi_overrides = profile.get("vertical_intelligence_overrides") or {}

    # Build the effective dictionary the UI renders.
    bt = (biz.get("type") or "").lower().strip()
    vertical = VERTICAL_TERMS.get(bt) or {}
    effective = {**BASE_TERMS, **vertical, **overrides}

    return {
        "ok": True,
        "business_id": business_id,
        "business_type": bt or None,
        "terminology_overrides": overrides,
        "vertical_intelligence_overrides": vi_overrides,
        "effective_terms": effective,
    }


# ─── Write ───────────────────────────────────────────────────────────


class OverridePatchBody(BaseModel):
    business_id: str
    terminology: Optional[Dict[str, Any]] = None
    vertical_intelligence: Optional[Dict[str, Any]] = None


@router.patch("/overrides")
def patch_overrides(
    body: OverridePatchBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(body.business_id, user)
    profile = _get_or_create_profile(body.business_id)

    cur_term = dict(profile.get("terminology_overrides") or {})
    cur_vi = dict(profile.get("vertical_intelligence_overrides") or {})

    # Merge: null values delete the key; non-null replace.
    if body.terminology is not None:
        for k, v in body.terminology.items():
            if v is None:
                cur_term.pop(k, None)
            else:
                cur_term[str(k)] = str(v)
    if body.vertical_intelligence is not None:
        for k, v in body.vertical_intelligence.items():
            if v is None:
                cur_vi.pop(k, None)
            else:
                cur_vi[str(k)] = v

    sb_clients.sb_patch_as_service(
        f"/business_profiles?business_id=eq.{body.business_id}",
        {
            "terminology_overrides": cur_term,
            "vertical_intelligence_overrides": cur_vi,
        },
    )
    return {
        "ok": True,
        "terminology_overrides": cur_term,
        "vertical_intelligence_overrides": cur_vi,
    }


class OverrideResetBody(BaseModel):
    business_id: str
    scope: str = "all"   # 'terminology' | 'vertical_intelligence' | 'all'


@router.post("/overrides/reset")
def reset_overrides(
    body: OverrideResetBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(body.business_id, user)
    _get_or_create_profile(body.business_id)

    patch: Dict[str, Any] = {}
    if body.scope in ("terminology", "all"):
        patch["terminology_overrides"] = {}
    if body.scope in ("vertical_intelligence", "all"):
        patch["vertical_intelligence_overrides"] = {}
    if not patch:
        raise HTTPException(400, "scope must be 'terminology', 'vertical_intelligence', or 'all'")

    sb_clients.sb_patch_as_service(
        f"/business_profiles?business_id=eq.{body.business_id}",
        patch,
    )
    return {"ok": True, "reset": list(patch.keys())}


# ─── Chief-driven dynamic generation for unmapped verticals (B2) ────


class GenerateBody(BaseModel):
    business_id: str
    # Optional one-line hint from the practitioner to nudge Chief.
    hint: Optional[str] = None


@router.post("/overrides/generate")
async def generate_overrides_via_chief(
    body: GenerateBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Chief proposes terminology overrides for an unmapped vertical.
    The proposal is RETURNED (not auto-applied) so the practitioner
    reviews + edits before saving.

    Used when business.type is outside the 10 mapped verticals (agency,
    ecommerce, custom, write-in, etc.). The frontend Settings →
    Terminology page surfaces a "Suggest from Chief" button that calls
    this endpoint and pre-populates the editor with the response."""
    biz = _require_owner(body.business_id, user)
    business_type = biz.get("type") or ""
    business_name = ""
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{body.business_id}&select=name&limit=1"
    ) or []
    if biz_rows:
        business_name = biz_rows[0].get("name") or ""

    # The 12 terms in scope for v1.5 (matches BASE_TERMS keys that
    # frequently appear in vertical-sensitive UI).
    target_terms = [
        "customer", "customers", "client", "clients",
        "service", "services", "appointment", "appointments",
        "booking", "bookings", "invoice", "invoices",
        "session", "sessions", "offering", "offerings",
        "member",
    ]

    prompt = (
        f"You are calibrating practitioner-facing vocabulary for a business.\n"
        f"Business name: {business_name or '(unknown)'}\n"
        f"Business type: {business_type or '(unset/unknown)'}\n"
        + (f"Practitioner hint: {body.hint!r}\n" if body.hint else "")
        + f"\nReturn JSON only — one object whose keys are these vocabulary\n"
        f"terms and whose values are the right word for this business:\n"
        f"{target_terms}\n\n"
        f"Rules:\n"
        f"- Use Title Case singular for singular keys, plural Title Case for plural keys.\n"
        f"- 'customer' and 'client' may be the same word if the business has only one concept; same for 'customers'/'clients'.\n"
        f"- If you genuinely don't know the right word, return the generic baseline\n"
        f"  (Customer, Customers, Client, Clients, Service, Services, etc.).\n"
        f"- Do not invent jargon. Real-world vocabulary only.\n"
    )

    # Use the existing AI proxy if available; defensive in case
    # not configured. Don't 500 on AI failure — return generic.
    proposed: Dict[str, str] = {}
    try:
        import os
        import json as _json
        import httpx
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 800,
                        "system": "Return only valid JSON, no prose.",
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            if resp.status_code < 400:
                data = resp.json()
                content_blocks = data.get("content") or []
                txt = ""
                for blk in content_blocks:
                    if blk.get("type") == "text":
                        txt = blk.get("text") or ""
                        break
                # Strip code fences if Claude wrapped it.
                txt = txt.strip()
                if txt.startswith("```"):
                    txt = txt.strip("`")
                    # Trim a leading 'json\n' if present.
                    if txt.startswith("json"):
                        txt = txt[4:].lstrip()
                try:
                    parsed = _json.loads(txt)
                    if isinstance(parsed, dict):
                        # Only keep keys we asked for + non-empty string values.
                        for k in target_terms:
                            v = parsed.get(k)
                            if isinstance(v, str) and v.strip():
                                proposed[k] = v.strip()
                except Exception as e:
                    logger.warning(f"chief-overrides JSON parse failed: {e}")
    except Exception as e:
        logger.warning(f"chief-overrides generation failed (non-fatal): {e}")

    return {
        "ok": True,
        "business_type": business_type,
        "proposed_terminology": proposed,
        "note": (
            "Review and edit, then save via PATCH /terminology/overrides."
            if proposed else
            "Could not generate — fill terms manually or keep defaults."
        ),
    }
