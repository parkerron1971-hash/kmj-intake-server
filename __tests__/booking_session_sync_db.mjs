// A booking's calendar copy, kept by public.booking_session_sync
// (supabase/APPLY-2026-10-16-booking-calendar-copies.sql), on a real Postgres
// (PGlite): production's sessions constraints before and after the apply,
// replay, who may call it, and every case it decides, called as service_role
// the way the backend calls it. Overlapping transactions need a second
// connection, which PGlite doesn't have: test_booking_session_sync_sql.py runs
// those on a Postgres server.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/booking_session_sync_db.mjs
// (CI installs PGlite into $RUNNER_TEMP and sets PGLITE_MODULE.)
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const columns = await readFile(new URL('../supabase/APPLY-2026-10-08-booking-columns.sql', import.meta.url), 'utf8');
const migration = await readFile(new URL('../supabase/APPLY-2026-10-16-booking-calendar-copies.sql', import.meta.url), 'utf8');

// Production's tables as far as the function touches them (read 2026-10-16):
// sessions with its type and status checks, contact_id NOT NULL with its
// foreign key, and audit triggers like production's (SECURITY DEFINER, their
// own search_path); module_entries with the booking-columns trigger.
const SCHEMA = `
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE TABLE public.businesses (id uuid PRIMARY KEY);
CREATE TABLE public.contacts (id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id));
CREATE TABLE public.custom_modules (id uuid PRIMARY KEY, business_id uuid NOT NULL, archetype text,
  is_active boolean NOT NULL DEFAULT true);
CREATE TABLE public.module_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  module_id uuid NOT NULL REFERENCES public.custom_modules(id) ON DELETE CASCADE,
  business_id uuid NOT NULL, data jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active', appointment_at timestamptz, duration_min_at_booking integer);
CREATE TABLE public.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  contact_id uuid NOT NULL REFERENCES public.contacts(id) ON DELETE CASCADE,
  title text NOT NULL, session_type text NOT NULL DEFAULT 'other',
  status text NOT NULL DEFAULT 'scheduled', scheduled_for timestamptz NOT NULL,
  duration_minutes integer NOT NULL DEFAULT 60, notes text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT sessions_session_type_check CHECK (session_type = ANY (ARRAY['coaching_session'::text,
    'consultation'::text, 'pastoral_visit'::text, 'mentorship'::text, 'discovery_call'::text,
    'follow_up'::text, 'other'::text])),
  CONSTRAINT sessions_status_check CHECK (status = ANY (ARRAY['scheduled'::text, 'completed'::text,
    'cancelled'::text, 'no_show'::text])));
CREATE TABLE public.audit_log (tbl text, op text);
CREATE FUNCTION public.audit_row_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public AS $$
BEGIN INSERT INTO audit_log VALUES (TG_TABLE_NAME, TG_OP); RETURN coalesce(new, old); END $$;
CREATE TRIGGER audit_sessions_insert AFTER INSERT ON public.sessions
  FOR EACH ROW EXECUTE FUNCTION public.audit_row_change();
CREATE TRIGGER audit_sessions_update AFTER UPDATE ON public.sessions
  FOR EACH ROW WHEN (old.* IS DISTINCT FROM new.*) EXECUTE FUNCTION public.audit_row_change();
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
`;

const BIZ = 'b0000000-0000-4000-8000-000000000001';
const BIZ2 = 'b0000000-0000-4000-8000-000000000002';
const C1 = 'c1000000-0000-4000-8000-000000000001';
const C2 = 'c1000000-0000-4000-8000-000000000002';
const MOD = 'd0000000-0000-4000-8000-000000000001';
const MOD2 = 'd0000000-0000-4000-8000-000000000002';
const EVENTS = 'd0000000-0000-4000-8000-000000000003';
const OLD = '2026-11-04T14:00:00Z';
const NEW = '2026-11-06T16:00:00Z';
const LATER = '2026-11-09T10:00:00Z';
const epoch = (iso) => Date.parse(iso) / 1000;

const one = async (db, q, p = []) => (await db.query(q, p)).rows[0];
let n = 0;
const book = async (db, when = OLD, { biz = BIZ, module = MOD, contact = C1, status = 'active' } = {}) => {
  const id = `e0000000-0000-4000-8000-${String(++n).padStart(12, '0')}`;
  const data = { appointment_at: when, customer_name: 'Test Client', duration_min_at_booking: 45 };
  if (contact) data.contact_id = contact;
  await db.query(`INSERT INTO module_entries (id, module_id, business_id, status, data) VALUES ($1,$2,$3,$4,$5::jsonb)`,
    [id, module, biz, status, JSON.stringify(data)]);
  return id;
};
const move = (db, id, when) => db.query(
  `UPDATE module_entries SET data = data || jsonb_build_object('appointment_at', $2::text) WHERE id = $1`, [id, when]);
