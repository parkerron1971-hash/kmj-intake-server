"""Pass 4.0g Phase F — Multi-Module Comparison page.

Renders all three spike businesses through the full Pass 4.0g multi-
module pipeline (Module Router -> module-specific Composer -> module-
specific render) and surfaces, for each business:

  - Module label (CATHEDRAL or STUDIO BRUT) prominently displayed,
    color-themed per module
  - Router decision: module_id, confidence, alternative_module,
    reasoning
  - Composer output: variant + all 8 treatments + content
  - Rendered Hero embedded via iframe srcdoc

Optional second column per business: the SAME business's output forced
through Cathedral (module_id='cathedral'). This makes the comparison
visually concrete:

  KMJ           — routed Cathedral   vs forced Cathedral   (backward compat)
  Director Loop — routed Cathedral   vs forced Cathedral   (backward compat)
  RoyalTee      — routed Studio Brut vs forced Cathedral   (THE key compare —
                                                            spike's failed case
                                                            vs the fix)

The Phase 4.0f Phase 5 comparison page (comparison_page.py) is kept
unchanged so the spike artifacts remain reviewable. This page is the
Phase F artifact for the Pass 4.0g GO/NO-GO decision.

Cost: ~$0.45 per uncached visit (3 router + 3 composer + 3 force-
Cathedral composer = 9 Sonnet calls). The page caches its pipeline
output in a process-local dict; repeat visits cost $0 unless the
caller passes ?refresh=1 to invalidate the cache.
"""
from __future__ import annotations

import html as html_lib
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Same three spike businesses Phase 3 + Phase 4 + Phase 4-bis + Phase D
# + Phase E used. Centralised so any future business swap touches one
# place across all spike + Pass 4.0g artifacts.
SPIKE_BUSINESSES: List[Tuple[str, str]] = [
    ("KMJ Creative Solutions", "12773842-3cc6-41a7-9094-b8606e3f7549"),
    ("Director Loop Test",     "c8b7e157-903b-40c9-b5f2-700f196fe35b"),
    ("RoyalTeez Designz",      "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d"),
]


# ─── In-memory cache ────────────────────────────────────────────────
# Pipeline output (router + composition + html) is expensive to
# regenerate — 9 Sonnet calls per visit at temperature 0.4/0.3, ~$0.45
# per regeneration. The page is a review surface viewed many times per
# day during Phase F decision-making, so the cache is keyed by
# business_id and lives for the lifetime of the process. Pass
# ?refresh=1 on the comparison_page URL to invalidate.
#
# Lock: dict mutation is GIL-safe but pipeline regeneration is the
# expensive op — guard regeneration with a per-business lock so two
# concurrent first-loads don't fire the LLM twice. The lock dict
# itself is module-global, but per-business locks scope concurrency
# to the smallest unit.

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_PER_BIZ_LOCKS: Dict[str, threading.Lock] = {}


def _get_biz_lock(business_id: str) -> threading.Lock:
    """Return (creating if absent) a per-business regeneration lock."""
    with _CACHE_LOCK:
        if business_id not in _PER_BIZ_LOCKS:
            _PER_BIZ_LOCKS[business_id] = threading.Lock()
        return _PER_BIZ_LOCKS[business_id]


