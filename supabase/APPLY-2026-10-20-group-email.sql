-- Group news by email (Kevin, 2026-10-20, decision 4: phone alerts AND
-- email for group news; the approved canvas "Church Groups, Together",
-- boards Post and Notify). Idempotent.
--
--   group_posts.email_rest         the leader chose "Email the rest": the
--                                  group's people with no phone set up get it
--   group_posts.emailed            how many emails went (the leader sees it)
--   group_posts.missed_checked_at  the one-hour follow-up has been done
--   member_push_prefs.email_missed a member's "Email me if my phone misses
--                                  a leader's post" (off unless turned on)
begin;

alter table public.group_posts add column if not exists email_rest boolean not null default false;
alter table public.group_posts add column if not exists emailed integer not null default 0 check (emailed >= 0);
alter table public.group_posts add column if not exists missed_checked_at timestamptz;
create index if not exists group_posts_missed_due on public.group_posts(created_at)
  where missed_checked_at is null and removed_at is null and group_id is not null;

alter table public.member_push_prefs add column if not exists email_missed boolean not null default false;

commit;
