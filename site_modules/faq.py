"""
faq — Arc S "Business Picture" (2026-07-10). The rules-of-engagement
section: policies (cancellation / deposit / lateness / refunds /
no-show) and owner-authored Q&As, rendered as a quiet ledger of
<details> rows.

Data source: ctx["faq"] — assembled by gather_context from
businesses.settings.business_picture (policies become questions;
explicit faq entries follow). Renders NOTHING when the business has no
picture yet — never invented. Q&A text is business data edited at the
source (Chief: set_business_policy / add_faq), so the rows ride the
sxm-faq-rows editability exemption; only the section heading is a
presentation target.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov

VARIANTS = ("ledger",)


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    rows = [r for r in (ctx.get("faq") or [])
            if isinstance(r, dict) and str(r.get("q") or "").strip()
            and str(r.get("a") or "").strip()]
    if not rows:
        return "", ""

    headline = str(content.get("headline") or "Good to know").strip()
    eyebrow_txt = str(content.get("eyebrow") or "").strip()
    eb = (f'<div class="sxm-eyebrow" {ov("faq", "eyebrow")}>{safe(eyebrow_txt)}</div>'
          if eyebrow_txt else "")

    items = "\n".join(
        f'''    <details class="sxm-faq-item"{" open" if i == 0 else ""}>
      <summary>{safe(r["q"])}<span class="sxm-faq-mark" aria-hidden="true">+</span></summary>
      <p>{safe(r["a"])}</p>
    </details>'''
        for i, r in enumerate(rows[:10]))

    html = f"""
<section class="sxm-section sxm-faq sxm-reveal" id="faq">
  <div class="sxm-inner">
    {eb}
    <h2 {ov('faq', 'headline')}>{safe(headline)}</h2>
    <div class="sxm-faq-rows">
{items}
    </div>
  </div>
</section>"""
    css = """
.sxm-faq .sxm-inner { max-width: min(var(--sx-content-max), 760px); }
.sxm-faq-rows { margin-top: 28px; border-top: 1px solid var(--sx-border); }
.sxm-faq-item { border-bottom: 1px solid var(--sx-border); }
.sxm-faq-item summary { display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; cursor: pointer; list-style: none; padding: 18px 2px;
  font-family: var(--sx-font-heading); font-weight: var(--sx-h3-weight, 600);
  font-size: 1.06rem; color: var(--sx-text); }
.sxm-faq-item summary::-webkit-details-marker { display: none; }
.sxm-faq-mark { color: var(--sx-accent); font-weight: 400; flex-shrink: 0;
  transition: transform .3s var(--sx-ease); }
.sxm-faq-item[open] .sxm-faq-mark { transform: rotate(45deg); }
.sxm-faq-item p { margin: 0; padding: 0 2px 20px; max-width: 58ch;
  color: var(--sx-text); opacity: .82; line-height: 1.65; font-size: .98rem; }
@media (max-width: 768px) { .sxm-faq-item summary { font-size: 1rem; padding: 16px 2px; } }"""
    return html, css
