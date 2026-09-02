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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

import llm_call
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from lead_admin import require_owner, _service_headers, SUPABASE_URL
from api_usage_logger import log_api_usage, _compute_cost_cents
from platform_chief_actions import (
    extract_actions, strip_action_tags, dispatch_actions,
)


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
# ─── The API registry (beta-readiness arc, 2026-07-11) ────────────────
# Every external service the platform talks to: which env vars wire it
# (NAMES only — values never leave the process), what it powers, and
# where the code touches it. /platform/health reports configured-or-not
# per service so Mission Control shows the whole dependency surface.
API_REGISTRY: List[Dict[str, Any]] = [
    {"id": "supabase",  "name": "Supabase",       "envs": ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET"],
     "powers": "Database, auth, RLS, storage, realtime — the system of record",
     "touchpoints": "sb_clients.py, every router"},
    {"id": "anthropic", "name": "Anthropic (Claude)", "envs": ["ANTHROPIC_API_KEY"],
     "powers": "Chief chat + reasoning lanes, site composer, atelier, DRL, module composer",
     "touchpoints": "chief_llm.py, chief_models.py, site_composer.py, atelier.py"},
    {"id": "openai",    "name": "OpenAI",          "envs": ["OPENAI_API_KEY"],
     "powers": "Chief voice (TTS), Whisper transcription, inference-gate embeddings",
     "touchpoints": "whisper_proxy.py (/ai/tts/speak, /ai/whisper), inference gate"},
    {"id": "twilio",    "name": "Twilio",          "envs": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
     "powers": "SMS rail — keywords, two-way texting, booking reminders",
     "touchpoints": "sms_service.py, sms_routing.py, sms_alerts.py"},
    {"id": "resend",    "name": "Resend",          "envs": ["RESEND_API_KEY"],
     "powers": "Transactional + nurture email, ticket replies, reports",
     "touchpoints": "email senders in chief_of_staff.py / agents"},
    {"id": "stripe",    "name": "Stripe",          "envs": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
     "powers": "Subscriptions, payment links, PAYG billing (dormant until enforcement)",
     "touchpoints": "billing routers, stripe_webhook_events"},
    {"id": "meta",      "name": "Meta (FB/IG)",    "envs": ["META_APP_ID", "META_APP_SECRET"],
     "powers": "Facebook + Instagram OAuth and post publishing",
     "touchpoints": "meta integration router"},
    {"id": "meta_ads",  "name": "Meta Ads (Pixel + CAPI)", "envs": ["META_PIXEL_ID", "META_CAPI_ACCESS_TOKEN"],
     "powers": "Ad measurement for the platform's own marketing — pixel on mysolutionist.app + server-side Lead / CompleteRegistration / Subscribe conversions",
     "touchpoints": "meta_capi.py, marketing_pages.py, launch_access.py, stripe_billing.py"},
    {"id": "meta_spend", "name": "Meta Ads spend (read-only)", "envs": ["META_ADS_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"],
     "powers": "Ad spend + CAC on the Growth panel — campaigns stay managed in Ads Manager; this only reads what they cost",
     "touchpoints": "meta_ads.py, platform_console.py:/platform/growth"},
    {"id": "webpush",   "name": "Web Push (VAPID)", "envs": ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"],
     "powers": "Chief notifications to phones (PWA push)",
     "touchpoints": "push sender"},
    {"id": "github",    "name": "GitHub (builder bridge)", "envs": ["GITHUB_TOKEN"],
     "powers": "Chief → Claude Code dispatch: build requests become @claude issues that build themselves",
     "touchpoints": "chief_of_staff.py:_fire_build_issue"},
    {"id": "googlefonts", "name": "Google Fonts",  "envs": [],
     "powers": "Font pairings on composed sites (css2 endpoint, no key)",
     "touchpoints": "brand_dna.py"},
]


def _api_registry_status() -> List[Dict[str, Any]]:
    """Registry + configured flag per service (env NAMES only)."""
    out: List[Dict[str, Any]] = []
    for svc in API_REGISTRY:
        envs = svc.get("envs", [])
        missing = [e for e in envs if not (os.environ.get(e) or "").strip()]
        out.append({
            **svc,
            "configured": not missing,
            "missing_envs": missing,
        })
    return out


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
        "services": _api_registry_status(),
        "blind_spots": BLIND_SPOTS,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Builder model control (Mission Control -> System Health) ──────────
# The cloud-build workflows read the repo variable CLAUDE_BUILD_MODEL;
# these endpoints let Kevin flip it live. Requires the Railway
# GITHUB_TOKEN to carry "Variables: read and write" on both repos.

BUILD_MODEL_REPOS = [
    "parkerron1971-hash/solutionist-studio",
    "parkerron1971-hash/kmj-intake-server",
]
BUILD_MODELS_ALLOWED = ["claude-fable-5", "claude-opus-4-8", "claude-sonnet-5"]
BUILD_MODEL_DEFAULT = "claude-fable-5"
_BUILD_VAR = "CLAUDE_BUILD_MODEL"
_AUTOMERGE_VAR = "CLAUDE_AUTO_MERGE"   # absent = 'on' (workflow default)


async def _get_repo_var(c: "httpx.AsyncClient", headers: Dict[str, str],
                        repo: str, name: str, default: str) -> str:
    try:
        r = await c.get(
            f"https://api.github.com/repos/{repo}/actions/variables/{name}",
            headers=headers)
        if r.status_code == 200:
            return r.json().get("value") or default
    except Exception:
        pass
    return default


async def _set_repo_var(c: "httpx.AsyncClient", headers: Dict[str, str],
                        repo: str, name: str, value: str) -> str:
    try:
        r = await c.patch(
            f"https://api.github.com/repos/{repo}/actions/variables/{name}",
            headers=headers, json={"name": name, "value": value})
        if r.status_code == 404:
            r = await c.post(
                f"https://api.github.com/repos/{repo}/actions/variables",
                headers=headers, json={"name": name, "value": value})
        return "ok" if r.status_code in (201, 204) else (
            f"failed ({r.status_code} — token may need Variables read/write)")
    except Exception as e:
        return f"failed ({e})"


def _gh_headers() -> Dict[str, str]:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    } if token else {}


