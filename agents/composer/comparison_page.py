"""Pass 4.0f Phase 5 — side-by-side comparison page.

Renders all three spike businesses' Cathedral Heros stacked vertically,
each iframe-embedded next to a metadata panel that surfaces:

  - business name + uuid
  - chosen variant
  - treatment fingerprint (color × spacing × emphasis)
  - heading_emphasis word
  - Composer's reasoning text in full

The reasoning text is the spike's primary judgment surface — Phase 4
showed three businesses produce visually distinct outputs, but visual
variety alone doesn't prove the variant choices are intentional. The
convergence diagnostic (Phase 4-bis) confirmed convergence across runs;
this page lets reviewers verify that intent against the visible
rationale at glance time.

Iframe srcdoc keeps each Hero's CSS scoped to its own document — no
risk of bleed between Heros or between Hero and the comparison shell.

Cost: ~$0.15/visit (3 fresh Composer calls). Cache-Control: no-store
on the endpoint so spike iteration keeps reviewing latest compositions.
"""
from __future__ import annotations

import html as html_lib
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# Same three spike businesses Phase 3 + Phase 4 + the convergence
# diagnostic used. Centralized so any future business swap touches one
# place.
SPIKE_BUSINESSES: List[Tuple[str, str]] = [
    ("KMJ Creative Solutions", "12773842-3cc6-41a7-9094-b8606e3f7549"),
    ("Director Loop Test",     "c8b7e157-903b-40c9-b5f2-700f196fe35b"),
    ("RoyalTeez Designz",      "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d"),
]


def _gather_renders() -> List[Dict[str, Any]]:
    """Fire Composer + render for each spike business. Soft-fails per
    business so one Composer error doesn't blank the whole page."""
    from agents.composer.render_pipeline import compose_and_render

    out: List[Dict[str, Any]] = []
    for name, bid in SPIKE_BUSINESSES:
        try:
            envelope = compose_and_render(bid, standalone=True)
            out.append({
                "name": name,
                "business_id": bid,
                "composition": envelope["composition"],
                "html": envelope["html"],
                "error": None,
            })
        except Exception as exc:
            logger.warning(f"[comparison_page] {name} failed: {exc}")
            out.append({
                "name": name,
                "business_id": bid,
                "composition": None,
                "html": None,
                "error": str(exc),
            })
    return out


def _render_metadata_panel(name: str, business_id: str, comp: Dict[str, Any]) -> str:
    """Right-side panel: variant + treatments + heading_emphasis + reasoning."""
    treatments = comp.get("treatments") or {}
    content = comp.get("content") or {}
    variant = comp.get("variant", "(unknown)")
    color_emphasis = treatments.get("color_emphasis", "?")
    spacing_density = treatments.get("spacing_density", "?")
    emphasis_weight = treatments.get("emphasis_weight", "?")
    heading = content.get("heading", "")
    heading_emphasis = content.get("heading_emphasis", "")
    eyebrow = content.get("eyebrow", "")
    cta_primary = content.get("cta_primary", "")
    reasoning = comp.get("reasoning", "(no reasoning captured)")

    return f"""
    <aside class="meta-panel">
      <div class="meta-row">
        <span class="meta-label">business</span>
        <span class="meta-value">
          <strong>{html_lib.escape(name)}</strong><br>
          <code>{html_lib.escape(business_id)}</code>
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">variant</span>
        <span class="meta-value variant-pill">{html_lib.escape(variant)}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">treatments</span>
        <span class="meta-value">
          <span class="treatment-pill">{html_lib.escape(color_emphasis)}</span>
          <span class="treatment-pill">{html_lib.escape(spacing_density)}</span>
          <span class="treatment-pill">{html_lib.escape(emphasis_weight)}</span>
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
          <br><small>italic emphasis: <em>{html_lib.escape(heading_emphasis)}</em></small>
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
    </aside>
    """


