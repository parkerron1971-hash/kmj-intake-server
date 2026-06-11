"""
launch_access.py — Arc 19 Phase B — invite-only launch gate, waitlist,
grandfathering, and backend-mediated business creation.

Access model (Kevin's ruling): invite-only/waitlist pre-launch →
14-day-trial pattern post-validation. The HARD gate is server-side at
business creation + invite redemption: an uninvited browser can still
create a bare Supabase auth user, but without an invite (or grandfather
flag) they cannot create a business — they see the waitlist message.
(Belt-and-braces option of disabling public signup in the Supabase
dashboard is documented in the runbook, not required.)

Kill switch: LAUNCH_INVITE_ONLY env (default ON). Flip to "off" when the
trial pattern opens to the public.

Admin endpoints gate on lead_admin.require_owner (platform-owner email),
matching Mission Control. Invite tokens are deliberately a SEPARATE
table from business_collaborators (I.3 PR3) / business_users (E v1.1):
those invite people INTO an existing business; these admit people TO THE
PLATFORM. Same token-link pattern, different lifecycle — no conflict.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
import billing_limits
import usage_metering
from auth_supabase import AuthedUser, require_user
from lead_admin import require_owner

logger = logging.getLogger("launch_access")

router = APIRouter(prefix="/access", tags=["launch_access"])

_APP_BASE = "https://system.mysolutionist.app"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def invite_only() -> bool:
    return (os.environ.get("LAUNCH_INVITE_ONLY") or "on").lower() != "off"


def _profile(user_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/user_profiles?user_id=eq.{user_id}&select=*&limit=1") or []
    return rows[0] if rows else None


def user_admitted(user_id: str) -> bool:
    """Grandfathered OR accepted a platform invite."""
    p = _profile(user_id)
    return bool(p and (p.get("is_grandfathered") or p.get("invited_via_token")))


# ─── Waitlist (public) ───────────────────────────────────────────────

class WaitlistBody(BaseModel):
    email: str
    name: Optional[str] = None


@router.post("/waitlist")
def join_waitlist(body: WaitlistBody) -> Dict[str, Any]:
    email = (body.email or "").strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(400, "valid email required")
    existing = sb_clients.sb_get_as_service(
        f"/waitlist?email=eq.{email}&select=id&limit=1") or []
    if not existing:
        sb_clients.sb_post_as_service("/waitlist", {
            "email": email, "name": (body.name or "").strip()[:120] or None,
        }, prefer=None)
    # Idempotent + non-enumerating: same answer either way.
    return {"ok": True, "message": "You're on the list — we'll email you "
                                   "when your invite is ready."}


# ─── Invite validation + redemption ──────────────────────────────────

def _load_token(token: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/invite_tokens?token=eq.{token}&select=*&limit=1") or []
    return rows[0] if rows else None


def _token_state(inv: Optional[Dict[str, Any]]) -> str:
    if not inv:
        return "invalid"
    if inv.get("status") in ("revoked", "accepted", "expired"):
        return inv["status"]
    if (inv.get("expires_at") or "") < _now_iso():
        return "expired"
    return "pending"


@router.get("/invites/validate")
def validate_invite(token: str) -> Dict[str, Any]:
    """Public — the signup screen asks before showing the form."""
    inv = _load_token(token)
    state = _token_state(inv)
    return {"ok": True, "valid": state == "pending",
            "state": state,
            "email": inv.get("email") if state == "pending" else None}


class RedeemBody(BaseModel):
    token: str


@router.post("/redeem")
def redeem_invite(body: RedeemBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Signed-in user consumes their platform invite (first use wins).
    Marks the profile invited — NOT grandfathered (Kevin's ruling)."""
    inv = _load_token(body.token)
    state = _token_state(inv)
    if state == "accepted" and str(inv.get("accepted_by_user_id")) == str(user.id):
        return {"ok": True, "already": True}
    if state != "pending":
        raise HTTPException(409, f"invite is {state}")
    sb_clients.sb_patch_as_service(
        f"/invite_tokens?id=eq.{inv['id']}",
        {"status": "accepted", "accepted_at": _now_iso(),
         "accepted_by_user_id": str(user.id)})
    if _profile(str(user.id)):
        sb_clients.sb_patch_as_service(
            f"/user_profiles?user_id=eq.{user.id}",
            {"invited_via_token": inv["token"], "updated_at": _now_iso()})
    else:
        sb_clients.sb_post_as_service("/user_profiles", {
            "user_id": str(user.id), "invited_via_token": inv["token"],
        }, prefer=None)
    return {"ok": True, "admitted": True}


# ─── Backend-mediated business creation (the real gate) ──────────────

