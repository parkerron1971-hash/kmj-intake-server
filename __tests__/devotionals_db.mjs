// Plans & devotionals on a real Postgres (PGlite):
// supabase/APPLY-2026-10-19-devotionals.sql. Rows go through every check:
//   devotionals          a church's devotional, its days in one array; a
//                        published one has a day; its day count is worked out;
//                        an unknown voice, a blank title or 91 days is refused
//   devotional_progress  a member's own day, merged by the upsert
//                        member_portal_devotionals.save_day sends; never on
//                        another church's devotional; goes with the
//                        devotional and with the member
//   member_plan_starts   the plans a member started; only a reading plan's key
//                        or a devotional's id
// and the browser's roles can't read any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/devotionals_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '99999999-9999-4999-8999-999999999999';
const jas = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', sam = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$2,$5)', [jas, b1, 'Jasmine', sam, 'Sam']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-19-devotionals.sql'));
await db.exec(await sql('APPLY-2026-10-19-devotionals.sql'));   // idempotent

const day = t => ({ title: t, scripture: 'Proverbs 4:25', body: 'Words.', pull: '', pray: '', act: '', together: '', journal: '' });
const days = n => JSON.stringify(Array.from({ length: n }, (_, i) => day(`Day ${i + 1}`)));

// A draft with no days yet is fine; the database counts the days.
const draft = (await db.query(`INSERT INTO devotionals(business_id, title) VALUES ($1, 'Consecrate Your Focus') RETURNING *`,
  [b1])).rows[0];
assert.equal(draft.day_count, 0); assert.equal(draft.status, 'draft'); assert.equal(draft.voice, 'grace'); checks += 3;
const dev = (await db.query(`UPDATE devotionals SET days = $1::jsonb, status = 'published', starts_on = '2026-10-19'
  WHERE id = $2 RETURNING *`, [days(7), draft.id])).rows[0];
assert.equal(dev.day_count, 7); checks++;
const other = (await db.query(`INSERT INTO devotionals(business_id, title, days) VALUES ($1, 'Elsewhere', $2::jsonb) RETURNING id`,
  [b2, days(1)])).rows[0].id;

// What a devotional can't be.
await refuses(`INSERT INTO devotionals(business_id, title, status) VALUES ($1, 'Empty', 'published')`, [b1], /check constraint/);
await refuses(`INSERT INTO devotionals(business_id, title) VALUES ($1, '   ')`, [b1], /check constraint/);
await refuses(`INSERT INTO devotionals(business_id, title, voice) VALUES ($1, 'x', 'robot')`, [b1], /check constraint/);
await refuses(`INSERT INTO devotionals(business_id, title, days) VALUES ($1, 'x', $2::jsonb)`, [b1, days(91)], /check constraint/);
await refuses(`INSERT INTO devotionals(business_id, title, days) VALUES ($1, 'x', '{"a":1}'::jsonb)`, [b1], /check constraint|non-array/);
await refuses(`INSERT INTO devotionals(business_id, title, day_count) VALUES ($1, 'x', 3)`, [b1], /generated|day_count/);

// member_portal_devotionals.save_day: PostgREST's merge-duplicates upsert on the key.
const upsert = `INSERT INTO devotional_progress(business_id, contact_id, devotional_id, day, done_at, checks, journal, updated_at)
  VALUES ($1,$2,$3,$4,$5,$6,$7, now())
  ON CONFLICT (business_id, contact_id, devotional_id, day) DO UPDATE SET done_at = excluded.done_at,
    checks = excluded.checks, journal = excluded.journal, updated_at = excluded.updated_at RETURNING *`;
await db.query(upsert, [b1, jas, dev.id, 3, null, ['a1b2c3d4'], '']);
let row = (await db.query(upsert, [b1, jas, dev.id, 3, new Date().toISOString(), ['a1b2c3d4'], 'Where did my focus go?'])).rows[0];
assert.ok(row.done_at); assert.equal(row.journal, 'Where did my focus go?'); checks += 2;
await db.query(upsert, [b1, jas, dev.id, 1, new Date().toISOString(), [], '']);
await db.query(upsert, [b1, sam, dev.id, 1, null, [], 'Sam\'s own']);
await refuses(upsert, [b1, jas, dev.id, 0, null, [], ''], /check constraint/);
await refuses(upsert, [b1, jas, dev.id, 91, null, [], ''], /check constraint/);
await refuses(upsert, [b1, jas, dev.id, 2, null, [], 'x'.repeat(4001)], /check constraint/);
await refuses(upsert, [b1, jas, dev.id, 2, null, Array.from({ length: 9 }, (_, i) => `k${i}`), ''], /check constraint/);
// never a day on another church's devotional
await refuses(upsert, [b1, jas, other, 1, null, [], ''], /foreign key/);

// member_plan_starts: a reading plan's key or a devotional's id, once each.
const start = `INSERT INTO member_plan_starts(business_id, contact_id, plan, started_on) VALUES ($1,$2,$3,'2026-10-21')
  ON CONFLICT (business_id, contact_id, plan) DO NOTHING RETURNING *`;
await db.query(start, [b1, jas, 'reading:gospels-30']);
await db.query(start, [b1, jas, `devotional:${dev.id}`]);
const again = (await db.query(start, [b1, jas, 'reading:gospels-30'])).rows;
assert.equal(again.length, 0); checks++;                                           // starting again keeps the first day
await refuses(start, [b1, jas, 'whatever'], /check constraint/);
await refuses(start, [b1, jas, 'devotional:not-an-id'], /check constraint/);

// A member's days go when they do; a devotional's days go with it.
await db.query(`DELETE FROM contacts WHERE id = $1`, [sam]);
let n = (await db.query(`SELECT count(*)::int n FROM devotional_progress`)).rows[0].n;
assert.equal(n, 2); checks++;
await db.query(`DELETE FROM devotionals WHERE id = $1`, [dev.id]);
n = (await db.query(`SELECT count(*)::int n FROM devotional_progress`)).rows[0].n;
assert.equal(n, 0); checks++;

// Server-only: RLS on, no grant for the browser's roles.
const locked = (await db.query(`SELECT bool_and(relrowsecurity) r FROM pg_class
  WHERE relname IN ('devotionals', 'devotional_progress', 'member_plan_starts')`)).rows[0].r;
assert.equal(locked, true); checks++;
const grants = (await db.query(`SELECT has_table_privilege('anon','public.devotionals','select') a,
  has_table_privilege('authenticated','public.devotional_progress','select') b,
  has_table_privilege('authenticated','public.member_plan_starts','insert') c,
  has_table_privilege('service_role','public.devotional_progress','insert') d`)).rows[0];
assert.deepEqual(grants, { a: false, b: false, c: false, d: true }); checks++;

console.log(`devotionals_db: ${checks} checks passed`);