@router.get("/build-model")
async def get_build_model(_owner=Depends(require_owner)):
    """Current cloud-build model per repo (repo variable, default Fable 5)."""
    headers = _gh_headers()
    out: Dict[str, Any] = {"allowed": BUILD_MODELS_ALLOWED,
                           "default": BUILD_MODEL_DEFAULT,
                           "configured": bool(headers), "repos": {}}
    out["auto_merge"] = {}
    if not headers:
        return out
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for repo in BUILD_MODEL_REPOS:
            out["repos"][repo] = await _get_repo_var(
                c, headers, repo, _BUILD_VAR, BUILD_MODEL_DEFAULT)
            out["auto_merge"][repo] = await _get_repo_var(
                c, headers, repo, _AUTOMERGE_VAR, "on")
    return out


class BuildModelBody(BaseModel):
    model: Optional[str] = None
    auto_merge: Optional[str] = None   # 'on' | 'off'


@router.post("/build-model")
async def set_build_model(body: BuildModelBody, _owner=Depends(require_owner)):
    """Set builder controls on BOTH repos (upsert repo variables):
    model (CLAUDE_BUILD_MODEL) and/or auto_merge (CLAUDE_AUTO_MERGE)."""
    model = (body.model or "").strip()
    auto = (body.auto_merge or "").strip().lower()
    if not model and not auto:
        raise HTTPException(400, "provide model and/or auto_merge")
    if model and model not in BUILD_MODELS_ALLOWED:
        raise HTTPException(400, f"model must be one of {BUILD_MODELS_ALLOWED}")
    if auto and auto not in ("on", "off"):
        raise HTTPException(400, "auto_merge must be 'on' or 'off'")
    headers = _gh_headers()
    if not headers:
        raise HTTPException(503, "GITHUB_TOKEN not configured on the backend")
    results: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for repo in BUILD_MODEL_REPOS:
            parts = []
            if model:
                parts.append(f"model {await _set_repo_var(c, headers, repo, _BUILD_VAR, model)}")
            if auto:
                parts.append(f"auto-merge {await _set_repo_var(c, headers, repo, _AUTOMERGE_VAR, auto)}")
            results[repo] = "; ".join(parts)
    return {"model": model or None, "auto_merge": auto or None, "results": results}


# ─── Watchdog + error stream (beta-readiness arc) ───────────────────────

@router.get("/watchdog")
async def platform_watchdog_view(run: int = 0, _owner=Depends(require_owner)):
    """Latest autonomous sweep; ?run=1 forces a fresh pass now."""
    import platform_watchdog as wd
    if run:
        snap = await wd.watchdog_sweep()
    else:
        snap = wd.LAST_SWEEP or await wd.watchdog_sweep()
    return {"enabled": wd.watchdog_enabled(), **snap}


@router.get("/errors")
async def platform_errors(limit: int = 100, _owner=Depends(require_owner)):
    """The in-process error ring buffer (server + [client]-tagged)."""
    import platform_watchdog as wd
    return {"errors": wd.recent_errors(limit)}


@router.get("/ledger/anchor-health")
async def ledger_anchor_health(days: int = 7,
                               _owner=Depends(require_owner)) -> Dict[str, Any]:
    """Is the Action Ledger actually being anchored, on each network?

    WHY THIS IS PLATFORM AND NOT PER-BUSINESS. A practitioner's question
    is "is MY record provable", and the ledger surfaces in their room
    already answer it. This one is the operator's question — "is the
    anchoring infrastructure working at all, for anyone" — which is
    exactly the Mission Control boundary.

    WHY IT EXISTS. Running two providers only buys anything if a
    provider going quiet is noticed. Until this endpoint the only
    evidence of a failed publish was a log line on Railway, which in
    practice meant a network could stop working indefinitely with
    nothing anywhere to say so.

    PLATFORM-WIDE, SO SERVICE ROLE. This deliberately reads across every
    tenant, which no practitioner-facing route may do — the owner gate
    above is the whole reason that is acceptable here.
    """
    import ledger_anchor
    # Bounded so a stray ?days=100000 cannot turn a health check into a
    # full-table scan against every tenant's anchors at once.
    return ledger_anchor.anchor_health(days=max(1, min(int(days), 90)))


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
    # Launch-ops (2026-07-03): real MRR — active subs' price ids map to
    # plan names via env, plan names to list price. Was a hardcoded 0.
    mrr_cents = 0
    try:
        from feature_gates import price_to_plan as _p2p
        from usage_metering import TIER_PRICE_CENTS as _tier_cents
        _price_map = _p2p()
    except Exception:
        _price_map, _tier_cents = {}, {}

    if view_present:
        total_businesses = len(rows)
        for row in rows:
            stat = row.get("subscription_status")
            if stat:
                by_status[stat] = by_status.get(stat, 0) + 1
            if stat == "active":
                _plan = _price_map.get(row.get("subscription_plan") or "")
                if _plan:
                    mrr_cents += _tier_cents.get(_plan, 0)
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


# ─── Growth — the funnel by channel (GROWTH ARC Rung 1) ────────────────

def _channel_of(attribution: Optional[Dict[str, Any]]) -> Optional[str]:
    """One label per funnel row. utm_source is the tag the link went out
    with; the ad-click ids and the referrer host are the fallbacks for
    untagged links. None = the row carries no attribution at all (older
    than the feature, or genuinely untraceable) — callers label that
    "untracked", which is honest where "direct" would be a claim."""
    a = attribution if isinstance(attribution, dict) else None
    if not a:
        return None
    src = a.get("utm_source")
    if src:
        return str(src).strip().lower()[:60] or "direct"
    if a.get("gclid"):
        return "google-ads"
    if a.get("fbclid"):
        return "facebook"
    host = a.get("referrer_host")
    if host:
        return str(host).strip().lower()[:60]
    if a.get("ref"):
        return "referral"
    return "direct"


