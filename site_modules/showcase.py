"""Showcase module — renders the practitioner's PUBLIC custom modules and
their real entries (the things the business actually runs: consultations,
trackers, projects, programs…). Pulls from ctx['public_modules'] which
gather_context populated from custom_modules(public_display.enabled) +
module_entries. Never invents entries. Content: eyebrow, headline, intro
(section framing only). Variants: cards, list."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, ov, eyebrow, heading_accent, accent_headline

VARIANTS = ("cards", "list")

_MAX_MODULES = 4
_MAX_FIELDS_PER_ENTRY = 4


def _entry_card(entry: Dict[str, Any], card: bool = False) -> str:
    """Render one entry as a small card from its kept fields (label: value).
    `card=True` (cards layout) adds the shared quality-floor depth/hover."""
    lines = []
    for i, (k, v) in enumerate(entry.items()):
        if k == "created_at" or i >= _MAX_FIELDS_PER_ENTRY:
            continue
        label = safe(str(k).replace("_", " ").title())
        val = safe(str(v))
        if i == 0:
            lines.append(f'<div class="sxm-sc-title">{val}</div>')
        else:
            lines.append(f'<div class="sxm-sc-field"><span class="sxm-muted">{label}:</span> {val}</div>')
    cls = "sxm-sc-entry sxm-card" if card else "sxm-sc-entry"
    return f'<div class="{cls}">{"".join(lines)}</div>' if lines else ""


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    mods: List[Dict[str, Any]] = [m for m in (ctx.get("public_modules") or [])
                                  if m.get("entries")][:_MAX_MODULES]
    if not mods:
        return "", ""  # nothing public to show → no section; nothing invented

    eb = eyebrow("showcase", content.get("eyebrow") or "What we run")
    headline = content.get("headline") or "Inside the practice"
    intro = content.get("intro") or ""
    intro_html = (f'<p class="sxm-sc-intro sxm-muted" {ov("showcase", "intro")}>{safe(intro)}</p>'
                  if intro else "")

    blocks = []
    for m in mods:
        layout_class = "sxm-sc-cards" if (variant != "list" and m.get("display_type") != "list") else "sxm-sc-list"
        cards = "".join(_entry_card(e, card=(layout_class == "sxm-sc-cards"))
                        for e in m["entries"][:8])
        desc = safe(m.get("description") or "")
        desc_html = f'<p class="sxm-sc-mdesc sxm-muted">{desc}</p>' if desc else ""
        blocks.append(f"""
    <div class="sxm-sc-module">
      <h3 class="sxm-sc-mtitle">{safe(m.get('title') or '')}</h3>
      {desc_html}
      <div class="{layout_class}">{cards}</div>
    </div>""")

    html = f"""
<section class="sxm-section sxm-showcase sxm-reveal" id="showcase">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('showcase', 'headline')}>{accent_headline(headline)}</h2>
    {intro_html}
    {''.join(blocks)}
  </div>
</section>"""

    css = """
.sxm-showcase h2 { margin-bottom: 16px; }
.sxm-sc-intro { font-size: 1.05rem; margin-bottom: 8px; }
.sxm-sc-module { margin-top: 40px; }
.sxm-sc-mtitle { font-size: 1.3rem; margin-bottom: 6px; }
.sxm-sc-mdesc { font-size: .98rem; margin: 0 0 18px; }
.sxm-sc-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 18px; }
.sxm-sc-list { display: flex; flex-direction: column; }
.sxm-sc-list .sxm-sc-entry { padding: 18px 0; border-top: 1px solid var(--sx-border); }
.sxm-sc-list .sxm-sc-entry:last-child { border-bottom: 1px solid var(--sx-border); }
.sxm-sc-cards .sxm-sc-entry { background: var(--sx-surface); border: 1px solid var(--sx-border);
  border-radius: var(--sx-radius-card); padding: 20px; }
.sxm-sc-title { font-family: var(--sx-font-heading); font-size: 1.08rem; font-weight: 700; margin-bottom: 8px; }
.sxm-sc-field { font-size: .94rem; margin-top: 4px; }"""
    return html, css
