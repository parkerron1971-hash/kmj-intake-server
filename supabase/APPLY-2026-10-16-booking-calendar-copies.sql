-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-10-16 — booking calendar copies (PR #1465)
--
-- APPLYING THIS FILE STARTS REMINDER TEXTS TO BOOKING CLIENTS.
-- It is Kevin's to apply, and only after the go-live order below.
--
-- WHY
-- Every booking is meant to have one calendar copy: a sessions row with
-- [booking:{id}] in its notes. The SMS reminder sweep, Chief's
-- upcoming-sessions context and the no-show fee button read it. No
-- booking has ever had one. The mirror writes session_type 'booking',
-- and sessions_session_type_check has never allowed it, so every insert
-- since 2026-07-10 was refused. Production, 2026-10-16: 0 sessions carry
-- a booking marker; 17 bookings, 12 active, none with a copy.
--
-- WHAT IT DOES
--   1. Allows session_type 'booking'.
--   2. Adds public.booking_session_sync: the one place a booking's copy
--      is written, moved or cleared, one booking at a time, in one
--      transaction (Codex's review of #1465: P1-1, P1-2, P1-3, P2-4).
-- Until it is applied the backend writes no copies and says nothing
-- about them: the function's absence is the switch.
--
-- WHO STARTS GETTING TEXTS (production, 2026-10-16, counts only)
-- 12 active bookings in 2 businesses: 6 have a contact, 1 has a phone
-- that normalises, and that 1 has SMS consent, no STOP, reminders on and
-- automations not paused. None of the 12 is upcoming, so applying it
-- today texts nobody. From then on, each booking with a consented phone
-- gets one reminder 22-26 hours before its time (SMS_ALERTS_ENABLED is
-- unset on Railway, so on). The 6 bookings with no contact get no copy
-- and no text; no contact is made up for them.
--
-- GO-LIVE ORDER (KAI, 2026-10-16)
--   1. The frontend calendar stops drawing a booking's copy as a second
--      appointment (CalendarView already draws the booking itself; a
--      session whose notes carry [booking:...] is that same booking).
--   2. Kevin applies this file.
--   3. Within 10 minutes the sync tick writes copies for upcoming
--      bookings, and reminders start.
--
-- THE FUNCTION: booking_session_sync(p_business_id, p_booking_id, p_row)
-- brings one booking's copies in line with the booking.
--   * It locks the booking row first (FOR UPDATE). Two syncs of one
--     booking never interleave, and a sync never interleaves with a write
--     to the booking. It reads the booking it locked, not what the caller
--     read, so a late or repeated call can't bring back an old time.
--   * No such booking in this business, or a row outside a
--     booking_calendar module: nothing is touched.
--   * Not active (cancelled, deleted, archived): every scheduled copy is
--     cancelled, and no copy is made.
--   * Active: exactly one scheduled copy, at the booking's time.
--     - A copy already at that time is kept (the oldest, if several).
--     - Otherwise a new copy is written from p_row. p_row must name the
--       booking's current time; if it doesn't, nothing changes and the
--       answer is 'stale', and the caller reads the booking again.
--     - Every other scheduled copy is cancelled.
--     - A new row is written, not the old one moved, because reminders
--       are de-duplicated per session id.
--   * Not put back: when the newest copy sits at the booking's own time
--     and isn't scheduled (cancelled on the calendar, completed,
--     no-show).
--   * No contact in this business: no copy ('no_contact'). sessions.
--     contact_id is NOT NULL, and no contact is invented.
--   * Completed and no-show copies are history and are never changed.
-- It returns {ok, state, session_id, created, cancelled, appointment_at}
-- and runs whole or not at all.
--
-- VERIFY (after applying)
--   select pg_get_constraintdef(oid) from pg_constraint
--    where conname = 'sessions_session_type_check';    -- ends with 'booking'
--   select has_function_privilege('service_role',
--     'public.booking_session_sync(uuid,uuid,jsonb)', 'execute');   -- true
--   select has_function_privilege('authenticated',
--     'public.booking_session_sync(uuid,uuid,jsonb)', 'execute');   -- false
--   -- after 10 minutes: one scheduled copy per upcoming booking with a contact
--   select count(*) from public.sessions
--    where notes like '%[booking:%' and status = 'scheduled';
--
-- TO SWITCH IT OFF AGAIN
--   DROP FUNCTION public.booking_session_sync(uuid, uuid, jsonb);
--   NOTIFY pgrst, 'reload schema';
-- The backend then writes and moves no copies. Copies already written
-- stay. A copy only gets a reminder while it matches an active booking's
-- time, so a stale one is never texted.
-- ══════════════════════════════════════════════════════════════════

BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.sessions DROP CONSTRAINT IF EXISTS sessions_session_type_check;
ALTER TABLE public.sessions ADD CONSTRAINT sessions_session_type_check
  CHECK (session_type = ANY (ARRAY[
    'coaching_session'::text, 'consultation'::text, 'pastoral_visit'::text,
    'mentorship'::text, 'discovery_call'::text, 'follow_up'::text,
    'other'::text, 'booking'::text]));

CREATE OR REPLACE FUNCTION public.booking_session_sync(
  p_business_id uuid,
  p_booking_id  uuid,
  p_row         jsonb DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_marker    text := '[booking:' || p_booking_id::text || ']';
  v_status    text;
  v_data      jsonb;
  v_col       timestamptz;
  v_module    uuid;
  v_text      text;
  v_target    timestamptz;
  v_keep      uuid;
  v_latest    record;
  v_contact   uuid;
  v_notes     text;
  v_minutes   integer;
  v_created   boolean := false;
  v_cancelled integer := 0;
  v_state     text := 'live';
BEGIN
  -- One booking at a time: every sync of this booking, and every write to
  -- it, waits here for the one before.
  SELECT e.status, e.data, e.appointment_at, e.module_id
    INTO v_status, v_data, v_col, v_module
    FROM public.module_entries e
   WHERE e.id = p_booking_id AND e.business_id = p_business_id
     FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', true, 'state', 'not_found');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.custom_modules m
                  WHERE m.id = v_module AND m.archetype = 'booking_calendar') THEN
    RETURN jsonb_build_object('ok', true, 'state', 'not_booking');
  END IF;

  IF v_status IS DISTINCT FROM 'active' THEN
    UPDATE public.sessions s SET status = 'cancelled'
     WHERE s.business_id = p_business_id AND s.status = 'scheduled'
       AND strpos(s.notes, v_marker) > 0;
    GET DIAGNOSTICS v_cancelled = ROW_COUNT;
    RETURN jsonb_build_object('ok', true, 'state', 'inactive',
                              'cancelled', v_cancelled);
  END IF;

  -- The booking's time, read as the backend reads it: data first (every
  -- booking write moves data; the column follows it by trigger).
  v_text := COALESCE(NULLIF(btrim(v_data->>'appointment_at'), ''),
                     NULLIF(btrim(v_data->>'starts_at'), ''),
                     NULLIF(btrim(v_data->>'scheduled_for'), ''));
  v_target := CASE WHEN v_text IS NULL THEN v_col
                   ELSE public.booking_ts(v_text) END;
  IF v_target IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'state', 'no_time');
  END IF;

  SELECT s.id INTO v_keep
    FROM public.sessions s
   WHERE s.business_id = p_business_id AND s.status = 'scheduled'
     AND strpos(s.notes, v_marker) > 0 AND s.scheduled_for = v_target
   ORDER BY s.created_at, s.id
   LIMIT 1;

  IF v_keep IS NULL THEN
    SELECT s.status, s.scheduled_for INTO v_latest
      FROM public.sessions s
     WHERE s.business_id = p_business_id AND strpos(s.notes, v_marker) > 0
     ORDER BY s.created_at DESC, s.id DESC
     LIMIT 1;
    IF FOUND AND v_latest.status <> 'scheduled'
       AND v_latest.scheduled_for = v_target THEN
      v_state := 'kept_off';
    ELSIF p_row IS NULL
       OR public.booking_ts(p_row->>'scheduled_for') IS DISTINCT FROM v_target THEN
      RETURN jsonb_build_object('ok', false, 'state', 'stale',
                                'appointment_at', v_target);
    ELSE
      IF (p_row->>'contact_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        SELECT c.id INTO v_contact
          FROM public.contacts c
         WHERE c.id = (p_row->>'contact_id')::uuid
           AND c.business_id = p_business_id;
      END IF;
      IF v_contact IS NULL THEN
        v_state := 'no_contact';
      ELSE
        -- The newest live copy's notes come along: they carry what the
        -- practitioner wrote on it.
        SELECT s.notes INTO v_notes
          FROM public.sessions s
         WHERE s.business_id = p_business_id AND s.status = 'scheduled'
           AND strpos(s.notes, v_marker) > 0
         ORDER BY s.created_at DESC, s.id DESC
         LIMIT 1;
        v_notes := COALESCE(v_notes, p_row->>'notes', '');
        IF strpos(v_notes, v_marker) = 0 THEN
          v_notes := btrim(v_notes || ' ' || v_marker);
        END IF;
        v_minutes := CASE WHEN (p_row->>'duration_minutes') ~ '^[0-9]{1,5}$'
                          THEN GREATEST(5, (p_row->>'duration_minutes')::integer)
                          ELSE 60 END;
        INSERT INTO public.sessions (business_id, contact_id, title, session_type,
                                     status, scheduled_for, duration_minutes, notes)
        VALUES (p_business_id, v_contact,
                left(COALESCE(NULLIF(btrim(p_row->>'title'), ''), 'Booking'), 80),
                'booking', 'scheduled', v_target, v_minutes, v_notes)
        RETURNING id INTO v_keep;
        v_created := true;
      END IF;
    END IF;
  END IF;

  UPDATE public.sessions s SET status = 'cancelled'
   WHERE s.business_id = p_business_id AND s.status = 'scheduled'
     AND strpos(s.notes, v_marker) > 0 AND s.id IS DISTINCT FROM v_keep;
  GET DIAGNOSTICS v_cancelled = ROW_COUNT;

  RETURN jsonb_build_object(
    'ok', true,
    'state', CASE WHEN v_keep IS NOT NULL THEN 'live' ELSE v_state END,
    'session_id', v_keep,
    'created', v_created,
    'cancelled', v_cancelled,
    'appointment_at', v_target);
END
$$;

REVOKE ALL ON FUNCTION public.booking_session_sync(uuid, uuid, jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.booking_session_sync(uuid, uuid, jsonb)
  TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
