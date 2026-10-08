// Bookings fill their own columns (supabase/APPLY-2026-10-08-booking-columns.sql)
// on a real Postgres (PGlite): the safe casts, the backfill and its side effects,
// the trigger on insert and on reschedule, a deliberate column write left alone,
// replay, a write as the app's role, and an apply that fails changing nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/booking_columns_db.mjs
// (CI installs PGlite into $RUNNER_TEMP and sets PGLITE_MODULE; locally the
// fallback is output/marketing-qa, like the other database checks.)
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const migration = await readFile(new URL('../supabase/APPLY-2026-10-08-booking-columns.sql', import.meta.url), 'utf8');
const cases = JSON.parse(await readFile(new URL('./booking_time_cases.json', import.meta.url), 'utf8'));

// What production already has on module_entries, reduced to what these
// columns touch: the table (custom-modules-migration.sql + the 2026-07-23
// columns), both updated_at triggers (custom-modules-migration.sql,
// APPLY-2026-09-29-ministry-readiness.sql), the restricted-store guard
// (APPLY-2026-09-07-restricted-entry-boundary.sql) and the ledger's db tier
// (APPLY-2026-08-03-ledger-coverage.sql), counted instead of hashed.
const SCHEMA = `
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE TABLE public.custom_modules (id uuid PRIMARY KEY, business_id uuid NOT NULL,
  agent_config jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE TABLE public.module_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  module_id uuid NOT NULL REFERENCES public.custom_modules(id) ON DELETE CASCADE,
  business_id uuid NOT NULL,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active',
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  appointment_at timestamptz,
  duration_min_at_booking integer);
CREATE FUNCTION public.set_updated_at_timestamp() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;
CREATE TRIGGER trg_module_entries_updated BEFORE UPDATE ON public.module_entries
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_timestamp();
CREATE FUNCTION public.advance_module_revision() RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN new.updated_at = greatest(clock_timestamp(), coalesce(old.updated_at, '-infinity'::timestamptz) + interval '1 microsecond');
RETURN new; END $$;
CREATE TRIGGER zz_module_revision BEFORE UPDATE ON public.module_entries
  FOR EACH ROW EXECUTE FUNCTION public.advance_module_revision();
CREATE FUNCTION public.is_standard_module_store(p_business_id uuid, p_module_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.custom_modules m WHERE m.id = p_module_id
    AND m.business_id = p_business_id AND coalesce(m.agent_config->>'access_level', '') <> 'restricted'); $$;
CREATE FUNCTION public.require_standard_module_store() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.is_standard_module_store(NEW.business_id, NEW.module_id) THEN
    RAISE EXCEPTION 'Restricted readings require the authorized restricted-module endpoint';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER require_standard_module_store BEFORE INSERT OR UPDATE ON public.module_entries
  FOR EACH ROW EXECUTE FUNCTION public.require_standard_module_store();
CREATE TABLE public.audit_log (target_id text, verb text, after jsonb);
CREATE FUNCTION public.audit_row_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO public.audit_log VALUES (coalesce(new.id, old.id)::text, 'db:module_entries_' || lower(tg_op), to_jsonb(new));
  RETURN coalesce(new, old);
END $$;
CREATE TRIGGER audit_module_entries_update AFTER UPDATE ON public.module_entries
  FOR EACH ROW WHEN (old.* IS DISTINCT FROM new.*) EXECUTE FUNCTION public.audit_row_change();
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.module_entries TO authenticated, service_role;
GRANT SELECT ON public.custom_modules TO authenticated, service_role;
`;

const BIZ = 'b0000000-0000-4000-8000-000000000001';
const MOD = 'c0000000-0000-4000-8000-000000000001';
const LOCKED = 'c0000000-0000-4000-8000-000000000002';
const id = (n) => `e0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const OLD = '2026-01-01T00:00:00Z';

async function fresh() {
  const db = new PGlite();
  await db.exec(SCHEMA);
  await db.query(`INSERT INTO custom_modules(id, business_id, agent_config) VALUES ($1,$2,'{}'), ($3,$2,'{"access_level":"restricted"}')`,
    [MOD, BIZ, LOCKED]);
  return db;
}
const one = async (db, q, p = []) => (await db.query(q, p)).rows[0];
// Rows are compared as epoch seconds / plain values, so the session's time zone never matters.
const row = (db, n) => one(db, `SELECT extract(epoch FROM appointment_at)::float8 AS at, duration_min_at_booking AS min,
  extract(epoch FROM updated_at)::float8 AS upd FROM module_entries WHERE id=$1`, [id(n)]);
const epoch = (iso) => (iso === null ? null : Date.parse(iso) / 1000);
const insert = (db, n, data, extra = {}) => db.query(
  `INSERT INTO module_entries(id, module_id, business_id, data, status, updated_at, appointment_at, duration_min_at_booking)
   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
  [id(n), extra.module || MOD, BIZ, JSON.stringify(data), extra.status || 'active', extra.updated_at || OLD,
   extra.at ?? null, extra.min ?? null]);