@router.get("/growth")
async def growth_summary(days: int = 30, _owner=Depends(require_owner)):
    """The marketing scoreboard: visits → leads → waitlist → signups →
    paying, grouped by the door people walked in through.

    Window semantics: sessions, leads, waitlist and signups count the
    last `days` only. businesses_total, active_subs and mrr_cents are
    ALL-TIME per channel — revenue stays attributed to the door that
    produced it, however long ago the walk-in happened.
    """
    days = max(1, min(int(days or 30), 365))
    since = ((datetime.now(timezone.utc) - timedelta(days=days))
             .isoformat().replace("+00:00", "Z"))
    headers = _service_headers()

    try:
        from feature_gates import price_to_plan as _p2p
        from usage_metering import TIER_PRICE_CENTS as _tier_cents
        _price_map = _p2p()
    except Exception:
        _price_map, _tier_cents = {}, {}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        async def _get(path: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
            """Missing table/column (pre-migration) degrades to [] —
            the panel renders what exists rather than erroring whole."""
            try:
                r = await c.get(f"{SUPABASE_URL}/rest/v1/{path}",
                                headers=headers, params=params)
                return r.json() if r.status_code < 400 else []
            except Exception as e:
                logger.warning(f"growth fetch {path} failed: {e}")
                return []

        businesses = await _get("businesses", {
            "select": "id,name,created_at,attribution,subscription_status,subscription_plan",
            "is_active": "eq.true", "limit": "2000"})
        leads = await _get("marketing_leads", {
            "select": "id,created_at,status,attribution",
            "created_at": f"gte.{since}", "limit": "2000"})
        waitlist = await _get("waitlist", {
            "select": "id,created_at,attribution",
            "created_at": f"gte.{since}", "limit": "2000"})
        events = await _get("site_events", {
            "select": "session_id,event,data",
            "business_id": "is.null", "ts": f"gte.{since}",
            "limit": "50000"})

    def _bucket() -> Dict[str, Any]:
        return {"sessions": 0, "leads": 0, "waitlist": 0, "signups": 0,
                "businesses_total": 0, "active_subs": 0, "mrr_cents": 0}

    channels: Dict[str, Dict[str, Any]] = {}

    def _row(label: str) -> Dict[str, Any]:
        return channels.setdefault(label, _bucket())

    def _ch(attribution: Any) -> str:
        return _channel_of(attribution) or "untracked"

    # Marketing-site traffic: distinct sessions per channel. A session's
    # first campaign-carrying event names its channel; sessions that
    # never carried one are untracked (organic direct, mostly).
    session_channel: Dict[str, str] = {}
    all_sessions: set = set()
    for e in events:
        sid = e.get("session_id")
        if not sid:
            continue
        all_sessions.add(sid)
        ch = _channel_of(e.get("data"))
        if ch and sid not in session_channel:
            session_channel[sid] = ch
    for sid in all_sessions:
        _row(session_channel.get(sid, "untracked"))["sessions"] += 1

    for l in leads:
        _row(_ch(l.get("attribution")))["leads"] += 1
    for w in waitlist:
        _row(_ch(w.get("attribution")))["waitlist"] += 1

    signups_window = 0
    active_total = 0
    mrr_total = 0
    for b in businesses:
        row = _row(_ch(b.get("attribution")))
        row["businesses_total"] += 1
        if (b.get("created_at") or "") >= since:
            row["signups"] += 1
            signups_window += 1
        if b.get("subscription_status") == "active":
            row["active_subs"] += 1
            active_total += 1
            plan = _price_map.get(b.get("subscription_plan") or "")
            if plan:
                cents = _tier_cents.get(plan, 0)
                row["mrr_cents"] += cents
                mrr_total += cents

    lead_statuses: Dict[str, int] = {}
    for l in leads:
        st = l.get("status") or "new"
        lead_statuses[st] = lead_statuses.get(st, 0) + 1

    ordered = sorted(
        ({"channel": k, **v} for k, v in channels.items()),
        key=lambda r: (r["mrr_cents"], r["signups"], r["leads"], r["sessions"]),
        reverse=True)

    recent = sorted(businesses, key=lambda b: b.get("created_at") or "",
                    reverse=True)[:15]
    recent_signups = [{
        "name": b.get("name") or "(unnamed)",
        "created_at": b.get("created_at"),
        "channel": _ch(b.get("attribution")),
        "subscription_status": b.get("subscription_status"),
    } for b in recent]

    # Rung 3 — spend next to what it bought. Dark ({"configured": False},
    # no card rendered) until META_ADS_ACCESS_TOKEN + META_AD_ACCOUNT_ID
    # are set. CAC divides Meta spend by the window's Meta-channel
    # signups — both sides measured here, so the number is honest, and
    # None whenever either side is zero rather than a fake $0.
    import meta_ads
    ads = await meta_ads.spend_summary(days)
    if ads.get("configured"):
        paid_signups = sum(v["signups"] for k, v in channels.items()
                           if k in ("facebook", "instagram", "meta", "fb", "ig"))
        ads["paid_signups_window"] = paid_signups
        ads["cac_cents"] = (int(ads["spend_cents"] / paid_signups)
                            if ads.get("ok") and ads.get("spend_cents") and paid_signups
                            else None)

    return {
        "ok": True,
        "days": days,
        "totals": {
            "sessions": len(all_sessions),
            "leads": len(leads),
            "waitlist": len(waitlist),
            "signups": signups_window,
            "active_subs": active_total,
            "mrr_cents": mrr_total,
        },
        "channels": ordered,
        "recent_signups": recent_signups,
        "lead_statuses": lead_statuses,
        "truncated_traffic": len(events) >= 50000,
        "ads": ads,
    }


# ─── The platform's own business (dogfood books) ───────────────────────
# Kevin's ruling 2026-07-03: The Solutionist System is its own company —
# its books run INSIDE Solutionist (a business flagged
# settings.platform_books=true under the owner's account). Mission
# Control's Money & Website page sets it up and tracks it from here.

PLATFORM_BIZ_NAME = "The Solutionist System"


async def _find_platform_business(c: httpx.AsyncClient, headers: Dict[str, str],
                                  owner_id: str) -> Optional[Dict[str, Any]]:
    r = await c.get(
        f"{SUPABASE_URL}/rest/v1/businesses",
        headers=headers,
        params={
            "owner_id": f"eq.{owner_id}",
            "settings->>platform_books": "eq.true",
            "select": "id,name,created_at,settings",
            "limit": "1",
        },
    )
    if r.status_code < 400:
        rows = r.json() or []
        if rows:
            return rows[0]
    return None


@router.get("/business/platform-books")
async def platform_books_status(owner=Depends(require_owner)):
    """Does the platform's own business exist yet, and is its bank on?

    Fix (2026-07-03): the connection record is the plaid_items row —
    written by /plaid/exchange the moment Link succeeds. plaid_accounts
    only populates after the FIRST transactions sync, so checking it
    showed "not connected" right after a successful connect (Kevin got
    Plaid's confirmation email while the chip said no). Items first,
    accounts as a legacy fallback."""
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        biz = await _find_platform_business(c, headers, str(owner.id))
        plaid_connected = False
        institution = None
        if biz:
            try:
                pr = await c.get(
                    f"{SUPABASE_URL}/rest/v1/plaid_items",
                    headers=headers,
                    params={
                        "business_id": f"eq.{biz['id']}",
                        "select": "item_id,institution_name,status",
                        "limit": "5",
                    },
                )
                if pr.status_code < 400:
                    items = pr.json() or []
                    live = [i for i in items
                            if (i.get("status") or "active") not in ("revoked", "removed")]
                    if live:
                        plaid_connected = True
                        institution = live[0].get("institution_name")
            except Exception:
                pass
            if not plaid_connected:
                try:
                    pr = await c.get(
                        f"{SUPABASE_URL}/rest/v1/plaid_accounts",
                        headers=headers,
                        params={"business_id": f"eq.{biz['id']}", "select": "id", "limit": "1"},
                    )
                    plaid_connected = pr.status_code < 400 and bool(pr.json())
                except Exception:
                    pass
    return {"ok": True, "exists": bool(biz), "business": biz,
            "plaid_connected": plaid_connected,
            "institution": institution}


@router.post("/business/platform-setup")
async def platform_books_setup(owner=Depends(require_owner)):
    """Idempotent: create the platform's own business under the owner's
    account (settings.platform_books=true) if it doesn't exist yet."""
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        existing = await _find_platform_business(c, headers, str(owner.id))
        if existing:
            return {"ok": True, "created": False, "business": existing}
        r = await c.post(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            json={
                "owner_id": str(owner.id),
                "name": PLATFORM_BIZ_NAME,
                "type": "saas",
                "settings": {
                    "platform_books": True,
                    "practitioner_name": "Kevin McCloud Jr.",
                },
            },
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"platform business insert failed: {r.text[:300]}")
        rows = r.json()
        biz = rows[0] if isinstance(rows, list) and rows else rows
        logger.info(f"platform business created: {biz.get('id')}")
    return {"ok": True, "created": True, "business": biz}


@router.get("/subscriptions/list")
async def subscriptions_list(_owner=Depends(require_owner)):
    """The subscriber ROSTER (2026-07-03): every business with its
    subscription state, tier, comp/grandfather flags, and the computed
    access verdict — so Mission Control knows exactly who has one, who
    pays, and who would lose access under enforcement."""
    import feature_gates
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        br = await c.get(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={
                "select": "id,name,owner_id,subscription_status,subscription_plan,"
                          "trial_ends_at,comp_tier,created_at",
                "is_active": "eq.true",
                "order": "created_at.desc",
                "limit": "500",
            },
        )
        if br.status_code >= 400:
            # comp_tier column may be missing pre-migration — retry without it.
            br = await c.get(
                f"{SUPABASE_URL}/rest/v1/businesses",
                headers=headers,
                params={
                    "select": "id,name,owner_id,subscription_status,subscription_plan,"
                              "trial_ends_at,created_at",
                    "is_active": "eq.true",
                    "order": "created_at.desc",
                    "limit": "500",
                },
            )
        if br.status_code >= 400:
            raise HTTPException(502, f"businesses fetch failed: {br.text[:200]}")
        businesses = br.json() or []

        # One batched read: which owners are grandfathered.
        gf: set = set()
        try:
            gr = await c.get(
                f"{SUPABASE_URL}/rest/v1/user_profiles",
                headers=headers,
                params={"is_grandfathered": "is.true", "select": "user_id", "limit": "1000"},
            )
            if gr.status_code < 400:
                gf = {str(x.get("user_id")) for x in (gr.json() or [])}
        except Exception:
            pass

    out: List[Dict[str, Any]] = []
    price_map = feature_gates.price_to_plan()
    for b in businesses:
        grandfathered = str(b.get("owner_id")) in gf
        state = feature_gates.access_state(b, grandfathered)
        out.append({
            "business_id":         b.get("id"),
            "name":                b.get("name"),
            "subscription_status": b.get("subscription_status"),
            "plan":                feature_gates.plan_of(b),
            "stripe_plan":         price_map.get(b.get("subscription_plan") or ""),
            "comp_tier":           b.get("comp_tier"),
            "grandfathered":       grandfathered,
            "trial_ends_at":       b.get("trial_ends_at"),
            "created_at":          b.get("created_at"),
            "access_state":        state["state"],
            "access_reason":       state["reason"],
        })
    return {"ok": True, "rows": out, "enforce": feature_gates.enforcement_on()}


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
    "advisor and chief of operations. You are NOT the practitioner Chief (warm, encouraging, "
    "growth-focused). You are direct, data-first, and blunt about risk. Think hands-on COO who "
    "has read every dashboard AND can take action.\n\n"
    "Your job is twofold:\n"
    "  1. ANSWER Kevin's questions about how the SOLUTIONIST PLATFORM (not any single practitioner) "
    "     is doing. Health, growth, costs, risks.\n"
    "  2. TAKE ACTIONS on his behalf when he asks you to (or when it is clearly implied) — extend "
    "     trials, resend invites, email practitioners, bump lead status.\n\n"
    "Be specific. Quote numbers from the snapshot. If the snapshot does not have the data, SAY so "
    "explicitly — never invent numbers.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "THE BUSINESS YOU ADVISE (strategic context — Kevin's company, not a practitioner's)\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "  • Product: The Solutionist System — an AI-powered business operating system for solo\n"
    "    practitioners and small studios (barbers, coaches, lawyers, ministries, creators…).\n"
    "    One workspace replaces ~8 tools: contacts, invoicing, bookkeeping, scheduling, content,\n"
    "    brand, sites, goals — commanded by a per-business AI Chief of Staff.\n"
    "  • Stage: invite-only private beta. Revenue engine exists (Stripe + hybrid subscription\n"
    "    + usage-overage pricing: Starter $79 / Professional $199 / Agency $399 hypothesis) but\n"
    "    the paying base is small — treat every practitioner as strategically significant.\n"
    "  • Moats to protect and deepen: (1) the Chief — context-rich, acts not just answers;\n"
    "    (2) vertical archetypes + terminology (a barber and a lawyer each see THEIR business);\n"
    "    (3) the module composer — custom modules without code; (4) all-in-one at SMB price.\n"
    "  • Owner: Kevin McCloud Jr., KMJ Creative Solutions LLC (Michigan). Solo founder building\n"
    "    with AI leverage — recommendations must fit a one-person company's execution budget.\n\n"
    "ADVISOR MODE — when Kevin asks about direction, expansion, pricing, or 'am I on the right\n"
    "path': this is your highest-value job. Structure those answers as:\n"
    "  1. **The honest read** — what the snapshot actually says, good and bad. Facts first.\n"
    "  2. **The constraint** — the ONE thing most limiting growth right now.\n"
    "  3. **The move** — 1-3 concrete next plays, sized for a solo founder's week.\n"
    "  4. **What would change your mind** — the data that would raise confidence either way.\n"
    "Label judgment as judgment. Small numbers are normal at this stage — never dress them up,\n"
    "and never catastrophize them either. Beta-stage wins are retention, activation, and word\n"
    "of mouth, not raw MRR.\n\n"
    "Format: 2-3 sentences for most answers. For 'how is the business' and advisor-mode\n"
    "questions, lead with the single most important fact, then short supporting bullets. Never\n"
    "long. Always end with one actionable next step if there is an obvious one. You may use\n"
    "light markdown — **bold** for the headline fact, '-' bullets, and short '###' headings on\n"
    "structured answers — the console renders it properly.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "ACTION VOCABULARY (use sparingly — only when clearly asked or when the next step is obvious)\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "To take an action, EMBED it in your reply text using this exact pattern:\n\n"
    "    [ACTION:{\"type\":\"...\", ...}]\n\n"
    "The system will execute the action and the operator sees the result as a card under your "
    "message. You can take multiple actions in one reply.\n\n"
    "Available actions:\n\n"
    "  • [ACTION:{\"type\":\"extend_trial\",\"business_id\":\"<uuid>\",\"days\":14,\"reason\":\"...\"}]\n"
    "      Pushes their trial_ends_at out by N days.\n\n"
    "  • [ACTION:{\"type\":\"resend_invite\",\"lead_id\":\"<uuid>\",\"reason\":\"...\"}]\n"
    "      Re-fires the Supabase invite email for a marketing_leads row.\n\n"
    "  • [ACTION:{\"type\":\"send_practitioner_email\",\"business_id\":\"<uuid>\",\"subject\":\"...\",\"body\":\"...\",\"reason\":\"...\"}]\n"
    "      Sends a direct email to a practitioner. Draft the body yourself — warm + concise.\n\n"
    "  • [ACTION:{\"type\":\"mark_lead_status\",\"lead_id\":\"<uuid>\",\"status\":\"contacted\"|\"qualified\"|\"declined\"|\"archived\",\"note\":\"...\"}]\n"
    "      Bumps a marketing_leads.status with an optional internal note.\n\n"
    "  • [ACTION:{\"type\":\"log_platform_note\",\"category\":\"shipped\"|\"config\"|\"decision\"|\"pending\"|\"note\",\"title\":\"...\",\"detail\":\"...\"}]\n"
    "      Writes an entry to the operator log (your memory of the business).\n\n"
    "  • [ACTION:{\"type\":\"resolve_platform_note\",\"note_id\":<id from the snapshot's operator_log>}]\n"
    "      Marks a pending log entry done.\n\n"
    "  • [ACTION:{\"type\":\"queue_build\",\"title\":\"...\",\"details\":\"full brief: what, where, why, constraints\",\"repo\":\"frontend\"}]\n"
    "      THE BUILDER BRIDGE: dispatches a build/fix/feature straight to Claude Code — a GitHub\n"
    "      issue tagged @claude that becomes a pull request for Kevin to review. YOU write the\n"
    "      complete brief from the conversation. repo: \"frontend\" = the app UI (default);\n"
    "      \"backend\" = Chief/sites/bookings/SMS/billing machinery.\n\n"
    "  • [ACTION:{\"type\":\"send_to_solution_space\",\"title\":\"...\",\"details\":\"full brief: what, where, why, constraints\",\"repo\":\"frontend\"}]\n"
    "      THE LOCAL LANE: queues the task for Solution Space on Kevin's own machine — a live\n"
    "      Claude Code session opens there in the right project with the brief loaded. Choose\n"
    "      this over queue_build when the work needs the running app, local testing, or Kevin's\n"
    "      eyes; choose queue_build for self-contained changes that can ship from the cloud.\n"
    "      Both show progress in Mission Control → Dev Desk.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "KEEPER OF THE RECORD (Kevin forgets — you don't)\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "The snapshot carries your memory of the business itself:\n"
    "  • operator_log — config flips, migrations run, decisions, notes (you wrote these)\n"
    "  • pending_items — follow-ups not yet done. Surface these UNPROMPTED when relevant\n"
    "    (\"before you flip billing on, the log shows X is still pending\").\n"
    "  • recent_ships — merged pull requests from both repos = what actually shipped, with dates.\n"
    "Duties:\n"
    "  • When Kevin TELLS you something changed (\"I ran the migration\", \"campaign resubmitted\",\n"
    "    \"set the Stripe prices\") — LOG IT with log_platform_note, category config/decision, in the\n"
    "    same reply. Don't ask permission for logging; it's your job. Confirm in one short clause.\n"
    "  • When something must happen later, log it as category pending; when he says it's done,\n"
    "    resolve it.\n"
    "  • When he asks \"what changed?\", \"where did we leave off?\", or \"what's still open?\" —\n"
    "    answer from operator_log + recent_ships with dates. Never guess from memory of the\n"
    "    conversation alone; the log is the truth.\n\n"
    "RULES:\n"
    "  • Only fire an action when the operator asks or the action is the obviously-correct response "
    "    to what's in the snapshot.\n"
    "  • Use the EXACT JSON shape above — ANY deviation will be skipped.\n"
    "  • UUIDs MUST come from the snapshot. Never invent ids.\n"
    "  • If the operator's request is destructive (suspend, refund, mass email) — these actions are "
    "    NOT in your vocabulary yet. Tell the operator and suggest they handle it manually.\n"
    "  • After firing an action, the rest of your reply should briefly say what you did and why — "
    "    operator will see the result card anyway, so don't belabor it.\n\n"
    "You have access to a current snapshot of the platform state. Use it for both answering AND "
    "for sourcing UUIDs for actions."
)


# ─── The Chief's memory: operator log + shipped-work feed ─────────────
# (2026-07-04, Kevin: "I will forget a lot of things.") Two sources:
#   1. platform_changelog — the operator's log Chief writes via the
#      log_platform_note action (config flips, decisions, pending).
#   2. GitHub merged PRs from both repos — the shipped-work record
#      that exists automatically; nobody has to remember to write it.

_GH_REPOS = ("parkerron1971-hash/kmj-intake-server",
             "parkerron1971-hash/solutionist-studio")
_gh_cache: Dict[str, Any] = {"at": 0.0, "data": []}


async def _recent_merged_prs(limit_per_repo: int = 10) -> List[Dict[str, Any]]:
    """Merged PRs across both repos, newest first. 15-min in-process
    cache; GITHUB_TOKEN optional (public repos work unauthenticated
    within rate limits). Fails soft to []."""
    now = time.time()
    if now - _gh_cache["at"] < 900 and _gh_cache["data"]:
        return _gh_cache["data"]
    gh_headers = {"Accept": "application/vnd.github+json"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        gh_headers["Authorization"] = f"Bearer {token}"
    out: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            for repo in _GH_REPOS:
                r = await c.get(
                    f"https://api.github.com/repos/{repo}/pulls",
                    headers=gh_headers,
                    params={"state": "closed", "sort": "updated",
                            "direction": "desc", "per_page": "20"},
                )
                if r.status_code >= 400:
                    continue
                short = repo.split("/")[-1]
                for pr in r.json():
                    if not pr.get("merged_at"):
                        continue
                    out.append({
                        "repo": short,
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "merged_at": pr.get("merged_at"),
                    })
                    if len([p for p in out if p["repo"] == short]) >= limit_per_repo:
                        break
        out.sort(key=lambda p: p.get("merged_at") or "", reverse=True)
        _gh_cache["at"] = now
        _gh_cache["data"] = out
    except Exception as e:
        logger.warning(f"merged-PR feed failed: {e}")
    return out


async def _changelog_rows(c: httpx.AsyncClient, headers: Dict[str, str],
                          limit: int = 25) -> List[Dict[str, Any]]:
    try:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/platform_changelog",
            headers=headers,
            params={"select": "id,created_at,category,title,detail,status",
                    "order": "created_at.desc", "limit": str(limit)},
        )
        if r.status_code < 400:
            return r.json() or []
    except Exception:
        pass
    return []  # migration not run — fail soft


@router.get("/changelog")
async def get_changelog(_owner=Depends(require_owner)):
    """The Ship's Log: operator entries + recent merged PRs, one call."""
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        rows = await _changelog_rows(c, headers, limit=50)
    ships = await _recent_merged_prs()
    return {"ok": True,
            "log": rows,
            "pending": [r for r in rows if r.get("status") == "pending"],
            "ships": ships}


class ChangelogBody(BaseModel):
    title: str
    detail: Optional[str] = None
    category: str = "note"
    status: Optional[str] = None


@router.post("/changelog")
async def add_changelog(body: ChangelogBody, _owner=Depends(require_owner)):
    from platform_chief_actions import _handler_log_platform_note
    res = await _handler_log_platform_note({
        "title": body.title, "detail": body.detail,
        "category": body.category, "status": body.status,
    })
    if not res.get("ok"):
        raise HTTPException(502, res.get("error") or "log write failed")
    return res


# ─── The agent fleet (Mission Control → Agents) ───────────────────────
# One brain, many senses (Kevin's ruling 2026-07-04). The registry is
# the flow map: who watches what, where findings go, who narrates.

AGENT_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "business_chief",
        "name": "Business Chief",
        "kind": "brain",
        "beat": "The one intelligence you talk to. Reads every watcher's findings "
                "(operator log), the live snapshot, and the ship feed; narrates, "
                "advises, takes actions, keeps the record.",
        "schedule": "on demand (your conversations)",
        "writes_to": "platform_changelog (log_platform_note), chief_actions",
    },
    {
        "id": "hermes",
        "name": "Hermes",
        "kind": "watcher",
        "beat": "Communications rails: SMS delivery failures, customer texts left "
                "unanswered 4h+, messages stuck undelivered, opt-out/suppression "
                "spikes, Twilio config posture.",
        "schedule": "hourly",
        "writes_to": "platform_agent_runs (every tick), platform_changelog (findings only)",
    },
    {
        "id": "stripe_usage_report",
        "name": "Usage Reporter",
        "kind": "system",
        "beat": "Reports metered Chief-interaction overage to Stripe (dormant until "
                "BILLING_ENFORCE=on).",
        "schedule": "daily",
        "writes_to": "usage_stripe_reports, Stripe usage records",
    },
    {
        "id": "autopilot_sweep",
        "name": "Autopilot Sweep",
        "kind": "system",
        "beat": "Per-business automation rules (practitioner-side machinery, not "
                "platform ops).",
        "schedule": "interval",
        "writes_to": "agent_queue, events (per business)",
    },
    {
        "id": "push_morning_brief",
        "name": "Morning Brief",
        "kind": "system",
        "beat": "Daily push notification brief to practitioners' phones.",
        "schedule": "daily 13:00 UTC",
        "writes_to": "web push",
    },
]


