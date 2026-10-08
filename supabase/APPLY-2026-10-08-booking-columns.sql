-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-10-08 — bookings fill their own columns
--
-- module_entries.appointment_at (timestamptz) and
-- .duration_min_at_booking (integer) were added on 2026-07-23
-- (APPLY-2026-07-23-error-sweep.sql) and nothing ever wrote them. The
-- booking widget, Chief's create / reschedule and the weekly series put
-- the time and the booked length in `data` (data->>'appointment_at',
-- data->>'duration_min_at_booking'). Production, 2026-10-07: 39 active
-- entries, 0 with the column set; 12 active bookings with
-- data.appointment_at in 2 businesses (9 with a length, 3 without), the
-- times stored three ways (6 end in Z, 3 in +00:00, 3 are a bare date).
-- So every read that filters on the column saw no bookings: the agent
-- site and the Site Concierge offered taken times, Chief could not find a
-- booking by name, cancelling a weekly series "from a date" cancelled
-- nothing, and the booking→session sync never mirrored a future booking.
--
-- THE RULE (one BEFORE trigger, booking_columns_from_data):
--   * data is the source of truth. When data carries an appointment_at
--     that reads as a time, the column follows it: on insert, and on
--     every update that moves data's time (a reschedule moves data).
--     The same for the length.
--   * A statement that writes the column itself is left alone: an insert
--     that gives the column, an update that changes it. So the trigger can
--     never undo a deliberate column write. (2026-10-08, no writer in
--     either repo writes these columns; the draft Acuity PR #1257 would
--     write both data and the column with the same value, which this
--     keeps.)
--   * data with no time (or one that does not read as a time) leaves the
--     column as it is: never cleared, never guessed.
--   * An empty column is filled from data on any update that touches
--     data or the columns, so a row the backfill missed heals itself.
--
-- HOW A TIME IS READ (public.booking_ts, the same rule as
-- availability_engine.booking_instant in the backend): a bare date is
-- that day's midnight UTC; a date and time with Z or an offset is that
-- instant; a date and time without one is UTC. Anything else ('now',
-- 'tomorrow', a typo, a number) is NULL, never an error, so a booking
-- write never fails because of what its data says. The length
-- (public.booking_min) is a positive whole number of minutes, else NULL
-- (the backend's readers then count it as 60).
--
-- WHAT THE BACKFILL TOUCHES, AND ITS SIDE EFFECTS. Only rows whose
-- column is empty and whose data has a time or length that reads, any
-- status. Production 2026-10-08 (read-only count): 17 rows (12 active,
-- 5 archived); all 17 get a time, 14 a length; every stored time reads
-- (6 Z, 8 +00:00, 3 date-only); none sits in a restricted module. For
-- each such row the existing module_entries triggers do what they do on
-- any update:
--   * updated_at moves to now (trg_module_entries_updated and
--     zz_module_revision). Those rows rise to the top of a list sorted by
--     "recently updated" once. Booking rows are not rosters, so no
--     roster compare-and-save is disturbed.
--   * one audit_log row each (audit_module_entries_update,
--     'db:module_entries_update', actor 'system'), with the before/after
--     the ledger always records. Append-only, so they stay: an honest
--     record that the columns were filled.
--   * a realtime UPDATE event each (module_entries is in
--     supabase_realtime): an open calendar refetches.
--   * require_standard_module_store checks each row is in an ordinary
--     module (0 restricted modules on 2026-10-08). If one were not, the
--     whole apply would fail with that message and change nothing.
--   * The GL enqueue triggers do not fire: their WHEN conditions are money
--     fields, which this does not touch.
--
-- The backend reads the column OR data since 2026-10-08 (#1335 and this
-- PR), so it works before and after this file. Apply after the merge.
-- Additive, idempotent (CREATE OR REPLACE, DROP TRIGGER IF EXISTS, the
-- backfill only touches rows still empty). Takes a short lock on
-- module_entries for the trigger swap; lock_timeout makes it give up
-- rather than queue behind a long transaction (just run it again).
-- ══════════════════════════════════════════════════════════════════

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ─── 1. Read a stored time, never fail ──────────────────────────────
-- STABLE, not IMMUTABLE: Postgres marks the text→timestamptz cast STABLE
-- (it consults the TimeZone setting). The patterns below only ever pass
-- it a value with an explicit zone, so the answer does not depend on the
-- setting, but nothing needs this in an index, so it makes no promise
-- Postgres cannot check.
CREATE OR REPLACE FUNCTION public.booking_ts(p text)
RETURNS timestamptz
LANGUAGE plpgsql
STABLE
SET search_path = ''
AS $$
DECLARE
  s text := btrim(p);
BEGIN
  IF s IS NULL OR s = '' THEN
    RETURN NULL;
  END IF;
  -- A bare date: that day's midnight, UTC.
  IF s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
    RETURN s::date::timestamp AT TIME ZONE 'UTC';
  END IF;
  -- A date and time with no zone: read as UTC. (Hours 00-23 and
  -- minutes/seconds 00-59 only: Postgres would take 24:00 and :60, the
  -- backend's reader would not.)
  IF s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9]([.][0-9]+)?)?$' THEN
    RETURN s::timestamp AT TIME ZONE 'UTC';
  END IF;
  -- A date and time with Z or an offset (+00, +0000, +00:00): that instant.
  IF s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9]([.][0-9]+)?)?([Zz]|[+-][0-9]{2}(:?[0-9]{2})?)$' THEN
    RETURN s::timestamptz;
  END IF;
  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  -- 2026-02-30, 25:00, a year out of range: not a time.
  RETURN NULL;
