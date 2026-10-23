-- APPLY-2026-10-23-news-alerts.sql
-- Phone alerts and the weekly email for the church's news (part 5 of
-- "Church News & Celebrations"; the approved canvas Hfrz3Y174kbDmJv1G4puVq,
-- boards 6 and 9). news_alerts.py writes these.
--
--   * each member picks what rings for News: Important (the default: posts
--     a pastor marks important), Everything (every post, never more than the
--     church's three a day) or Off; and whether they hear about birthdays in
--     their own groups (one note at 9 AM, on by default), replies to their
--     comments (on by default) and the week's news by email (Saturdays,
--     off by default). Null is the default.
--   * a post is alerted once, when it goes up (alerted_at); a scheduled one
--     when its time comes.
--   * the week's email goes once a week per member (church_news_digests).
--
-- Applies twice without harm.

alter table public.member_push_prefs
  add column if not exists news_level text,
  add column if not exists news_birthdays boolean,
  add column if not exists news_replies boolean,
  add column if not exists news_email boolean;
do $$ begin
  alter table public.member_push_prefs add constraint member_push_prefs_news_level_check
    check (news_level is null or news_level in ('important', 'everything', 'off'));
exception when duplicate_object then null; end $$;

alter table public.church_posts add column if not exists alerted_at timestamptz;
create index if not exists church_posts_to_alert
  on public.church_posts(business_id, created_at desc) where alerted_at is null and status = 'posted';

create table if not exists public.church_news_digests(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  week_of date not null,
  posts int not null default 0,
  sent_at timestamptz not null default now(),
  primary key (business_id, contact_id, week_of)
);
alter table public.church_news_digests enable row level security;
revoke all on public.church_news_digests from anon, authenticated;
grant all on public.church_news_digests to service_role;
drop trigger if exists church_news_digests_same_business on public.church_news_digests;
create trigger church_news_digests_same_business before insert or update on public.church_news_digests
  for each row execute function public.member_push_same_business();