@router.get("/agents")
async def get_agents(_owner=Depends(require_owner)):
    """Registry + run history + recent findings — the whole flow in one
    read: watchers → runs → findings → (operator log) → Business Chief."""
    headers = _service_headers()
    runs: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        try:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                headers=headers,
                params={"select": "id,agent,started_at,finished_at,ok,findings,summary",
                        "order": "started_at.desc", "limit": "30"},
            )
            if r.status_code < 400:
                runs = r.json() or []
        except Exception:
            pass
        try:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/platform_changelog",
                headers=headers,
                params={"agent": "not.is.null",
                        "select": "id,created_at,agent,category,title,detail,status",
                        "order": "created_at.desc", "limit": "20"},
            )
            if r.status_code < 400:
                findings = r.json() or []
        except Exception:
            pass
    return {"ok": True, "registry": AGENT_REGISTRY, "runs": runs, "findings": findings}


@router.post("/agents/hermes/run")
async def run_hermes_now(_owner=Depends(require_owner)):
    """Manual tick from the console — same pass the hourly schedule runs."""
    from hermes_agent import hermes_tick
    return await hermes_tick()


class ChiefTurn(BaseModel):
    role: str            # "you" | "chief" (client-side roles)
    text: str


class ChiefMessageBody(BaseModel):
    message: str
    # Optional client-held conversation history (newest last). The
    # endpoint stays stateless server-side; the console sends its last
    # few turns so follow-up questions keep their thread.
    history: Optional[List[ChiefTurn]] = None


