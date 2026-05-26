"""
platform_console.py — Mission Control / Platform-operator endpoints.

Mounts under /platform/*. Every endpoint requires the caller to BE the
platform owner (require_owner from lead_admin.py — JWT verify + email
match against PLATFORM_OWNER_EMAIL). Service-role key is used for the
underlying data reads so we can see auth.users + all businesses.

Endpoints:
  GET  /platform/practitioners            → list of auth.users + their businesses
  GET  /platform/health                   → backend + DB snapshot
  GET  /platform/subscriptions/summary    → aggregate from billing_status view
  GET  /platform/costs/summary            → 30d cost aggregate from api_usage
  POST /platform/chief/message            → ask the Platform Chief a question

═══════════════════════════════════════════════════════════════════════
ENV
═══════════════════════════════════════════════════════════════════════

Reuses the same envs lead_admin.py needs:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  SUPABASE_JWT_SECRET
  PLATFORM_OWNER_EMAIL (defaults to kmjcreativesolution@gmail.com)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from lead_admin import require_owner, _service_headers, SUPABASE_URL
from api_usage_logger import log_api_usage, _compute_cost_cents


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


# ─── Costs ──────────────────────────────────────────────────────────────

@router.get("/costs/summary")
async def costs_summary(_owner=Depends(require_owner)):
    """Aggregate api_usage_summary_30d (created by api-usage-migration.sql).
    Falls back to zeros if the migration hasn't been run yet."""
    headers = _service_headers()
    rows: List[Dict[str, Any]] = []
    view_present = True
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/api_usage_summary_30d",
            headers=headers,
            params={"select": "*", "order": "cost_cents.desc"},
        )
        if r.status_code in (404, 406):
            view_present = False
        elif r.status_code >= 400:
            logger.warning(f"api_usage_summary fetch {r.status_code}: {r.text[:200]}")
            view_present = False
        else:
            rows = r.json()

    by_business: List[Dict[str, Any]] = []
    total_cents = 0.0
    total_calls = 0
    for row in rows:
        cents = float(row.get("cost_cents") or 0)
        calls = int(row.get("calls") or 0)
        total_cents += cents
        total_calls += calls
        if calls > 0:
            by_business.append({
                "business_id":   row.get("business_id"),
                "business_name": row.get("business_name", "(unnamed)"),
                "calls":         calls,
                "input_tokens":  int(row.get("input_tokens") or 0),
                "output_tokens": int(row.get("output_tokens") or 0),
                "cost_cents":    round(cents, 2),
                "last_call_at":  row.get("last_call_at"),
            })

    return {
        "view_present":      view_present,
        "window_days":       30,
        "total_cost_cents":  round(total_cents, 2),
        "total_calls":       total_calls,
        "top_by_business":   by_business[:10],
        "business_count":    len(by_business),
    }


# ─── Platform Chief ────────────────────────────────────────────────────

PLATFORM_CHIEF_MODEL = os.environ.get("PLATFORM_CHIEF_MODEL", "claude-sonnet-4-5-20250929")

PLATFORM_CHIEF_SYSTEM = (
    "You are the Platform Chief of Staff for the Solutionist System — Kevin's operator-side "
    "advisor. You are NOT the practitioner Chief (warm, encouraging, growth-focused). "
    "You are direct, data-first, and blunt about risk. Think hands-on COO who's read every dashboard.\n\n"
    "Your job: answer Kevin's questions about how the SOLUTIONIST PLATFORM (not any single "
    "practitioner) is doing. Health, growth, costs, risks. Be specific. Quote numbers from the "
    "snapshot. If the snapshot does not have the data, SAY so explicitly — never invent numbers.\n\n"
    "Format: 2-3 sentences for most answers. For 'how is the business' questions, lead with the "
    "single most important fact, then 2-3 supporting bullets. Never long. Always end with one "
    "actionable next step if there is an obvious one.\n\n"
    "You have access to a current snapshot of the platform state. Use it. If Kevin asks about "
    "something not in the snapshot, tell him what blind spot is preventing the answer and what "
    "would close it."
)


class ChiefMessageBody(BaseModel):
    message: str