const auditRows = async (db) => (await one(db, 'SELECT count(*)::int AS n FROM audit_log')).n;

// ── 1. the casts, against the cases the backend shares ───────────────
{
  const db = await fresh();
  await db.exec(migration);
  for (const zone of ['UTC', 'America/Chicago', 'Asia/Kolkata']) {
    await db.exec(`SET TIME ZONE '${zone}'`);            // a time with no zone is UTC whatever the session says
    for (const [input, want] of cases.times) {
      const got = await one(db, 'SELECT extract(epoch FROM public.booking_ts($1))::float8 AS t', [input]);
      assert.equal(got.t, epoch(want), `booking_ts(${JSON.stringify(input)}) in ${zone}`);
    }
  }
  await db.exec(`SET TIME ZONE 'UTC'`);
  for (const [input, want] of cases.lengths) {
    const got = await one(db, 'SELECT public.booking_min($1) AS m', [input]);
    assert.equal(got.m, want, `booking_min(${JSON.stringify(input)})`);
  }
  for (const big of ['99999999999', '1e40']) {
    assert.equal((await one(db, 'SELECT public.booking_min($1) AS m', [big])).m, null, `${big} does not fit a column`);
  }
  // Volatility as declared: the time cast is STABLE (it calls a STABLE cast), the length cast IMMUTABLE.
  const vol = Object.fromEntries((await db.query(`SELECT proname, provolatile FROM pg_proc
    WHERE pronamespace='public'::regnamespace AND proname IN ('booking_ts','booking_min')`)).rows.map((r) => [r.proname, r.provolatile]));
  assert.deepEqual(vol, { booking_ts: 's', booking_min: 'i' });
  await db.close();
}

// ── 2. backfill: the production shapes, and only rows that would change ─
const db = await fresh();
await insert(db, 1, { appointment_at: '2026-10-07T14:00:00Z', duration_min_at_booking: 45 });          // Z
await insert(db, 2, { appointment_at: '2026-10-07T15:00:00+00:00', duration_min_at_booking: '30' });   // +00:00, text length
await insert(db, 3, { appointment_at: '2026-10-06' });                                                  // date-only, no length
await insert(db, 4, { appointment_at: 'next tuesday', duration_min_at_booking: 'an hour' });           // garbage
await insert(db, 5, { customer_name: 'No time at all' });                                               // missing
await insert(db, 6, { appointment_at: '2026-10-09T09:00:00Z', duration_min_at_booking: 60 }, { status: 'cancelled' });
await insert(db, 7, { appointment_at: '2026-10-11T10:00:00Z', duration_min_at_booking: 30 },           // a column written on purpose
  { at: '2026-10-10T10:00:00Z', min: 90 });
await insert(db, 8, { appointment_at: '2026-10-12T10:00:00Z', duration_min_at_booking: 20 },           // time column set, length empty
  { at: '2026-10-12T10:00:00Z' });

await db.exec(migration);

const expectRow = async (n, at, min, label) => {
  const r = await row(db, n);
  assert.equal(r.at, epoch(at), `${label}: appointment_at`);
  assert.equal(r.min, min, `${label}: duration_min_at_booking`);
  return r;
};
await expectRow(1, '2026-10-07T14:00:00Z', 45, 'Z');
await expectRow(2, '2026-10-07T15:00:00Z', 30, '+00:00');
await expectRow(3, '2026-10-06T00:00:00Z', null, 'date-only is midnight UTC; no length stays empty');
await expectRow(4, null, null, 'garbage is left alone');
await expectRow(5, null, null, 'no time is left alone');
await expectRow(6, '2026-10-09T09:00:00Z', 60, 'a cancelled booking is filled too');
await expectRow(7, '2026-10-10T10:00:00Z', 90, 'a column that has a value is never overwritten');
await expectRow(8, '2026-10-12T10:00:00Z', 20, 'only the empty length is filled');

// Side effects: exactly the rows that changed got an audit row and a new updated_at.
const changed = [1, 2, 3, 6, 8];
assert.equal(await auditRows(db), changed.length, 'one ledger row per filled row, none for the rest');
for (let n = 1; n <= 8; n++) {
  const moved = (await row(db, n)).upd !== epoch(OLD);
  assert.equal(moved, changed.includes(n), `updated_at of row ${n} ${changed.includes(n) ? 'moves' : 'stays'}`);
}