@router.get("/chief/actions")
async def list_chief_actions(limit: int = 50, _owner=Depends(require_owner)):
    """Recent chief_actions rows for the Action History panel.
    Newest first. Capped at 200 to keep payloads sane."""
    headers = _service_headers()
    limit = max(1, min(int(limit or 50), 200))
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/chief_actions",
            headers=headers,
            params={
                "select": "id,ts,action_type,business_id,lead_id,ok,error,payload,result,triggered_by_message",
                "order":  "ts.desc",
                "limit":  str(limit),
            },
        )
    if r.status_code in (404, 406):
        return []  # migration not run yet
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"Failed to fetch chief_actions: {r.text[:200]}")
    return r.json()


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

    # Activity in the last 24h + week-over-week deltas (cheap counts)
    try:
        from datetime import timedelta as _td
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            async def _count_since(table: str, since_iso: str) -> int:
                try:
                    r = await c.head(
                        f"{SUPABASE_URL}/rest/v1/{table}",
                        headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
                        params={"created_at": f"gte.{since_iso}"},
                    )
                    if r.status_code in (200, 206):
                        cr = r.headers.get("content-range", "")
                        last = cr.split("/")[-1] if "/" in cr else "0"
                        return int(last) if last and last != "*" else 0
                except Exception:
                    pass
                return 0

            now = datetime.now(timezone.utc)
            since_24h = (now - _td(hours=24)).isoformat()
            since_7d  = (now - _td(days=7)).isoformat()
            since_14d = (now - _td(days=14)).isoformat()

            snap["last_24h"] = {
                "new_leads":      await _count_since("marketing_leads", since_24h),
                "new_businesses": await _count_since("businesses", since_24h),
            }
            leads_this_week = await _count_since("marketing_leads", since_7d)
            biz_this_week   = await _count_since("businesses",      since_7d)
            leads_prev_week = (await _count_since("marketing_leads", since_14d)) - leads_this_week
            biz_prev_week   = (await _count_since("businesses",      since_14d)) - biz_this_week
            snap["week_over_week"] = {
                "leads_this_week":      leads_this_week,
                "leads_prev_week":      max(0, leads_prev_week),
                "leads_delta":          leads_this_week - max(0, leads_prev_week),
                "businesses_this_week": biz_this_week,
                "businesses_prev_week": max(0, biz_prev_week),
                "businesses_delta":     biz_this_week - max(0, biz_prev_week),
            }

            # Recent chief actions (so Chief can reason about its own behavior)
            try:
                ar = await c.get(
                    f"{SUPABASE_URL}/rest/v1/chief_actions",
                    headers=headers,
                    params={"select": "action_type,ok,ts", "order": "ts.desc", "limit": "20"},
                )
                if ar.status_code < 400:
                    rows = ar.json()
                    by_type: Dict[str, int] = {}
                    failures = 0
                    for row in rows:
                        by_type[row["action_type"]] = by_type.get(row["action_type"], 0) + 1
                        if not row.get("ok"):
                            failures += 1
                    snap["recent_chief_actions"] = {
                        "last_20_by_type": by_type,
                        "failures_in_last_20": failures,
                    }
            except Exception:
                pass
    except Exception as e:
        snap["activity_error"] = str(e)

    # The Chief's memory (2026-07-04): operator log + pending follow-ups
    # + the shipped-work feed. This is how Chief keeps account of
    # changes Kevin will otherwise forget.
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            log_rows = await _changelog_rows(c, headers, limit=25)
        snap["operator_log"] = [
            {"id": r.get("id"), "when": r.get("created_at"),
             "category": r.get("category"), "title": r.get("title"),
             "detail": (r.get("detail") or "")[:300], "status": r.get("status")}
            for r in log_rows
        ]
        snap["pending_items"] = [
            e for e in snap["operator_log"] if e.get("status") == "pending"
        ]
    except Exception as e:
        snap["operator_log_error"] = str(e)
    try:
        snap["recent_ships"] = await _recent_merged_prs()
    except Exception:
        pass

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

    # Thread the console's recent turns (client-held; server stays
    # stateless). Cap at the last 12 turns and skip empties so a long
    # session can't bloat the prompt.
    messages: List[Dict[str, str]] = []
    for turn in (body.history or [])[-12:]:
        text = (turn.text or "").strip()
        if not text:
            continue
        messages.append({
            "role": "user" if turn.role == "you" else "assistant",
            "content": text[:4000],
        })
    # Anthropic requires the first message to be from the user.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    messages.append({"role": "user", "content": body.message})

    started_ms = int(time.time() * 1000)
    payload = {
        "model": PLATFORM_CHIEF_MODEL,
        "max_tokens": 1000,
        "temperature": 0.6,
        "system": system,
        "messages": messages,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0)) as c:
            r = await llm_call.apost(c, payload, key=api_key)
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
    raw_text = "".join(
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

    # Action dispatch — pull [ACTION:{...}] tags out, run them, log each.
    actions_in_reply = extract_actions(raw_text)
    actions_taken: List[Dict[str, Any]] = []
    if actions_in_reply:
        actions_taken = await dispatch_actions(
            actions_in_reply,
            triggered_by_message=body.message,
            chief_reply_excerpt=raw_text[:500],
        )

    # The reply the operator SEES has the action JSON stripped — the
    # action cards render the result instead.
    display_text = strip_action_tags(raw_text)

    return {
        "reply":         display_text,
        "raw_reply":     raw_text,
        "actions_taken": actions_taken,
        "model":         data.get("model"),
        "usage":         usage,
        "snapshot_keys": list(snapshot.keys()),
    }


# ═══════════════════════════════════════════════════════════════════════
# PLATFORM INBOX — mail for the platform itself (platform_emails)
# ═══════════════════════════════════════════════════════════════════════
#
# /email/inbound routes mail addressed to kevin@/support@/... (and any
# otherwise-unresolved mail, flagged catchall) into platform_emails.
# These endpoints are Mission Control's read side. Service-role reads —
# the table deliberately has no PostgREST policies.


def _require_email_uuid(email_id: str) -> str:
    """platform_emails ids are uuids; reject anything else before it
    reaches a PostgREST filter string."""
    import uuid as _uuid
    try:
        return str(_uuid.UUID(email_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="invalid email id")


@router.get("/inbox")
async def platform_inbox_list(
    limit: int = 50,
    unread_only: bool = False,
    user=Depends(require_owner),
):
    """List platform inbox mail, newest first, plus the unread count."""
    limit = min(max(limit, 1), 200)
    q = ("/platform_emails"
         "?select=id,to_address,from_email,from_name,subject,read,catchall,received_at"
         f"&order=received_at.desc&limit={limit}")
    if unread_only:
        q += "&read=eq.false"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1{q}", headers=_service_headers())
        if r.status_code >= 400:
            raise HTTPException(status_code=502,
                                detail=f"inbox read failed: {r.text[:200]}")
        rows = r.json()
        unread = 0
        try:
            hr = await c.head(
                f"{SUPABASE_URL}/rest/v1/platform_emails",
                headers={**_service_headers(), "Prefer": "count=exact", "Range": "0-0"},
                params={"read": "eq.false"},
            )
            cr = hr.headers.get("content-range", "")
            last = cr.split("/")[-1] if "/" in cr else "0"
            unread = int(last) if last and last != "*" else 0
        except Exception:
            pass
    return {"emails": rows, "unread": unread}


@router.get("/inbox/{email_id}")
async def platform_inbox_read(email_id: str, user=Depends(require_owner)):
    """Full message including body_html; opening marks it read."""
    eid = _require_email_uuid(email_id)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/platform_emails",
            headers=_service_headers(),
            params={"id": f"eq.{eid}", "select": "*", "limit": "1"},
        )
        if r.status_code >= 400 or not r.json():
            raise HTTPException(status_code=404, detail="email not found")
        row = r.json()[0]
        if not row.get("read"):
            try:
                await c.patch(
                    f"{SUPABASE_URL}/rest/v1/platform_emails",
                    headers=_service_headers(),
                    params={"id": f"eq.{eid}"},
                    json={"read": True},
                )
                row["read"] = True
            except Exception:
                pass
    return row


@router.delete("/inbox/{email_id}")
async def platform_inbox_delete(email_id: str, user=Depends(require_owner)):
    eid = _require_email_uuid(email_id)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.delete(
            f"{SUPABASE_URL}/rest/v1/platform_emails",
            headers=_service_headers(),
            params={"id": f"eq.{eid}"},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502,
                                detail=f"delete failed: {r.text[:200]}")
    return {"ok": True, "deleted": eid}


def _reply_subject(subject: str) -> str:
    """'Invoice question' -> 'Re: Invoice question'; already-Re: subjects
    pass through untouched (no 'Re: Re:' stacking)."""
    s = (subject or "").strip()
    if not s:
        return "Re: (no subject)"
    return s if s.lower().startswith("re:") else f"Re: {s}"


class InboxReplyBody(BaseModel):
    body: str


@router.post("/inbox/{email_id}/reply")
async def platform_inbox_reply(
    email_id: str,
    payload: InboxReplyBody,
    user=Depends(require_owner),
):
    """Reply from the address the message was sent to (kevin@, support@,
    ...). Goes through send_via_resend, so the suppression gate applies
    like every other platform send. The reply is appended to the row's
    `replies` so the thread stays on the message it belongs to."""
    from email_sender import send_via_resend

    body_text = (payload.body or "").strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="reply body is empty")

    eid = _require_email_uuid(email_id)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/platform_emails",
            headers=_service_headers(),
            params={"id": f"eq.{eid}", "select": "*", "limit": "1"},
        )
        if r.status_code >= 400 or not r.json():
            raise HTTPException(status_code=404, detail="email not found")
        row = r.json()[0]

    from_addr = (row.get("to_address") or "").strip().lower()
    if "@" not in from_addr:
        from_addr = os.environ.get("RESEND_FROM_EMAIL", "noreply@mysolutionist.app")
    # kevin@ replies as "Kevin", support@ as "Support" — the domain is
    # already the identity; the local part is the person.
    from_name = from_addr.split("@", 1)[0].capitalize()

    try:
        sent = await send_via_resend(
            to_email=row["from_email"],
            to_name=row.get("from_name") or None,
            from_email=from_addr,
            from_name=from_name,
            subject=_reply_subject(row.get("subject") or ""),
            body=body_text,
            reply_to=from_addr,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)[:300])

    reply_entry = {
        "body": body_text,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "resend_id": (sent or {}).get("id"),
    }
    replies = list(row.get("replies") or []) + [reply_entry]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await c.patch(
            f"{SUPABASE_URL}/rest/v1/platform_emails",
            headers=_service_headers(),
            params={"id": f"eq.{eid}"},
            json={"replies": replies, "read": True},
        )
    return {"ok": True, "reply": reply_entry, "reply_count": len(replies)}



