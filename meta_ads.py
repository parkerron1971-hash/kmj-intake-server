"""
meta_ads.py — Meta Marketing API: read-only ad spend for the platform's
own account. GROWTH ARC Rung 3.

WHY READ-ONLY: campaigns are created and managed in Ads Manager, which
is better at that job than anything worth building here. What Ads
Manager CANNOT show is spend next to the revenue it produced — that
join lives in /platform/growth, so the one thing this module does is
pull spend into it.

Reads act_<id>/insights at campaign level. Works with a System User
token from Kevin's own Business Manager (ads_read on the one ad
account) — no App Review needed for reading your own account through
your own app while it has standard Marketing API access.

FAIL-SOFT + CACHED: unconfigured → {"configured": False} and the Growth
panel simply doesn't render the card. Errors are a field, never a 500 —
the funnel numbers must not die because Meta rate-limited a spend read.
Insights calls are budgeted per ad account, and the panel refetches on
every mount, so results are cached in-process for 10 minutes.

Env (see .env.example + platform_console.API_REGISTRY):
  META_ADS_ACCESS_TOKEN — System User token with ads_read
  META_AD_ACCOUNT_ID    — the ad account id ("act_123..." or bare digits)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("meta_ads")

# Same Graph version meta_capi / meta_oauth pin.
FB_GRAPH = "https://graph.facebook.com/v21.0"
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)

_CACHE_TTL_S = 600
_cache: Dict[int, tuple] = {}   # days -> (result, fetched_at)


def _token() -> str:
    return (os.environ.get("META_ADS_ACCESS_TOKEN") or "").strip()


def _account_id() -> str:
    raw = (os.environ.get("META_AD_ACCOUNT_ID") or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


def configured() -> bool:
    return bool(_token() and _account_id())


def _spend_cents(value: Any) -> int:
    """Insights returns spend as a decimal STRING in account-currency
    units. A bad parse is 0, never an exception in a report."""
    try:
        return int(round(float(value or 0) * 100))
    except (ValueError, TypeError):
        return 0


async def spend_summary(days: int = 30) -> Dict[str, Any]:
    """Campaign-level spend for the window. Shape is stable for the
    Growth panel:
      {"configured": bool, "ok": bool, "spend_cents", "impressions",
       "clicks", "campaigns": [{"name", "spend_cents", "impressions",
       "clicks"}], "error"?: str}
    """
    if not configured():
        return {"configured": False}

    days = max(1, min(int(days or 30), 365))
    hit = _cache.get(days)
    if hit and time.time() - hit[1] < _CACHE_TTL_S:
        return hit[0]

    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).date().isoformat()
    until = now.date().isoformat()

    result: Dict[str, Any] = {
        "configured": True, "ok": False,
        "spend_cents": 0, "impressions": 0, "clicks": 0, "campaigns": [],
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(
                f"{FB_GRAPH}/{_account_id()}/insights",
                params={
                    "access_token": _token(),
                    "level": "campaign",
                    "fields": "campaign_name,spend,impressions,clicks",
                    "time_range": f'{{"since":"{since}","until":"{until}"}}',
                    "limit": "100",
                },
            )
        if r.status_code >= 400:
            # Meta wraps the useful part in error.message.
            try:
                msg = (r.json().get("error") or {}).get("message") or r.text[:200]
            except Exception:
                msg = r.text[:200]
            logger.warning("insights read failed %s: %s", r.status_code, msg)
            result["error"] = str(msg)[:200]
            return result   # NOT cached — a transient failure should retry

        rows = (r.json() or {}).get("data") or []
        campaigns = []
        for row in rows:
            spend = _spend_cents(row.get("spend"))
            imp = int(row.get("impressions") or 0)
            clk = int(row.get("clicks") or 0)
            campaigns.append({
                "name": (row.get("campaign_name") or "(unnamed)")[:120],
                "spend_cents": spend, "impressions": imp, "clicks": clk,
            })
            result["spend_cents"] += spend
            result["impressions"] += imp
            result["clicks"] += clk
        campaigns.sort(key=lambda x: x["spend_cents"], reverse=True)
        result["campaigns"] = campaigns
        result["ok"] = True
        _cache[days] = (result, time.time())
        return result
    except Exception as e:
        logger.warning("insights read error: %s", e)
        result["error"] = str(e)[:200]
        return result
