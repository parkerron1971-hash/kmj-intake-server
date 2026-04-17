"""
public_site.py — Solutionist System public site data + widget endpoints

Unauthenticated read-only endpoints that serve practitioner site data
and embeddable widget HTML. Only exposes modules with
public_display.enabled = true and only the fields listed in visible_fields.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.
2. In main.py:
       from public_site import router as public_site_router
       app.include_router(public_site_router)
3. No env vars beyond the existing SUPABASE_URL + SUPABASE_ANON.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
RATE_LIMIT_PER_MIN = 100
RATE_WINDOW_SEC = 60

# Business-type → color palette for widgets
TYPE_PALETTES: Dict[str, Dict[str, str]] = {
    "church":     {"bg": "#faf7f2", "card": "#fff", "accent": "#8B6914", "text": "#2d2417", "muted": "#7a6e5e", "border": "#e8dfd2"},
    "coaching":   {"bg": "#f0f4f8", "card": "#fff", "accent": "#1a6b8a", "text": "#1a2a3a", "muted": "#5a6a7a", "border": "#dce4ec"},
    "consulting": {"bg": "#f3f4f6", "card": "#fff", "accent": "#3730a3", "text": "#111827", "muted": "#6b7280", "border": "#e5e7eb"},
    "nonprofit":  {"bg": "#f0fdf4", "card": "#fff", "accent": "#166534", "text": "#14532d", "muted": "#4d7c5e", "border": "#d1e7d8"},
    "freelance":  {"bg": "#fdf4ff", "card": "#fff", "accent": "#7c3aed", "text": "#1e1033", "muted": "#6b5b7b", "border": "#e8d5f5"},
}
DEFAULT_PALETTE = TYPE_PALETTES["consulting"]

logger = logging.getLogger("public_site")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] public: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")

# In-memory rate limiter
_rate_buckets: Dict[str, Dict[str, Any]] = {}

def _check_rate(slug: str) -> bool:
    now = time.time()
    bucket = _rate_buckets.get(slug)
    if not bucket or now - bucket["start"] > RATE_WINDOW_SEC:
        _rate_buckets[slug] = {"start": now, "count": 1}
        return True
    if bucket["count"] >= RATE_LIMIT_PER_MIN:
        return False
    bucket["count"] += 1
    return True

# ═══════════════════════════════════════════════════════════════════════
# SUPABASE HELPER
# ═══════════════════════════════════════════════════════════════════════

async def _sb(client: httpx.AsyncClient, path: str):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
    }
    resp = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        return None
    text = resp.text
    return json.loads(text) if text else None

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _filter_entry(entry_data: Dict, visible: List[str], hidden: List[str]) -> Dict:
    """Keep only visible fields, remove hidden ones. If visible is empty, show all except hidden."""
    if visible:
        return {k: v for k, v in entry_data.items() if k in visible and k not in hidden}
    return {k: v for k, v in entry_data.items() if k not in hidden}


def _palette_for(biz_type: str) -> Dict[str, str]:
    return TYPE_PALETTES.get(biz_type, DEFAULT_PALETTE)


def _render_entries_html(entries: List[Dict], display_type: str, palette: Dict[str, str]) -> str:
    """Render module entries as HTML based on display_type."""
    if not entries:
        return '<p style="color:' + palette["muted"] + ';font-style:italic;">No items yet.</p>'

    if display_type == "grid":
        cards = []
        for e in entries:
            title = e.get("title") or e.get("deliverable_name") or e.get("name") or ""
            body_parts = [f'<strong>{title}</strong>'] if title else []
            for k, v in e.items():
                if k in ("title", "deliverable_name", "name") or v is None or v == "":
                    continue
                body_parts.append(f'<span style="color:{palette["muted"]};font-size:0.85em">{k}: {v}</span>')
            cards.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:6px;">'
                + "<br>".join(body_parts) + '</div>'
            )
        return (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;">'
            + "".join(cards) + '</div>'
        )

    if display_type == "wall":
        tiles = []
        for e in entries:
            title = e.get("title") or e.get("quote") or next((str(v) for v in e.values() if v), "")
            status = e.get("status") or ""
            tiles.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-left:3px solid {palette["accent"]};border-radius:0 8px 8px 0;'
                f'padding:14px;break-inside:avoid;margin-bottom:10px;">'
                f'<div style="font-size:0.95em;line-height:1.5;">{title}</div>'
                + (f'<div style="font-size:0.75em;color:{palette["muted"]};margin-top:6px;text-transform:uppercase;letter-spacing:1px;">{status}</div>' if status else '')
                + '</div>'
            )
        return (
            '<div style="column-count:2;column-gap:14px;">'
            + "".join(tiles) + '</div>'
        )

    if display_type == "catalog":
        items = []
        for e in entries:
            title = e.get("title") or e.get("name") or ""
            desc = e.get("description") or ""
            price = e.get("price")
            price_str = f'${price}' if price is not None else ""
            items.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:8px;">'
                f'<div style="font-size:1.1em;font-weight:600;">{title}</div>'
                + (f'<div style="font-size:0.85em;color:{palette["muted"]};line-height:1.5;">{desc[:200]}</div>' if desc else '')
                + (f'<div style="font-size:1.2em;font-weight:700;color:{palette["accent"]};">{price_str}</div>' if price_str else '')
                + '</div>'
            )
        return (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;">'
            + "".join(items) + '</div>'
        )

    # Default: list
    rows = []
    for e in entries:
        title = e.get("title") or e.get("deliverable_name") or e.get("name") or str(next(iter(e.values()), ""))
        sub = e.get("description") or e.get("status") or ""
        rows.append(
            f'<div style="padding:12px 0;border-bottom:1px solid {palette["border"]};display:flex;justify-content:space-between;align-items:center;">'
            f'<span>{title}</span>'
            + (f'<span style="font-size:0.8em;color:{palette["muted"]};">{sub}</span>' if sub else '')
            + '</div>'
        )
    return '<div>' + "".join(rows) + '</div>'


def _build_widget_html(module: Dict, entries: List[Dict], biz: Dict) -> str:
    pd = module.get("public_display") or {}
    display_type = pd.get("display_type", "list")
    title = pd.get("title_override") or module.get("name", "")
    description = pd.get("description") or ""
    palette = _palette_for(biz.get("type", "general"))

    entries_html = _render_entries_html(entries, display_type, palette)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Inter', system-ui, sans-serif;
  background: {palette['bg']};
  color: {palette['text']};
  padding: 24px;
  line-height: 1.6;
}}
h2 {{ font-size: 1.4em; font-weight: 700; margin-bottom: 6px; color: {palette['text']}; }}
.desc {{ font-size: 0.9em; color: {palette['muted']}; margin-bottom: 18px; }}
</style>
</head>
<body>
<h2>{title}</h2>
{f'<p class="desc">{description}</p>' if description else ''}
{entries_html}
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["public_site"])


@router.get("/public/site/{slug}")
async def get_site_html(slug: str):
    """Return the full generated site HTML for hosting/preview."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=html_content,business_id,status")
        if not sites:
            raise HTTPException(404, "Site not found")
        site = sites[0]
        html = site.get("html_content") or ""
        if not html:
            raise HTTPException(404, "Site has no content")
        return HTMLResponse(content=html)