class CreateBusinessBody(BaseModel):
    name: str
    type: str
    voice_profile: Dict[str, Any] = {}
    cdi_vocabulary: Optional[str] = None
    settings: Dict[str, Any] = {}
    tier: Optional[str] = None


@router.post("/businesses/create")
def create_business(body: CreateBusinessBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Replaces the frontend's direct PostgREST insert. Enforces, in order:
      1. Launch admission (invite-only): grandfathered or invited.
      2. Tier business cap (grandfathered bypass; advisory→REAL now).
    Insert payload mirrors OnboardingFlow exactly (whitelisted fields)."""
    uid = str(user.id)
    grandfathered = usage_metering.is_grandfathered_user(uid)

    if invite_only() and not grandfathered and not user_admitted(uid):
        raise HTTPException(403, {
            "error": "invite_only",
            "message": "Solutionist is currently invite-only. You're welcome "
                       "to join the waitlist — invites go out steadily.",
        })

    if not grandfathered:
        cap = billing_limits.can_create_business(uid)
        if cap.get("enforce") and not cap.get("allowed"):
            raise HTTPException(402, {
                "error": "business_cap",
                "message": f"Your plan includes {cap.get('limit')} business"
                           f"{'es' if (cap.get('limit') or 0) != 1 else ''} — "
                           f"you're using {cap.get('count')}. Upgrade to add another.",
                "upgrade_url": f"{_APP_BASE}/?settings=billing",
            })

    name = (body.name or "").strip()
    btype = (body.type or "").strip() or "custom"
    if not name:
        raise HTTPException(400, "business name required")
    # Arc 20B Part 6 — regulated-vertical ruling: lawyer + therapist (and
    # counseling-adjacent) businesses ship with client-facing autonomy
    # DISABLED by default; enabling later requires explicit practitioner
    # acknowledgment (Phase C consumes these flags; set at birth so the
    # default exists before any autonomy ships).
    settings = dict(body.settings or {})
    bt_l = btype.lower()
    if any(k in bt_l for k in ("law", "therap", "counsel")):
        settings.setdefault("autonomy", {
            "client_facing_autonomy": "disabled",
            "disabled_reason": "regulated_vertical_default",
            "acknowledgment_required": True,
            "acknowledged_at": None,
        })
    res = sb_clients.sb_post_as_service("/businesses", {
        "owner_id": uid,
        "name": name[:160],
        "type": btype[:60],
        "voice_profile": body.voice_profile or {},
        "cdi_vocabulary": body.cdi_vocabulary,
        "settings": settings,
        **({"tier": body.tier} if body.tier else {}),
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "business insert failed")
    return {"ok": True, "business": row}


@router.get("/status")
def access_status(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The signed-in user's own admission state (frontend gating)."""
    uid = str(user.id)
    p = _profile(uid) or {}
    return {"ok": True,
            "invite_only": invite_only(),
            "grandfathered": bool(p.get("is_grandfathered")),
            "admitted": bool(p.get("is_grandfathered") or p.get("invited_via_token"))}


# ─── Admin (platform owner only) ─────────────────────────────────────

class InviteCreateBody(BaseModel):
    email: str


@router.post("/invites")
async def create_invite(body: InviteCreateBody,
                        _owner=Depends(require_owner)) -> Dict[str, Any]:
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "valid email required")
    res = sb_clients.sb_post_as_service("/invite_tokens", {
        "email": email, "created_by": "platform_owner",
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "invite insert failed")
    invite_url = f"{_APP_BASE}/?invite={row.get('token')}"

    email_sent = False
    try:
        from email_sender import send_via_resend
        await send_via_resend(
            to_email=email, to_name=None,
            from_email="invites@mysolutionist.app", from_name="The Solutionist System",
            reply_to=None,
            subject="Your invite to The Solutionist System",
            body=("You're in.\n\n"
                  "The Solutionist System is invite-only right now, and this "
                  "is yours — your whole practice (bookings, invoices, real "
                  "bookkeeping, and Chief, your AI chief of staff) in one place.\n\n"
                  f"Create your account here:\n{invite_url}\n\n"
                  "The link is yours alone and expires in 30 days.\n\n"
                  "— Kevin\nKMJ Creative Solutions · mysolutionist.app"))
        email_sent = True
    except Exception as e:
        logger.warning(f"[access] invite email failed: {e}")
    return {"ok": True, "invite": row, "invite_url": invite_url,
            "email_sent": email_sent}


@router.get("/invites")
def list_invites(_owner=Depends(require_owner)) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        "/invite_tokens?order=created_at.desc&limit=200&select=*") or []
    return {"ok": True, "invites": rows}