async def _build_snapshot(headers: Dict[str, str]) -> Dict[str, Any]:
    """Compact platform snapshot for the Chief's system prompt."""
    snap: Dict[str, Any] = {"fetched_at": datetime.now(timezone.utc).isoformat()}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        # Practitioners
        try:
            ur = await c.get(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers={
                    "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                    "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
                },
                params={"per_page": "50"},
            )
            if ur.status_code < 400:
                u = ur.json()
                users = u.get("users", []) if isinstance(u, dict) else u
                snap["practitioners"] = {
                    "total":             len(users),
                    "signed_in_ever":    sum(1 for x in users if x.get("last_sign_in_at")),
                    "recent_signups":    [
                        {"email": x.get("email"), "created_at": x.get("created_at")}
                        for x in users[:5]
                    ],
                }
        except Exception as e:
            snap["practitioners"] = {"error": str(e)}

        async def _head_count(table: str, params: Optional[Dict] = None) -> int:
            try:
                r = await c.head(
                    f"{SUPABASE_URL}/rest/v1/{table}",
                    headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
                    params=params or {},
                )
                if r.status_code in (200, 206):
                    cr = r.headers.get("content-range", "")
                    last = cr.split("/")[-1] if "/" in cr else "0"
                    return int(last) if last and last != "*" else 0
            except Exception:
                pass
            return 0

        snap["businesses_active"] = await _head_count("businesses", {"is_active": "eq.true"})
        snap["leads_new"]         = await _head_count("marketing_leads", {"status": "eq.new"})
        snap["leads_onboarded"]   = await _head_count("marketing_leads", {"status": "eq.onboarded"})

        # Subscriptions
        try:
            sr = await c.get(
                f"{SUPABASE_URL}/rest/v1/billing_status",
                headers=headers,
                params={"select": "subscription_status,trial_days_left"},
            )
            if sr.status_code < 400:
                rows = sr.json()
                by_status: Dict[str, int] = {}
                trials_ending_in_7d = 0
                for row in rows:
                    s = row.get("subscription_status")
                    if s:
                        by_status[s] = by_status.get(s, 0) + 1
                    dl = row.get("trial_days_left")
                    if isinstance(dl, (int, float)) and 0 < dl <= 7:
                        trials_ending_in_7d += 1
                snap["subscriptions"] = {
                    "by_status":            by_status,
                    "trials_ending_in_7d":  trials_ending_in_7d,
                    "stripe_configured":    bool(os.environ.get("STRIPE_SECRET_KEY")),
                }
        except Exception as e:
            snap["subscriptions"] = {"error": str(e)}

        # Costs (last 30d)
        try:
            cr = await c.get(
                f"{SUPABASE_URL}/rest/v1/api_usage_summary_30d",
                headers=headers,
                params={"select": "cost_cents,calls", "limit": "1000"},
            )
            if cr.status_code < 400:
                rows = cr.json()
                total_cents = sum(float(r.get("cost_cents") or 0) for r in rows)
                total_calls = sum(int(r.get("calls") or 0) for r in rows)
                snap["costs_30d"] = {
                    "total_dollars":   round(total_cents / 100.0, 2),
                    "total_calls":     total_calls,
                    "business_count":  sum(1 for r in rows if (r.get("calls") or 0) > 0),
                }
            elif cr.status_code in (404, 406):
                snap["costs_30d"] = {"error": "api-usage-migration.sql not run yet"}
        except Exception as e:
            snap["costs_30d"] = {"error": str(e)}

    snap["blind_spots"] = [
        "Backend errors / Railway log stream (no aggregator wired)",
        "Frontend client errors (no error reporter)",
        "Per-business storage usage (no snapshot job)",
        "Meta token expiry alerts (data exists, no alerting)",
        "Resend bounce / spam complaints (no webhook handler)",
        "Per-agent AI call breakdown (only ai_proxy + chief_of_staff are instrumented)",
    ]
    return snap


@router.post("/chief/message")
async def platform_chief_message(body: ChiefMessageBody, _owner=Depends(require_owner)):
    """Stateless Q&A — builds snapshot, asks Anthropic, returns reply."""
    headers = _service_headers()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    snapshot = await _build_snapshot(headers)
    import json as _json
    system = (
        PLATFORM_CHIEF_SYSTEM
        + "\n\nCURRENT PLATFORM SNAPSHOT:\n```json\n"
        + _json.dumps(snapshot, indent=2, default=str)
        + "\n```"
    )

    started_ms = int(time.time() * 1000)
    payload = {
        "model": PLATFORM_CHIEF_MODEL,
        "max_tokens": 800,
        "temperature": 0.6,
        "system": system,
        "messages": [{"role": "user", "content": body.message}],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0)) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
    except Exception as e:
        raise HTTPException(502, f"Anthropic call failed: {e}")

    if r.status_code >= 400:
        await log_api_usage(
            endpoint="/platform/chief/message", model=PLATFORM_CHIEF_MODEL,
            input_tokens=0, output_tokens=0,
            duration_ms=int(time.time() * 1000) - started_ms,
            ok=False, error=f"{r.status_code}: {r.text[:200]}",
        )
        raise HTTPException(r.status_code, f"Anthropic: {r.text[:200]}")

    data = r.json()
    content_blocks = data.get("content", [])
    text = "".join(
        b.get("text", "")
        for b in content_blocks
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()
    usage = data.get("usage", {})

    await log_api_usage(
        endpoint="/platform/chief/message",
        model=data.get("model", PLATFORM_CHIEF_MODEL),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        duration_ms=int(time.time() * 1000) - started_ms,
    )

    return {
        "reply":         text,
        "model":         data.get("model"),
        "usage":         usage,
        "snapshot_keys": list(snapshot.keys()),
    }
