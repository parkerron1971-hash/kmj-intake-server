-- A word from the office to every group, or to the group leaders only (the
-- approved canvas "Church Groups, Together", board Office: "A word to every
-- group … Every group · Group leaders"). It's a group_posts row with no
-- group (already "from the pastors, to every group") and no author contact
-- (the office isn't a member); `audience` says who sees it on their Board.
-- Idempotent.
begin;

alter table public.group_posts add column if not exists audience text not null default 'all'
  check (audience in ('all','leaders'));

commit;
