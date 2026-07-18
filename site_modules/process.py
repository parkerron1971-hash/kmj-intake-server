"""
process — Design audit P3 (2026-07-18). The owner's own how-it-works
walk: the interview's process_steps (≤5 titled steps, optional blurbs)
rendered as a numbered sequence — numbering is honest here, the data IS
an ordered process.

Integrity rule (statband-strict): steps come from
ctx["site_prefs"]["process_steps"] — the owner typed them. Nothing is
ever invented; no steps → no section. Step text is business data edited
at the source (the site interview), so rows are not presentation
targets; only the framing (eyebrow/headline/intro) is.

Craft notes: the step numeral is the accent face in italic — the P2
third type role spending its one editorial moment per section — over a
hairline rule; titles in the display face; a quiet connector line walks
the eye across on desktop and down on mobile.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, ov, eyebrow, accent_headline, heading_accent

VARIANTS = ("steps",)

_MAX_STEPS = 5


def collect_steps(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """Owner-typed steps only. Public so the composer/smoke tests can ask
    'would process render?' without rendering."""
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    out: List[Dict[str, str]] = []
    for item in (prefs.get("process_steps") or [])[:_MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        out.append({"title": title, "blurb": str(item.get("blurb") or "").strip()})
    return out


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    steps = collect_steps(ctx)
    if not steps:
        return "", ""  # never invented — the owner writes the process

    eb = eyebrow("process", content.get("eyebrow") or "")
    headline = str(content.get("headline") or "How it works").strip()
    intro = str(content.get("intro") or "").strip()
    intro_html = (f'<p class="sxm-process-intro" {ov("process", "intro")}>{safe(intro)}</p>'
                  if intro else "")

    blocks = "".join(f"""
      <li class="sxm-step">
        <span class="sxm-step-n" aria-hidden="true">{i:02d}</span>
        <h3 class="sxm-step-title">{safe(s["title"])}</h3>
        {f'<p class="sxm-step-blurb">{safe(s["blurb"])}</p>' if s["blurb"] else ''}
      </li>""" for i, s in enumerate(steps, start=1))

    html = f"""
<section class="sxm-section sxm-process sxm-reveal" id="process">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('process', 'headline')}>{accent_headline(headline)}</h2>
    {intro_html}
    <ol class="sxm-step-track">{blocks}
    </ol>
  </div>
</section>"""
    css = """
.sxm-process-intro { max-width: 56ch; margin-top: 14px; opacity: .82; line-height: 1.65; }
.sxm-step-track { list-style: none; margin: clamp(32px, 5vw, 48px) 0 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: clamp(24px, 4vw, 40px); counter-reset: none; }
.sxm-step { position: relative; border-top: 1px solid var(--sx-border); padding-top: 18px; }
.sxm-step::before { content: ""; position: absolute; top: -1px; left: 0; width: 44px;
  height: 3px; border-radius: 99px;
  background: linear-gradient(90deg, var(--sx-accent), transparent); }
.sxm-step-n { display: block; font-family: var(--sx-font-accent, var(--sx-font-heading));
  font-style: italic; font-weight: 500; font-size: clamp(1.6rem, 3vw, 2.2rem);
  line-height: 1; color: var(--sx-accent); margin-bottom: 10px; }
.sxm-step-title { font-size: 1.08rem; margin: 0 0 8px; }
.sxm-step-blurb { margin: 0; font-size: .95rem; opacity: .8; line-height: 1.6;
  max-width: 34ch; }
@media (max-width: 768px) {
  .sxm-step-track { grid-template-columns: 1fr; gap: 20px; }
  .sxm-step { display: grid; grid-template-columns: auto 1fr; column-gap: 16px;
    align-items: baseline; padding-top: 16px; }
  .sxm-step-n { grid-row: 1 / span 2; margin-bottom: 0; }
  .sxm-step-blurb { grid-column: 2; max-width: none; }
}"""
    return html, css
