# Pass 3.8b — Backend Return Point

Created: 2026-05-06 21:35 local
Tag: `pre-pass-3-8b-20260506-2135`
Branch: `pass-3-8b` (off `main` @ `6b58ad4`)
Base: Pass 3.8a foundation (Designer Agent endpoint + 9-signal gate + bundle extension)

## Scope — Brief Expander only

LLM #2 expands a Pass 3.8a design recommendation into a full 30-field
DesignBrief. Sites still render via the existing pipeline; brief is
stored at `site_config.design_brief` but not yet consumed (deferred to
Pass 3.8c).

## New files

- `studio_design_brief.py` — DesignBrief TypedDict + validator + `get_default_brief`
- `studio_brief_expander.py` — LLM #2 orchestration with deterministic font override + cold-start fallback

## Modified files

- `public_site.py`:
  - `POST /sites/{id}/expand-design-brief` — manual idempotent endpoint
  - `POST /sites/{id}/generate-design-recommendation` — now auto-fires brief expansion after recommendation succeeds
  - `GET /sites/{id}/decoration-status` — now surfaces `has_brief`, `brief_generated_at`, `brief_warnings`

## Backwards compatibility

- `design_brief` is a new key inside existing JSONB `site_config`; readers ignore unknown keys.
- The auto-fire chain in `/generate-design-recommendation` is wrapped in try/except — brief failures do NOT 500 the recommendation request.
- The recommendation endpoint's response shape adds optional `brief` + `auto_expanded` fields; existing clients continue to work.
- No new env vars. Only `ANTHROPIC_API_KEY` required (already set).

## Backups

- `public_site.py.pre-3-8b.bak`
- `studio_designer_agent.py.pre-3-8b.bak`

## Rollback

```bash
git checkout main
git reset --hard pre-pass-3-8b-20260506-2135
git push --force-with-lease origin main
```
Optional cleanup of persisted briefs:
```sql
UPDATE business_sites SET site_config = site_config - 'design_brief' WHERE site_config ? 'design_brief';
```
