"""
launch_access.py — Arc 19 Phase B — invite-only launch gate, waitlist,
grandfathering, and backend-mediated business creation.

Access model (Kevin's ruling): invite-only/waitlist pre-launch → free-
trial pattern post-validation. **The trial pattern is live as of
2026-08-24** — invite_only() now defaults OFF, so anyone can create a
business and start a subscription. The HARD gate is still here and still
server-side at business creation: set LAUNCH_INVITE_ONLY=on and an
uninvited browser can create a bare Supabase auth user but not a
business, and sees the waitlist message again.

Invites, referrals and team invites are unchanged by the flip. They stop
being the only door; they do not stop working. Grandfathering, comped
tiers and the waitlist table all behave exactly as before.

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
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

import lead_attribution
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
    """Default OFF as of 2026-08-24: the doors are open, and anyone can
    create a business and subscribe without an invite. This is the flip
    the module docstring's kill switch was built for — set
    LAUNCH_INVITE_ONLY=on to close them again, which re-gates business
    creation to invited + grandfathered users with no other change.

    The invite, referral and team-invite paths all keep working while
    it is off; they simply stop being the ONLY way in."""
    return (os.environ.get("LAUNCH_INVITE_ONLY") or "off").lower() != "off"


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
    # Campaign params the app captured off its own front-door URL
    # (utm_*, gclid, fbclid, referrer, landing_path). Whitelisted
    # server-side — a lie here can only misattribute one marketing row.
    attribution: Optional[Dict[str, Any]] = None


@router.post("/waitlist")
def join_waitlist(body: WaitlistBody, request: Request = None) -> Dict[str, Any]:
    email = (body.email or "").strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(400, "valid email required")
    attribution = lead_attribution.capture(
        request, {"attribution": body.attribution}) or None
    existing = sb_clients.sb_get_as_service(
        f"/waitlist?email=eq.{email}&select=id&limit=1") or []
    if not existing:
        sb_clients.sb_post_as_service("/waitlist", {
            "email": email, "name": (body.name or "").strip()[:120] or None,
            **({"attribution": attribution} if attribution else {}),
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


def _uses_left(inv: Dict[str, Any]) -> int:
    """Launch-ops: multi-use invites. Pre-migration rows (no max_uses
    column) behave exactly like before: one use."""
    max_uses = int(inv.get("max_uses") or 1)
    uses = int(inv.get("uses_count") or 0)
    return max(0, max_uses - uses)


@router.get("/invites/validate")
def validate_invite(token: str) -> Dict[str, Any]:
    """Public — the signup screen asks before showing the form."""
    inv = _load_token(token)
    state = _token_state(inv)
    # Multi-use links stay valid while uses remain, even after the
    # first redemption flipped a legacy-minded status.
    if state == "accepted" and _uses_left(inv) > 0:
        state = "pending"
    return {"ok": True, "valid": state == "pending",
            "state": state,
            "email": inv.get("email") if state == "pending" else None}


class RedeemBody(BaseModel):
    token: str


@router.post("/redeem")
def redeem_invite(body: RedeemBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Signed-in user consumes their platform invite. Single-use invites
    keep first-use-wins; multi-use links admit until uses run out.
    Marks the profile invited — NOT grandfathered (Kevin's ruling)."""
    inv = _load_token(body.token)
    state = _token_state(inv)
    if state == "accepted" and str(inv.get("accepted_by_user_id")) == str(user.id):
        return {"ok": True, "already": True}
    multi = int(inv.get("max_uses") or 1) > 1
    if multi and state == "accepted" and _uses_left(inv) > 0:
        state = "pending"  # multi-use link with uses remaining
    if state != "pending":
        raise HTTPException(409, f"invite is {state}")
    uses_after = int(inv.get("uses_count") or 0) + 1
    patch: Dict[str, Any] = {"accepted_at": _now_iso(),
                             "accepted_by_user_id": str(user.id)}
    if multi:
        patch["uses_count"] = uses_after
        if uses_after >= int(inv.get("max_uses") or 1):
            patch["status"] = "accepted"
    else:
        patch["status"] = "accepted"
        # Pre-migration rows have no uses_count; only write it when the
        # row already carries the column.
        if "uses_count" in inv:
            patch["uses_count"] = uses_after
    sb_clients.sb_patch_as_service(
        f"/invite_tokens?id=eq.{inv['id']}", patch)
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
    # Which door they walked in through — the app stashed campaign params
    # off its front-door URL at first visit (same stash-and-redeem as
    # invite tokens) and sends them once, here. Whitelisted server-side.
    attribution: Optional[Dict[str, Any]] = None


