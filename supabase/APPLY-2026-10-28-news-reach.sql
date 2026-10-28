-- News reaches the people without the app (news_reach.py, Kevin 2026-10-28:
-- "texting only people without app alerts", important posts only, "with email
-- as you shared"). An important post is texted to the people it's for who said
-- yes to the church's texts and emailed to the rest, once, when they have no
-- phone set up for the member app.
--
--   church_posts.reached_at    the claim: set once, when the post is reached
--   church_posts.reach         what went: {texts, emails, phones, at}, or {why}
--                              when it was let go (old, off, full)
--   member_push_prefs.news_texts
--                              a member's own "Text me important news"; null
--                              = never chose (texts still need a yes to the
--                              church's texts), false = no texts
--
-- Additive only. Rollback: drop the three columns and the index.

alter table public.church_posts add column if not exists reached_at timestamptz;
alter table public.church_posts add column if not exists reach jsonb;
alter table public.member_push_prefs add column if not exists news_texts boolean;

-- The sweep's read: important posts still waiting to reach the rest.
create index if not exists church_posts_reach_due
  on public.church_posts (created_at)
  where important and reached_at is null;
