"""Spike-only FastAPI app. Mounts ONLY the Composer router.

Pass 4.0f Phase 4: the spike branch must not merge to main, which
means the Composer router can't be wired into kmj_intake_automation.py
yet. This tiny app serves the spike endpoints locally so CHECKPOINT 4
verification + Phase 5 comparison page have live URLs to hit.

Run via:
  railway run uvicorn agents.composer._spike_app:app --port 8765

Endpoints exposed:
  POST /composer/_diag/compose_hero
  POST /composer/_spike/render_hero/{business_id}
  GET  /composer/_spike/render_hero_html/{business_id}
  GET  /  — index page listing the three spike businesses + their
           render URLs (for CHECKPOINT 4 convenience)
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agents.composer.router import router as composer_router

app = FastAPI(
    title="Cathedral Hero Spike (Pass 4.0f)",
    description=(
        "Spike-only FastAPI exposing Composer + render endpoints. "
        "NOT wired into kmj_intake_automation.py — branch never merges."
    ),
)
app.include_router(composer_router)


# Spike businesses — same three used for Phase 3 CHECKPOINT 3.
SPIKE_BUSINESSES = [
    ("KMJ Creative Solutions", "12773842-3cc6-41a7-9094-b8606e3f7549"),
    ("Director Loop Test",     "c8b7e157-903b-40c9-b5f2-700f196fe35b"),
    ("RoyalTeez Designz",      "a8d1abb7-b8c5-4ee0-8d46-84e69efc220d"),
]


@app.get("/", response_class=HTMLResponse)
def spike_index() -> str:
    """Tiny landing page with one link per spike business."""
    rows = "\n".join(
        f'      <li>'
        f'<strong>{name}</strong> <code>({bid[:8]})</code><br>'
        f'<a href="/composer/_spike/render_hero_html/{bid}" target="_blank">'
        f'render_hero_html</a> · '
        f'<a href="/composer/_spike/render_hero/{bid}" target="_blank">'
        f'render_hero (JSON)</a>'
        f'</li>'
        for name, bid in SPIKE_BUSINESSES
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cathedral Hero Spike — Phase 4</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif;
          max-width: 720px; margin: 48px auto; padding: 0 24px;
          color: #0F172A; }}
  h1   {{ font-weight: 600; letter-spacing: -0.5px; }}
  code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 3px;
          font-size: 0.85em; }}
  ul   {{ list-style: none; padding: 0; }}
  li   {{ padding: 14px 0; border-bottom: 1px solid #e5e7eb; }}
  a    {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .meta {{ color: #64748b; font-size: 0.9em; }}
</style>
</head>
<body>
  <h1>Cathedral Hero Spike — Phase 4</h1>
  <p class="meta">Three test businesses. Each link fires Composer (Sonnet 4.5)
  then renders through the canonical four-step pipeline.</p>
  <ul>
{rows}
  </ul>
  <p class="meta"><em>Note: every visit re-fires Composer (~$0.05/call) because
  Cache-Control: no-store is set.</em></p>
</body>
</html>"""
