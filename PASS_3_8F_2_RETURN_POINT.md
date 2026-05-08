# Pass 3.8f.2 (Preview Wiring + Basic Style Controls) — Return Point — Backend

## Purpose

Pass 3.8d Builder Agent ships bespoke HTML to live URLs; Pass 3.8f raised
its quality. But the MySite SmartSitesEditor preview iframe was still
serving from the legacy `previewSmartSite()` path, so practitioners
regenerating designs saw no change in MySite — only on the live URL.

3.8f.2 closes that gap by exposing the **same** fallback chain the live
URL uses (`render_smart_site_page("home", ...)`) under a new
`/sites/{id}/preview` endpoint, plus a one-click alternative-promotion
endpoint that re-fires Brief Expander + Builder against one of the
Designer Agent's two alternatives.

## Pre-pass safety

- Backend file backups: `public_site.py.pre-3-8f-2.bak`,
  `smart_sites.py.pre-3-8f-2.bak`

## Files modified

- **`smart_sites.py`** — adds `render_full_site_html(business_id)` thin
  alias. Loads products from the DB and delegates to the existing
  `render_smart_site_page("home", ...)` so the live URL behavior is
  byte-identical to before. New preview endpoint and the live URL renderer
  now share the same code path.
- **`public_site.py`**
  - **`/sites/{business_id}/decoration-status`** — adds five new fields:
    `recommendation` (full Designer Agent object), `has_recommendation`,
    `signal_count`, `threshold`, plus `can_regenerate_recommendation` /
    `recommendation_cooldown_remaining_seconds`. All existing fields
    untouched (backward-compatible).
  - **`/sites/{business_id}/preview` (GET)** — renders the home page
    through the full Builder→archetype→Studio→legacy chain with
    `Cache-Control: no-store`. Accepts `?v={timestamp}` for browser/CDN
    cache busting. No `X-Frame-Options` header so the MySite iframe can
    embed it from any origin.
  - **`/sites/{business_id}/promote-alternative` (POST)** — takes
    `?alternative_index=0|1`. Promotes the picked alternative to the
    primary recommendation, persists it, runs Brief Expander synchronously,
    then kicks the Builder Agent in a daemon thread (same pattern as
    `/generate-design-recommendation`). Reuses the 60-s design-rec
    cooldown.

## Out of scope (deferred)

- Per-page preview for multi-page sites (Pass 3.8g)
- Direct brief field editing (Pass 3.8i)
- HTML element editing (Pass 3.8i)
- Frontend tests beyond manual verification

## Smoke tests

```bash
# Health
curl https://kmj-intake-server-production.up.railway.app/public/health

# Preview endpoint
curl -I https://kmj-intake-server-production.up.railway.app/sites/{id}/preview
# Expect 200, Cache-Control: no-store, X-Solutionist-Source: preview

# Status now includes recommendation
curl https://kmj-intake-server-production.up.railway.app/sites/{id}/decoration-status \
  | python -m json.tool | grep -E "recommendation|signal_count|threshold"

# Promote (replace 0 with 1 to try the second alternative)
curl -X POST "https://kmj-intake-server-production.up.railway.app/sites/{id}/promote-alternative?alternative_index=0"
```

## Rollback

```bash
git checkout public_site.py.pre-3-8f-2.bak smart_sites.py.pre-3-8f-2.bak
# or revert pass-3-8f-2 commit
```