const setStatus = (db, id, status) => db.query('UPDATE module_entries SET status = $2 WHERE id = $1', [id, status]);
// What the backend passes as p_row (booking_widget_router._booking_session_row).
const row = (id, when, contact = C1) => ({ business_id: BIZ, contact_id: contact, title: 'Skin Fade',
  session_type: 'booking', status: 'scheduled', scheduled_for: when, duration_minutes: 45,
  notes: `Booked online. [booking:${id}]` });
// Called as the backend calls it: service_role, through PostgREST.
const sync = async (db, id, when = null, { biz = BIZ, contact = C1 } = {}) => {
  await db.exec('SET ROLE service_role');
  try {
    return (await one(db, 'SELECT public.booking_session_sync($1, $2, $3::jsonb) AS r',
      [biz, id, when ? JSON.stringify(row(id, when, contact)) : null])).r;
  } finally {
    await db.exec('RESET ROLE');
  }
};
const copies = async (db, id, status = null, biz = BIZ) => (await db.query(
  `SELECT id, status, extract(epoch FROM scheduled_for)::float8 AS at, notes, session_type, title, duration_minutes
     FROM sessions WHERE business_id = $1 AND strpos(notes, $2) > 0 AND ($3::text IS NULL OR status = $3)
    ORDER BY created_at, id`, [biz, `[booking:${id}]`, status])).rows;
const live = async (db, id, biz = BIZ) => (await copies(db, id, 'scheduled', biz)).map((r) => r.at);

async function fresh({ applied = true } = {}) {
  const db = new PGlite();
  await db.exec(SCHEMA);
  await db.exec(columns);
  await db.query('INSERT INTO businesses VALUES ($1), ($2)', [BIZ, BIZ2]);
  await db.query('INSERT INTO contacts VALUES ($1,$2), ($3,$4)', [C1, BIZ, C2, BIZ2]);
  await db.query(`INSERT INTO custom_modules (id, business_id, archetype) VALUES
    ($1,$2,'booking_calendar'), ($3,$4,'booking_calendar'), ($5,$2,'events')`, [MOD, BIZ, MOD2, BIZ2, EVENTS]);
  if (applied) await db.exec(migration);
  return db;
}

// ── 1. before the apply: why no booking has ever had a copy ───────────
{
  const db = await fresh({ applied: false });
  await assert.rejects(db.query(`INSERT INTO sessions (business_id, contact_id, title, session_type, scheduled_for)
    VALUES ($1,$2,'x','booking',now())`, [BIZ, C1]), /sessions_session_type_check/,
  "production refuses session_type 'booking'");
  await assert.rejects(db.query(`INSERT INTO sessions (business_id, title, session_type, scheduled_for)
    VALUES ($1,'x','other',now())`, [BIZ]), /contact_id/, 'and a session with no contact');
  await db.close();
}

// ── 2. the apply: the type, replay, who may call it ───────────────────
{
  const db = await fresh();
  const def = async () => (await one(db, `SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint
    WHERE conname = 'sessions_session_type_check'`)).d;
  assert.match(await def(), /'booking'::text/, "'booking' is allowed");
  for (const t of ['coaching_session', 'consultation', 'pastoral_visit', 'mentorship', 'discovery_call', 'follow_up', 'other']) {
    assert.match(await def(), new RegExp(`'${t}'::text`), `'${t}' is still allowed`);
  }
  await assert.rejects(db.query(`INSERT INTO sessions (business_id, contact_id, title, session_type, scheduled_for)
    VALUES ($1,$2,'x','salon',now())`, [BIZ, C1]), /sessions_session_type_check/, 'other types are still refused');
  const b = await book(db);
  assert.equal((await sync(db, b, OLD)).state, 'live');
  const before = await db.query('SELECT id, status, scheduled_for FROM sessions ORDER BY id');
  await db.exec(migration);
  assert.deepEqual((await db.query('SELECT id, status, scheduled_for FROM sessions ORDER BY id')).rows, before.rows,
    'a second apply changes nothing');
  assert.equal((await one(db, `SELECT count(*)::int AS n FROM pg_proc WHERE proname = 'booking_session_sync'`)).n, 1,
    'one function, not two');
  const sig = 'public.booking_session_sync(uuid,uuid,jsonb)';
  for (const [role, allowed] of [['service_role', true], ['authenticated', false], ['anon', false]]) {
    assert.equal((await one(db, `SELECT has_function_privilege($1, $2, 'execute') AS ok`, [role, sig])).ok, allowed,
      `${role} ${allowed ? 'may' : 'may not'} call it`);
  }
  await db.close();
}