def invalidate_cache() -> None:
    """Clear all cached pipeline outputs. Called when ?refresh=1."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_get(business_id: str) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        return _CACHE.get(business_id)


def _cache_set(business_id: str, entry: Dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE[business_id] = entry


# ─── Pipeline gather ────────────────────────────────────────────────

def _gather_one(name: str, business_id: str, *, include_force_cathedral: bool) -> Dict[str, Any]:
    """Fire the full Pass 4.0g pipeline (Router + Composer + Render)
    for one business AND optionally a force-Cathedral variant for the
    comparison column. Returns a dict suitable for the section
    renderer. Soft-fails per stage."""
    # Check cache first. Cache stores the FULL entry including the
    # optional force-Cathedral side, so a cache hit serves the whole
    # row without re-firing any LLM.
    cached = _cache_get(business_id)
    if cached is not None and cached.get("_include_force_cathedral") == include_force_cathedral:
        return cached

    lock = _get_biz_lock(business_id)
    with lock:
        # Re-check inside the lock — a concurrent caller may have just
        # populated the cache while we were waiting.
        cached = _cache_get(business_id)
        if cached is not None and cached.get("_include_force_cathedral") == include_force_cathedral:
            return cached

        entry: Dict[str, Any] = {
            "name": name,
            "business_id": business_id,
            "_include_force_cathedral": include_force_cathedral,
            "pipeline_error": None,
            "force_cathedral_error": None,
            "routing": None,
            "composition": None,
            "html": None,
            "module_id": None,
            "force_cathedral_composition": None,
            "force_cathedral_html": None,
        }

        # Step 1+2+3: full pipeline (Router -> Composer -> Render).
        # apply_overrides=False: this page surfaces what the COMPOSER
        # chose. Practitioner text/color overrides (Pass 4.0d PART 1)
        # are a downstream edit layer that runs AFTER composition; if
        # they were applied here they'd mask the composer's heading
        # under whatever the practitioner last edited on the live site.
        # Diagnosed in Pass 4.0g.x (L12): RoyalTee had a stored
        # hero.heading='Test Title' override-row that was bleeding into
        # the comparison page's iframes and hiding the composed
        # "Wear your crown loud" heading.
        try:
            from agents.composer.render_pipeline import compose_and_render_hero
            pipeline = compose_and_render_hero(business_id, apply_overrides=False)
            entry["routing"] = pipeline.get("routing_decision") or {}
            entry["composition"] = pipeline.get("composition") or {}
            entry["html"] = pipeline.get("html") or ""
            entry["module_id"] = pipeline.get("module_id") or "cathedral"
        except Exception as exc:
            logger.warning(f"[multi_module_comparison] {name} pipeline failed: {exc}")
            entry["pipeline_error"] = str(exc)

        # Step 4 (optional): force Cathedral for the comparison column.
        # apply_overrides=False here for the same reason as above —
        # the force-Cathedral column is part of the same architecture-
        # review surface.
        if include_force_cathedral:
            try:
                from agents.composer.render_pipeline import compose_and_render
                forced = compose_and_render(
                    business_id,
                    module_id="cathedral",
                    standalone=True,
                    apply_overrides=False,
                )
                entry["force_cathedral_composition"] = forced.get("composition") or {}
                entry["force_cathedral_html"] = forced.get("html") or ""
            except Exception as exc:
                logger.warning(f"[multi_module_comparison] {name} force-Cathedral failed: {exc}")
                entry["force_cathedral_error"] = str(exc)

        _cache_set(business_id, entry)
        return entry


def _gather_all(*, include_force_cathedral: bool) -> List[Dict[str, Any]]:
    return [
        _gather_one(name, bid, include_force_cathedral=include_force_cathedral)
        for name, bid in SPIKE_BUSINESSES
    ]


# ─── Section renderer ───────────────────────────────────────────────

def _pill(value: str, css_class: str = "treatment-pill") -> str:
    return f'<span class="{css_class}">{html_lib.escape(value)}</span>'


def _module_badge(module_id: str) -> str:
    """Big, prominent module label. Color-themed per module: Cathedral
    = navy+gold; Studio Brut = red+near-black."""
    if module_id == "studio_brut":
        return (
            '<span class="module-badge module-studio-brut" '
            'title="Studio Brut module">STUDIO BRUT</span>'
        )
    return (
        '<span class="module-badge module-cathedral" '
        'title="Cathedral module">CATHEDRAL</span>'
    )


def _render_router_panel(routing: Dict[str, Any]) -> str:
    """Top of the metadata column — router decision in full."""
    if not routing:
        return ""
    module_id = routing.get("module_id", "?")
    confidence = routing.get("confidence", 0.0)
    reasoning = routing.get("reasoning", "(no reasoning captured)")
    alternative_module = routing.get("alternative_module") or "—"
    try:
        conf_str = f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        conf_str = str(confidence)

    return f"""
    <div class="router-panel">
      <div class="panel-title">MODULE ROUTER</div>
      <div class="meta-row">
        <span class="meta-label">module</span>
        <span class="meta-value">{_pill(module_id, "variant-pill")}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">confidence</span>
        <span class="meta-value">{_pill(conf_str, "treatment-pill")}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">alt</span>
        <span class="meta-value">{html_lib.escape(str(alternative_module))}</span>
      </div>
      <div class="meta-row reasoning-row">
        <span class="meta-label">reasoning</span>
        <span class="meta-value reasoning-text router-reasoning">{html_lib.escape(reasoning)}</span>
      </div>
    </div>
    """


def _render_composer_panel(comp: Dict[str, Any]) -> str:
    """Middle of the metadata column — composer choice in full
    (variant + 8 treatments + content + reasoning)."""
    if not comp:
        return ""
    treatments = comp.get("treatments") or {}
    content = comp.get("content") or {}
    variant = comp.get("variant", "?")
    reasoning = comp.get("reasoning", "(no reasoning captured)")
    # Structural
    color_emphasis = treatments.get("color_emphasis", "?")
    spacing_density = treatments.get("spacing_density", "?")
    emphasis_weight = treatments.get("emphasis_weight", "?")
    # Visual depth (Phase 2.6)
    background = treatments.get("background", "?")
    color_depth = treatments.get("color_depth", "?")
    ornament = treatments.get("ornament", "?")
    typography = treatments.get("typography", "?")
    image_treatment = treatments.get("image_treatment", "?")
    # Content
    heading = content.get("heading", "")
    heading_emphasis = content.get("heading_emphasis", "")
    eyebrow = content.get("eyebrow", "")
    cta_primary = content.get("cta_primary", "")

    return f"""
    <div class="composer-panel">
      <div class="panel-title">COMPOSER</div>
      <div class="meta-row">
        <span class="meta-label">variant</span>
        <span class="meta-value">{_pill(variant, "variant-pill")}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">structural</span>
        <span class="meta-value">
          {_pill(color_emphasis)}
          {_pill(spacing_density)}
          {_pill(emphasis_weight)}
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">depth</span>
        <span class="meta-value">
          {_pill(f"bg: {background}", "depth-pill")}
          {_pill(f"color: {color_depth}", "depth-pill")}
          {_pill(f"orn: {ornament}", "depth-pill")}
          {_pill(f"type: {typography}", "depth-pill")}
          {_pill(f"img: {image_treatment}", "depth-pill")}
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">eyebrow</span>
        <span class="meta-value">{html_lib.escape(eyebrow)}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">heading</span>
        <span class="meta-value">
          {html_lib.escape(heading)}
          <br><small>emphasis: <em>{html_lib.escape(heading_emphasis)}</em></small>
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">CTA</span>
        <span class="meta-value">{html_lib.escape(cta_primary)}</span>
      </div>
      <div class="meta-row reasoning-row">
        <span class="meta-label">reasoning</span>
        <span class="meta-value reasoning-text">{html_lib.escape(reasoning)}</span>
      </div>
    </div>
    """


def _render_hero_iframe(hero_html: str, label: str) -> str:
    """Embed a Hero via iframe srcdoc."""
    if not hero_html:
        return '<div class="iframe-wrap iframe-empty">No render</div>'
    srcdoc_value = html_lib.escape(hero_html, quote=True)
    return f"""
    <div class="iframe-wrap">
      <iframe
        class="hero-iframe"
        srcdoc="{srcdoc_value}"
        title="Hero render — {html_lib.escape(label)}"
        loading="lazy"
        sandbox="allow-same-origin"
      ></iframe>
    </div>
    """


def _render_business_block(idx: int, entry: Dict[str, Any], *, include_force_cathedral: bool) -> str:
    """One <section> per business: header bar + new pipeline render +
    metadata + optional force-Cathedral column."""
    name = entry["name"]
    business_id = entry["business_id"]

    # Hard failure (pipeline blew up entirely) — render error card.
    if entry.get("pipeline_error") and not entry.get("html"):
        return f"""
        <section class="business-block error" id="biz-{idx}">
          <header class="block-header">
            <h2>{html_lib.escape(name)} <small>{html_lib.escape(business_id)}</small></h2>
            <span class="block-badge error-badge">Pipeline error</span>
          </header>
          <div class="error-detail">
            <code>{html_lib.escape(str(entry['pipeline_error']))}</code>
          </div>
        </section>"""

    module_id = entry.get("module_id") or "cathedral"
    routing = entry.get("routing") or {}
    composition = entry.get("composition") or {}
    hero_html = entry.get("html") or ""
    variant = composition.get("variant", "?")

    router_panel = _render_router_panel(routing)
    composer_panel = _render_composer_panel(composition)
    primary_iframe = _render_hero_iframe(hero_html, f"{name} — {module_id}")

    # Optional force-Cathedral column.
    force_col = ""
    if include_force_cathedral:
        force_comp = entry.get("force_cathedral_composition") or {}
        force_html = entry.get("force_cathedral_html") or ""
        force_err = entry.get("force_cathedral_error")
        if force_err:
            force_col = f"""
            <div class="force-cathedral-col">
              <div class="force-label">FORCED CATHEDRAL (comparison)</div>
              <div class="error-detail">
                <code>{html_lib.escape(str(force_err))}</code>
              </div>
            </div>
            """
        else:
            force_variant = force_comp.get("variant", "?")
            force_iframe = _render_hero_iframe(force_html, f"{name} — forced Cathedral")
            force_col = f"""
            <div class="force-cathedral-col">
              <div class="force-label">FORCED CATHEDRAL
                <span class="force-variant">{_pill(force_variant, "variant-pill")}</span>
              </div>
              {force_iframe}
            </div>
            """

    return f"""
    <section class="business-block" id="biz-{idx}">
      <header class="block-header">
        <div class="header-left">
          <h2>{html_lib.escape(name)} <small>{html_lib.escape(business_id[:8])}</small></h2>
        </div>
        <div class="header-right">
          {_module_badge(module_id)}
          <span class="block-badge">{html_lib.escape(variant)}</span>
        </div>
      </header>
      <div class="block-body">
        <div class="primary-col">
          <div class="col-label">ROUTED → {html_lib.escape(module_id.upper().replace('_', ' '))}</div>
          {primary_iframe}
        </div>
        {force_col}
        <aside class="meta-panel">
          {router_panel}
          {composer_panel}
        </aside>
      </div>
    </section>"""


# ─── Page shell ─────────────────────────────────────────────────────

_COMPARISON_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pass 4.0g Multi-Module Comparison</title>
<style>
  :root {{
    --shell-bg: #0F172A;
    --shell-fg: #E2E8F0;
    --panel-bg: #1E293B;
    --panel-fg: #CBD5E1;
    --label-fg: #94A3B8;
    --pill-bg: #334155;
    --pill-fg: #F1F5F9;
    --variant-bg: #C6952F;
    --variant-fg: #0F172A;
    --error-bg: #7F1D1D;
    --error-fg: #FECACA;
    --link-fg: #60A5FA;
    --cathedral-bg: #0A1628;
    --cathedral-fg: #C6952F;
    --studio-brut-bg: #DC2626;
    --studio-brut-fg: #FACC15;
  }}
  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    background: var(--shell-bg);
    color: var(--shell-fg);
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.55;
  }}
  .page-header {{
    padding: 32px 32px 16px;
    border-bottom: 1px solid #1E293B;
    position: sticky;
    top: 0;
    background: rgba(15, 23, 42, 0.94);
    backdrop-filter: blur(8px);
    z-index: 20;
  }}
  .page-header h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: -0.4px; }}
  .page-header p {{ margin: 0; color: var(--label-fg); font-size: 13px; }}
  .page-nav {{ margin-top: 14px; display: flex; gap: 18px; flex-wrap: wrap; }}
  .page-nav a {{ color: var(--link-fg); text-decoration: none; font-size: 13px; }}
  .page-nav a:hover {{ text-decoration: underline; }}
  .refresh-link {{
    margin-left: auto; padding: 4px 10px; border: 1px solid var(--link-fg);
    border-radius: 4px; font-size: 12px;
  }}

  .business-block {{ padding: 28px 32px; border-bottom: 1px solid #1E293B; }}
  .business-block.error {{ background: rgba(127, 29, 29, 0.18); }}
  .block-header {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px; gap: 16px;
  }}
  .header-left {{ display: flex; align-items: center; gap: 14px; }}
  .header-right {{ display: flex; align-items: center; gap: 10px; }}
  .block-header h2 {{ margin: 0; font-size: 18px; font-weight: 600; }}
  .block-header small {{ color: var(--label-fg); font-weight: 400; font-size: 12px; }}
  .block-badge {{
    background: var(--variant-bg); color: var(--variant-fg);
    padding: 4px 12px; border-radius: 4px;
    font-family: ui-monospace, monospace; font-size: 12px;
    font-weight: 600; letter-spacing: 0.4px;
  }}
  .error-badge {{ background: var(--error-bg); color: var(--error-fg); }}
  .error-detail {{ background: var(--panel-bg); padding: 12px 16px; border-radius: 6px;
                  font-family: ui-monospace, monospace; font-size: 12px; }}

  .module-badge {{
    padding: 6px 14px; border-radius: 4px;
    font-family: ui-monospace, monospace; font-size: 13px;
    font-weight: 700; letter-spacing: 1.2px;
    text-transform: uppercase;
  }}
  .module-cathedral {{
    background: var(--cathedral-bg); color: var(--cathedral-fg);
    border: 1px solid var(--cathedral-fg);
  }}
  .module-studio-brut {{
    background: var(--studio-brut-bg); color: var(--studio-brut-fg);
    border: 1px solid var(--studio-brut-fg);
  }}

  .block-body {{
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.2fr) minmax(0, 1fr);
    gap: 20px;
    align-items: start;
  }}
  .block-body.no-compare {{
    grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
  }}
  @media (max-width: 1400px) {{
    .block-body {{ grid-template-columns: 1fr; }}
  }}
  .primary-col, .force-cathedral-col {{ display: flex; flex-direction: column; gap: 8px; }}
  .col-label {{
    color: var(--label-fg);
    font-size: 11px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding-bottom: 4px;
  }}
  .force-label {{
    color: var(--label-fg);
    font-size: 11px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .iframe-wrap {{
    background: #000;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }}
  .iframe-empty {{ background: var(--panel-bg); padding: 24px; text-align: center;
                  color: var(--label-fg); font-size: 12px; }}
  .hero-iframe {{
    width: 100%;
    height: 640px;
    border: none;
    display: block;
    background: #fff;
  }}

  .meta-panel {{
    background: var(--panel-bg);
    color: var(--panel-fg);
    padding: 18px 20px;
    border-radius: 8px;
    font-size: 12.5px;
    max-height: 640px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }}
  .panel-title {{
    color: var(--label-fg);
    font-size: 10px;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    font-weight: 700;
    padding-bottom: 4px;
    border-bottom: 1px solid #334155;
  }}
  .router-panel, .composer-panel {{ display: flex; flex-direction: column; }}
  .meta-row {{
    display: grid;
    grid-template-columns: 80px 1fr;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #334155;
    align-items: start;
  }}
  .router-panel .meta-row:last-of-type,
  .composer-panel .meta-row:last-of-type {{ border-bottom: none; }}
  .meta-label {{
    color: var(--label-fg);
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.8px;
    padding-top: 2px;
  }}
  .meta-value {{ color: var(--panel-fg); word-break: break-word; }}
  .meta-value code {{ background: #0F172A; padding: 2px 6px; border-radius: 3px;
                     font-family: ui-monospace, monospace; font-size: 11px; }}
  .meta-value small {{ color: var(--label-fg); font-size: 11px; }}
  .meta-value em {{ color: var(--variant-bg); font-style: italic; font-weight: 500; }}

  .variant-pill {{
    display: inline-block;
    background: var(--variant-bg); color: var(--variant-fg);
    padding: 4px 10px; border-radius: 4px;
    font-family: ui-monospace, monospace; font-size: 11px;
    font-weight: 600; letter-spacing: 0.3px;
  }}
  .treatment-pill {{
    display: inline-block;
    background: var(--pill-bg); color: var(--pill-fg);
    padding: 3px 8px; border-radius: 3px;
    font-family: ui-monospace, monospace; font-size: 11px;
    margin-right: 4px; margin-bottom: 4px;
  }}
  .depth-pill {{
    display: inline-block;
    background: color-mix(in srgb, var(--variant-bg) 22%, var(--panel-bg));
    color: var(--pill-fg);
    border: 1px solid color-mix(in srgb, var(--variant-bg) 35%, transparent);
    padding: 3px 8px; border-radius: 3px;
    font-family: ui-monospace, monospace; font-size: 10.5px;
    margin-right: 4px; margin-bottom: 4px;
  }}
  .reasoning-row {{ padding-top: 12px; }}
  .reasoning-text {{
    line-height: 1.6;
    font-size: 12.5px;
    color: #E2E8F0;
    background: #0F172A;
    padding: 10px 12px;
    border-left: 3px solid var(--variant-bg);
    border-radius: 4px;
  }}
  .router-reasoning {{ border-left-color: #60A5FA; }}

  footer.page-footer {{
    padding: 24px 32px 40px;
    color: var(--label-fg);
    font-size: 12px;
    text-align: center;
    line-height: 1.7;
  }}
  footer.page-footer code {{ background: var(--panel-bg); padding: 2px 6px;
                             border-radius: 3px; font-family: ui-monospace, monospace; }}
  .footer-stats {{ display: inline-flex; gap: 16px; margin-top: 6px; flex-wrap: wrap;
                  justify-content: center; }}
</style>
</head>
<body>
<header class="page-header">
  <h1>Pass 4.0g Multi-Module Comparison</h1>
  <p>Module Router + Composer + Render through the full pipeline. Each
     business routed automatically; module label and routing rationale
     surfaced beside the rendered hero.</p>
  <nav class="page-nav">
    {nav_links}
    <a class="refresh-link" href="?refresh=1">Refresh (re-fire pipeline)</a>
  </nav>
</header>

{business_blocks}

<footer class="page-footer">
  Pass 4.0g Phase F · Architecture summary: 2 modules · 22 total variants (11 Cathedral + 11 Studio Brut) ·
  Module Router + Composer + Render pipeline operational
  <div class="footer-stats">
    <span>cached: <code>{cache_status}</code></span>
    <span>cost on cache miss: ~$0.45 (9 Sonnet calls)</span>
    <span>cached visits: $0</span>
  </div>
</footer>
</body>
</html>"""


