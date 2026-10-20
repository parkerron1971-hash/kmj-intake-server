// A group's own place in the member app, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-space.sql. Groups that already exist take
// a way in (a closed one stays invite-only, an open one takes its type's
// default) once, never again on a re-run; join_mode and the older
// open_to_join move together whichever one the office changes; a person
// waits once per group; and a request, post or "seen" can't point at
// another church's group, person or post.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_space_db.mjs
// (CI installs PGlite into $RUNNER_TEMP and sets PGLITE_MODULE; locally the
// fallback is output/marketing-qa, like the other database checks.)
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const tasha = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', rochelle = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
// Supabase's pieces the policies name: the auth schema and the seat checks.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$2,$5),($6,$7,$8)',
  [tasha, b1, 'Tasha Williams', rochelle, 'Rochelle Taylor', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
const g = async (name, kind, open, biz = b1) => (await db.query(
  `INSERT INTO groups(business_id, name, kind, open_to_join) VALUES ($1,$2,$3,$4) RETURNING id`, [biz, name, kind, open])).rows[0].id;
const sisters = await g('Sisters in the City', 'small_group', true);
const closed = await g('Ministers Alliance', 'ministry', false);
const klass = await g('New Members', 'class', true);
const theirs = await g('Theirs', 'small_group', true, b2);

// First apply: groups that already exist take their way in.
await db.exec(await sql('APPLY-2026-10-20-group-space.sql'));
const mode = async id => (await db.query('SELECT join_mode, open_to_join, name_display FROM groups WHERE id=$1', [id])).rows[0];
assert.deepEqual(await mode(sisters), { join_mode: 'ask', open_to_join: true, name_display: 'full' }); checks++;
assert.deepEqual(await mode(closed), { join_mode: 'invite', open_to_join: false, name_display: 'full' }); checks++;
assert.equal((await mode(klass)).join_mode, 'open'); checks++;

// The office opens Sisters up; a re-run must not undo that.
await db.query(`UPDATE groups SET join_mode='open' WHERE id=$1`, [sisters]);
await db.exec(await sql('APPLY-2026-10-20-group-space.sql'));
assert.equal((await mode(sisters)).join_mode, 'open'); checks++;

// join_mode and open_to_join move together, whichever one changes.
await db.query(`UPDATE groups SET join_mode='invite' WHERE id=$1`, [sisters]);
assert.deepEqual(await mode(sisters), { join_mode: 'invite', open_to_join: false, name_display: 'full' }); checks++;
await db.query(`UPDATE groups SET open_to_join=true WHERE id=$1`, [sisters]);   // the older way
assert.deepEqual(await mode(sisters), { join_mode: 'ask', open_to_join: true, name_display: 'full' }); checks++;
const newClosed = await g('Elders', 'small_group', false);
assert.equal((await mode(newClosed)).join_mode, 'invite'); checks++;
await refuses(`UPDATE groups SET name_display='everyone' WHERE id=$1`, [sisters], /check constraint/);
await refuses(`UPDATE groups SET join_mode='maybe' WHERE id=$1`, [sisters], /check constraint/);

// Asking to join: one waiting request per person per group.
const ask = `INSERT INTO group_join_requests(business_id, group_id, contact_id) VALUES ($1,$2,$3) RETURNING id`;
const req = (await db.query(ask, [b1, sisters, rochelle])).rows[0].id;
assert.ok(req); checks++;
await refuses(ask, [b1, sisters, rochelle], /duplicate key|unique/);
await db.query(`UPDATE group_join_requests SET status='yes', decided_at=now(), decided_by=$2 WHERE id=$1`, [req, tasha]);
assert.ok((await db.query(ask, [b1, sisters, rochelle])).rows[0].id); checks++;   // answered: may ask again later

// Another church's people, groups and posts stay out.
await refuses(ask, [b1, sisters, elsewhere], /That person is not in this business/);
await refuses(ask, [b1, theirs, rochelle], /That group is not in this business/);
const post = `INSERT INTO group_posts(business_id, group_id, title, body, posted_by) VALUES ($1,$2,$3,$4,$5) RETURNING id`;
const p1 = (await db.query(post, [b1, sisters, 'No gathering Thanksgiving week', 'Potluck Nov 19.', tasha])).rows[0].id;
assert.ok(p1); checks++;
const toAll = (await db.query(post, [b1, null, 'Every group', 'From the pastors.', tasha])).rows[0].id;
assert.ok(toAll); checks++;   // group_id null: from the pastors, to every group
await refuses(post, [b1, theirs, 'x', 'y', tasha], /That group is not in this business/);
await refuses(post, [b1, sisters, 'x', 'y', elsewhere], /That person is not in this business/);
await refuses(post, [b1, sisters, 'x', '   ', tasha], /check constraint/);
const seen = `INSERT INTO group_post_seen(business_id, post_id, contact_id) VALUES ($1,$2,$3)`;
await db.query(seen, [b1, p1, rochelle]); checks++;
await refuses(seen, [b2, p1, elsewhere], /That post is not in this business/);
await refuses(seen, [b1, p1, elsewhere], /That person is not in this business/);
await db.query(`UPDATE group_post_seen SET acked_at=now() WHERE post_id=$1 AND contact_id=$2`, [p1, rochelle]); checks++;

console.log(`group space db: ${checks} checks passed`);