const db = await fresh();

// ── 3. one copy, at the booking's time ────────────────────────────────
{
  const b = await book(db);
  const first = await sync(db, b, OLD);
  assert.equal(first.state, 'live');
  assert.equal(first.created, true);
  const [c] = await copies(db, b);
  assert.equal(c.session_type, 'booking');
  assert.equal(c.title, 'Skin Fade');
  assert.equal(c.duration_minutes, 45);
  const again = await sync(db, b, OLD);
  assert.equal(again.created, false, 'a retry writes nothing');
  assert.equal(again.session_id, first.session_id);
  assert.deepEqual(await live(db, b), [epoch(OLD)]);

  await move(db, b, NEW);
  const moved = await sync(db, b, NEW);
  assert.equal(moved.created, true, 'a move writes a new copy (reminders are per session id)');
  assert.equal(moved.cancelled, 1, 'and cancels the old one');
  assert.notEqual(moved.session_id, first.session_id);
  assert.deepEqual(await live(db, b), [epoch(NEW)]);

  await move(db, b, OLD);
  await sync(db, b, OLD);
  assert.deepEqual(await live(db, b), [epoch(OLD)], 'moving back writes the old time again');

  await move(db, b, '2026-11-04T14:00:00+00:00');
  assert.equal((await sync(db, b, '2026-11-04 14:00:00+00')).created, false,
    'the same moment written another way is not a move');
}

// ── 4. a stale caller changes nothing; a later call repairs ───────────
{
  const b = await book(db);
  await sync(db, b, OLD);
  await move(db, b, NEW);
  const stale = await sync(db, b, OLD);
  assert.equal(stale.ok, false);
  assert.equal(stale.state, 'stale', 'a row read before the move is refused');
  assert.equal(Date.parse(stale.appointment_at) / 1000, epoch(NEW));
  assert.deepEqual(await live(db, b), [epoch(OLD)], 'and changes nothing');
  assert.equal((await sync(db, b, NEW)).state, 'live', 'the next call with the booking as it is repairs it');
  assert.deepEqual(await live(db, b), [epoch(NEW)]);
  assert.equal((await sync(db, b)).state, 'live', 'once right, no row is needed');
  assert.equal((await sync(db, await book(db, LATER))).state, 'stale', 'a first copy needs one');
}

// ── 5. notes, duplicates, history ─────────────────────────────────────
{
  const b = await book(db);
  await sync(db, b, OLD);
  await db.query('UPDATE sessions SET notes = $2 WHERE strpos(notes, $1) > 0', [`[booking:${b}]`, `No beard. [booking:${b}]`]);
  await move(db, b, NEW);
  await sync(db, b, NEW);
  assert.equal((await copies(db, b, 'scheduled'))[0].notes, `No beard. [booking:${b}]`, "the practitioner's notes come along");

  const d = await book(db);
  const keep = (await sync(db, d, OLD)).session_id;
  await db.query(`INSERT INTO sessions (business_id, contact_id, title, session_type, scheduled_for, notes, created_at)
    VALUES ($1,$2,'dup','booking',$3,$4, now() + interval '1 hour')`, [BIZ, C1, OLD, `[booking:${d}]`]);
  const collapsed = await sync(db, d, OLD);
  assert.equal(collapsed.session_id, keep, 'duplicates collapse to the oldest');
  assert.equal(collapsed.cancelled, 1);

  const h = await book(db);
  for (let i = 0; i < 60; i++) {
    await db.query(`INSERT INTO sessions (business_id, contact_id, title, session_type, status, scheduled_for, notes, created_at)
      VALUES ($1,$2,'old','booking','cancelled','2026-01-01T09:00:00Z',$3, now() - interval '1 day')`, [BIZ, C1, `[booking:${h}]`]);
  }
  assert.equal((await sync(db, h, OLD)).created, true);
  assert.equal((await sync(db, h, OLD)).created, false, 'sixty old copies never hide the live one');
  assert.deepEqual(await live(db, h), [epoch(OLD)]);

  const x = await book(db);
  await sync(db, x, OLD);
  await db.query(`UPDATE sessions SET status = 'no_show' WHERE strpos(notes, $1) > 0`, [`[booking:${x}]`]);
  await move(db, x, NEW);
  await sync(db, x, NEW);
  assert.deepEqual((await copies(db, x)).map((r) => r.status), ['no_show', 'scheduled'], 'completed and no-show copies are history');
}

