"""
platform_console.py — Mission Control / Platform-operator endpoints.

Mounts under /platform/*. Every endpoint requires the caller to BE the
platform owner (require_owner from lead_admin.py — JWT verify + email
match against PLATFORM_OWNER_EMAIL). Service-role key is used for the
underlying data reads so we can see auth.users + all businesses.

Endpoints:
  GET /platform/practitioners            → list of auth.users + their businesses
  GET /platform/health                   → backend + DB snapshot
  GET /platform/subscriptions/summary    → aggregate from billing_status view

═══════════════════════════════════════════════════════════════════════
ENV
═══════════════════════════════════════════════════════════════════════

Reuses the same envs lead_admin.py needs:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  SUPABASE_JWT_SECRET
  PLATFORM_OWNER_EMAIL (defaults to parkerron1971@gmail.com)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from lead_admin import require_owner, _service_headers, SUPABASE_URL


logger = logging.getLogger("platform_console")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] platform: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


router = APIRouter(prefix="/platform", tags=["platform-console"])


HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)
PROCESS_START = time.time()
BACKEND_VERSION = os.environ.get("BACKEND_VERSION", "unknown")

# Tables whose row counts we surface on the health panel. Picked to
# cover the most informative signals — the rest are easy to derive
# from these.
HEALTH_ROW_COUNT_TABLES = [
    "businesses",
    "contacts",
    "invoices",
    "marketing_leads",
    "products",
    "sessions",
    "tasks",
    "chief_conversations",
    "social_accounts",
    "stripe_webhook_events",
]

# Things the platform currently has zero visibility on. Surfaced on
# the health panel so the operator knows where they're blind.
BLIND_SPOTS = [
    "Anthropic token usage per practitioner (needs api_usage table + AI proxy logging)",
    "Backend error stream (Railway logs are the only source today)",
    "Frontend client errors (no error reporter wired)",
    "Per-business storage usage (Supabase storage bucket totals)",
    "Meta token expiry warnings (we know when they expire but don't alert)",
    "Resend bounce / spam complaints (no webhook handler yet)",
]


# ─── Practitioners ──────────────────────────────────────────────────────

@router.get("/practitioners")
async def list_practitioners(_owner=Depends(require_owner)):
    """Join auth.users with public.businesses. Returned shape matches
    `Practitioner` in src/modules/platform/lib/platformApi.ts."""
    headers = _service_headers()

    # 1. Auth users — only available via the /auth/v1/admin/users endpoint
    #    (PostgREST can't see the auth schema). Paginated; for now we
    #    pull the first 200 since we're in private beta. Extend later.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        ur = await c.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers={
                "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
            },
            params={"per_page": "200"},
        )
    if ur.status_code >= 400:
        logger.error(f"auth users fetch {ur.status_code}: {ur.text[:300]}")
        raise HTTPException(status_code=502, detail=f"Auth admin fetch failed: {ur.text[:200]}")
    users_payload = ur.json() if ur.text else {}
    users = users_payload.get("users", []) if isinstance(users_payload, dict) else users_payload

    # 2. Businesses — pull all rows, group by owner_id in memory.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        br = await c.get(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={
                "select": "id,name,owner_id,subscription_status,trial_ends_at",
                "is_active": "eq.true",
            },
        )
    if br.status_code >= 400:
        logger.error(f"businesses fetch {br.status_code}: {br.text[:300]}")
        raise HTTPException(status_code=502, detail=f"Businesses fetch failed: {br.text[:200]}")
    businesses = br.json()

    biz_by_owner: Dict[str, List[Dict[str, Any]]] = {}
    for b in businesses:
        owner_id = b.get("owner_id")
        if not owner_id:
            continue
        biz_by_owner.setdefault(owner_id, []).append(b)

    out: List[Dict[str, Any]] = []
    for u in users:
        uid = u.get("id")
        owned = biz_by_owner.get(uid, [])
        # Pick the "most-relevant" subscription state from owned businesses:
        # active > trialing > anything else > None.
        rank = {"active": 4, "trialing": 3, "past_due": 2, "canceled": 1}
        owned_sorted = sorted(owned, key=lambda b: rank.get(b.get("subscription_status") or "", 0), reverse=True)
        head_sub = owned_sorted[0] if owned_sorted else None

        out.append({
            "id": uid,
            "email": u.get("email"),
            "created_at": u.get("created_at"),
            "last_sign_in_at": u.get("last_sign_in_at"),
            "business_count": len(owned),
            "business_names": [b.get("name", "(unnamed)") for b in owned],
            "subscription_status": (head_sub or {}).get("subscription_status"),
            "trial_ends_at": (head_sub or {}).get("trial_ends_at"),
        })

    # Newest first
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


# ─── Health ─────────────────────────────────────────────────────────────

@router.get("/health")
async def platform_health(_owner=Depends(require_owner)):
    """Snapshot used by SystemHealthPanel."""
    headers = _service_headers()

    row_counts: Dict[str, int] = {}
    supabase_ok = True

    # Counts via PostgREST. Prefer: count=exact in the response header.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for tbl in HEALTH_ROW_COUNT_TABLES:
            try:
                r = await c.head(
                    f"{SUPABASE_URL}/rest/v1/{tbl}",
                    headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
                )
                if r.status_code in (200, 206):
                    content_range = r.headers.get("content-range", "")
                    # Format: "0-0/123" or "*/0"
                    total = content_range.split("/")[-1] if "/" in content_range else "0"
                    try:
                        row_counts[tbl] = int(total) if total and total != "*" else 0
                    except ValueError:
                        row_counts[tbl] = 0
                elif r.status_code in (404, 406):
                    # Table doesn't exist (migration not run); skip silently.
                    pass
                else:
                    supabase_ok = False
                    logger.warning(f"row count for {tbl} failed: {r.status_code} {r.text[:120]}")
            except Exception as e:
                supabase_ok = False
                logger.warning(f"row count for {tbl} exception: {e}")

    # Recent webhook failures — stripe_webhook_events rows with processed_at IS NULL.
    recent_webhook_failures = 0
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.head(
                f"{SUPABASE_URL}/rest/v1/stripe_webhook_events",
                headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
                params={"processed_at": "is.null"},
            )
            if r.status_code in (200, 206):
                cr = r.headers.get("content-range", "")
                total = cr.split("/")[-1] if "/" in cr else "0"
                try:
                    recent_webhook_failures = int(total) if total and total != "*" else 0
                except ValueError:
                    pass
    except Exception:
        pass  # billing-migration may not have run; treat as zero

    return {
        "backend_ok": True,                       # we are this endpoint, by definition
        "backend_version": BACKEND_VERSION,
        "uptime_s": time.time() - PROCESS_START,
        "supabase_ok": supabase_ok,
        "row_counts": row_counts,
        "recent_webhook_failures": recent_webhook_failures,
        "blind_spots": BLIND_SPOTS,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Subscriptions ──────────────────────────────────────────────────────

@router.get("/subscriptions/summary")
async def subscriptions_summary(_owner=Depends(require_owner)):
    """Aggregate the billing_status view. Until Phase 5b populates the
    subscription columns, every business comes back with NULLs and the
    aggregate reflects that ('all on free tier')."""
    headers = _service_headers()
    stripe_configured = bool(os.environ.get("STRIPE_SECRET_KEY"))

    rows: List[Dict[str, Any]] = []
    view_present = True
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/billing_status",
            headers=headers,
            params={"select": "*", "limit": "1000"},
        )
        if r.status_code in (404, 406):
            view_present = False
        elif r.status_code >= 400:
            logger.warning(f"billing_status fetch {r.status_code}: {r.text[:200]}")
            view_present = False
        else:
            rows = r.json()

    by_status: Dict[str, int] = {}
    trial_ending_soon: List[Dict[str, Any]] = []
    payment_issues: List[Dict[str, Any]] = []
    total_businesses = 0
    mrr_cents = 0  # Computed once we have subscription_plan + Stripe price metadata; placeholder for now

    if view_present:
        total_businesses = len(rows)
        for row in rows:
            stat = row.get("subscription_status")
            if stat:
                by_status[stat] = by_status.get(stat, 0) + 1
            days_left = row.get("trial_days_left")
            if isinstance(days_left, (int, float)) and 0 < days_left <= 7:
                trial_ending_soon.append({
                    "business_id":    row.get("business_id"),
                    "business_name":  row.get("business_name", "(unnamed)"),
                    "trial_days_left": days_left,
                })
            if stat in ("past_due", "unpaid", "incomplete"):
                payment_issues.append({
                    "business_id":   row.get("business_id"),
                    "business_name": row.get("business_name", "(unnamed)"),
                    "status":        stat,
                })
    else:
        # Migration not run; fall back to a businesses count so the
        # frontend still has something to show.
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            br = await c.head(
                f"{SUPABASE_URL}/rest/v1/businesses",
                headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
                params={"is_active": "eq.true"},
            )
            if br.status_code in (200, 206):
                cr = br.headers.get("content-range", "")
                try:
                    total_businesses = int(cr.split("/")[-1])
                except (ValueError, IndexError):
                    pass

    # Sort: most-urgent first
    trial_ending_soon.sort(key=lambda r: r["trial_days_left"])

    return {
        "total_businesses":     total_businesses,
        "by_status":            by_status,
        "trial_ending_soon":    trial_ending_soon,
        "payment_issues":       payment_issues,
        "mrr_cents":            mrr_cents,
        "stripe_configured":    stripe_configured,
    }