def _attribution_from_funnel(email: Optional[str]) -> Optional[Dict[str, Any]]:
    """The invite funnel crosses days and devices — apply on the
    marketing site, get the invite email later, sign up on whatever
    device the email was opened on. The signup URL carries nothing by
    then; the EMAIL is the join key back to the marketing_leads or
    waitlist row that did see the campaign."""
    em = (email or "").strip().lower()
    if not em or "@" not in em:
        return None
    for table, via in (("marketing_leads", "lead_form"), ("waitlist", "waitlist")):
        try:
            rows = sb_clients.sb_get_as_service(
                f"/{table}?email=eq.{quote(em)}&select=attribution"
                f"&attribution=not.is.null&order=created_at.desc&limit=1") or []
        except Exception as e:
            logger.warning(f"[access] funnel attribution lookup ({table}) failed: {e}")
            rows = []
        if rows and isinstance(rows[0].get("attribution"), dict) and rows[0]["attribution"]:
            a = dict(rows[0]["attribution"])
            a["via"] = via
            return a
    return None


def _seed_new_business(row: Dict[str, Any], business_type: str,
                       voice_profile: Optional[Dict[str, Any]], owner_id: str) -> Dict[str, bool]:
    """Everything a new business should be born with, run server-side
    right after the row exists: the profile defaults for its archetype,
    the blueprint module set, and the vertical's default autopilot.

    Until 2026-09-02 all three hung off a SEPARATE client call
    (POST /business-profile/profile/seed-from-onboarding) that the
    frontend made one second after creation — and that call answered
    404 from May to September (route-order bug, #777), so no real
    business ever received any of it, and nothing noticed because the
    client called the failure "non-fatal". The client call still exists
    and is idempotent (it only fills empty fields), so a practitioner
    with an older tab loses nothing; this just stops the birth of a
    business depending on a second request nobody monitors.

    Never raises. Each step is its own try, each failure its own
    warning, and the result names what ran so a test can see it."""
    biz_id = str((row or {}).get("id") or "")
    out = {"profile": False, "modules": False, "autopilot": False}
    if not biz_id:
        return out
    try:
        import business_profile_agent as bp
        out["profile"] = bp.seed_from_onboarding(
            business_id=biz_id, business_type=business_type,
            tones=None, voice_profile=voice_profile or None) is not None
    except Exception as e:
        logger.warning(f"[access] seed profile failed for {biz_id}: {e}")
    try:
        import module_blueprint_agent
        module_blueprint_agent.provision_modules(biz_id, business_type)
        out["modules"] = True
    except Exception as e:
        logger.warning(f"[access] blueprint provision failed for {biz_id}: {e}")
    try:
        import vertical_autopilot
        vertical_autopilot.seed_defaults(
            business_id=biz_id, business_type=business_type, owner_id=owner_id)
        out["autopilot"] = True
    except Exception as e:
        logger.warning(f"[access] autopilot seed failed for {biz_id}: {e}")
    return out


