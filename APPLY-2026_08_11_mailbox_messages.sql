-- APPLY-2026_08_11_mailbox_messages.sql
--
-- Mail pulled from a connected Gmail / Workspace mailbox.
--
-- WHY THIS IS NOT email_replies
--   Two reasons, and the first one is access control.
--
--   email_replies is SEAT-READABLE — business_member_access [ALL] by
--   owner_id, tenant_member_read [SELECT] via is_business_member(), and
--   tenant_writer_write [ALL] via is_business_writer(). That is correct
--   for what it holds: mail the business provoked by sending first, which
--   the team that did the sending can reasonably see.
--
--   A connected mailbox is the practitioner's PERSONAL inbox. For a
--   therapist or a lawyer, making that seat-readable is a disclosure, not
--   a preference. Owner-only was the decision, and the safe way to reach
--   it is a table that starts closed — not an ALTER POLICY on predicates
--   that are currently protecting live data.
--
--   The second reason is volume. A real mailbox delivers hundreds of
--   messages a day into a table sized for a handful of replies. Keeping
--   them apart means the Email Hub's existing queries do not degrade the
--   day someone connects a busy inbox.
--
-- WHY RLS IS ON WITH NO POLICIES
--   Same doctrine as google_mailboxes, for the same reason. RLS enabled +
--   zero policies means PostgREST returns nothing for ANY anon or user
--   JWT, while the service role bypasses RLS entirely. The practitioner
--   reads their mail through GET /mailbox/messages, which checks
--   _require_owner server-side and returns only the fields the Hub needs.
--
--   This is deliberately NOT the new-table owner-RLS trap (seat policies
--   alone locking out the owner). Nobody reads this over the wire. The
--   owner reaches it through an endpoint that authenticates them, which
--   is strictly narrower than a policy any holder of their JWT could use.
--
-- ON DELETING A MAILBOX
--   Disconnecting revokes at Google and drops the google_mailboxes row.
--   The messages already pulled are NOT cascaded away with it: they are
--   the practitioner's received mail, and silently destroying it because
--   they unlinked an integration would be its own kind of data loss.
--   Cascade is on business_id only.

create extension if not exists pgcrypto;

create table if not exists public.mailbox_messages (
  id              uuid primary key default gen_random_uuid(),
  business_id     uuid not null references public.businesses(id) on delete cascade,

  -- Which mailbox this came from. Text, not a FK to google_mailboxes:
  -- the mailbox row can be deleted on disconnect and these rows survive.
  google_email    text not null,

  -- Gmail's own ids. gmail_message_id is the dedupe key — a history
  -- replay or an overlapping incremental sync must not create a second
  -- copy of the same message.
  gmail_message_id text not null,
  gmail_thread_id  text,

  from_email      text,
  from_name       text,
  subject         text,
  body_text       text,
  received_at     timestamptz,

  -- Resolved when the sender matches a contact. NULL is the normal case
  -- and the whole point of the feature: mail from someone we have never
  -- mailed is exactly what this pipeline exists to surface. It is also
  -- what the selection policy keys on — a NULL here means the message is
  -- stored and shown but never reaches Chief's prompt.
  contact_id      uuid references public.contacts(id) on delete set null,

  read            boolean not null default false,
  metadata        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),

  -- One row per Gmail message per business. Makes re-sync idempotent.
  unique (business_id, gmail_message_id)
);

create index if not exists mailbox_messages_business_received_idx
  on public.mailbox_messages (business_id, received_at desc);

-- The selection policy fetches recent mail and filters by sender; this
-- keeps the known-contact lookup off a sequential scan.
create index if not exists mailbox_messages_business_contact_idx
  on public.mailbox_messages (business_id, contact_id);

alter table public.mailbox_messages enable row level security;

-- INTENTIONALLY NO POLICIES. See the header. Do not "fix" this by adding
-- a tenant_member_read policy copied from email_replies — seat-readable
-- is the exact property this table exists to avoid.

comment on table public.mailbox_messages is
  'Mail pulled from a connected Google mailbox. Owner-only by construction: '
  'RLS on with zero policies, reachable only via service-role code and the '
  'owner-gated /mailbox/messages endpoint. Deliberately separate from '
  'email_replies, which is seat-readable.';


-- ─── Sync state on the mailbox row ──────────────────────────────────
--
-- Gmail's History API is incremental: give it the historyId you last saw
-- and it returns what changed since. Storing it is what stops every run
-- from re-reading the whole mailbox.
--
-- last_synced_at is NOT decoration. A connected source that has delivered
-- nothing is indistinguishable from a broken one unless we record when it
-- last actually ran — silence is what a dead feed looks like.

alter table public.google_mailboxes
  add column if not exists last_history_id text;

alter table public.google_mailboxes
  add column if not exists last_synced_at timestamptz;

comment on column public.google_mailboxes.last_history_id is
  'Gmail historyId watermark for incremental sync. NULL means the next run '
  'does a bounded initial backfill instead.';

comment on column public.google_mailboxes.last_synced_at is
  'When a sync last COMPLETED. Staleness is a first-class state: a feed that '
  'has gone quiet must be distinguishable from one that is broken.';