# ─── Margin: revenue minus what it cost to serve ─────────────────────
#
# The one number nobody had. pricing_config knows every price;
# api_usage knows every cost; nothing subtracted them. See margin.py for
# what is and is not counted — in particular that pack revenue is
# missing because nothing records a pack PURCHASE, so these figures are
# a floor rather than an estimate.

@router.get("/first-week")
async def first_week_view(days: int = 30, _owner=Depends(require_owner)):
    """What every business created in the window actually did in its
    first days — the onboarding steps it reached, whether the sit-down
    with Chief was opened, paused or finished, how many plug-ins are
    probed done and which comes next, and whether it ever came back.
    The read side of the onboarding telemetry (see first_week.py)."""
    import first_week
    return first_week.first_week_report(days=max(1, min(365, days)))


@router.get("/margin")
async def platform_margin_view(days: int = 30, _owner=Depends(require_owner)):
    """Platform-wide margin, per tier, worst 20 accounts first."""
    import margin
    return margin.platform_margin(days=max(1, min(365, days)))


@router.get("/margin/{business_id}")
async def business_margin_view(business_id: str, days: int = 30,
                               _owner=Depends(require_owner)):
    """One account's revenue, COGS and margin over the window."""
    import margin
    return margin.business_margin(business_id, days=max(1, min(365, days)))
