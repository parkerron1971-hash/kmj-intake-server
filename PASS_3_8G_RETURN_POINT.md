# Pass 3.8g (Solutionist Quality + Multi-Page) — Backend Return Point

## Purpose

The single largest backend pass. Two integrated tracks:

1. **Solutionist Quality** — encode the visual quality ceiling (italic
   accent words, pill buttons, 28px card radii, warm whites, 0.9s
   cubic-bezier reveals, film grain, shimmer on CTAs) into Builder
   prompt + post-build validator + reactivity injection.
2. **Multi-Page Architecture** — Home / About / Services / Contact
   page types, per-page Brief Expander variant, multi-page Builder
   orchestrator, shared nav, path-based routing on the live URL.

A hard cost cap (50 Builder runs / 24h, midnight UTC reset) is layered
under both tracks so a runaway loop or unexpected demand can't burn
through Anthropic credits unchecked. A kill switch
(`SOLUTIONIST_QUALITY_ENABLED`, `MULTI_PAGE_ENABLED`) lets ops disable
either track instantly.

## Files added

- `studio_cost_cap.py` — thread-safe daily counter + circuit breaker.
  `can_generate()`, `record_generation()`, `get_status()`. Resets at
  midnight UTC.
- `studio_config.py` — runtime feature flags.
- `studio_solutionist_quality.py` — `HARD_RULES`, `SOLUTIONIST_COMPONENTS`,
  `SOLUTIONIST_ANIMATIONS`, `get_quality_rules_block_for_prompt()`,
  `validate_solutionist_quality(html)`.
- `studio_reactivity/solutionist_motion.py` — film grain overlay,
  shimmer on CTAs, floating diamonds for dark/luxury/corporate strands,
  pulse glow on `[data-headshot-frame]`, signature `.accent-word`
  styling, 0.9s cubic-bezier reveal timing override.
- `studio_page_types.py` — `PAGE_TYPES` (home/about/services/contact),
  `default_page_set()`, `landing_page_set()`, `slug_to_page_id(path)`.
- `studio_multi_page_builder.py` — `build_pages()`, `_generate_nav()`,
  `_inject_nav()` (idempotent), `landing_page_html()`.

## Files modified

- `studio_reactivity/inject.py` — appends Solutionist motion to the
  reactivity stylesheet behind `SOLUTIONIST_QUALITY_ENABLED`.
- `studio_brief_expander.py` — new `expand_page_brief()` with cold-start
  shortcut, page-focus prompt addendum, fallback to base brief on any
  failure.
- `studio_builder_agent.py` — adds Solutionist Quality block to the
  prompt, multi-page context block when brief carries `_other_pages`,
  new RULES section with measurable SQ rules, calls
  `validate_solutionist_quality` alongside `validate_quality` in
  `build_html()`.
- `smart_sites.py` — new `_try_serve_multi_page()` Layer 0; extended
  `render_smart_site_page()` and `render_full_site_html()` to accept
  `path` and route multi-page sites by URL.
- `public_site.py`
  - `/decoration-status` — adds `site_type`, `site_pages`,
    `generated_pages_count`, `generated_page_ids`, `pages_generated_at`,
    `pages_errors`, `cost_cap_status`.
  - `GET /sites/{id}/preview-page/{page_id}` — per-page preview with
    no-store headers.
  - `POST /sites/{id}/set-site-type?site_type=…` — switches between
    `landing-page` and `multi-page`.
  - `POST /sites/{id}/generate-multi-page` — kicks Brief Expander +
    Builder per page in a daemon thread; cost-cap-gated and
    kill-switch-gated.
  - `GET /system/cost-cap-status` — diagnostic.
  - `_serve_site_by_slug` and `_serve_site_by_custom_domain` accept and
    forward `path`. Catch-all `/{path:path}` passes the request path
    through, so `kmj-creative-solutions.mysolutionist.app/about` works.

## Out of scope (deferred)

- Per-page custom domains
- WYSIWYG inline editing
- Image-upload pipeline
- Audience-tier product structure

## Smoke tests

```bash
# Health + cost cap diagnostic
curl https://kmj-intake-server-production.up.railway.app/public/health
curl https://kmj-intake-server-production.up.railway.app/system/cost-cap-status

# /decoration-status now surfaces all 3.8g fields
curl https://kmj-intake-server-production.up.railway.app/sites/{id}/decoration-status \
  | python -m json.tool | grep -E "site_type|site_pages|cost_cap_status"

# Switch a business to multi-page and trigger generation
curl -X POST "https://kmj-intake-server-production.up.railway.app/sites/{id}/set-site-type?site_type=multi-page"
curl -X POST  https://kmj-intake-server-production.up.railway.app/sites/{id}/generate-multi-page
# Wait ~6-10 minutes for 4 pages to build; poll /decoration-status

# Per-page preview after generation
curl -I https://kmj-intake-server-production.up.railway.app/sites/{id}/preview-page/about
```

## Rollback

```bash
git checkout main
git reset --hard pre-pass-3-8g-<timestamp>   # tag pushed pre-PART-1
```

Or restore individual files from the `*.pre-3-8g.bak` backups.