END
$$;

-- ─── 2. Read a stored length, never fail ────────────────────────────
-- Whole minutes, truncated like the backend's int(float(v)); zero,
-- negative, NaN, infinite, too large or not a number is NULL.
CREATE OR REPLACE FUNCTION public.booking_min(p text)
RETURNS integer
LANGUAGE plpgsql
IMMUTABLE
SET search_path = ''
AS $$
DECLARE
  n numeric;
BEGIN
  IF p IS NULL OR btrim(p) = '' THEN
    RETURN NULL;
  END IF;
  n := trunc(btrim(p)::numeric);
  IF NOT (n > 0) THEN
    RETURN NULL;
  END IF;
  RETURN n::integer;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END
$$;

-- The trigger runs as whoever writes module_entries (the backend's
-- service role; the app as authenticated), and calls these as that role.
REVOKE ALL ON FUNCTION public.booking_ts(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.booking_min(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.booking_ts(text) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.booking_min(text) TO anon, authenticated, service_role;

-- ─── 3. The trigger: the columns follow data ────────────────────────
CREATE OR REPLACE FUNCTION public.module_entries_booking_columns()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_at  timestamptz;
  v_min integer;
BEGIN
  IF TG_OP = 'INSERT' THEN
    -- A column the insert gives is kept; an empty one takes data's.
    IF NEW.appointment_at IS NULL THEN
      v_at := public.booking_ts(NEW.data->>'appointment_at');
      IF v_at IS NOT NULL THEN
        NEW.appointment_at := v_at;
      END IF;
    END IF;
    IF NEW.duration_min_at_booking IS NULL THEN
      v_min := public.booking_min(NEW.data->>'duration_min_at_booking');
      IF v_min IS NOT NULL THEN
        NEW.duration_min_at_booking := v_min;
      END IF;
    END IF;
    RETURN NEW;
  END IF;

  -- UPDATE. A statement that changes the column itself is left alone.
  -- Otherwise the column follows data when data's time moved (a
  -- reschedule), or fills when it is still empty.
  IF NEW.appointment_at IS NOT DISTINCT FROM OLD.appointment_at
     AND (NEW.appointment_at IS NULL
          OR (NEW.data->>'appointment_at') IS DISTINCT FROM (OLD.data->>'appointment_at')) THEN
    v_at := public.booking_ts(NEW.data->>'appointment_at');
    IF v_at IS NOT NULL THEN
      NEW.appointment_at := v_at;
    END IF;
  END IF;
  IF NEW.duration_min_at_booking IS NOT DISTINCT FROM OLD.duration_min_at_booking
     AND (NEW.duration_min_at_booking IS NULL
          OR (NEW.data->>'duration_min_at_booking') IS DISTINCT FROM (OLD.data->>'duration_min_at_booking')) THEN
    v_min := public.booking_min(NEW.data->>'duration_min_at_booking');
    IF v_min IS NOT NULL THEN
      NEW.duration_min_at_booking := v_min;
    END IF;
  END IF;
  RETURN NEW;
END
$$;

-- A trigger function is never called directly; firing it checks nothing.
REVOKE ALL ON FUNCTION public.module_entries_booking_columns() FROM PUBLIC, anon, authenticated;

-- Fires only for rows whose data mentions a time or a length, and on an
-- update only when data or the two columns are in the SET list (a
-- status-only change costs nothing). BEFORE triggers run by name: this
-- one ('b…') runs before require_standard_module_store and the
-- updated_at triggers, which do not look at these columns.
DROP TRIGGER IF EXISTS booking_columns_from_data ON public.module_entries;
CREATE TRIGGER booking_columns_from_data
  BEFORE INSERT OR UPDATE OF data, appointment_at, duration_min_at_booking
  ON public.module_entries
  FOR EACH ROW
  WHEN (NEW.data ? 'appointment_at' OR NEW.data ? 'duration_min_at_booking')
  EXECUTE FUNCTION public.module_entries_booking_columns();

-- ─── 4. Backfill: the rows that would change, and only those ────────
-- Writes the columns directly (so the trigger, seeing the statement set
-- them, leaves them be). Never overwrites a column that has a value.
UPDATE public.module_entries
   SET appointment_at = coalesce(appointment_at, public.booking_ts(data->>'appointment_at')),
       duration_min_at_booking = coalesce(duration_min_at_booking,
                                          public.booking_min(data->>'duration_min_at_booking'))
 WHERE (data ? 'appointment_at' OR data ? 'duration_min_at_booking')
   AND ((appointment_at IS NULL AND public.booking_ts(data->>'appointment_at') IS NOT NULL)
     OR (duration_min_at_booking IS NULL
         AND public.booking_min(data->>'duration_min_at_booking') IS NOT NULL));

NOTIFY pgrst, 'reload schema';

COMMIT;

-- ─── VERIFY (counts only) ───────────────────────────────────────────
-- The two functions and the trigger function exist (expect 3), and the
-- trigger is on the table (expect 1):
--   SELECT count(*) FROM pg_proc
--    WHERE pronamespace = 'public'::regnamespace
--      AND proname IN ('booking_ts', 'booking_min', 'module_entries_booking_columns');
--   SELECT count(*) FROM pg_trigger
--    WHERE tgrelid = 'public.module_entries'::regclass AND tgname = 'booking_columns_from_data';
--
-- Nothing left to fill (expect 0, 0):
--   SELECT count(*) FILTER (WHERE appointment_at IS NULL
--                             AND public.booking_ts(data->>'appointment_at') IS NOT NULL) AS time_unfilled,
--          count(*) FILTER (WHERE duration_min_at_booking IS NULL
--                             AND public.booking_min(data->>'duration_min_at_booking') IS NOT NULL) AS length_unfilled
--     FROM public.module_entries;
--
-- The column agrees with data wherever data has a time (expect 0):
--   SELECT count(*) FROM public.module_entries
--    WHERE public.booking_ts(data->>'appointment_at') IS NOT NULL
--      AND appointment_at IS DISTINCT FROM public.booking_ts(data->>'appointment_at');
--
-- A time in data that does not read as one (expect 0 on 2026-10-08):
--   SELECT count(*) FROM public.module_entries
--    WHERE coalesce(data->>'appointment_at', '') <> ''
--      AND public.booking_ts(data->>'appointment_at') IS NULL;
--
-- What the column readers now see (before, 2026-10-07: 39 active, 0 with
-- the column; expect 12 active with a time, 9 of them with a length, and
-- 17 rows with a time in all):
--   SELECT count(*) FILTER (WHERE status = 'active') AS active,
--          count(*) FILTER (WHERE status = 'active' AND appointment_at IS NOT NULL) AS active_with_time,
--          count(*) FILTER (WHERE status = 'active' AND appointment_at IS NOT NULL
--                             AND duration_min_at_booking IS NOT NULL) AS active_with_length,
--          count(*) FILTER (WHERE appointment_at IS NOT NULL) AS all_with_time
--     FROM public.module_entries;
--
-- ─── ROLLBACK ───────────────────────────────────────────────────────
-- Remove the trigger and the functions, then empty the columns again:
-- without the trigger a later reschedule moves data and not the column,
-- and a read that filters on a stale column would find the old time. The
-- shared reads (availability_engine) take data first and handle an empty
-- column. (2026-10-08 no writer sets these columns itself, so emptying
-- them loses nothing.)
--   BEGIN;
--   DROP TRIGGER IF EXISTS booking_columns_from_data ON public.module_entries;
--   DROP FUNCTION IF EXISTS public.module_entries_booking_columns();
--   UPDATE public.module_entries SET appointment_at = NULL, duration_min_at_booking = NULL
--    WHERE appointment_at IS NOT NULL OR duration_min_at_booking IS NOT NULL;
--   DROP FUNCTION IF EXISTS public.booking_min(text);
--   DROP FUNCTION IF EXISTS public.booking_ts(text);
--   COMMIT;
