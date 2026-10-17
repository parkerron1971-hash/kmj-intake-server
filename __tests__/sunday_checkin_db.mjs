// Sunday check-in on a real Postgres (PGlite): supabase/APPLY-2026-10-17-sunday-checkin.sql
// over the attendance tables it extends. Rows go through every trigger and
// check it touches (a DDL-only probe once passed a trigger that refused every
// row: APPLY-2026-10-17-church-leaders-trigger-fix.sql):
//   attendance               'kids_parent' (and every earlier method) saves through
//                            attendance_same_business; an unknown method, another
//                            church's person or occasion is refused
//   church_checkin_settings  the defaults; a bad time, day or window is refused
//   module_entries           one check-in occasion per church per day; other
//                            entries and other churches unaffected
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/sunday_checkin_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const calvin = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', sam = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const mod1 = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', mod2 = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth; CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ select null::uuid $$;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE TABLE public.module_entries(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), module_id uuid NOT NULL,
    business_id uuid NOT NULL REFERENCES public.businesses(id), data jsonb NOT NULL DEFAULT '{}', status text NOT NULL DEFAULT 'active',
    created_by text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS $$ select false $$;
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS $$ select false $$;`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6)', [calvin, b1, 'Calvin', sam, b2, 'Sam']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-29-attendance.sql'));
await db.exec(await sql('APPLY-2026-10-17-sunday-checkin.sql'));
await db.exec(await sql('APPLY-2026-10-17-sunday-checkin.sql'));   // idempotent

// The occasion: once per church per day.
const day = '{"title":"Sunday Worship","date":"2026-10-18T11:00","_checkin_day":"2026-10-18","_visibility":"private"}';
const occ = (await db.query(`INSERT INTO module_entries(module_id, business_id, data, created_by) VALUES ($1,$2,$3,'sunday_checkin') RETURNING id`,
  [mod1, b1, day])).rows[0].id;
assert.ok(occ); checks++;
await refuses(`INSERT INTO module_entries(module_id, business_id, data) VALUES ($1,$2,$3)`, [mod1, b1, day], /duplicate key|unique/);
await db.query(`INSERT INTO module_entries(module_id, business_id, data) VALUES ($1,$2,$3)`, [mod2, b2, day]);
await db.query(`INSERT INTO module_entries(module_id, business_id, data) VALUES ($1,$2,'{"title":"Sunday Worship","date":""}'),($1,$2,'{"title":"Bible Study"}')`, [mod1, b1]);
await db.query(`UPDATE module_entries SET data = data || '{"notes":"Made for Sunday check-in."}' WHERE id = $1`, [occ]);
checks += 3;

// Attendance: every method a check-in writes, through the same-church trigger.
for (const method of ['self', 'online', 'kids_parent', 'staff', 'station', 'rsvp']) {
  await db.query(`DELETE FROM attendance WHERE contact_id = $1`, [calvin]);
  await db.query(`INSERT INTO attendance(business_id, entry_id, contact_id, name, method) VALUES ($1,$2,$3,'Calvin',$4)`,
    [b1, occ, calvin, method]);
  checks++;
}
await db.query(`UPDATE attendance SET method = 'self' WHERE contact_id = $1`, [calvin]);
checks++;
await refuses(`INSERT INTO attendance(business_id, entry_id, contact_id, name, method) VALUES ($1,$2,$3,'Calvin','self')`,
  [b1, occ, calvin], /duplicate key|unique/);
await refuses(`UPDATE attendance SET method = 'kiosk_adult' WHERE contact_id = $1`, [calvin], /check constraint/);
await refuses(`INSERT INTO attendance(business_id, entry_id, contact_id, name, method) VALUES ($1,$2,$3,'Sam','kids_parent')`,
  [b1, occ, sam], /not in this business/);
const theirs = (await db.query(`SELECT id FROM module_entries WHERE business_id = $1`, [b2])).rows[0].id;
await refuses(`INSERT INTO attendance(business_id, entry_id, contact_id, name, method) VALUES ($1,$2,$3,'Calvin','self')`,
  [b1, theirs, null], /not in this business/);

// The church's Sunday: defaults, and nothing nonsensical.
await db.query(`INSERT INTO church_checkin_settings(business_id) VALUES ($1)`, [b1]);
const st = (await db.query(`SELECT * FROM church_checkin_settings WHERE business_id = $1`, [b1])).rows[0];
assert.equal(st.enabled, false); assert.equal(st.weekday, 6); assert.equal(st.start_time, '11:00');
assert.equal(st.opens_before_min, 30); assert.equal(st.closes_after_min, 180); checks++;
await db.query(`INSERT INTO church_checkin_settings(business_id, enabled, timezone) VALUES ($1, true, 'America/Detroit')
  ON CONFLICT (business_id) DO UPDATE SET enabled = excluded.enabled, timezone = excluded.timezone`, [b1]);
checks++;
await refuses(`UPDATE church_checkin_settings SET start_time = '25:00' WHERE business_id = $1`, [b1], /check constraint/);
await refuses(`UPDATE church_checkin_settings SET weekday = 7 WHERE business_id = $1`, [b1], /check constraint/);
await refuses(`UPDATE church_checkin_settings SET closes_after_min = 5 WHERE business_id = $1`, [b1], /check constraint/);
await refuses(`INSERT INTO church_checkin_settings(business_id) VALUES ($1)`, [b1], /duplicate key|unique/);

console.log(`sunday_checkin_db: ${checks} checks passed`);
