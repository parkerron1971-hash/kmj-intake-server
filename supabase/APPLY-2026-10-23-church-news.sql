-- Church news in the member app (Kevin, 2026-10-23: "a news feed area in the
-- app that flows news and announcements from the church … allow people to
-- comment but not make a post themselves only admins and certain leaders can
-- make a post"). The approved canvas "Church News & Celebrations"
-- (Hfrz3Y174kbDmJv1G4puVq). Kevin's calls the same day:
--   * News lives on Home ("From the church") with a News page behind it;
--   * a leader always posts to their own ministry (group_id); the people
--     the church picks (church_news_posters) post to the whole church;
--   * teenagers may comment too: every comment is checked first;
--   * members never post, they share good news for an admin to approve
--     (status 'waiting', source 'member').
-- Celebrations (birthdays, anniversaries, milestones) come in a later part.
-- Idempotent.

begin;

-- ─── a post ─────────────────────────────────────────────────────────
create table if not exists public.church_posts(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null default 'announcement'
    check (kind in ('announcement','event','photos','celebration','praise','message','milestone','good_news')),
  title text not null default '' check (length(title) <= 120),
  body text not null default '' check (length(body) <= 4000),
  -- null = the whole church; otherwise the ministry or group it's for
  group_id uuid references public.groups(id) on delete cascade,
  -- who wrote it: a member (a leader, a picked poster, or a member sharing
  -- good news) or someone in the office (their login, and the name shown)
  posted_by uuid references public.contacts(id) on delete set null,
  office_user uuid,
  author_label text not null default '' check (length(author_label) <= 80),
  source text not null default 'office' check (source in ('office','leader','member','chief','sermon')),
  status text not null default 'posted' check (status in ('posted','waiting','declined','removed')),
  pinned_until timestamptz,
  important boolean not null default false,
  comments text not null default 'on' check (comments in ('on','prayers','off')),
  publish_at timestamptz,
  -- what the post carries: {"event": "<entry id>", "sermon": "<id>", "photos": ["<url>", …]}
  attach jsonb not null default '{}'::jsonb,
  -- for a celebration, a milestone or good news: who it's about
  person_id uuid references public.contacts(id) on delete cascade,
  decided_at timestamptz,
  decided_by text not null default '',
  told_at timestamptz,
  created_at timestamptz not null default now(),
  removed_at timestamptz
);
create index if not exists church_posts_feed on public.church_posts(business_id, status, created_at desc);
create index if not exists church_posts_group on public.church_posts(business_id, group_id) where group_id is not null;

-- Love / Praying / Amen / Celebrate: one of each per person per post.
create table if not exists public.church_post_reactions(
  post_id uuid not null references public.church_posts(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('love','pray','amen','cheer')),
  created_at timestamptz not null default now(),
  primary key (post_id, contact_id, kind)
);
create index if not exists church_post_reactions_contact on public.church_post_reactions(contact_id);

-- Who has seen a post (the office's "Seen" column; a member's new count).
create table if not exists public.church_post_seen(
  post_id uuid not null references public.church_posts(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  seen_at timestamptz not null default now(),
  primary key (post_id, contact_id)
);
create index if not exists church_post_seen_contact on public.church_post_seen(contact_id);

-- ─── comments ───────────────────────────────────────────────────────
-- Every comment is checked before anyone sees it (msg_screen): 'shown',
-- 'held' for the safety officers, or 'removed' (by its writer, whoever
-- posted, or a safety officer).
create table if not exists public.church_post_comments(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  post_id uuid not null references public.church_posts(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  reply_to uuid references public.church_post_comments(id) on delete set null,
  body text not null check (length(btrim(body)) between 1 and 1000),
  status text not null default 'shown' check (status in ('shown','held','removed')),
  removed_by text not null default '',
  created_at timestamptz not null default now(),
  removed_at timestamptz
);
create index if not exists church_post_comments_post on public.church_post_comments(post_id, created_at);
create index if not exists church_post_comments_held on public.church_post_comments(business_id, status) where status = 'held';

create table if not exists public.church_post_comment_loves(
  comment_id uuid not null references public.church_post_comments(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (comment_id, contact_id)
);

create table if not exists public.church_post_reports(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  comment_id uuid not null references public.church_post_comments(id) on delete cascade,
  reported_by uuid references public.contacts(id) on delete set null,
  status text not null default 'open' check (status in ('open','closed')),
  created_at timestamptz not null default now(),
  closed_at timestamptz
);
create unique index if not exists church_post_reports_once on public.church_post_reports(comment_id, reported_by);

-- ─── who posts to the whole church ─────────────────────────────────
create table if not exists public.church_news_posters(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  added_at timestamptz not null default now(),
  added_by uuid,
  primary key (business_id, contact_id)
);

-- Seats read; only the server writes.
do $$ declare t text; begin
  foreach t in array array['church_posts','church_post_reactions','church_post_seen','church_post_comments',
                           'church_post_comment_loves','church_post_reports','church_news_posters'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists business_owner_read on public.%I', t);
    execute format('create policy business_owner_read on public.%I for select to authenticated
      using (business_id in (select id from public.businesses where owner_id = auth.uid()))', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format('create policy tenant_member_read on public.%I for select to authenticated
      using (public.is_business_member(business_id))', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- Every row's post, group, comment and person must be this church's own.
-- Nested per table: PL/pgSQL does not short-circuit `and`.
create or replace function public.church_news_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'church_posts' then
    if new.group_id is not null then
      if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
        raise exception 'That group is not in this business';
      end if;
    end if;
    if new.posted_by is not null then
      if not exists (select 1 from public.contacts c where c.id = new.posted_by and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
    if new.person_id is not null then
      if not exists (select 1 from public.contacts c where c.id = new.person_id and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  elsif tg_table_name in ('church_post_reactions','church_post_seen') then
    if not exists (select 1 from public.church_posts p where p.id = new.post_id and p.business_id = new.business_id) then
      raise exception 'That post is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'church_post_comments' then
    if not exists (select 1 from public.church_posts p where p.id = new.post_id and p.business_id = new.business_id) then
      raise exception 'That post is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
    if new.reply_to is not null then
      if not exists (select 1 from public.church_post_comments r where r.id = new.reply_to and r.post_id = new.post_id) then
        raise exception 'A reply answers a comment on the same post';
      end if;
    end if;
  elsif tg_table_name = 'church_post_comment_loves' then
    if not exists (select 1 from public.church_post_comments m where m.id = new.comment_id and m.business_id = new.business_id) then
      raise exception 'That comment is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'church_post_reports' then
    if not exists (select 1 from public.church_post_comments m where m.id = new.comment_id and m.business_id = new.business_id) then
      raise exception 'That comment is not in this business';
    end if;
    if new.reported_by is not null then
      if not exists (select 1 from public.contacts c where c.id = new.reported_by and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  elsif tg_table_name = 'church_news_posters' then
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_news_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['church_posts','church_post_reactions','church_post_seen','church_post_comments',
                           'church_post_comment_loves','church_post_reports','church_news_posters'] loop
    execute format('drop trigger if exists church_news_same_business on public.%I', t);
    execute format('create trigger church_news_same_business before insert or update on public.%I
      for each row execute function public.church_news_same_business()', t);
  end loop;
end $$;

commit;