@router.post("/businesses/create")
def create_business(body: CreateBusinessBody,
                    user: AuthedUser = Depends(require_user),
                    background_tasks: BackgroundTasks = None) -> Dict[str, Any]:
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
    # Signup attribution — stamped once, at birth. The app's own blob
    # (direct signup with a tagged URL) wins; otherwise the funnel row
    # that shares this email (invite path) supplies it. Absent both,
    # the column stays NULL and the Growth panel says "untracked".
    attribution = lead_attribution.from_client(body.attribution)
    if attribution:
        attribution["via"] = "app"
    else:
        attribution = _attribution_from_funnel(getattr(user, "email", None))

    res = sb_clients.sb_post_as_service("/businesses", {
        "owner_id": uid,
        "name": name[:160],
        "type": btype[:60],
        "voice_profile": body.voice_profile or {},
        "cdi_vocabulary": body.cdi_vocabulary,
        "settings": settings,
        **({"tier": body.tier} if body.tier else {}),
        **({"attribution": attribution} if attribution else {}),
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "business insert failed")

    # Born whole (2026-09-02): profile defaults, blueprint modules and the
    # vertical autopilot, after the response, no second request needed.
    try:
        if background_tasks is not None:
            background_tasks.add_task(_seed_new_business, row, btype,
                                      body.voice_profile or None, uid)
    except Exception as e:
        logger.warning(f"[access] seed schedule failed: {e}")
    # Day one for everyone who never reaches Stripe. Comped, invited and
    # grandfathered accounts have no subscription and so no `trialing`
    # webhook ever fires — an arc that only opened from Stripe would skip
    # exactly the people we hand-picked.
    #
    # For a self-serve signup this fires first (checkout comes minutes
    # later, from the paywall) and the subscription then aligns the arc
    # to the real trial start. Best-effort: a practitioner whose business
    # was created must never see that fail because a side table did.
    try:
        import first_run_arc
        first_run_arc.begin(row.get("id"), source="signup")
    except Exception as e:
        logger.warning(f"[access] first-run arc begin failed (non-fatal): {e}")

    # Growth arc Rung 2 — tell Meta a signup completed, after the
    # response. No-op unless the pixel + CAPI token are configured.
    try:
        import meta_capi
        if background_tasks is not None and meta_capi.configured():
            a = body.attribution or {}
            background_tasks.add_task(
                meta_capi.send_event, "CompleteRegistration",
                email=getattr(user, "email", None),
                event_id=str(row.get("id") or "") or None,
                fbp=a.get("fbp"), fbc=a.get("fbc"))
    except Exception as e:
        logger.warning(f"[access] capi registration schedule failed: {e}")

    # Lifecycle (2026-09-01) — the welcome email, after the response.
    # send_welcome decides for itself whether this is the owner's first
    # business and never raises; a signup must not fail on mail.
    try:
        import lifecycle_emails
        if background_tasks is not None:
            background_tasks.add_task(
                lifecycle_emails.send_welcome, row,
                getattr(user, "email", None),
                (settings.get("practitioner_name") or None))
    except Exception as e:
        logger.warning(f"[access] welcome email schedule failed: {e}")

    return {"ok": True, "business": row}


@router.get("/open")
def access_open() -> Dict[str, Any]:
    """Public: is the platform taking self-serve signups right now?

    Deliberately unauthenticated — it is the same fact the marketing
    site states in public copy, and the app's front door has to know it
    BEFORE anyone has an account to authenticate with. /status answers
    the signed-in version of the question and stays authed.

    This exists so LAUNCH_INVITE_ONLY really is the one switch the
    runbook promises: with it, flipping the env re-gates the app's
    "Create account" button too, with no frontend deploy. Without it the
    app would keep offering a signup the server then refuses at business
    creation. trial_days rides along for the same reason — so the front
    door can say what checkout will actually grant."""
    try:
        trial_days = max(0, int(os.environ.get("BILLING_TRIAL_DAYS") or "7"))
    except ValueError:
        trial_days = 7
    return {"ok": True, "invite_only": invite_only(), "trial_days": trial_days}


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
    # Email optional for multi-use links (a shareable code isn't tied to
    # one inbox). Single-use invites still require it.
    email: Optional[str] = None
    max_uses: int = 1
    label: Optional[str] = None   # e.g. "barber-group-july" — shows in the list


async def _send_invite_email(email: str, invite_url: str) -> bool:
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
        return True
    except Exception as e:
        logger.warning(f"[access] invite email failed: {e}")
        return False


async def _mint_invite(email: Optional[str], max_uses: int = 1,
                       label: Optional[str] = None) -> Dict[str, Any]:
    """Insert an invite row + return {invite, invite_url, email_sent}.
    Tolerates the pre-migration schema (no max_uses/label columns) by
    retrying a plain single-use insert."""
    payload: Dict[str, Any] = {"created_by": "platform_owner"}
    if email:
        payload["email"] = email
    if max_uses > 1 or label:
        payload.update({"max_uses": max_uses, **({"label": label} if label else {})})
    res = sb_clients.sb_post_as_service("/invite_tokens", payload)
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row and (max_uses > 1 or label):
        # launch-ops migration not applied — fall back to single-use.
        res = sb_clients.sb_post_as_service("/invite_tokens", {
            "email": email, "created_by": "platform_owner"})
        row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "invite insert failed")
    invite_url = f"{_APP_BASE}/?invite={row.get('token')}"
    email_sent = False
    if email:
        email_sent = await _send_invite_email(email, invite_url)
    return {"ok": True, "invite": row, "invite_url": invite_url,
            "email_sent": email_sent}


@router.post("/invites")
async def create_invite(body: InviteCreateBody,
                        _owner=Depends(require_owner)) -> Dict[str, Any]:
    email = (body.email or "").strip().lower() or None
    max_uses = max(1, min(int(body.max_uses or 1), 500))
    if max_uses == 1 and (not email or "@" not in email):
        raise HTTPException(400, "valid email required for single-use invites")
    if email and "@" not in email:
        raise HTTPException(400, "email looks invalid")
    return await _mint_invite(email, max_uses, (body.label or "").strip() or None)


@router.post("/invites/{invite_id}/resend")
async def resend_invite(invite_id: str, _owner=Depends(require_owner)) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/invite_tokens?id=eq.{invite_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "invite not found")
    inv = rows[0]
    if not inv.get("email"):
        raise HTTPException(400, "multi-use links have no email — copy the link instead")
    if _token_state(inv) != "pending":
        raise HTTPException(409, f"invite is {_token_state(inv)}")
    invite_url = f"{_APP_BASE}/?invite={inv.get('token')}"
    sent = await _send_invite_email(inv["email"], invite_url)
    return {"ok": True, "email_sent": sent, "invite_url": invite_url}


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