// ── 6. a copy cancelled on the calendar is not put back ───────────────
{
  const b = await book(db);
  await sync(db, b, OLD);
  await db.query(`UPDATE sessions SET status = 'cancelled' WHERE strpos(notes, $1) > 0`, [`[booking:${b}]`]);
  assert.equal((await sync(db, b, OLD)).state, 'kept_off');
  assert.deepEqual(await live(db, b), []);
  await move(db, b, NEW);
  assert.equal((await sync(db, b, NEW)).state, 'live', 'moving it asks for it on the calendar again');
}

// ── 7. only an active booking has a copy (Codex P1-3) ─────────────────
for (const status of ['cancelled', 'deleted', 'archived']) {
  const b = await book(db);
  await sync(db, b, OLD);
  await setStatus(db, b, status);
  const out = await sync(db, b, NEW);
  assert.equal(out.state, 'inactive', `${status}: no copy`);
  assert.equal(out.cancelled, 1, `${status}: the live copy is cancelled`);
  await move(db, b, NEW);
  assert.equal((await sync(db, b, NEW)).state, 'inactive', `${status}: a new time brings nothing back`);
  assert.deepEqual(await live(db, b), []);
}

// ── 8. no contact, another business's contact, not a booking ──────────
{
  const contactsBefore = (await one(db, 'SELECT count(*)::int AS n FROM contacts')).n;
  const b = await book(db, OLD, { contact: null });
  const out = await sync(db, b, OLD, { contact: null });
  assert.equal(out.ok, true);
  assert.equal(out.state, 'no_contact', 'a booking with no contact gets no copy');
  assert.deepEqual(await copies(db, b), []);
  assert.equal((await one(db, 'SELECT count(*)::int AS n FROM contacts')).n, contactsBefore, 'and no contact is made up');

  const o = await book(db, OLD, { contact: C2 });
  assert.equal((await sync(db, o, OLD, { contact: C2 })).state, 'no_contact', "another business's contact is never used");

  const e = await book(db, OLD, { module: EVENTS });
  assert.equal((await sync(db, e, OLD)).state, 'not_booking', 'a row outside a booking module is left alone');
  assert.deepEqual(await copies(db, e), []);
}

// ── 9. a second business ──────────────────────────────────────────────
{
  const theirs = await book(db, OLD, { biz: BIZ2, module: MOD2, contact: C2 });
  await db.exec('SET ROLE service_role');
  await db.query('SELECT public.booking_session_sync($1, $2, $3::jsonb)',
    [BIZ2, theirs, JSON.stringify({ ...row(theirs, OLD, C2), business_id: BIZ2 })]);
  await db.exec('RESET ROLE');
  const mine = await book(db);
  await db.query(`INSERT INTO sessions (business_id, contact_id, title, scheduled_for, notes)
    VALUES ($1,$2,'theirs',$3,$4)`, [BIZ2, C2, OLD, `Pasted from an old note: [booking:${mine}]`]);
  const snapshot = async () => (await db.query(
    'SELECT id, status, scheduled_for, notes FROM sessions WHERE business_id = $1 ORDER BY id', [BIZ2])).rows;
  const before = await snapshot();

  assert.equal((await sync(db, theirs, OLD)).state, 'not_found', "another business's booking is not found");
  await sync(db, mine, OLD);
  await move(db, mine, NEW);
  await sync(db, mine, NEW);
  await setStatus(db, mine, 'cancelled');
  await sync(db, mine);
  assert.deepEqual(await snapshot(), before, "nothing in the other business changes, even a session carrying this booking's marker");
}

// ── 10. the audit trail sees every write ──────────────────────────────
{
  const writes = (await one(db, `SELECT count(*)::int AS n FROM audit_log WHERE tbl = 'sessions'`)).n;
  const b = await book(db);
  await sync(db, b, OLD);
  await move(db, b, NEW);
  await sync(db, b, NEW);
  assert.equal((await one(db, `SELECT count(*)::int AS n FROM audit_log WHERE tbl = 'sessions'`)).n, writes + 3,
    'two inserts and one cancel, each audited');
}

await db.close();
console.log('booking_session_sync: all checks passed');