def render_multi_module_comparison_html(
    *,
    refresh: bool = False,
    include_force_cathedral: bool = True,
) -> str:
    """Build the Phase F multi-module comparison HTML.

    refresh=True invalidates the in-memory pipeline cache before
    re-gathering. include_force_cathedral=False omits the second
    column (faster + cheaper; the architectural test still passes
    with only the routed output)."""
    if refresh:
        invalidate_cache()

    # Cache snapshot BEFORE gathering — distinguishes cold vs warm
    # visits in the footer.
    with _CACHE_LOCK:
        had_cache = bool(_CACHE)

    entries = _gather_all(include_force_cathedral=include_force_cathedral)

    nav_links = "\n".join(
        f'<a href="#biz-{i}">#{i+1} {html_lib.escape(e["name"])}</a>'
        for i, e in enumerate(entries)
    )
    business_blocks = "\n".join(
        _render_business_block(i, e, include_force_cathedral=include_force_cathedral)
        for i, e in enumerate(entries)
    )

    with _CACHE_LOCK:
        cache_status = (
            f"WARM ({len(_CACHE)}/{len(SPIKE_BUSINESSES)} businesses)"
            if had_cache
            else f"COLD → WARM ({len(_CACHE)}/{len(SPIKE_BUSINESSES)} businesses cached)"
        )

    return _COMPARISON_SHELL.format(
        nav_links=nav_links,
        business_blocks=business_blocks,
        cache_status=cache_status,
    )