@router.post("/waitlist-entries/{entry_id}/approve")
async def approve_waitlist_entry(entry_id: str,
                                 _owner=Depends(require_owner)) -> Dict[str, Any]:
    """One-click waitlist → invite: mints a single-use invite for the
    entry's email, emails it, and stamps the waitlist row."""
    rows = sb_clients.sb_get_as_service(
        f"/waitlist?id=eq.{entry_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "waitlist entry not found")
    email = (rows[0].get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "waitlist entry has no usable email")
    result = await _mint_invite(email, 1, None)
    try:
        sb_clients.sb_patch_as_service(
            f"/waitlist?id=eq.{entry_id}",
            {"invited_at": _now_iso()})
    except Exception:
        pass  # column may not exist — the invite itself is the record
    return result


# ─── Launch-ops: unit grants + tier override (platform owner) ─────────

class GrantUnitsBody(BaseModel):
    business_id: str
    units: int
    # 'YYYY-MM' → one month only; omit → recurring monthly bonus.
    month: Optional[str] = None
    reason: Optional[str] = None


@router.post("/grant-units")
def grant_units(body: GrantUnitsBody,
                _owner=Depends(require_owner)) -> Dict[str, Any]:
    """Give a business bonus Chief interactions (beta testers, partners,
    make-goods). Consumed by usage_metering.usage_summary — grants top
    up the tier allotment and lift the bill cap by the same amount."""
    if not body.business_id:
        raise HTTPException(400, "business_id required")
    units = int(body.units or 0)
    if units == 0 or abs(units) > 100_000:
        raise HTTPException(400, "units must be non-zero and sane (±100k)")
    if body.month and not (len(body.month) == 7 and body.month[4] == "-"):
        raise HTTPException(400, "month must be 'YYYY-MM'")
    res = sb_clients.sb_post_as_service("/usage_grants", {
        "business_id": body.business_id,
        "units": units,
        "month": body.month,
        "reason": (body.reason or "").strip() or None,
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "grant insert failed — is the launch-ops migration applied?")
    return {"ok": True, "grant": row}


@router.get("/grants")
def list_grants(business_id: Optional[str] = None,
                _owner=Depends(require_owner)) -> Dict[str, Any]:
    q = "/usage_grants?order=created_at.desc&limit=200&select=*"
    if business_id:
        q += f"&business_id=eq.{business_id}"
    rows = sb_clients.sb_get_as_service(q) or []
    return {"ok": True, "grants": rows}


class TierBody(BaseModel):
    comp_tier: Optional[str] = None   # 'starter'|'professional'|'practice'|null to clear
    reason: Optional[str] = None


@router.post("/business/{business_id}/tier")
def set_comp_tier(business_id: str, body: TierBody,
                  _owner=Depends(require_owner)) -> Dict[str, Any]:
    """Owner tier override — comp a business at any tier without a
    Stripe subscription (feature_gates.plan_of prefers comp_tier).
    Pass comp_tier null to clear back to Stripe-derived."""
    tier = (body.comp_tier or "").strip().lower() or None
    if tier is not None and tier not in ("starter", "professional", "practice"):
        raise HTTPException(400, "comp_tier must be starter|professional|practice|null")
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"comp_tier": tier})
    logger.info(f"[access] comp_tier={tier} business={business_id} reason={body.reason}")
    return {"ok": True, "business_id": business_id, "comp_tier": tier}


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
        "&select=id,owner_id,subscription_status,subscription_plan,comp_tier&limit=2000") or []
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
        f"&select=endpoint,units&limit=10000") or []
    weighted = sum(usage_metering.weight_for_row(r) for r in month_usage)

    tiers_env = {p: bool((os.environ.get(f"STRIPE_PRICE_ID_{p.upper()}") or "").strip())
                 for p in feature_gates.PLANS}
    # No STRIPE_PRICE_ID_*_OVERAGE check here, deliberately (2026-08-29).
    # Pricing v2 retired postpaid overage on 2026-07-12: usage past the
    # allowance draws down PREPAID credits (credit_ledger), and
    # usage_metering.report_overage_to_stripe() is a permanent no-op so
    # nothing ever reaches a Stripe metered item -- that would
    # double-charge. Those env vars SHOULD be absent, so asserting on
    # them pinned ready_to_flip to False forever and told the owner to
    # go add config that would be wrong to add.
    would_break = []
    if unsubscribed:
        would_break.append(f"{len(unsubscribed)} active business(es) with no plan and a "
                           "non-grandfathered owner would lose gated features.")
    if not all(tiers_env.values()):
        would_break.append("Subscription price ids missing: "
                           + ", ".join(p for p, v in tiers_env.items() if not v))
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
        "stripe_env": {"tiers": tiers_env,
                       "webhook_secret": bool(os.environ.get("STRIPE_WEBHOOK_SECRET"))},
        "preflight_issues": would_break,
        "ready_to_flip": not would_break,
    }
