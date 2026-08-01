"""
setup_plan.py — the strategy session's exit ramp into a set-up business.

Kevin's ruling (8/01): when a strategy session ends, the coach should
recommend the basic setup — and the split is by KIND of step, three
tiers:

  TIER 1 — INSERTS. Anything the session already LEARNED is written by
    the system after ONE confirmation (the receipts pattern: the model
    proposes, the practitioner disposes). Nobody re-types what they
    just told the coach.
  TIER 2 — CONNECTS. Steps that need the practitioner's own
    credentials (Stripe, bank, booking publish) can only be navigated
    to — with STATE-AWARE honesty: a connected thing shows done,
    never a button to redo it.
  TIER 3 — FOLLOW-UP. Whatever the practitioner skips becomes a
    chief_notification with the nav target, so the recommendation
    survives the overlay closing instead of dying with the session.

Surface (owner-gated):
  GET  /strategy/setup-plan?biz=          — the current plan
  POST /strategy/setup-plan/apply?biz=    — apply chosen inserts +
                                            seed Tier-3 follow-ups
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("setup_plan")

router = APIRouter(prefix="/strategy", tags=["setup-plan"])


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}"
        f"&select=id,name,owner_id,type,stripe_account_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:60] or "offering"


def parse_price(raw: Any) -> Optional[float]:
    """'$1,200/mo' -> 1200.0; None when nothing numeric survives."""
    if isinstance(raw, (int, float)):
        return round(float(raw), 2)
    m = re.search(r"[\d][\d,]*(?:\.\d+)?", str(raw or ""))
    if not m:
        return None
    try:
        return round(float(m.group(0).replace(",", "")), 2)
    except ValueError:
        return None


# ─── The plan ────────────────────────────────────────────────────────

def build_setup_plan(biz: Dict[str, Any]) -> Dict[str, Any]:
    """State-aware plan: what the session knows (inserts) + what still
    needs the practitioner's own hands (connects)."""
    biz_id = biz["id"]

    track_rows = sb_clients.sb_get_as_service(
        f"/strategy_tracks?business_id=eq.{biz_id}"
        f"&select=service_packages,pricing_strategy&limit=1") or []
    track = track_rows[0] if track_rows else {}
    packages = track.get("service_packages") or []

    offerings = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{biz_id}&is_active=eq.true&select=id&limit=1") or []

    profile_rows = sb_clients.sb_get_as_service(
        f"/business_profiles?business_id=eq.{biz_id}"
        f"&select=service_models,pricing_models,governing_state&limit=1") or []
    profile = profile_rows[0] if profile_rows else {}

    settings = biz.get("settings") or {}
    financial = settings.get("financial") or {}

    # ── Tier 1: inserts (only offered when they'd actually do work) ──
    inserts: List[Dict[str, Any]] = []
    if packages and not offerings:
        inserts.append({
            "kind": "offerings_from_packages",
            "label": f"Create {len(packages)} offering{'s' if len(packages) != 1 else ''} "
                     f"from your service packages",
            "preview": [{"name": p.get("name") or "Package",
                         "price": p.get("price")} for p in packages[:6]],
        })
    bridge_would_write = (
        (not profile.get("service_models") and any(p.get("delivery_format") for p in packages))
        or (not profile.get("pricing_models")
            and (track.get("pricing_strategy") or {}).get("tiers"))
    )
    if bridge_would_write:
        inserts.append({
            "kind": "profile_fields",
            "label": "Fill your business profile from the session "
                     "(service models, pricing models)",
        })
    gov_state = (profile.get("governing_state") or "").strip()
    if gov_state and not (financial.get("state") or "").strip():
        inserts.append({
            "kind": "financial_state",
            "label": f"Set {gov_state} as your tax state in Financial Settings",
        })

    # ── Tier 2: connects (state-aware; done items shown done) ────────
    import offering_profiles
    state = offering_profiles.business_state(biz_id)
    plaid = sb_clients.sb_get_as_service(
        f"/plaid_items?business_id=eq.{biz_id}&status=not.eq.revoked&select=item_id&limit=1") or []
    qb = sb_clients.sb_get_as_service(
        f"/quickbooks_connections?business_id=eq.{biz_id}"
        f"&status=eq.connected&select=business_id&limit=1") or []

    connects = [
        {"id": "stripe", "label": "Connect Stripe so you can get paid online",
         "done": bool(state.get("stripe_connected")),
         "nav": {"tab": "operate", "sub": "payments"}},
        {"id": "bank", "label": "Link your bank so the books fill themselves",
         "done": bool(plaid),
         "nav": {"tab": "build", "sub": "integrations"}},
        {"id": "booking", "label": "Publish your booking page so clients can book you",
         "done": bool(state.get("booking_enabled")),
         "nav": {"tab": "build", "sub": "booking"}},
        {"id": "quickbooks", "label": "Optional: connect QuickBooks for your accountant",
         "done": bool(qb), "optional": True,
         "nav": {"tab": "build", "sub": "integrations"}},
    ]

    return {"ok": True, "inserts": inserts, "connects": connects,
            "actionable": bool(inserts or any(not c["done"] for c in connects))}


