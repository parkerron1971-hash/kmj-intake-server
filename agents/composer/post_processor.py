"""Pass 4.0h Phase B — Composer post-processor.

Takes a Builder-generated HTML document and, when the target business
has opted into the multi-module pipeline (`businesses.use_composer =
TRUE`), replaces the Hero section with one produced by the Composer
pipeline (Module Router -> module-specific Composer -> module-specific
render). Returns the hybrid HTML and the module_id used.

Integration contract (wired in Phase C at
agents/director_agent/build_with_loop.py:619):

  final_html, hero_module = await post_process_hero(
      business_id=business_id,
      builder_html=final_html,
      enriched_brief=enriched_brief,
      brand_kit=brand_kit,
      site_config=cfg,       # may be mutated to update composer_cache
  )
  cfg["generated_html"] = final_html
  cfg["hero_composer_module"] = hero_module   # surfaces in PATCH
  # ... existing PATCH of business_sites with new cfg ...

Pass 4.0h additions on top of the planning baseline:

  * Hero section identification logs a WARNING when the class-based
    fallback path is taken (Builder stopped emitting
    data-section="hero") and an ERROR when neither selector matches.
    Pass 4.0g.x review surfaced this as the right discipline — silent
    fallback turns a real regression invisible.

  * Hash-based composition cache keyed on a canonical SHA-256 of the
    enriched_brief. Cache lives in `site_config.composer_cache`
    (post_processor MUTATES the passed-in site_config dict so the
    update rides along on Builder's existing PATCH — single round-
    trip, no race against build_with_loop's site_config write).

  * Defensive integration. Every step in post_process_hero is wrapped
    so any failure (use_composer read, hash, router, composer, render,
    surgical replace) logs the exception and returns
    (builder_html, None). The post-processor must never break a build
    — it can only enhance or no-op.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────

_COMPOSER_CACHE_KEY = "composer_cache"
_CACHE_VERSION = 1  # bump if cache shape changes; old entries miss harmlessly
_SUPABASE_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


# ─── Supabase helpers ──────────────────────────────────────────────

def _supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "")


def _supabase_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "") or os.environ.get("SUPABASE_ANON_KEY", "")


async def _read_use_composer(client: httpx.AsyncClient, business_id: str) -> bool:
    """Return businesses.use_composer for a business. False on any
    error (missing row, network failure, column not yet migrated)."""
    base = _supabase_url()
    key = _supabase_anon()
    if not (base and key and business_id):
        return False
    url = (
        f"{base}/rest/v1/businesses"
        f"?id=eq.{business_id}&select=use_composer&limit=1"
    )
    try:
        resp = await client.get(
            url,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=_SUPABASE_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.warning(f"[post_processor] use_composer fetch failed: {e}")
        return False
    if resp.status_code >= 400:
        logger.warning(
            f"[post_processor] use_composer HTTP {resp.status_code}: {resp.text[:120]}"
        )
        return False
    try:
        rows = resp.json()
        return bool(rows and rows[0].get("use_composer"))
    except (ValueError, IndexError, KeyError, AttributeError):
        return False


# ─── Brief hashing + cache ─────────────────────────────────────────

def hash_brief(enriched_brief: Any) -> str:
    """SHA-256 of canonical JSON of enriched_brief. sort_keys=True +
    ensure_ascii=False produces a stable canonical form so two equal
    briefs hash identically regardless of dict ordering or unicode
    representation choices.

    The hash is the cache key — if the brief is unchanged from the
    last successful build, the cached composition is reused (saves
    one Module Router + one Composer LLM call per cache hit)."""
    try:
        canonical = json.dumps(
            enriched_brief or {},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        # Non-serializable brief shape — disable caching, return a
        # sentinel hash that won't match any real cache entry.
        return "unhashable:" + str(id(enriched_brief))
    return hashlib.sha256(canonical).hexdigest()


def cache_lookup(site_config: Dict[str, Any], brief_hash: str) -> Optional[Dict[str, Any]]:
    """Return the cached entry {module_id, composition, cached_at} if
    the cached brief_hash matches, else None. Returns None on any
    cache shape problem (forward-compat with future cache versions)."""
    cache = (site_config or {}).get(_COMPOSER_CACHE_KEY) or {}
    if not isinstance(cache, dict):
        return None
    if cache.get("_version") != _CACHE_VERSION:
        return None
    if cache.get("brief_hash") != brief_hash:
        return None
    comp = cache.get("composition")
    module_id = cache.get("module_id")
    if not (isinstance(comp, dict) and isinstance(module_id, str)):
        return None
    return cache


def cache_store(
    site_config: Dict[str, Any],
    brief_hash: str,
    module_id: str,
    composition: Dict[str, Any],
    routing_decision: Optional[Dict[str, Any]] = None,
) -> None:
    """Mutate site_config in place to store this composition under
    brief_hash. The mutation is intentional — Builder's existing
    site_config PATCH carries the cache update along in one round-
    trip, so there's no race against build_with_loop's write."""
    site_config[_COMPOSER_CACHE_KEY] = {
        "_version": _CACHE_VERSION,
        "brief_hash": brief_hash,
        "module_id": module_id,
        "composition": composition,
        # Routing decision is small and useful for debugging cache hits
        # — surface confidence/reasoning so a cached build can still
        # answer "why this module?" without re-firing the router.
        "routing_decision": routing_decision,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Hero section identification ───────────────────────────────────

def find_hero_section(soup: BeautifulSoup) -> Optional[Tag]:
    """Locate the Hero section in Builder's HTML.

    Primary selector: <section data-section="hero">. This is the
    contract Builder is expected to emit and what every Studio Brut
    and Cathedral variant emits.

    Fallback: first <section> with "hero" in its class list. When this
    path is taken we log a WARNING so the regression is visible —
    Pass 4.0g.x review identified silent fallback as the failure mode
    that turns invisible bugs into "Test Title"-style mysteries.

    If neither matches, log an ERROR and return None so the caller
    skips post-processing rather than corrupting Builder's output."""
    hero = soup.find("section", attrs={"data-section": "hero"})
    if hero is not None:
        return hero
    # BS4 calls this lambda once per class NAME on each candidate
    # <section> (NOT once per element with the full list) — c is a
    # single class string. If the callable returns True for any class
    # on the element, the element matches.
    hero = soup.find(
        "section",
        class_=lambda c: bool(c) and "hero" in c.lower(),
    )
    if hero is not None:
        logger.warning(
            "[post_processor] data-section='hero' not found; falling back to "
            "class-based selector. Builder may have changed Hero section emission "
            "pattern — investigate before silent failure becomes load-bearing."
        )
        return hero
    logger.error(
        "[post_processor] no Hero section found (neither data-section='hero' "
        "nor class containing 'hero'). Cannot post-process; returning Builder "
        "HTML unchanged."
    )
    return None


