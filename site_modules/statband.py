"""Stat band module — Arc 3 "Expressive Range".

3-4 big-number stats with small-caps labels (craft source: studio_brut
stat_strip's massive-numeral + small-caps-label + thin signal underline
vocabulary — ported into the site_modules token contract; the underline
gradient FADES per the soft-gradient rule).

Integrity rule, stricter than most modules: numbers are computed from
REAL ctx data only — years on the platform (business created_at),
active offerings count, testimonials count, plus a sessions-completed
figure if the context ever carries one. Nothing is ever invented; with
fewer than two real stats the section renders nothing at all.

Content: eyebrow, headline (both optional framing).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from ._base import safe, ov, eyebrow, heading_accent

VARIANTS = ("band",)

_MIN_STATS = 2
_MAX_STATS = 4


def _years_on_platform(ctx: Dict[str, Any]) -> int:
    """Whole years since the business row was created; 0 when unknown."""
    created = str((ctx.get("business") or {}).get("created_at") or "").strip()
    if not created:
        return 0
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - dt).days // 365.25)
    except (ValueError, OverflowError):
        return 0


def collect_stats(ctx: Dict[str, Any]) -> List[Tuple[str, str]]:
    """[(number, label)] from real ctx data only. Public so the composer
    (or smoke tests) can ask 'would statband render?' without rendering."""
    stats: List[Tuple[str, str]] = []
    years = _years_on_platform(ctx)
    if years >= 1:
        stats.append((f"{years}+", "Years in business"))
    n_off = len([o for o in (ctx.get("offerings") or []) if o.get("name")])
    if n_off >= 2:
        stats.append((str(n_off), "Ways to work together"))
    n_t = len([t for t in (ctx.get("testimonials") or [])
               if (t.get("quote") or "").strip()])
    if n_t >= 2:
        stats.append((str(n_t), "Client voices"))
    sessions = ctx.get("sessions_completed")  # not populated today —
    # honored if a future context ever carries it; never fabricated here.
    if isinstance(sessions, (int, float)) and sessions >= 10:
        stats.append((f"{int(sessions):,}", "Sessions completed"))
    return stats[:_MAX_STATS]


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    stats = collect_stats(ctx)
    if len(stats) < _MIN_STATS:
        return "", ""  # no real numbers → no section, ever

    eb = eyebrow("statband", content.get("eyebrow") or "")
    headline = content.get("headline") or ""
    headline_html = (f'<h2 {ov("statband", "headline")}>{safe(headline)}</h2>'
                     if headline else "")
    blocks = "".join(f"""
      <div class="sxm-stat">
        <span class="sxm-stat-n">{safe(num)}</span>
        <span class="sxm-stat-rule" aria-hidden="true"></span>
        <span class="sxm-stat-label">{safe(label)}</span>
      </div>""" for num, label in stats)

    html = f"""
<section class="sxm-section sxm-statband sxm-reveal" id="stats">
  <div class="sxm-inner">
    {heading_accent(dna) if (headline or content.get('eyebrow')) else ''}
    {eb}
    {headline_html}
    <div class="sxm-stat-grid">{blocks}
    </div>
  </div>
</section>"""
    css = """
.sxm-statband { background: var(--sx-surface-2); }
.sxm-statband h2 { margin-bottom: 30px; }
.sxm-stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: clamp(24px, 4vw, 48px); }
.sxm-stat-n { display: block; font-family: var(--sx-font-heading);
  font-size: clamp(2.8rem, 6vw, 4.6rem); font-weight: var(--sx-heading-weight);
  letter-spacing: var(--sx-letter-tight); line-height: 1; }
.sxm-stat-rule { display: block; width: 44px; height: 3px; border-radius: 99px;
  margin: 14px 0 10px; background: linear-gradient(90deg, var(--sx-accent), transparent); }
.sxm-stat-label { font-size: .8rem; letter-spacing: .2em; text-transform: uppercase;
  color: var(--sx-muted); font-weight: 600; }"""
    return html, css