def _render_business_block(idx: int, entry: Dict[str, Any]) -> str:
    """One <section> per business: header bar + iframe + metadata panel."""
    name = entry["name"]
    business_id = entry["business_id"]

    if entry.get("error"):
        return f"""
        <section class="business-block error" id="biz-{idx}">
          <header class="block-header">
            <h2>{html_lib.escape(name)} <small>{html_lib.escape(business_id)}</small></h2>
            <span class="block-badge error-badge">Composer error</span>
          </header>
          <div class="error-detail">
            <code>{html_lib.escape(entry['error'])}</code>
          </div>
        </section>"""

    comp = entry["composition"] or {}
    hero_html = entry["html"] or ""
    variant = comp.get("variant", "?")

    # Embed the rendered Hero via iframe srcdoc. srcdoc takes raw HTML
    # but the value attribute requires &quot; for embedded double
    # quotes. html_lib.escape with quote=True handles & " < > correctly
    # for an attribute context.
    srcdoc_value = html_lib.escape(hero_html, quote=True)

    metadata_panel = _render_metadata_panel(name, business_id, comp)

    return f"""
    <section class="business-block" id="biz-{idx}">
      <header class="block-header">
        <h2>{html_lib.escape(name)} <small>{html_lib.escape(business_id[:8])}</small></h2>
        <span class="block-badge">{html_lib.escape(variant)}</span>
      </header>
      <div class="block-body">
        <div class="iframe-wrap">
          <iframe
            class="hero-iframe"
            srcdoc="{srcdoc_value}"
            title="Hero render — {html_lib.escape(name)}"
            loading="lazy"
            sandbox="allow-same-origin"
          ></iframe>
        </div>
        {metadata_panel}
      </div>
    </section>"""


# Comparison page shell. Fonts pulled in case any reasoning text
# benefits from the same family the Heros use; main shell stays
# system-font for clear contrast with Cathedral typography inside
# the iframes.
_COMPARISON_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cathedral Hero Composer — Side-by-side Comparison (Phase 5)</title>
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
    background: rgba(15, 23, 42, 0.92);
    backdrop-filter: blur(8px);
    z-index: 20;
  }}
  .page-header h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: -0.4px; }}
  .page-header p {{ margin: 0; color: var(--label-fg); font-size: 13px; }}
  .page-nav {{ margin-top: 14px; display: flex; gap: 18px; flex-wrap: wrap; }}
  .page-nav a {{ color: var(--link-fg); text-decoration: none; font-size: 13px; }}
  .page-nav a:hover {{ text-decoration: underline; }}

  .business-block {{ padding: 28px 32px; border-bottom: 1px solid #1E293B; }}
  .business-block.error {{ background: rgba(127, 29, 29, 0.18); }}
  .block-header {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px; gap: 16px;
  }}
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

  .block-body {{
    display: grid;
    grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
    gap: 24px;
    align-items: start;
  }}
  @media (max-width: 1100px) {{
    .block-body {{ grid-template-columns: 1fr; }}
  }}
  .iframe-wrap {{
    background: #000;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }}
  .hero-iframe {{
    width: 100%;
    height: 720px;
    border: none;
    display: block;
    background: #fff;
  }}

  .meta-panel {{
    background: var(--panel-bg);
    color: var(--panel-fg);
    padding: 20px 22px;
    border-radius: 8px;
    font-size: 13px;
    max-height: 720px;
    overflow-y: auto;
  }}
  .meta-row {{
    display: grid;
    grid-template-columns: 90px 1fr;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid #334155;
    align-items: start;
  }}
  .meta-row:last-child {{ border-bottom: none; }}
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
  .reasoning-row {{ padding-top: 14px; }}
  .reasoning-text {{
    line-height: 1.6;
    font-size: 13px;
    color: #E2E8F0;
    background: #0F172A;
    padding: 12px 14px;
    border-left: 3px solid var(--variant-bg);
    border-radius: 4px;
  }}

  footer.page-footer {{
    padding: 24px 32px 40px;
    color: var(--label-fg);
    font-size: 12px;
    text-align: center;
  }}
  footer.page-footer code {{ background: var(--panel-bg); padding: 2px 6px;
                             border-radius: 3px; font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<header class="page-header">
  <h1>Cathedral Hero Composer — Comparison</h1>
  <p>Three spike businesses. Each Hero embedded live in its own document.
     Composer reasoning surfaced beside the rendering — judge variant
     choice intent against the visible explanation.</p>
  <nav class="page-nav">{nav_links}</nav>
</header>

{business_blocks}

<footer class="page-footer">
  Pass 4.0f Phase 5 spike · 3 fresh Composer calls per visit
  (~$0.15) · <code>Cache-Control: no-store</code>
</footer>
</body>
</html>"""


def render_comparison_page_html() -> str:
    """Build the side-by-side comparison HTML."""
    entries = _gather_renders()
    nav_links = "\n".join(
        f'<a href="#biz-{i}">#{i+1} {html_lib.escape(e["name"])}</a>'
        for i, e in enumerate(entries)
    )
    business_blocks = "\n".join(
        _render_business_block(i, e) for i, e in enumerate(entries)
    )
    return _COMPARISON_SHELL.format(
        nav_links=nav_links,
        business_blocks=business_blocks,
    )
