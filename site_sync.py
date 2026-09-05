"""site_sync.py — hand-built sites install themselves on boot.

A site under sites/<dir>/ with a build.py that exposes SLUG, BUSINESS_ID
and render_pages() is the source of truth for that business's
business_sites row. On every boot this module renders the pages, hashes
them, and — only when the hash differs from what the row already carries
— writes them in and marks the row html_source = "manual" (the mode
public_site.py serves as stored, with overrides + the verified sending
address filled at serve time; see public_site._apply_manual_source).

Why on boot and not by SQL: the site is code. Merging a change to
sites/kmj-creative-solutions/ and having Railway deploy it IS the
release; a 150 KB paste into the SQL editor was the step that could be
forgotten, mis-pasted, or applied against the wrong project. Idempotent
(hash-gated), so every replica may run it. Fail-soft: a sync problem is
logged and the app boots regardless — the live page is never blanked.

The first install of a row that was built by a composer keeps that page
set under site_config.manual_backup; supabase/ROLLBACK-2026-09-03-
kmj-site-manual.sql puts it back. SITE_SYNC=off disables the whole
thing for an emergency deploy.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import pathlib
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("site_sync")

SITES_DIR = pathlib.Path(__file__).resolve().parent / "sites"
SECONDARY_PAGES = ("about", "services", "contact")


def enabled() -> bool:
    return (os.environ.get("SITE_SYNC") or "on").strip().lower() not in ("off", "0", "false", "no")


def discover(sites_dir: pathlib.Path = SITES_DIR) -> List[Any]:
    """Every sites/<dir>/build.py that exposes the contract, as loaded modules."""
    found: List[Any] = []
    if not sites_dir.is_dir():
        return found
    for d in sorted(sites_dir.iterdir()):
        bp = d / "build.py"
        if not bp.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"site_build_{d.name}", bp)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning(f"[site-sync] {d.name}: build.py failed to load: {e}")
            continue
        if all(hasattr(mod, a) for a in ("SLUG", "BUSINESS_ID", "render_pages")):
            found.append(mod)
        else:
            logger.warning(f"[site-sync] {d.name}: build.py lacks SLUG/BUSINESS_ID/render_pages; skipped")
    return found


def content_hash(pages: Dict[str, str]) -> str:
    blob = json.dumps({k: pages[k] for k in sorted(pages)}, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def sync_site(mod: Any) -> str:
    """Install or update one site. Returns one of: current, installed,
    updated, no-row, wrong-business, error."""
    import sb_clients

    slug = str(mod.SLUG)
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{slug}"
        "&select=id,business_id,html_content,site_config&limit=1") or []
    if not rows:
        logger.warning(f"[site-sync] {slug}: no business_sites row; nothing installed")
        return "no-row"
    row = rows[0]
    if str(row.get("business_id")) != str(mod.BUSINESS_ID):
        # The slug moved to another business since this source was written.
        # Overwriting someone else's site is the one thing this must never do.
        logger.error(f"[site-sync] {slug}: row belongs to {str(row.get('business_id'))[:8]}, "
                     f"source says {str(mod.BUSINESS_ID)[:8]}; refusing")
        return "wrong-business"

    pages = mod.render_pages()
    if "home" not in pages:
        logger.error(f"[site-sync] {slug}: render_pages() returned no home page; refusing")
        return "error"
    digest = content_hash(pages)
    cfg = dict(row.get("site_config") or {}) if isinstance(row.get("site_config"), dict) else {}
    was_manual = cfg.get("html_source") == "manual"
    if was_manual and cfg.get("manual_hash") == digest:
        return "current"

    now = datetime.now(timezone.utc).isoformat()
    new_cfg = dict(cfg)
    if not was_manual:
        new_cfg["manual_backup"] = {
            "saved_at": now,
            "html_content": row.get("html_content"),
            "html_source": cfg.get("html_source"),
            "generated_pages": cfg.get("generated_pages"),
            "site_pages": cfg.get("site_pages"),
        }
    secondary = [p for p in SECONDARY_PAGES if p in pages]
    new_cfg.update({
        "html_source": "manual",
        "site_type": "multi-page",
        "site_pages": ["home"] + secondary,
        "generated_pages": {p: pages[p] for p in secondary},
        "manual_hash": digest,
        "manual_installed_at": now,
    })
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}",
        {"html_content": pages["home"], "site_config": new_cfg,
         "status": "published", "updated_at": now})
    outcome = "updated" if was_manual else "installed"
    logger.info(f"[site-sync] {slug}: {outcome} ({digest}, {len(pages)} pages)")
    # Every deploy that changed the site gets looked at (site_check.py):
    # the pages are live within seconds; the check opens them from the
    # public address, so it waits a beat before starting.
    try:
        import site_check
        if site_check.enabled():
            t = threading.Timer(45.0, lambda: site_check.run(
                str(mod.BUSINESS_ID), reason="deploy", vision=True))
            t.daemon = True   # never holds a shutdown or a test run open
            t.start()
    except Exception as e:
        logger.info(f"[site-sync] post-deploy check not scheduled: {e}")
    return outcome


def sync_all() -> Dict[str, str]:
    results: Dict[str, str] = {}
    if not enabled():
        logger.info("[site-sync] SITE_SYNC=off; skipped")
        return results
    for mod in discover():
        slug = str(getattr(mod, "SLUG", "?"))
        try:
            results[slug] = sync_site(mod)
        except Exception as e:
            logger.warning(f"[site-sync] {slug}: failed (non-fatal): {e}")
            results[slug] = "error"
    return results


def sync_all_async() -> None:
    """Boot-time entry: never blocks or fails startup."""
    def _run() -> None:
        try:
            res = sync_all()
            if res:
                logger.info(f"[site-sync] {res}")
        except Exception as e:
            logger.warning(f"[site-sync] crashed (non-fatal): {e}")
    threading.Thread(target=_run, name="site-sync", daemon=True).start()
