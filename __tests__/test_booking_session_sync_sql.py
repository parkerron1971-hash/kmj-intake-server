"""public.booking_session_sync under real concurrency, on a Postgres server.

Every one-at-a-time case (the type check, replay, who may call it, moves,
retries, stale callers, history, ended bookings, no contact, a second
business) is in booking_session_sync_db.mjs, which CI runs on PGlite. PGlite
has one connection, so what needs two or three at once is here: overlapping
moves, syncs and a cancel on one booking (Codex's P1-1 on #1465).

The SQL in supabase/APPLY-2026-10-16-booking-calendar-copies.sql is applied
verbatim, after APPLY-2026-10-08-booking-columns.sql, to a small copy of the
production tables with production's sessions constraints.

Needs a Postgres the tests may create a database in. Set
BOOKING_SYNC_PG_DSN (for example postgresql://postgres@127.0.0.1:54329/postgres);
without it, or without psycopg, these are skipped (as in CI).
"""
from __future__ import annotations

import os
import pathlib
import threading
import time
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402
DSN = os.environ.get("BOOKING_SYNC_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="BOOKING_SYNC_PG_DSN not set")

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPLY_COLUMNS = ROOT / "supabase" / "APPLY-2026-10-08-booking-columns.sql"
APPLY_COPIES = ROOT / "supabase" / "APPLY-2026-10-16-booking-calendar-copies.sql"

# Production's tables, as far as the function touches them (read 2026-10-16).
SCHEMA = """
DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE TABLE public.businesses (id uuid PRIMARY KEY);
CREATE TABLE public.contacts (
  id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id));
CREATE TABLE public.custom_modules (
  id uuid PRIMARY KEY, business_id uuid NOT NULL, archetype text,
  is_active boolean DEFAULT true);
CREATE TABLE public.module_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL,
  module_id uuid, status text DEFAULT 'active', data jsonb DEFAULT '{}'::jsonb,
  appointment_at timestamptz, duration_min_at_booking integer);
CREATE TABLE public.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  contact_id uuid NOT NULL REFERENCES public.contacts(id) ON DELETE CASCADE,
  title text NOT NULL, session_type text NOT NULL DEFAULT 'other',
  status text NOT NULL DEFAULT 'scheduled', scheduled_for timestamptz NOT NULL,
  duration_minutes integer NOT NULL DEFAULT 60, notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT sessions_session_type_check CHECK (session_type = ANY (ARRAY[
    'coaching_session'::text, 'consultation'::text, 'pastoral_visit'::text,
    'mentorship'::text, 'discovery_call'::text, 'follow_up'::text, 'other'::text])),
  CONSTRAINT sessions_status_check CHECK (status = ANY (ARRAY[
    'scheduled'::text, 'completed'::text, 'cancelled'::text, 'no_show'::text])));
-- Like production's audit triggers: SECURITY DEFINER with its own search_path.
CREATE TABLE public.audit_log (tbl text, op text, at timestamptz DEFAULT now());
CREATE FUNCTION public.audit_row_change() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path = public AS $$
BEGIN INSERT INTO audit_log (tbl, op) VALUES (TG_TABLE_NAME, TG_OP); RETURN NULL; END $$;
CREATE TRIGGER audit_sessions_insert AFTER INSERT ON public.sessions
  FOR EACH ROW EXECUTE FUNCTION public.audit_row_change();
CREATE TRIGGER audit_sessions_update AFTER UPDATE ON public.sessions
  FOR EACH ROW WHEN (old.* IS DISTINCT FROM new.*) EXECUTE FUNCTION public.audit_row_change();
"""

BIZ, BIZ2 = str(uuid.uuid4()), str(uuid.uuid4())
C1, C2 = str(uuid.uuid4()), str(uuid.uuid4())
MOD, MOD2, EVENTS = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
OLD, NEW, LATER = "2026-11-04T14:00:00Z", "2026-11-06T16:00:00Z", "2026-11-09T10:00:00Z"


@pytest.fixture(scope="module")
def dsn():
    name = f"booking_sync_{os.getpid()}_{int(time.time())}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    base = psycopg.conninfo.conninfo_to_dict(DSN)
    test_dsn = psycopg.conninfo.make_conninfo(**{**base, "dbname": name})
    try:
        with psycopg.connect(test_dsn, autocommit=True) as c:
            c.execute(SCHEMA)
            c.execute(APPLY_COLUMNS.read_text(encoding="utf-8"))
        yield test_dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def bare(dsn):
    """Production's tables as they stood on 2026-10-16, before the APPLY."""
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DROP FUNCTION IF EXISTS public.booking_session_sync(uuid, uuid, jsonb)")
        c.execute("TRUNCATE public.sessions, public.module_entries, public.custom_modules,"
                  " public.contacts, public.businesses, public.audit_log CASCADE")
        c.execute("ALTER TABLE public.sessions DROP CONSTRAINT sessions_session_type_check")
        c.execute("""ALTER TABLE public.sessions ADD CONSTRAINT sessions_session_type_check
                     CHECK (session_type = ANY (ARRAY['coaching_session'::text,
                     'consultation'::text, 'pastoral_visit'::text, 'mentorship'::text,
                     'discovery_call'::text, 'follow_up'::text, 'other'::text]))""")
        c.execute("INSERT INTO public.businesses VALUES (%s), (%s)", (BIZ, BIZ2))
        c.execute("INSERT INTO public.contacts VALUES (%s, %s), (%s, %s)", (C1, BIZ, C2, BIZ2))
        c.execute("INSERT INTO public.custom_modules (id, business_id, archetype) VALUES"
                  " (%s, %s, 'booking_calendar'), (%s, %s, 'booking_calendar'),"
                  " (%s, %s, 'events')", (MOD, BIZ, MOD2, BIZ2, EVENTS, BIZ))
        yield c


@pytest.fixture
def db(bare):
    bare.execute(APPLY_COPIES.read_text(encoding="utf-8"))
    return bare


# ─── helpers ──────────────────────────────────────────────────────────

def book(c, when=OLD, *, biz=BIZ, module=MOD, contact=C1, status="active") -> str:
    data = {"appointment_at": when, "customer_name": "Test Client",
            "duration_min_at_booking": 45}
    if contact:
        data["contact_id"] = contact
    return str(c.execute(
        "INSERT INTO public.module_entries (business_id, module_id, status, data)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (biz, module, status, Jsonb(data))).fetchone()[0])


def move(c, booking: str, when: str) -> None:
    c.execute("UPDATE public.module_entries SET data = data || jsonb_build_object("
              "'appointment_at', %s::text) WHERE id = %s", (when, booking))


def row(booking: str, when: str, contact=C1) -> dict:
    """What the backend passes: _booking_session_row."""
    return {"business_id": BIZ, "contact_id": contact, "title": "Skin Fade",
            "session_type": "booking", "status": "scheduled", "scheduled_for": when,
            "duration_minutes": 45, "notes": f"Booked online. [booking:{booking}]"}


def sync(c, booking: str, when=None, *, biz=BIZ, contact=C1) -> dict:
    p_row = Jsonb(row(booking, when, contact)) if when else None
    return c.execute("SELECT public.booking_session_sync(%s, %s, %s)",
                     (biz, booking, p_row)).fetchone()[0]


def copies(c, booking: str, status=None, biz=BIZ):
    q = ("SELECT id, status, to_char(scheduled_for AT TIME ZONE 'UTC',"
         " 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), notes, session_type, created_at"
         " FROM public.sessions WHERE business_id = %s AND strpos(notes, %s) > 0")
    args = [biz, f"[booking:{booking}]"]
    if status:
        q += " AND status = %s"
        args.append(status)
    return c.execute(q + " ORDER BY created_at, id", args).fetchall()


def live(c, booking: str, biz=BIZ):
    return [r[2] for r in copies(c, booking, "scheduled", biz)]


# ─── concurrency: one booking at a time ───────────────────────────────

def test_overlapping_moves_and_syncs_end_with_one_copy_at_the_bookings_time(db, dsn):
    """Codex's P1-1 on a real database. While one sync holds the booking,
    a second move and two more syncs (one with the old, now stale, row)
    queue behind it. Whatever order they run in, the booking ends with one
    live copy, at its final time."""
    b = book(db)
    sync(db, b, OLD)
    move(db, b, NEW)

    holder = psycopg.connect(dsn)
    holder.execute("SELECT public.booking_session_sync(%s, %s, %s)",
                   (BIZ, b, Jsonb(row(b, NEW))))   # holds the lock
    waited = {}

    def stale_sync():
        with psycopg.connect(dsn, autocommit=True) as c:
            t = time.monotonic()
            sync(c, b, NEW)
            waited["stale"] = time.monotonic() - t

    def second_move():
        with psycopg.connect(dsn) as c:
            t = time.monotonic()
            move(c, b, LATER)
            sync(c, b, LATER)
            c.commit()
            waited["move"] = time.monotonic() - t

    threads = [threading.Thread(target=stale_sync), threading.Thread(target=second_move)]
    for t in threads:
        t.start()
    time.sleep(0.6)
    assert all(t.is_alive() for t in threads)        # both are waiting on the booking
    holder.commit()
    holder.close()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads)
    assert waited["stale"] >= 0.5 and waited["move"] >= 0.5

    at = db.execute("SELECT data->>'appointment_at' FROM public.module_entries WHERE id = %s",
                    (b,)).fetchone()[0]
    assert at == LATER
    assert live(db, b) == [LATER]


def test_a_cancel_that_lands_while_a_sync_runs_wins(db, dsn):
    b = book(db)
    sync(db, b, OLD)
    move(db, b, NEW)
    holder = psycopg.connect(dsn)
    holder.execute("SELECT public.booking_session_sync(%s, %s, %s)",
                   (BIZ, b, Jsonb(row(b, NEW))))

    def cancel():
        with psycopg.connect(dsn) as c:
            c.execute("UPDATE public.module_entries SET status = 'cancelled' WHERE id = %s", (b,))
            c.execute("SELECT public.booking_session_sync(%s, %s, NULL)", (BIZ, b))
            c.commit()

    t = threading.Thread(target=cancel)
    t.start()
    time.sleep(0.4)
    holder.commit()
    holder.close()
    t.join(10)
    assert live(db, b) == []
    # And a late, stale sync after it puts nothing back.
    assert sync(db, b, NEW)["state"] == "inactive"
    assert live(db, b) == []