@router.get("/setup-plan")
def get_setup_plan(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    return build_setup_plan(_owner(biz, user))


# ─── Apply ───────────────────────────────────────────────────────────

class ApplyBody(BaseModel):
    kinds: List[str] = []


def _apply_offerings(biz_id: str, packages: List[Dict[str, Any]]) -> int:
    made = 0
    for p in packages:
        name = (p.get("name") or "").strip() or "Package"
        slug = _slugify(name)
        exists = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{biz_id}&slug=eq.{slug}&select=id&limit=1") or []
        if exists:
            continue
        created = sb_clients.sb_post_as_service("/offerings", {
            "business_id": biz_id,
            "name": name[:120],
            "slug": slug,
            "description": (p.get("description") or p.get("included") or "")[:1000] or None,
            "category": "service",
            "current_price": parse_price(p.get("price")),
            "currency": "usd",
            "is_active": True,
        })
        if created:
            made += 1
    return made


@router.post("/setup-plan/apply")
async def apply_setup_plan(biz: str, body: ApplyBody,
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    plan = build_setup_plan(b)
    offered = {i["kind"] for i in plan["inserts"]}
    chosen = [k for k in body.kinds if k in offered]

    results: Dict[str, Any] = {}
    import audit_log

    if "offerings_from_packages" in chosen:
        track_rows = sb_clients.sb_get_as_service(
            f"/strategy_tracks?business_id=eq.{biz}&select=service_packages&limit=1") or []
        packages = (track_rows[0].get("service_packages") if track_rows else []) or []
        n = _apply_offerings(biz, packages)
        results["offerings_from_packages"] = f"{n} offering(s) created"
        audit_log.record(biz, actor_type="chief", actor_id=str(user.id),
                         verb="setup_apply_offerings",
                         summary=f"Session setup: created {n} offerings from packages",
                         source="desktop")

    if "profile_fields" in chosen:
        import asyncio
        import business_profile_agent
        out = await asyncio.to_thread(
            business_profile_agent.import_from_strategy_track, biz)
        results["profile_fields"] = out if isinstance(out, str) else "profile updated"
        audit_log.record(biz, actor_type="chief", actor_id=str(user.id),
                         verb="setup_apply_profile",
                         summary="Session setup: profile filled from strategy track",
                         source="desktop")

    if "financial_state" in chosen:
        profile_rows = sb_clients.sb_get_as_service(
            f"/business_profiles?business_id=eq.{biz}&select=governing_state&limit=1") or []
        gov = ((profile_rows[0].get("governing_state") if profile_rows else "") or "").strip()
        if gov:
            settings = dict(b.get("settings") or {})
            fin = dict(settings.get("financial") or {})
            fin["state"] = gov
            settings["financial"] = fin
            sb_clients.sb_patch_as_service(
                f"/businesses?id=eq.{biz}", {"settings": settings})
            results["financial_state"] = f"tax state set to {gov}"
            audit_log.record(biz, actor_type="chief", actor_id=str(user.id),
                             verb="setup_apply_financial",
                             summary=f"Session setup: tax state set to {gov}",
                             source="desktop")

    # ── Tier 3: whatever is still unconnected becomes a follow-up ────
    seeded = 0
    for c in plan["connects"]:
        if c["done"] or c.get("optional"):
            continue
        dedupe_key = f"setup:{c['id']}"
        existing = sb_clients.sb_get_as_service(
            f"/chief_notifications?business_id=eq.{biz}&status=eq.unread"
            f"&data->>setup_id=eq.{dedupe_key}&select=id&limit=1") or []
        if existing:
            continue
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": biz,
            "type": "info",
            "title": "Finish your setup",
            "body": c["label"],
            "suggested_action": "Take me there",
            "status": "unread",
            "data": {"setup_id": dedupe_key, "nav": c["nav"]},
        }, prefer=None)
        seeded += 1

    logger.info(f"[setup] applied biz={biz[:8]} kinds={chosen} follow_ups={seeded}")
    return {"ok": True, "applied": results, "follow_ups_seeded": seeded,
            "connects": plan["connects"]}
