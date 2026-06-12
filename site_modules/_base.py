"""
site_modules/_base.py — Arc 26 PR2 — shared plumbing for section modules.

Contract every module follows:
    render(variant: str, content: dict, ctx: dict) -> tuple[str, str]
      → (section_html, section_css)

- HTML is built here in Python, never by the LLM. All content fields are
  escaped via safe(). Function (working links, responsive layout) is the
  module's job; the composer only chooses variants and writes copy.
- Styling references ONLY the --sx-* variables from brand_dna.css_variables.
- Editable text carries data-override-target="<section>/<field>" so the
  existing override system (Pass 4.0d/e) works unchanged.
- Images carry data-slot="<name>" with src="" so the existing slot
  population (Pass 4.0b.5) fills them (user upload > Unsplash > DALL-E).

ctx keys: dna (brand_dna tokens), business {name, type, tagline, slug},
booking {enabled, url}, offerings [rows], assets {logo_url, ...}.
"""
from __future__ import annotations

import html as _html
from typing import Any, Dict, List, Optional, Tuple


def safe(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value))


def safe_url(value: Any) -> str:
    """Escape + reject javascript:/data: URLs (defense in depth — these
    are practitioner/system URLs, but modules never trust input)."""
    s = str(value or "").strip()
    low = s.lower()
    if low.startswith(("javascript:", "data:", "vbscript:")):
        return ""
    return _html.escape(s, quote=True)


def ov(section: str, field: str) -> str:
    """data-override-target attribute for an editable text node."""
    return f'data-override-target="{section}/{field}"'


def eyebrow(section: str, text: str, field: str = "eyebrow") -> str:
    if not text:
        return ""
    return f'<div class="sxm-eyebrow" {ov(section, field)}>{safe(text)}</div>'


def heading_accent(dna: Dict[str, Any]) -> str:
    """The brand accent mark that precedes section headings — visual
    signature varies by accent_style so verticals don't look identical."""
    style = dna.get("accent_style", "thin_rule")
    if style in ("block_mark", "block"):
        return '<span class="sxm-mark sxm-mark-block" aria-hidden="true"></span>'
    if style in ("soft_rule", "soft"):
        return '<span class="sxm-mark sxm-mark-soft" aria-hidden="true"></span>'
    return '<span class="sxm-mark sxm-mark-thin" aria-hidden="true"></span>'


def cta_button(ctx: Dict[str, Any], label: str, section: str,
               field: str = "cta_label") -> str:
    """A CTA that always WORKS: booking page when enabled, else a
    mailto/contact anchor. Never a dead button."""
    booking = ctx.get("booking") or {}
    if booking.get("enabled") and booking.get("url"):
        href = safe_url(booking["url"])
    else:
        href = "#contact"
    return (f'<a class="sxm-cta" href="{href}">'
            f'<span {ov(section, field)}>{safe(label or "Get in touch")}</span></a>')


# ─── Base CSS shared by all modules (emitted once per page) ───────────

def base_css(dna: Dict[str, Any]) -> str:
    motion = dna.get("motion", "standard")
    reveal_css = "" if motion == "subtle" else """
.sxm-reveal { opacity: 0; transform: translateY(18px); transition: opacity .7s ease, transform .7s ease; }
.sxm-reveal.sxm-in { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) { .sxm-reveal { opacity: 1; transform: none; transition: none; } }"""
    return f"""
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; background: var(--sx-bg); color: var(--sx-text);
  font-family: var(--sx-font-body); font-size: 16.5px; line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}}
img {{ max-width: 100%; display: block; }}
h1, h2, h3 {{ font-family: var(--sx-font-heading); line-height: 1.08; margin: 0; }}
h1 {{ font-size: var(--sx-h1); font-weight: var(--sx-heading-weight); letter-spacing: var(--sx-letter-tight); }}
h2 {{ font-size: var(--sx-h2); font-weight: var(--sx-heading-weight); letter-spacing: var(--sx-letter-tight); }}
p {{ margin: 0 0 1.15em; max-width: 62ch; }}
a {{ color: var(--sx-accent); text-decoration: none; }}
.sxm-section {{ padding: var(--sx-section-pad) var(--sx-gutter); }}
.sxm-inner {{ max-width: var(--sx-content-max); margin: 0 auto; }}
.sxm-eyebrow {{
  font-size: .76rem; letter-spacing: .26em; text-transform: uppercase;
  color: var(--sx-accent); font-weight: 600; margin-bottom: 14px;
}}
.sxm-mark {{ display: block; margin-bottom: 22px; }}
.sxm-mark-thin {{ width: 56px; height: 2px; background: var(--sx-accent); }}
.sxm-mark-soft {{ width: 72px; height: 6px; border-radius: 99px; background: var(--sx-accent-soft); }}
.sxm-mark-block {{ width: 26px; height: 26px; background: var(--sx-accent); }}
.sxm-cta {{
  display: inline-block; padding: 16px 30px; border-radius: var(--sx-radius-button);
  background: var(--sx-accent); color: var(--sx-on-accent); font-weight: 700;
  letter-spacing: .04em; font-size: .95rem; transition: transform .18s ease, background .18s ease;
}}
.sxm-cta:hover {{ transform: translateY(-2px); background: var(--sx-accent-strong); }}
.sxm-muted {{ color: var(--sx-muted); }}
{reveal_css}
@media (max-width: 768px) {{ body {{ font-size: 15.5px; }} }}
"""


def reveal_script(dna: Dict[str, Any]) -> str:
    """Tiny self-contained IntersectionObserver — the only JS a composed
    page ships. Deterministic platform code (same trust model as the
    motion-module injections), never LLM-written."""
    if dna.get("motion", "standard") == "subtle":
        return ""
    return ("<script>(function(){try{var els=document.querySelectorAll('.sxm-reveal');"
            "if(!('IntersectionObserver'in window)){els.forEach(function(e){e.classList.add('sxm-in')});return}"
            "var io=new IntersectionObserver(function(entries){entries.forEach(function(en){"
            "if(en.isIntersecting){en.target.classList.add('sxm-in');io.unobserve(en.target)}})},"
            "{threshold:.12});els.forEach(function(e){io.observe(e)})}catch(e){}})();</script>")


def page_shell(dna: Dict[str, Any], title: str, body: str, css: str) -> str:
    import brand_dna
    fonts = brand_dna.google_fonts_url(dna)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts}" rel="stylesheet">
<style>
{brand_dna.css_variables(dna)}
{base_css(dna)}
{css}
</style>
</head>
<body>
{body}
{reveal_script(dna)}
</body>
</html>"""
