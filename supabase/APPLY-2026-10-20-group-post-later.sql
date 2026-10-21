-- A Board post that goes out later (the approved canvas "Church Groups,
-- Together", board Post: "Send later · Thursday at 9:00 AM"). Idempotent.
--
--   group_posts.publish_at   when it goes out (null = when it was written);
--                            until then only the group's leaders see it
--   group_posts.told_at      when the group's note and emails went out for
--                            a scheduled post (once)
begin;

alter table public.group_posts add column if not exists publish_at timestamptz;
alter table public.group_posts add column if not exists told_at timestamptz;

-- The every-5-minutes job finds what's due.
create index if not exists group_posts_due on public.group_posts(publish_at)
  where publish_at is not null and told_at is null and removed_at is null;

commit;
