// A church group's prayer wall, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-prayer.sql. A request is words on the wall
// OR a "a pastor has it" card with no words, never both and never neither;
// marks are "I'm praying" / "Praise God", one of each per person; everything
// is this church's own; members never touch the tables directly. Applied
// twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_prayer_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const dana = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', keisha = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$2,$5),($6,$7,$8)',
  [dana, b1, 'Dana Walker', keisha, 'Keisha Davis', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-prayer.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-prayer.sql'));   // twice

const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const theirs = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Theirs') RETURNING id`, [b2])).rows[0].id;
const ask = `INSERT INTO group_prayers(business_id, group_id, contact_id, body, to_pastor) VALUES ($1,$2,$3,$4,$5) RETURNING id`;
const p = (await db.query(ask, [b1, g, dana, 'Surgery Thursday morning', false])).rows[0].id; checks++;
await db.query(ask, [b1, g, dana, null, true]); checks++;                                  // a pastor has it
await refuses(ask, [b1, g, dana, 'words', true], /check constraint/);                     // a pastor card never carries words
await refuses(ask, [b1, g, dana, null, false], /check constraint/);                       // a wall request has words
await refuses(ask, [b1, g, dana, '   ', false], /check constraint/);
await refuses(ask, [b1, g, dana, 'x'.repeat(1001), false], /check constraint/);
await refuses(ask, [b1, theirs, dana, 'hi', false], /That group is not in this business/);
await refuses(ask, [b1, g, elsewhere, 'hi', false], /That person is not in this business/);

const mark = `INSERT INTO group_prayer_marks(prayer_id, contact_id, business_id, kind) VALUES ($1,$2,$3,$4)`;
await db.query(mark, [p, keisha, b1, 'praying']); checks++;
await refuses(mark, [p, keisha, b1, 'praying'], /duplicate key|unique/);
await refuses(mark, [p, keisha, b1, 'amen'], /check constraint/);
await refuses(mark, [p, elsewhere, b1, 'praying'], /That person is not in this business/);
await refuses(mark, [p, elsewhere, b2, 'praying'], /That prayer is not in this business/);
await refuses(`UPDATE group_prayers SET praise = $1 WHERE id = $2`, ['x'.repeat(501), p], /check constraint/);

const grants = (await db.query(`SELECT DISTINCT grantee FROM information_schema.role_table_grants
  WHERE table_name IN ('group_prayers','group_prayer_marks')`)).rows.map(r => r.grantee);
assert.ok(!grants.includes('anon') && !grants.includes('authenticated'), grants.join(',')); checks++;
await db.query('DELETE FROM group_prayers WHERE id = $1', [p]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM group_prayer_marks')).rows[0].n, 0); checks++;   // marks go with it

console.log(`group prayer db: ${checks} checks passed`);
