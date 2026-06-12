"""
referrals.py — Arc 25 Stream 4 — practitioner referral loop.

Every practitioner gets a permanent referral code (generated on first
view of Settings → Referrals). Share link: {APP}/?ref=<code>.

Invite-only coexistence (Kevin's Part 4.3 ruling): during the gated
launch a redeemed referral ADMITS the referee — implemented by writing
the sentinel ``ref:<code>`` into user_profiles.invited_via_token, so the
Arc 19 admission check (``is_grandfathered OR invited_via_token``) passes
with zero changes to launch_access. Post-launch (LAUNCH_INVITE_ONLY=off)
the same redeem call becomes pure attribution.

Rewards (v1, manual application): reward goes to the REFERRER only —
one free month per referee who subscribes and stays past 30 days.
Because Stripe webhooks aren't consumed yet, "stayed 30 days" is
approximated as: referee owns a business with subscription_status =
'active' AND the referral is >30 days old. Statuses surface in
Settings → Referrals; Kevin applies earned credits by hand until the
Stripe credit automation lands. Referee gets the normal 14-day trial,
no bypass (double-sided rewards deferred to v1.5).

Migration: __migrations__/2026_06_12_referrals.sql (referral_code,
referred_by, referred_at on user_profiles).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("referrals")

router = APIRouter(prefix="/access/referrals", tags=["referrals"])

_APP_BASE = "https://system.mysolutionist.app"
# No 0/O/1/I — codes get read aloud and retyped.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8
_REWARD_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _profile(user_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/user_profiles?user_id=eq.{user_id}&select=*&limit=1") or []
    return rows[0] if rows else None


def _profile_by_code(code: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/user_profiles?referral_code=eq.{code}&select=*&limit=1") or []
    return rows[0] if rows else None


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def _normalize(code: str) -> str:
    return (code or "").strip().upper()[:32]


def _ensure_code(user_id: str) -> str:
    """Return the caller's referral code, generating + persisting it on
    first request. Unique-collision retry is belt-and-braces — 32^8 space."""
    p = _profile(user_id)
    if p and p.get("referral_code"):
        return p["referral_code"]
    for _ in range(5):
        code = _gen_code()
        if _profile_by_code(code):
            continue
        if p:
            sb_clients.sb_patch_as_service(
                f"/user_profiles?user_id=eq.{user_id}",
                {"referral_code": code, "updated_at": _now_iso()})
        else:
            sb_clients.sb_post_as_service("/user_profiles", {
                "user_id": user_id, "referral_code": code,
            }, prefer=None)
        return code
    raise HTTPException(500, "could not generate a referral code")


# ─── Public: signup screen checks the link before showing the form ────

@router.get("/resolve")
def resolve_code(code: str) -> Dict[str, Any]:
    """Public, non-enumerating: just valid/invalid — no referrer identity."""
    valid = bool(_profile_by_code(_normalize(code)))
    return {"ok": True, "valid": valid}


# ─── Authed: redeem (attribution + launch admission) ──────────────────

class RedeemBody(BaseModel):
    code: str


@router.post("/redeem")
def redeem_referral(body: RedeemBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """First authenticated load consumes the stashed ?ref= code (mirrors
    the Arc 19 invite redeem flow). Admits via the ``ref:<code>``
    sentinel in invited_via_token; attribution in referred_by."""
    uid = str(user.id)
    code = _normalize(body.code)
    if not code:
        raise HTTPException(400, "referral code required")
    ref = _profile_by_code(code)
    if not ref:
        raise HTTPException(404, "unknown referral code")
    if str(ref.get("user_id")) == uid:
        raise HTTPException(400, "you can't refer yourself")

    me = _profile(uid)
    if me and (me.get("referred_by") or me.get("invited_via_token")
               or me.get("is_grandfathered")):
        # Already attributed/admitted — first attribution wins, invites
        # outrank referrals. Idempotent for the frontend retry loop.
        return {"ok": True, "already": True}

    patch = {"referred_by": str(ref["user_id"]),
             "referred_at": _now_iso(),
             "invited_via_token": f"ref:{code}",
             "updated_at": _now_iso()}
    if me:
        sb_clients.sb_patch_as_service(f"/user_profiles?user_id=eq.{uid}", patch)
    else:
        patch.pop("updated_at", None)
        sb_clients.sb_post_as_service("/user_profiles",
                                      {"user_id": uid, **patch}, prefer=None)
    return {"ok": True, "admitted": True}


# ─── Authed: my referral panel (code + stats + rewards) ───────────────

@router.get("/me")
def my_referrals(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    uid = str(user.id)
    code = _ensure_code(uid)

    referees: List[Dict[str, Any]] = sb_clients.sb_get_as_service(
        f"/user_profiles?referred_by=eq.{uid}"
        "&select=user_id,referred_at&order=referred_at.desc&limit=500") or []

    subscribed_ids = set()
    if referees:
        ids = ",".join(str(r["user_id"]) for r in referees)
        bizzes = sb_clients.sb_get_as_service(
            f"/businesses?owner_id=in.({ids})&is_active=eq.true"
            "&select=owner_id,subscription_status&limit=1000") or []
        subscribed_ids = {str(b["owner_id"]) for b in bizzes
                          if b.get("subscription_status") == "active"}

    cutoff = _now() - timedelta(days=_REWARD_DAYS)
    out = []
    earned = 0
    for r in referees:
        rid = str(r["user_id"])
        referred_at = r.get("referred_at") or ""
        status = "signed_up"
        if rid in subscribed_ids:
            status = "subscribed"
            # Approximation until Stripe webhooks land: active sub +
            # referral older than 30 days counts as a retained referee.
            try:
                if datetime.fromisoformat(referred_at.replace("Z", "+00:00")) <= cutoff:
                    status = "reward_earned"
                    earned += 1
            except Exception:
                pass
        # Privacy: dates + status only, never the referee's identity.
        out.append({"referred_at": referred_at, "status": status})

    return {
        "ok": True,
        "code": code,
        "link": f"{_APP_BASE}/?ref={code}",
        "referrals": out,
        "counts": {"signed_up": len(out),
                   "subscribed": len(subscribed_ids),
                   "rewards_earned": earned},
        "reward": {"type": "free_month_credit", "per": "referee retained 30 days",
                   "application": "manual"},
    }
