-- Smart Sites Arc 4 "Trust & Polish" — override reconciliation status.
--
-- site_content_overrides gains a `status` column so a FULL recompose can
-- mark text overrides that no longer match the fresh composer copy
-- (composer rewrote the target text, or the target path left the
-- document) as 'stale' instead of silently re-stamping them (the mask
-- bug) or silently dropping them (the vanish bug).
--
--   active — applied at render time (default; all existing rows).
--   stale  — NOT applied; kept for a future "re-apply my edit" UI.
--            Exposed via GET /composer/spec → stale_overrides.
--
-- Least-invasive choice, documented: the table has no jsonb/extra column
-- to tuck a flag into (columns: id, business_id, override_type,
-- target_path, target_selector, override_value, original_value,
-- created_via, timestamps), so a plain text column with a CHECK is the
-- smallest mechanism. Code degrades gracefully while this migration is
-- unapplied: status writes soft-fail (logged) and rows without the
-- column are treated as 'active'.

alter table public.site_content_overrides
  add column if not exists status text not null default 'active';

alter table public.site_content_overrides
  drop constraint if exists site_content_overrides_status_check;

alter table public.site_content_overrides
  add constraint site_content_overrides_status_check
  check (status in ('active', 'stale'));

comment on column public.site_content_overrides.status is
  'active = applied at render; stale = superseded by a recompose (composer rewrote or removed the target) — kept for re-apply, never auto-deleted.';