@router.get("/public/site/{slug}/data")
async def get_site_data(slug: str):
    """Return structured JSON for dynamic site sections + forms."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        biz_id = sites[0]["business_id"]

        biz_rows, modules, forms = await asyncio.gather(
            _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,voice_profile&limit=1"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true"
                        f"&select=id,name,schema,public_display&limit=50"),
            _sb(client, f"/intake_forms?business_id=eq.{biz_id}&is_active=eq.true"
                        f"&select=id,name,form_type,settings&limit=20"),
        )

        biz = biz_rows[0] if biz_rows else {}

        # Filter to public modules and fetch their entries
        public_modules = [
            m for m in (modules or [])
            if (m.get("public_display") or {}).get("enabled")
        ]

        entry_tasks = [
            _sb(client,
                f"/module_entries?module_id=eq.{m['id']}&status=eq.active"
                f"&order={(m.get('public_display') or {}).get('sort_by', 'created_at')}.desc"
                f"&limit={(m.get('public_display') or {}).get('max_display', 20)}"
                f"&select=id,data,created_at")
            for m in public_modules
        ]
        entry_results = await asyncio.gather(*entry_tasks) if entry_tasks else []

        sections = []
        for i, m in enumerate(public_modules):
            pd = m.get("public_display") or {}
            visible = pd.get("visible_fields") or []
            hidden = pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"]
            filter_status = pd.get("filter_status") or []

            raw_entries = entry_results[i] or []
            filtered = []
            for e in raw_entries:
                data = e.get("data") or {}
                if filter_status and data.get("status") not in filter_status:
                    continue
                filtered.append({
                    **_filter_entry(data, visible, hidden),
                    "created_at": e.get("created_at"),
                })

            sections.append({
                "module_id": m["id"],
                "title": pd.get("title_override") or m.get("name"),
                "display_type": pd.get("display_type", "list"),
                "description": pd.get("description") or "",
                "entries": filtered,
            })

        # Forms linked to public modules
        public_mod_ids = {m["id"] for m in public_modules}
        linked_forms = [
            {"form_id": f["id"], "name": f["name"],
             "embed_url": f"/public/widget/form/{f['id']}"}
            for f in (forms or [])
            if (f.get("settings") or {}).get("linked_module_id") in public_mod_ids
        ]

        return {
            "business": {
                "name": biz.get("name"),
                "type": biz.get("type"),
            },
            "sections": sections,
            "forms": linked_forms,
        }


@router.get("/public/widget/{module_id}")
async def get_widget(module_id: str):
    """Return a self-contained styled HTML page for iframe embedding."""
    if not _check_rate(module_id):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        modules = await _sb(client,
            f"/custom_modules?id=eq.{module_id}&is_active=eq.true&limit=1&select=*")
        if not modules:
            raise HTTPException(404, "Module not found")
        module = modules[0]

        pd = module.get("public_display") or {}
        if not pd.get("enabled"):
            raise HTTPException(403, "Module not publicly visible")

        biz_id = module["business_id"]
        biz_rows = await _sb(client,
            f"/businesses?id=eq.{biz_id}&select=name,type,voice_profile&limit=1")
        biz = biz_rows[0] if biz_rows else {}

        sort_field = pd.get("sort_by", "created_at")
        max_display = pd.get("max_display", 20)
        filter_status = pd.get("filter_status") or []
        visible = pd.get("visible_fields") or []
        hidden = pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"]

        raw = await _sb(client,
            f"/module_entries?module_id=eq.{module_id}&status=eq.active"
            f"&order={sort_field}.desc&limit={max_display}&select=id,data,created_at") or []

        entries = []
        for e in raw:
            data = e.get("data") or {}
            if filter_status and data.get("status") not in filter_status:
                continue
            entries.append(_filter_entry(data, visible, hidden))

        html = _build_widget_html(module, entries, biz)
        return HTMLResponse(content=html)


@router.get("/public/health")
async def public_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "rate_limit_per_min": RATE_LIMIT_PER_MIN,
        "palettes": list(TYPE_PALETTES.keys()),
    }
