-- How you hear about a group's chat (the approved canvas "Church Groups,
-- Together", board Notify: "Group chat: Every message · Evening summary ·
-- Off"). Each person chooses per chat:
--
--   every     a note for each message (what was live before)
--   evening   one quiet note at 7 PM: who talked, and how many replied to you
--   replies   only when someone replies to you
--
--   msg_participants.notify     the choice ('every' unless changed)
--   msg_participants.summed_at  when this person's last evening note covered
--                               up to (so the next one counts only what's new)
-- Idempotent.
begin;

alter table public.msg_participants add column if not exists notify text not null default 'every'
  check (notify in ('every','evening','replies'));
alter table public.msg_participants add column if not exists summed_at timestamptz;

-- The 7 PM sweep finds who chose the evening note, church by church.
create index if not exists msg_participants_evening on public.msg_participants(business_id, thread_id)
  where notify = 'evening';

commit;
