// This week's study, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-study.sql. Groups have study on unless
// turned off; a study is one group's questions for one of this church's own
// messages, made once; the questions are a short list; the group, the
// message and whoever posted it are this church's own; members never write
// it directly. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_study_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const tasha = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6)', [tasha, b1, 'Tasha Williams', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-09-30-sermons.sql'));
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const g2 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Theirs') RETURNING id`, [b2])).rows[0].id;
const s = (await db.query(`INSERT INTO sermons(business_id, title, preached_on) VALUES ($1,'Built to Last','2026-10-18') RETURNING id`, [b1])).rows[0].id;
const s2 = (await db.query(`INSERT INTO sermons(business_id, title, preached_on) VALUES ($1,'Theirs','2026-10-18') RETURNING id`, [b2])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-study.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-study.sql'));   // twice

// Study is on unless the office turns it off.
assert.equal((await db.query('SELECT study_on FROM groups WHERE id=$1', [g])).rows[0].study_on, true); checks++;

const add = `INSERT INTO group_studies(business_id, group_id, sermon_id, source, drafted, questions) VALUES ($1,$2,$3,$4,$5,$5) RETURNING id`;
const qs = JSON.stringify(['What did the wise builder do?', 'Where do you hear and not do?']);
const id = (await db.query(add, [b1, g, s, 'chief', qs])).rows[0].id; checks++;
const row = (await db.query('SELECT posted_at, questions FROM group_studies WHERE id=$1', [id])).rows[0];
assert.equal(row.posted_at, null); assert.equal(row.questions.length, 2); checks++;

// Once per group per message.
await refuses(add, [b1, g, s, 'office', qs], /duplicate key|unique/);
// Where it came from, and a short list.
await refuses(add.replace('$2,$3', '$2,$3'), [b1, g2, s, 'chief', qs], /That group is not in this business/);
await refuses(add, [b1, g, s2, 'chief', qs], /That message is not in this business/);
await refuses(`UPDATE group_studies SET source = 'guess' WHERE id=$1`, [id], /check constraint/);
await refuses(`UPDATE group_studies SET questions = $2 WHERE id=$1`, [id, JSON.stringify(Array(9).fill('Q?'))], /check constraint/);
await refuses(`UPDATE group_studies SET questions = '{"a":1}' WHERE id=$1`, [id], /check constraint/);
await refuses(`UPDATE group_studies SET questions = $2 WHERE id=$1`, [id, JSON.stringify(['x'.repeat(4100)])], /check constraint/);
// Posted by this church's own person.
await db.query(`UPDATE group_studies SET posted_at = now(), posted_by = $2 WHERE id=$1`, [id, tasha]); checks++;
await refuses(`UPDATE group_studies SET posted_by = $2 WHERE id=$1`, [id, elsewhere], /That person is not in this business/);

// Members never write it directly; the office reads it.
const grants = (await db.query(`SELECT grantee, privilege_type FROM information_schema.role_table_grants
  WHERE table_name = 'group_studies' AND grantee IN ('anon','authenticated')`)).rows;
assert.deepEqual(grants.map(r => `${r.grantee}:${r.privilege_type}`).sort(), ['authenticated:SELECT']); checks++;

// The message goes, its studies go; so does the group's.
await db.query(`DELETE FROM sermons WHERE id=$1`, [s]);
assert.equal((await db.query('SELECT count(*)::int n FROM group_studies')).rows[0].n, 0); checks++;

console.log(`group study db: ${checks} checks passed`);