@router.post("/invites/{invite_id}/revoke")
def revoke_invite(invite_id: str, _owner=Depends(require_owner)) -> Dict[str, Any]:
    sb_clients.sb_patch_as_service(
        f"/invite_tokens?id=eq.{invite_id}&status=eq.pending",
        {"status": "revoked"})
    return {"ok": True}


@router.get("/waitlist-entries")
def list_waitlist(_owner=Depends(require_owner)) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        "/waitlist?order=created_at.desc&limit=500&select=*") or []
    return {"ok": True, "entries": rows, "count": len(rows)}


class GrandfatherBody(BaseModel):
    user_id: str
    value: bool = True
    reason: Optional[str] = None


@router.post("/grandfather")
def set_grandfather(body: GrandfatherBody,
                    _owner=Depends(require_owner)) -> Dict[str, Any]:
    patch = {"is_grandfathered": bool(body.value), "updated_at": _now_iso()}
    if body.value:
        patch["grandfathered_at"] = _now_iso()
        patch["grandfathered_reason"] = (body.reason or "manually granted")[:300]
    if _profile(body.user_id):
        sb_clients.sb_patch_as_service(
            f"/user_profiles?user_id=eq.{body.user_id}", patch)
    else:
        sb_clients.sb_post_as_service("/user_profiles", {
            "user_id": body.user_id, **patch}, prefer=None)
    return {"ok": True, "user_id": body.user_id, "is_grandfathered": bool(body.value)}


@router.get("/inference-stats")
def inference_stats(_owner=Depends(require_owner)) -> Dict[str, Any]:
    """Arc 20B Part 9 — Layer-2 telemetry: hit rate, savings, cache size,
    top cached requests, per-surface breakdown. Read-only."""
    import inference_gate
    return inference_gate.stats()


@router.get("/readiness")
def billing_readiness(_owner=Depends(require_owner)) -> Dict[str, Any]:
    """Pre-flight panel for flipping BILLING_ENFORCE — read-only; the env
    var itself flips in Railway, never here."""
    import feature_gates
    profiles = sb_clients.sb_get_as_service(
        "/user_profiles?select=user_id,is_grandfathered&limit=2000") or []
    grandfathered = sum(1 for p in profiles if p.get("is_grandfathered"))
    bizzes = sb_clients.sb_get_as_service(
        "/businesses?is_active=eq.true"
        "&select=id,owner_id,subscription_status,subscription_plan&limit=2000") or []
    by_plan: Dict[str, int] = {}
    unsubscribed = []
    gf_ids = {p["user_id"] for p in profiles if p.get("is_grandfathered")}
    for b in bizzes:
        plan = feature_gates.plan_of(b)
        if plan:
            by_plan[plan] = by_plan.get(plan, 0) + 1
        elif str(b.get("owner_id")) not in gf_ids:
            unsubscribed.append(b["id"])
    month_usage = sb_clients.sb_get_as_service(
        f"/api_usage?created_at=gte.{usage_metering._month_start_iso()}"
        f"&select=endpoint&limit=10000") or []
    weighted = sum(usage_metering.weight_for(r.get("endpoint")) for r in month_usage)

    tiers_env = {p: bool((os.environ.get(f"STRIPE_PRICE_ID_{p.upper()}") or "").strip())
                 for p in feature_gates.PLANS}
    overage_env = {p: bool((os.environ.get(f"STRIPE_PRICE_ID_{p.upper()}_OVERAGE") or "").strip())
                   for p in feature_gates.PLANS}
    would_break = []
    if unsubscribed:
        would_break.append(f"{len(unsubscribed)} active business(es) with no plan and a "
                           "non-grandfathered owner would lose gated features.")
    if not all(tiers_env.values()):
        would_break.append("Subscription price ids missing: "
                           + ", ".join(p for p, v in tiers_env.items() if not v))
    if not all(overage_env.values()):
        would_break.append("Overage (metered) price ids missing: "
                           + ", ".join(p for p, v in overage_env.items() if not v))
    if not os.environ.get("STRIPE_WEBHOOK_SECRET"):
        would_break.append("STRIPE_WEBHOOK_SECRET not set — subscription state won't sync.")

    return {
        "ok": True,
        "billing_enforce": feature_gates.enforcement_on(),
        "invite_only": invite_only(),
        "grandfathered_users": grandfathered,
        "subscribers_by_tier": by_plan,
        "unsubscribed_non_grandfathered_businesses": len(unsubscribed),
        "weighted_usage_this_month_platform": weighted,
        "stripe_env": {"tiers": tiers_env, "overage": overage_env,
                       "webhook_secret": bool(os.environ.get("STRIPE_WEBHOOK_SECRET"))},
        "preflight_issues": would_break,
        "ready_to_flip": not would_break,
    }
