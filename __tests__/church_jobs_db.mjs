// A church's own jobs and the record of sheet changes, on a real Postgres
// (PGlite): supabase/APPLY-2026-11-17-church-jobs.sql. Two server-only tables
// (RLS on, no policies, the browser's roles can't read or write them); one
// key a church for good, so a removed job keeps its key; the shapes the code
// sends are the shapes the checks take; running the file twice changes
// nothing; a church that goes takes everything. And the grant "Sets up jobs
// and people's sheets" rides the duties' own tables (APPLY-2026-11-01-church-
// duties.sql) under a key that is not one of the duties: church_duty_set
// takes it, and logs who gave it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_jobs_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ruth = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO auth.users(id) VALUES ($1), ($2)', [owner, ruth]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-11-17-church-jobs.sql'));
await db.exec(await sql('APPLY-2026-11-17-church-jobs.sql'));   // safe to run twice

for (const table of ['church_jobs', 'church_sheet_changes']) {
  const t = await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS policies,
      has_table_privilege('authenticated', c.oid, 'select') AS browser_reads,
      has_table_privilege('anon', c.oid, 'insert') AS anon_writes,
      has_table_privilege('service_role', c.oid, 'insert') AS server_writes
    FROM pg_class c WHERE c.relname = $1`, [table]);
  assert.deepEqual(t, { rls: true, policies: 0, browser_reads: false, anon_writes: false, server_writes: true }, table);
  checks++;
}
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_constraint
  WHERE conrelid IN ('public.church_jobs'::regclass, 'public.church_sheet_changes'::regclass) AND contype = 'c'`)).n, 7);
checks++;

// A job as church_job_defs.create sends it.
const add = (biz, key, label, more = {}) => db.query(
  `INSERT INTO church_jobs(business_id, key, label, does, description, role, areas, duties, created_by, updated_by)
   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9) RETURNING *`,
  [biz, key, label, more.does ?? 'Runs the kids rooms', more.description ?? null, more.role ?? 'manager',
   more.areas ?? ['kids_youth'], more.duties ?? ['kids'], owner]);
const made = (await add(b1, 'kids_director', 'Kids Director')).rows[0];
assert.deepEqual([made.areas, made.duties, made.role, made.deleted_at], [['kids_youth'], ['kids'], 'manager', null]);
checks++;

// One key a church for good: the same key again is refused, even after the job is removed.
await refuses('INSERT INTO church_jobs(business_id, key, label) VALUES ($1, $2, $3)', [b1, 'kids_director', 'Again'],
  /church_jobs_business_key|duplicate/);
await db.query('UPDATE church_jobs SET deleted_at = now() WHERE business_id = $1 AND key = $2', [b1, 'kids_director']);
await refuses('INSERT INTO church_jobs(business_id, key, label) VALUES ($1, $2, $3)', [b1, 'kids_director', 'Again'],
  /church_jobs_business_key|duplicate/);
// Another church may use the same key.
await add(b2, 'kids_director', 'Kids Director'); checks++;

// The shapes the checks take.
await refuses('INSERT INTO church_jobs(business_id, key, label) VALUES ($1, $2, $3)', [b1, 'Kids Director', 'x x'],
  /church_jobs_key_shape/);
await refuses('INSERT INTO church_jobs(business_id, key, label) VALUES ($1, $2, $3)', [b1, 'k1', 'K'],
  /church_jobs_label_length/);
await refuses('INSERT INTO church_jobs(business_id, key, label, role) VALUES ($1, $2, $3, $4)',
  [b1, 'usher_lead', 'Usher Lead', 'owner'], /church_jobs_role/);
await refuses('INSERT INTO church_jobs(business_id, key, label, does) VALUES ($1, $2, $3, $4)',
  [b1, 'usher_lead', 'Usher Lead', 'x'.repeat(241)], /church_jobs_does_length/);
await refuses('INSERT INTO church_jobs(business_id, key, label, description) VALUES ($1, $2, $3, $4)',
  [b1, 'usher_lead', 'Usher Lead', ''], /church_jobs_description_length/);

// The record, as church_job_defs.record sends it.
await db.query(`INSERT INTO church_sheet_changes(business_id, kind, subject_user_id, changed_by, summary, detail)
  VALUES ($1, 'sheet', $2, $3, $4, $5)`, [b1, ruth, owner, "changed Ruth Ellison's sheet: added Office", { areas: ['office'] }]);
await db.query(`INSERT INTO church_sheet_changes(business_id, kind, job_key, changed_by, summary)
  VALUES ($1, 'job', 'kids_director', $2, $3)`, [b1, ruth, 'added the job “Kids Director”']);
await refuses(`INSERT INTO church_sheet_changes(business_id, kind, summary) VALUES ($1, 'grant', 'x')`, [b1],
  /church_sheet_changes_kind/);
assert.equal((await one('SELECT count(*)::int AS n FROM church_sheet_changes WHERE business_id = $1', [b1])).n, 2);
checks++;

// A church that goes takes its jobs and its record.
await db.query('DELETE FROM businesses WHERE id = $1', [b2]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_jobs WHERE business_id = $1', [b2])).n, 0); checks++;

// The grant rides the duties' own tables under a key that is not a duty.
await db.exec(await sql('APPLY-2026-11-01-church-duties.sql'));
const give = (await one('SELECT church_duty_set($1, $2, $3::uuid[], $4, null) AS c',
  [b1, 'jobs_and_sheets', [ruth], owner])).c;
assert.deepEqual([give.duty, give.from_holders, give.to_holders, give.changed_by],
  ['jobs_and_sheets', null, [ruth], owner]); checks++;
const held = (await db.query(`SELECT user_id::text AS u, given_by::text AS by FROM church_duty_holders
  WHERE business_id = $1 AND duty = 'jobs_and_sheets'`, [b1])).rows;
assert.deepEqual(held, [{ u: ruth, by: owner }]); checks++;
const take = (await one('SELECT church_duty_set($1, $2, $3::uuid[], $4, null) AS c',
  [b1, 'jobs_and_sheets', [], owner])).c;
assert.deepEqual([take.from_holders, take.to_holders], [[ruth], null]); checks++;

console.log(`church jobs db: ${checks} checks passed`);