// Replay-safe: a second apply changes nothing and writes no ledger rows.
const before = await db.query('SELECT id, appointment_at, duration_min_at_booking, updated_at FROM module_entries ORDER BY id');
await db.exec(migration);
assert.deepEqual((await db.query('SELECT id, appointment_at, duration_min_at_booking, updated_at FROM module_entries ORDER BY id')).rows,
  before.rows, 'the second apply touches nothing');
assert.equal(await auditRows(db), changed.length, 'and logs nothing');
assert.equal((await one(db, `SELECT count(*)::int AS n FROM pg_trigger WHERE tgrelid='public.module_entries'::regclass
  AND tgname='booking_columns_from_data'`)).n, 1, 'one trigger, not two');

// ── 3. insert: the widget's shape fills the columns ───────────────────
await insert(db, 10, { appointment_at: '2026-11-02T16:30:00Z', duration_min_at_booking: 45 });
await expectRow(10, '2026-11-02T16:30:00Z', 45, 'insert with data only');
await insert(db, 11, { appointment_at: '2026-11-03' });
await expectRow(11, '2026-11-03T00:00:00Z', null, 'insert date-only, no length');
await insert(db, 12, { appointment_at: 'whenever', duration_min_at_booking: -10 });
await expectRow(12, null, null, 'insert with garbage: the write succeeds, the columns stay empty');
await insert(db, 13, { appointment_at: '2026-11-04T09:00:00Z', duration_min_at_booking: 30 },
  { at: '2026-11-05T09:00:00Z', min: 50 });
await expectRow(13, '2026-11-05T09:00:00Z', 50, 'an insert that gives the columns keeps them');
await insert(db, 14, { notes: 'not a booking' });
await expectRow(14, null, null, 'a row that is not a booking is untouched');

// ── 4. update: reschedule moves data, the column follows ──────────────
const patch = (n, sql, p = []) => db.query(`UPDATE module_entries SET ${sql} WHERE id=$1`, [id(n), ...p]);
await patch(10, `data = jsonb_set(data, '{appointment_at}', '"2026-11-02T18:00:00+00:00"')`);
await expectRow(10, '2026-11-02T18:00:00Z', 45, 'reschedule (data moved) moves the column');
await patch(10, `data = jsonb_set(data, '{duration_min_at_booking}', '60')`);
await expectRow(10, '2026-11-02T18:00:00Z', 60, 'a new length in data moves the length');
await patch(10, `data = jsonb_set(data, '{appointment_at}', '"2026-11-09"')`);
await expectRow(10, '2026-11-09T00:00:00Z', 60, 'reschedule to a bare date');
await patch(10, `data = jsonb_set(data, '{appointment_at}', '"soon"')`);
await expectRow(10, '2026-11-09T00:00:00Z', 60, 'data moved to garbage: the column keeps the last real time');
await patch(10, `data = data - 'appointment_at' - 'duration_min_at_booking'`);
await expectRow(10, '2026-11-09T00:00:00Z', 60, 'data that drops the time: the column is not cleared');
await patch(10, `status = 'cancelled'`);
await expectRow(10, '2026-11-09T00:00:00Z', 60, 'a status change leaves the columns');

// A deliberate column write is left alone, and an unrelated data edit does not undo it.
await patch(1, `appointment_at = '2026-12-01T10:00:00Z'`);
await expectRow(1, '2026-12-01T10:00:00Z', 45, 'a column-only write is kept');
await patch(1, `data = data || '{"notes":"bring the blue folder"}'::jsonb`);
await expectRow(1, '2026-12-01T10:00:00Z', 45, 'an edit that leaves data.appointment_at alone keeps the written column');
await patch(1, `duration_min_at_booking = 25`);
await expectRow(1, '2026-12-01T10:00:00Z', 25, 'a length-only write is kept');
await patch(1, `data = jsonb_set(data, '{appointment_at}', '"2026-12-02T10:00:00Z"')`);
await expectRow(1, '2026-12-02T10:00:00Z', 25, 'when data moves again, data wins');
// One statement writing both, as the Acuity draft (#1257) would: the column it wrote is kept,
// even where it differs from data.
await patch(2, `data = jsonb_set(data, '{appointment_at}', '"2026-12-03T10:00:00Z"'), appointment_at = '2026-12-03T10:00:00Z'`);
await expectRow(2, '2026-12-03T10:00:00Z', 30, 'data and column written together');
await patch(2, `data = jsonb_set(data, '{appointment_at}', '"2026-12-04T10:00:00Z"'), appointment_at = '2026-12-05T10:00:00Z',
  duration_min_at_booking = 35`);
