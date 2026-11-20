// A leader's moment, on a real Postgres (PGlite): supabase/APPLY-2026-11-21-church-moments.sql.
// A moment is a photo and one line of at most 120 characters, for the whole
// church or one of its groups, showing for at most seven days and two hours;
// its button is whole or absent; a held one says why; every row stays inside
// its own church; a mark is one row a person a moment. No app login reads or
// writes either table (no policy, browser roles revoked). Applied twice (it is
// idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_moments_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const james = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', ruth = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6),($7,$8,$9)',
  [james, b1, 'Pastor James', ruth, b1, 'Ruth Miles', elsewhere, b2, 'Sam Other']);
await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
const g1 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Young Adults') RETURNING id`, [b1])).rows[0].id;
const g2 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Elsewhere') RETURNING id`, [b2])).rows[0].id;

let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-11-21-church-moments.sql'));
await db.exec(await sql('APPLY-2026-11-21-church-moments.sql'));   // twice

const add = `INSERT INTO church_moments(business_id, posted_by, group_id, line, media_path, button_kind, button_ref, ends_at)
  VALUES ($1,$2,$3,$4,'church-moments/b1/one.jpg',$5,$6, now() + $7::interval) RETURNING id, media_kind, status, starts_at`;

// A moment: the whole church, a photo, a day.
const m1 = (await db.query(add, [b1, james, null, 'Praying for you this morning. See you Sunday.', null, null, '1 day'])).rows[0];
assert.deepEqual([m1.media_kind, m1.status], ['photo', 'shown']); checks++;
// One group's, with its gathering's button, until Sunday from a Monday (almost seven days).
await db.query(add, [b1, ruth, g1, 'Friday night is back.', 'gathering', `${g1}@2026-11-27`, '6 days 23 hours']); checks++;
await db.query(add, [b1, james, null, 'x'.repeat(120), 'service', 'e0000000-0000-4000-8000-000000000001', '3 days']); checks++;

// The line: one to 120 characters.
await refuses(add, [b1, james, null, 'x'.repeat(121), null, null, '1 day'], /check constraint/);
await refuses(add, [b1, james, null, '   ', null, null, '1 day'], /check constraint/);
// Photo only today; the column is ready for video.
await refuses(`INSERT INTO church_moments(business_id, posted_by, line, media_path, media_kind, ends_at)
  VALUES ($1,$2,'A clip','church-moments/b1/clip.mp4','video', now() + interval '1 day')`, [b1, james], /check constraint/);
// A button is a kind this build knows, and whole.
await refuses(add, [b1, james, null, 'Hi', 'giving', 'x', '1 day'], /check constraint/);
await refuses(add, [b1, james, null, 'Hi', 'event', null, '1 day'], /church_moments_button_whole/);
await refuses(add, [b1, james, null, 'Hi', null, 'e1', '1 day'], /church_moments_button_whole/);
// How long: after it starts, never more than seven days and two hours.
await refuses(add, [b1, james, null, 'Hi', null, null, '0 seconds'], /church_moments_ends_after/);
await refuses(add, [b1, james, null, 'Hi', null, null, '7 days 3 hours'], /church_moments_ends_within/);
// Held says why.
await refuses(`UPDATE church_moments SET status = 'held' WHERE id = $1`, [m1.id], /church_moments_held_has_reason/);
await db.query(`UPDATE church_moments SET status = 'held', held_reason = 'self_harm' WHERE id = $1`, [m1.id]); checks++;
await refuses(`UPDATE church_moments SET held_reason = 'rude' WHERE id = $1`, [m1.id], /check constraint/);
await refuses(`UPDATE church_moments SET status = 'hidden' WHERE id = $1`, [m1.id], /check constraint/);
await db.query(`UPDATE church_moments SET status = 'shown', held_reason = null, decided_at = now(), decided_by = 'officer' WHERE id = $1`, [m1.id]); checks++;

// Inside its own church.
await refuses(add, [b1, elsewhere, null, 'Hi', null, null, '1 day'], /That person is not in this business/);
await refuses(add, [b1, james, g2, 'Hi', null, null, '1 day'], /That group is not in this business/);
await refuses(`UPDATE church_moments SET group_id = $2 WHERE id = $1`, [m1.id, g2], /That group is not in this business/);

// Marks: one row a person a moment, this church's.
const mark = `INSERT INTO church_moment_marks(moment_id, business_id, contact_id, seen_at) VALUES ($1,$2,$3, now())
  ON CONFLICT (moment_id, contact_id) DO UPDATE SET seen_at = coalesce(church_moment_marks.seen_at, excluded.seen_at)`;
await db.query(mark, [m1.id, b1, ruth]); checks++;
await db.query(mark, [m1.id, b1, ruth]);   // sent twice, still one row
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_moment_marks WHERE moment_id = $1', [m1.id])).rows[0].n, 1); checks++;
await db.query(`UPDATE church_moment_marks SET loved_at = now() WHERE moment_id = $1 AND contact_id = $2`, [m1.id, ruth]); checks++;
await refuses(mark, [m1.id, b2, elsewhere], /That moment is not in this business/);
await refuses(mark, [m1.id, b1, elsewhere], /That person is not in this business/);

// A person who leaves takes their moments and marks with them; a group's moments go with the group.
const before = (await db.query('SELECT count(*)::int AS n FROM church_moments')).rows[0].n;
await db.query('DELETE FROM groups WHERE id = $1', [g1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_moments')).rows[0].n, before - 1); checks++;
await db.query('DELETE FROM contacts WHERE id = $1', [ruth]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_moment_marks')).rows[0].n, 0); checks++;

// Server-only: RLS on, no policy, nothing granted to the browser roles.
for (const t of ['church_moments', 'church_moment_marks']) {
  const r = (await db.query(`SELECT relrowsecurity FROM pg_class WHERE relname = $1`, [t])).rows[0];
  assert.equal(r.relrowsecurity, true); checks++;
  const pol = (await db.query(`SELECT count(*)::int AS n FROM pg_policies WHERE tablename = $1`, [t])).rows[0].n;
  assert.equal(pol, 0); checks++;
  const grants = (await db.query(`SELECT grantee FROM information_schema.role_table_grants
    WHERE table_name = $1 AND grantee IN ('anon','authenticated','PUBLIC')`, [t])).rows;
  assert.deepEqual(grants, []); checks++;
}
await db.exec(`SET ROLE authenticated`);
await refuses('SELECT * FROM church_moments', [], /permission denied/);
await refuses('SELECT * FROM church_moment_marks', [], /permission denied/);
await db.exec(`RESET ROLE; SET ROLE anon`);
await refuses('SELECT * FROM church_moments', [], /permission denied/);
await db.exec(`RESET ROLE`);

console.log(`church moments db: ${checks} checks passed`);
