-- ROLLBACK-2026-09-03-kmj-site-manual.sql
-- Puts back the page set site_sync replaced when it first installed the
-- hand-built site (kept under site_config.manual_backup). Set SITE_SYNC=off
-- on Railway first, or the next boot installs it again.
BEGIN;

UPDATE business_sites
SET
  html_content = site_config->'manual_backup'->>'html_content',
  site_config = (site_config
    || jsonb_build_object(
      'html_source', COALESCE(site_config->'manual_backup'->'html_source', 'null'::jsonb),
      'generated_pages', COALESCE(site_config->'manual_backup'->'generated_pages', '{}'::jsonb),
      'site_pages', COALESCE(site_config->'manual_backup'->'site_pages', 'null'::jsonb)
    )) - 'manual_backup',
  updated_at = now()
WHERE slug = 'kmj-creative-solutions' AND site_config ? 'manual_backup';

-- Expect: UPDATE 1
COMMIT;
