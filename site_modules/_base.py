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
import json as _json
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


# Platform → profile-URL base. Shared by contact_footer (visible social
# links) and build_page_meta (JSON-LD sameAs). Handles may be full URLs
# or bare @handles.
SOCIAL_BASES: Dict[str, str] = {
    "instagram": "https://instagram.com/",
    "facebook": "https://facebook.com/",
    "youtube": "https://youtube.com/",
    "twitter": "https://twitter.com/",
    "linkedin": "https://linkedin.com/in/",
    "tiktok": "https://tiktok.com/@",
}


def social_profile_url(platform: str, handle: Any) -> str:
    """Full profile URL from a platform + handle (or pass-through URL).
    Empty string when it can't be resolved to a real URL."""
    h = str(handle or "").strip()
    if not h:
        return ""
    if h.startswith("http"):
        return h
    base = SOCIAL_BASES.get((platform or "").lower())
    return base + h.lstrip("@") if base else ""


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
/* Palette discipline — dark/light section alternation gives the page rhythm
   (a "stage then room then stage" cadence) instead of one flat ground. */
.sxm-section:nth-of-type(even) {{ background: var(--sx-surface); }}
/* Accent scarcity (DRO single_semantic): the accent carries MEANING, so it
   stays on CTAs + links only; decorative accent (eyebrows, marks) goes quiet. */
body.sx-scarce-accent .sxm-eyebrow {{ color: var(--sx-muted); }}
body.sx-scarce-accent .sxm-mark-thin,
body.sx-scarce-accent .sxm-mark-block {{ background: var(--sx-border); }}
body.sx-scarce-accent .sxm-mark-soft {{ background: color-mix(in srgb, var(--sx-muted) 45%, transparent); }}
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


def _trim_words(text: str, limit: int) -> str:
    """Trim to <= limit chars on a word boundary (no mid-word cuts)."""
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(",;:—- ")
    return cut


def build_page_meta(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic SEO/identity payload for page_shell — built ONLY
    from real business data; every field may be empty and empty fields
    emit no tags. (Arc 1 'Wear the Brand'.)"""
    bundle = ctx.get("bundle") or {}
    b = bundle.get("business") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    assets = bundle.get("assets") or {}
    biz = ctx.get("business") or {}
    contact = ctx.get("contact") or {}

    name = (biz.get("name") or b.get("name") or "").strip()
    tagline = str(b.get("tagline") or "").strip()
    pitch = str(b.get("elevator_pitch") or "").strip()
    about = str(intel.get("about_business") or "").strip()
    description = tagline or pitch or (_trim_words(about, 155) if about else "")

    slug = str(biz.get("slug") or "").strip()
    canonical = f"https://{slug}.mysolutionist.app" if slug else ""

    favicon = assets.get("favicon") or ""
    social_card = assets.get("social_card") or ""
    og_title = f"{name} — {tagline}" if (name and tagline) else name

    same_as = [u for u in (
        social_profile_url(k, v) for k, v in (contact.get("social") or {}).items()
    ) if u.startswith("http")]

    # JSON-LD LocalBusiness — only fields that exist; empties are omitted.
    jsonld: Dict[str, Any] = {"@context": "https://schema.org",
                              "@type": "LocalBusiness"}
    for key, val in (("name", name), ("description", description),
                     ("url", canonical), ("telephone", contact.get("phone")),
                     ("email", contact.get("email")),
                     ("address", contact.get("address"))):
        if str(val or "").strip():
            jsonld[key] = str(val).strip()
    hours = str(contact.get("hours") or "").strip()
    if hours:
        jsonld["openingHours"] = hours.replace("–", "-")
    if same_as:
        jsonld["sameAs"] = same_as
    if len(jsonld) <= 2:  # only @context/@type → nothing real to state
        jsonld = {}

    return {
        "description": description,
        "canonical": canonical,
        "favicon": favicon if str(favicon).startswith("http") else "",
        "og_title": og_title,
        "og_image": social_card if str(social_card).startswith("http") else "",
        "jsonld": jsonld,
    }


def _head_meta_block(meta: Optional[Dict[str, Any]]) -> str:
    """Emit description/canonical/favicon/OG/Twitter/JSON-LD tags —
    ONLY for fields that carry data (never an empty tag). og:image at
    shell time is the brand social card; when absent, the composer
    injects the resolved hero image post slot-resolution
    (site_composer._ensure_og_image)."""
    if not meta:
        return ""
    lines: List[str] = []
    desc = str(meta.get("description") or "").strip()
    canonical = str(meta.get("canonical") or "").strip()
    og_title = str(meta.get("og_title") or "").strip()
    og_image = str(meta.get("og_image") or "").strip()
    favicon = str(meta.get("favicon") or "").strip()

    if desc:
        lines.append(f'<meta name="description" content="{safe(desc)}">')
    if canonical:
        lines.append(f'<link rel="canonical" href="{safe_url(canonical)}">')
    if favicon:
        lines.append(f'<link rel="icon" href="{safe_url(favicon)}">')
    if og_title:
        lines.append(f'<meta property="og:title" content="{safe(og_title)}">')
    if desc:
        lines.append(f'<meta property="og:description" content="{safe(desc)}">')
    if canonical:
        lines.append(f'<meta property="og:url" content="{safe_url(canonical)}">')
    lines.append('<meta property="og:type" content="website">')
    if og_image:
        lines.append(f'<meta property="og:image" content="{safe_url(og_image)}">')
        lines.append('<meta name="twitter:card" content="summary_large_image">')
        lines.append(f'<meta name="twitter:image" content="{safe_url(og_image)}">')
    jsonld = meta.get("jsonld") or {}
    if jsonld:
        payload = _json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
        lines.append(f'<script type="application/ld+json">{payload}</script>')
    return "\n".join(lines)


def page_shell(dna: Dict[str, Any], title: str, body: str, css: str,
               design: Optional[Dict[str, Any]] = None,
               meta: Optional[Dict[str, Any]] = None) -> str:
    import brand_dna
    fonts = brand_dna.google_fonts_url(dna)
    # DRO single_semantic → accent scarcity body class (CSS in base_css).
    accent_strategy = ((design or {}).get("palette") or {}).get("accent_strategy")
    body_class = "sx-scarce-accent" if accent_strategy == "single_semantic" else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe(title)}</title>
{_head_meta_block(meta)}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts}" rel="stylesheet">
<style>
{brand_dna.css_variables(dna)}
{base_css(dna)}
{css}
</style>
</head>
<body class="{body_class}">
{body}
{reveal_script(dna)}
</body>
</html>"""
