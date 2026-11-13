// Church job descriptions, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-12-church-job-descriptions.sql. Running it twice
// changes nothing; one description a person, one a login with no person; a
// description's person is its own church's; the words keep their shapes (title
// 80, description 1-8000, a known source, a version of 1 and up; someone
// named); both tables are
// server-only; a login deleted leaves the row, a person or a church deleted
// takes theirs; the log takes before/after as jsonb, null for none; a
// description keeps its line breaks.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_job_descriptions_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const u2 = 'aaaaaaaa-2222-4222-8222-222222222222';
const c1 = 'cccccccc-1111-4111-8111-111111111111';
const c2 = 'cccccccc-2222-4222-8222-222222222222';
const c3 = 'cccccccc-3333-4333-8333-333333333333';
// What Supabase already has: the roles, auth.users, businesses and contacts.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid REFERENCES public.businesses(id) ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO auth.users VALUES ($1), ($2)', [u1, u2]);
await db.query('INSERT INTO contacts VALUES ($1, $2), ($3, $4), ($5, $2)', [c1, b1, c2, b2, c3]);

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const ok = async (text, args) => { await db.query(text, args); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const write = `INSERT INTO church_job_descriptions(business_id, contact_id, user_id, title, description, source, written_by,
  updated_by) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)`;

const sql = await readFile(new URL('../supabase/APPLY-2026-11-12-church-job-descriptions.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);                       // twice: nothing changes, nothing fails
checks++;

// One for a person; the stamps default.
await ok(write, [b1, c1, u1, 'Facilities lead', 'The building, keys and safety.', 'said', u1]);
const row = await one(`SELECT written_at IS NOT NULL AND updated_at IS NOT NULL AS stamped, source FROM church_job_descriptions`);
assert.deepEqual(row, { stamped: true, source: 'said' }); checks++;

// One a person; one a login with no person; a person's row may carry its login.
await refuses(write, [b1, c1, null, null, 'Again.', 'said', u1], /church_job_descriptions_person/);
await ok(write, [b1, null, u2, null, 'Runs the front desk.', 'pasted', u1]);
await refuses(write, [b1, null, u2, null, 'Again.', 'said', u1], /church_job_descriptions_login/);
await ok(write, [b1, c3, u2, null, 'The calendar.', 'drafted', u1]);   // the same login, now with a person

// The person is the church's own, on insert and update.
await refuses(write, [b1, c2, null, null, 'x', 'said', u1], /not in this church/);
await refuses(`UPDATE church_job_descriptions SET contact_id = $1 WHERE contact_id = $2`, [c2, c1], /not in this church/);

// The shapes: someone named, a title of 80 at most, a description 1 to 8000, a known source.
await refuses(write, [b1, null, null, null, 'x', 'said', u1], /church_job_descriptions_someone/);
await refuses(write, [b1, null, u1, 'x'.repeat(81), 'x', 'said', u1], /church_job_descriptions_words/);
await refuses(write, [b1, null, u1, null, '   ', 'said', u1], /church_job_descriptions_words/);
await refuses(write, [b1, null, u1, null, 'x'.repeat(8001), 'said', u1], /church_job_descriptions_words/);
await refuses(write, [b1, null, u1, null, 'x', 'emailed', u1], /church_job_descriptions_words/);
await refuses(write, [b1, null, u1, null, null, 'said', u1], /null value/);
await ok(write, [b1, null, u1, 'x'.repeat(80), 'x'.repeat(7989) + '\n\nOn Sunday', 'document', u1]);
assert.equal((await one(`SELECT description FROM church_job_descriptions WHERE user_id = $1 AND contact_id IS NULL`,
  [u1])).description.slice(-11), '\n\nOn Sunday'); checks++;

// The log: before and after as jsonb, null for none; someone named; undone_at.
const log = `INSERT INTO church_job_description_changes(business_id, contact_id, user_id, before, after, by)
  VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`;
const made = await one(log, [b1, c1, null, null, JSON.stringify({ title: 'Facilities lead', description: 'x' }), u1]);
checks++;
await ok(`UPDATE church_job_description_changes SET undone_at = now() WHERE id = $1 AND undone_at IS NULL`, [made.id]);
await refuses(log, [b1, null, null, null, null, u1], /church_job_description_changes_someone/);
const got = await one(`SELECT before IS NULL AS none_before, after->>'title' AS title, at IS NOT NULL AS stamped
  FROM church_job_description_changes WHERE id = $1`, [made.id]);
assert.deepEqual(got, { none_before: true, title: 'Facilities lead', stamped: true }); checks++;

// Server-only: RLS on, no policies, no browser reads.
for (const t of ['church_job_descriptions', 'church_job_description_changes']) {
  const s = await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = $1) AS policies,
      has_table_privilege('authenticated', c.oid, 'select') AS browser,
      has_table_privilege('anon', c.oid, 'select') AS anon
    FROM pg_class c WHERE c.oid = ('public.' || $1)::regclass`, [t]);
  assert.deepEqual(s, { rls: true, policies: 0, browser: false, anon: false }, t); checks++;
}

// The constraints the file's own check names: 11, the two businesses keys valid, the rest NOT VALID.
const cons = (await db.query(`SELECT conname, convalidated FROM pg_constraint
  WHERE conrelid IN ('public.church_job_descriptions'::regclass, 'public.church_job_description_changes'::regclass)
    AND contype IN ('c', 'f') ORDER BY conname`)).rows;
assert.equal(cons.length, 11); checks++;
assert.deepEqual(cons.filter(c => c.convalidated).map(c => c.conname).sort(),
  ['church_job_description_changes_business_id_fkey', 'church_job_descriptions_business_id_fkey']); checks++;

// The title is its own writer's, and goes null with their account; a version is 1 and up.
const u3 = 'aaaaaaaa-3333-4333-8333-333333333333';
await db.query('INSERT INTO auth.users VALUES ($1)', [u3]);
await ok(`UPDATE church_job_descriptions SET title = 'Calendar keeper', title_by = $1 WHERE contact_id = $2`, [u3, c3]);
await refuses(`UPDATE church_job_descriptions SET version = 0 WHERE contact_id = $1`, [c3], /church_job_descriptions_words/);
await ok(`UPDATE church_job_descriptions SET version = version + 1 WHERE contact_id = $1 AND version = 1`, [c3]);
assert.equal((await one(`SELECT version FROM church_job_descriptions WHERE contact_id = $1`, [c3])).version, 2); checks++;
await ok(`DELETE FROM auth.users WHERE id = $1`, [u3]);
assert.equal((await one(`SELECT title_by FROM church_job_descriptions WHERE contact_id = $1`, [c3])).title_by, null);
checks++;
// An undo that puts back a writer whose account is gone fails its key; with null in their place it saves (#1807
// review F8: the server puts null for a writer who is no longer the church's).
await refuses(`UPDATE church_job_descriptions SET written_by = $1, updated_by = $1, title_by = $1 WHERE contact_id = $2`,
  [u3, c3], /foreign key/);
await ok(`UPDATE church_job_descriptions SET written_by = NULL, updated_by = NULL, title_by = NULL,
  description = 'The calendar.' WHERE contact_id = $1`, [c3]);

// A login deleted leaves the row (its writer said as nobody); a person deleted takes theirs and its log; a church
// deleted takes everything.
await ok(`DELETE FROM auth.users WHERE id = $1`, [u2]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_job_descriptions WHERE user_id = $1`, [u2])).n, 2); checks++;
await ok(`DELETE FROM contacts WHERE id = $1`, [c1]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_job_descriptions WHERE contact_id = $1`, [c1])).n, 0);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_job_description_changes WHERE contact_id = $1`, [c1])).n, 0);
checks++;
await ok(`DELETE FROM businesses WHERE id = $1`, [b1]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_job_descriptions`)).n, 0); checks++;

console.log(`church_job_descriptions_db: ${checks} checks passed`);