def replace_hero_section(builder_html: str, composed_hero_html: str) -> str:
    """Surgically replace the Hero section in builder_html with the
    composed version. Returns builder_html unchanged on any structural
    problem (no Hero found in builder, composed output has no <section>
    root). Logs ERROR for the composed-output-malformed case since the
    Composer / render pipeline should never emit non-<section> Hero
    fragments."""
    soup = BeautifulSoup(builder_html, "html.parser")
    hero_section = find_hero_section(soup)
    if hero_section is None:
        return builder_html

    composed_soup = BeautifulSoup(composed_hero_html, "html.parser")
    composed_section = composed_soup.find("section")
    if composed_section is None:
        logger.error(
            "[post_processor] composed Hero HTML has no <section> root. "
            "Skipping replacement; returning Builder HTML unchanged."
        )
        return builder_html

    hero_section.replace_with(composed_section)
    return str(soup)


# ─── Public entry ──────────────────────────────────────────────────

async def post_process_hero(
    business_id: str,
    builder_html: str,
    enriched_brief: Optional[Dict[str, Any]] = None,
    brand_kit: Optional[Dict[str, Any]] = None,
    site_config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str]]:
    """Post-process Builder's HTML to replace the Hero section with a
    Composer-generated one when the business has opted in.

    Returns:
      (final_html, module_id)
        final_html: hybrid HTML when post-processing succeeded;
                    builder_html unchanged when opted-out, failed, or
                    no Hero section found.
        module_id:  'cathedral' or 'studio_brut' on success; None
                    when post-processing was skipped or any step
                    failed (the caller writes None to
                    business_sites.hero_composer_module so analytics
                    can distinguish "Composer Hero" from "Builder
                    Hero" rows).

    Side effects:
      * May mutate `site_config` to add/update the `composer_cache`
        key. The caller is expected to persist site_config to
        business_sites in its existing PATCH so the cache update
        rides along without a separate round-trip.

    Soft-fails: any exception inside the function is caught, logged,
    and returns (builder_html, None). The post-processor cannot break
    a build."""
    if not builder_html:
        return builder_html or "", None

    cfg = site_config if isinstance(site_config, dict) else {}

    try:
        async with httpx.AsyncClient() as client:
            opt_in = await _read_use_composer(client, business_id)
    except Exception as exc:
        logger.warning(
            f"[post_processor] {business_id}: use_composer read failed ({exc}); "
            f"treating as opt-out"
        )
        return builder_html, None

    if not opt_in:
        logger.info(
            f"[post_processor] {business_id}: use_composer=False; Builder Hero retained"
        )
        return builder_html, None

    # Cache lookup — hashing enriched_brief is what the caller passes
    # in, so the cache key is tied to the brief Builder actually used
    # for this build.
    try:
        brief_hash = hash_brief(enriched_brief)
        cached = cache_lookup(cfg, brief_hash)
    except Exception as exc:
        logger.warning(f"[post_processor] {business_id}: cache lookup failed ({exc})")
        brief_hash = None
        cached = None

    composition: Optional[Dict[str, Any]] = None
    module_id: Optional[str] = None
    routing_decision: Optional[Dict[str, Any]] = None

    if cached is not None:
        module_id = cached["module_id"]
        composition = cached["composition"]
        logger.info(
            f"[post_processor] {business_id}: cache HIT module={module_id!r} "
            f"hash={brief_hash[:12]}…"
        )
    else:
        # Cache miss — full pipeline. Module Router + Composer are
        # sync functions wrapped via asyncio.to_thread so the event
        # loop stays responsive during the LLM round-trip.
        try:
            from agents.composer.module_router import route_module
            routing_decision = await asyncio.to_thread(route_module, business_id)
            module_id = (routing_decision or {}).get("module_id") or "cathedral"
        except Exception as exc:
            logger.warning(
                f"[post_processor] {business_id}: Module Router failed ({exc}); "
                f"returning Builder HTML unchanged"
            )
            return builder_html, None
        try:
            from agents.composer.hero_composer import compose_hero
            composition = await asyncio.to_thread(compose_hero, business_id, module_id)
        except Exception as exc:
            logger.warning(
                f"[post_processor] {business_id}: Composer failed ({exc}); "
                f"returning Builder HTML unchanged"
            )
            return builder_html, None
        # Write-through cache only on successful Router + Composer.
        if brief_hash and isinstance(composition, dict):
            try:
                cache_store(cfg, brief_hash, module_id, composition, routing_decision)
                logger.info(
                    f"[post_processor] {business_id}: cache STORE module={module_id!r} "
                    f"hash={brief_hash[:12]}… variant={composition.get('variant')!r}"
                )
            except Exception as exc:
                logger.warning(f"[post_processor] {business_id}: cache store failed ({exc})")

    # Render the composed Hero. render_hero_fragment runs the full
    # four-step pipeline (variant render -> brand kit vars -> slot
    # resolution -> override resolution). apply_overrides=True so
    # practitioner edits win over composed content (matches Pass 4.0e
    # Edit Mode semantics).
    try:
        from agents.composer.render_pipeline import render_hero_fragment
        composed_hero_html = await asyncio.to_thread(
            render_hero_fragment, composition, business_id, module_id,
        )
    except Exception as exc:
        logger.warning(
            f"[post_processor] {business_id}: render failed ({exc}); "
            f"returning Builder HTML unchanged"
        )
        return builder_html, None

    if not composed_hero_html:
        logger.warning(
            f"[post_processor] {business_id}: render returned empty; "
            f"returning Builder HTML unchanged"
        )
        return builder_html, None

    # Surgical replacement.
    try:
        final_html = replace_hero_section(builder_html, composed_hero_html)
    except Exception as exc:
        logger.warning(
            f"[post_processor] {business_id}: surgical replace failed ({exc}); "
            f"returning Builder HTML unchanged"
        )
        return builder_html, None

    # If find_hero_section returned None, replace_hero_section returns
    # builder_html unchanged — module_id is still meaningful (we DID
    # compose), but the Hero didn't land. Caller decides how to record
    # that in hero_composer_module. We return module_id since the
    # composition succeeded; the caller can compare final_html ==
    # builder_html to detect the no-replace case if needed.
    return final_html, module_id
