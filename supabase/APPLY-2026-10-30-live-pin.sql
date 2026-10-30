-- APPLY-2026-10-30-live-pin.sql
--
-- A real pin for the live chat (Kevin 2026-10-30, after trying the live
-- room: "add the pin button and the hearts"). The team pins one message
-- (the host's or a member's) to the top of every member's chat, or
-- unpins it; a new host message pins itself, as the room did before.
--
--   live_sessions.pinned_message_id   the pinned message, or null
--   live_pin(...)                     pins (or, with null, unpins) on a
--                                     LIVE service and bumps chat_version
--                                     in the same update, so every phone
--                                     picks it up on its next poll; the
--                                     message must be this service's and
--                                     not hidden. Server only.
--
-- A hidden pinned message stays pinned but no phone shows it (the member
-- app reads only visible messages); showing it again brings it back.
--
-- Apply BEFORE the code that reads live_sessions.pinned_message_id
-- deploys. Check after:
--   select column_name from information_schema.columns
--    where table_name = 'live_sessions' and column_name = 'pinned_message_id';
--   select proname from pg_proc where proname = 'live_pin';
-- Rollback: drop the function, then the column (the code must go first).

alter table public.live_sessions
  add column if not exists pinned_message_id uuid references public.live_chat(id) on delete set null;

-- Returns true; anything wrong raises (the server reads any error as
-- "didn't save"), so an unpin's null is never mistaken for a failure.
create or replace function public.live_pin(p_session uuid, p_business uuid, p_message uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_session uuid;
begin
  if p_message is not null and not exists (
      select 1 from public.live_chat c
       where c.id = p_message and c.session_id = p_session and c.business_id = p_business and c.hidden = false) then
    raise exception 'That message is not in this live service' using errcode = 'P0002';
  end if;
  update public.live_sessions
     set pinned_message_id = p_message, chat_version = chat_version + 1, updated_at = now()
   where id = p_session and business_id = p_business and status = 'live'
  returning id into v_session;
  if v_session is null then
    raise exception 'That live service has ended' using errcode = 'P0002';
  end if;
  return true;
end $$;

revoke all on function public.live_pin(uuid, uuid, uuid) from public, anon, authenticated;
grant execute on function public.live_pin(uuid, uuid, uuid) to service_role;