await expectRow(2, '2026-12-05T10:00:00Z', 35, 'a statement that writes the columns wins over its own data');
await patch(13, 'appointment_at = NULL, duration_min_at_booking = NULL');
await expectRow(13, null, null, 'a deliberate clear is kept');

// An empty column heals on the next touch (a row the backfill could not read, later fixed).
await patch(4, `data = jsonb_set(data, '{appointment_at}', '"2026-11-20T12:00:00Z"')`);
await expectRow(4, '2026-11-20T12:00:00Z', null, 'a fixed time fills the empty column');

// ── 5. the app writes as authenticated; the trigger works for it ──────
await db.exec('SET ROLE authenticated');
await db.query(`INSERT INTO module_entries(id, module_id, business_id, data) VALUES ($1,$2,$3,$4)`,
  [id(20), MOD, BIZ, JSON.stringify({ appointment_at: '2026-11-06T11:00:00Z', duration_min_at_booking: 40 })]);
await db.query(`UPDATE module_entries SET data = jsonb_set(data, '{appointment_at}', '"2026-11-06T12:00:00Z"') WHERE id=$1`, [id(20)]);
await assert.rejects(db.query('SELECT public.module_entries_booking_columns()'), 'the trigger function is not callable');
await db.exec('RESET ROLE');
await expectRow(20, '2026-11-06T12:00:00Z', 40, 'insert + reschedule as authenticated');

// ── 6. the file's own VERIFY queries run, and its ROLLBACK undoes it ──
const commented = (from, to) => migration.split(from)[1].split(to)[0].split('\n')
  .filter((l) => l.startsWith('--   ')).map((l) => l.slice(5)).join('\n');
const verify = commented('VERIFY (counts only)', 'ROLLBACK').split(';').map((q) => q.trim()).filter(Boolean);
assert.equal(verify.length, 6, 'six verification queries');
for (const q of verify) await db.query(q);                                // each one is valid SQL
const unfilled = await one(db, verify[2]);
assert.deepEqual([unfilled.time_unfilled, unfilled.length_unfilled].map(Number), [1, 1],
  'nothing left to fill but row 13, whose columns were cleared on purpose above');
await db.exec(commented('-- ─── ROLLBACK', '\u0000'));
assert.equal((await one(db, `SELECT count(*)::int AS n FROM pg_trigger WHERE tgname='booking_columns_from_data'`)).n, 0);
assert.equal((await one(db, `SELECT count(*)::int AS n FROM module_entries WHERE appointment_at IS NOT NULL
  OR duration_min_at_booking IS NOT NULL`)).n, 0, 'the rollback empties the columns');
await db.exec(migration);                                                 // and the file applies again after it
await expectRow(3, '2026-10-06T00:00:00Z', null, 're-applied after a rollback');
await db.close();

// ── 7. an apply that fails changes nothing ────────────────────────────
// A booking in a restricted module (none in production, preflight 2026-09-07):
// require_standard_module_store refuses the backfill's update, and the whole
// file rolls back, trigger and functions included.
{
  const bad = await fresh();
  await bad.exec(`ALTER TABLE module_entries DISABLE TRIGGER require_standard_module_store`);
  await insert(bad, 1, { appointment_at: '2026-10-07T14:00:00Z' }, { module: LOCKED });
  await bad.exec(`ALTER TABLE module_entries ENABLE TRIGGER require_standard_module_store`);
  await assert.rejects(bad.exec(migration), /Restricted readings/);
  await bad.exec('ROLLBACK');
  assert.equal((await one(bad, `SELECT count(*)::int AS n FROM pg_proc WHERE pronamespace='public'::regnamespace
    AND proname IN ('booking_ts','booking_min','module_entries_booking_columns')`)).n, 0, 'no function left behind');
  assert.equal((await one(bad, `SELECT count(*)::int AS n FROM pg_trigger WHERE tgname='booking_columns_from_data'`)).n, 0,
    'no trigger left behind');
  assert.equal((await row(bad, 1)).at, null, 'no row changed');
  await bad.close();
}

console.log(`Booking columns database checks passed: ${cases.times.length} time and ${cases.lengths.length} length cases `
  + 'in three session zones, backfill of the production shapes (Z, +00:00, date-only) and only the rows that change, '
  + 'its ledger rows and updated_at, replay, insert, reschedule, deliberate column writes kept, a write as authenticated, '
  + "the file's VERIFY queries and ROLLBACK, and a failed apply that changes nothing.");
