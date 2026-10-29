-- A member's own highlights, notes and bookmarks in the member app's Bible
-- (member app round three, Kevin approved 2026-10-19: "the ability to
-- highlight and take notes"). One row per member per verse. Private to the
-- member: server-only (RLS on, no policies, browser roles revoked);
-- member_bible_marks.py reads and writes a member's own rows after the
-- member-page sign-in, and nothing lets the church's staff read them.
-- Idempotent.
begin;

create table if not exists public.bible_marks(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  book text not null check (book ~ '^[1-3A-Z][A-Z]{2}$'),
  chapter integer not null check (chapter between 1 and 150),
  verse integer not null check (verse between 1 and 176),
  colour text check (colour in ('gold', 'pink', 'teal', 'violet', 'coral')),
  note text check (char_length(note) <= 2000),
  bookmarked boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id, book, chapter, verse)
);

create index if not exists bible_marks_newest
  on public.bible_marks (business_id, contact_id, updated_at desc);

alter table public.bible_marks enable row level security;
revoke all on public.bible_marks from anon, authenticated;
grant all on public.bible_marks to service_role;

commit;
