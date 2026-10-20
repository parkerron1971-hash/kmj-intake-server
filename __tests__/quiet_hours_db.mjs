// Quiet hours and the after-hours alert, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-quiet-hours.sql. A member keeps quiet hours and
// lets after-hours alerts ring unless they turn them off; what waits is one
// note per person per thing, this church's own person, a group kind only;
// messages and Board posts are not alerts unless sent as one. Applied twice
// (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/quiet_hours_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const ana = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text,
    birthdate date);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_manager(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts(id, business_id, name) VALUES ($1,$2,$3),($4,$5,$6)', [ana, b1, 'Ana Rivers', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-14-member-push.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-space.sql'));
await db.exec(await sql('APPLY-2026-10-20-quiet-hours.sql'));
await db.exec(await sql('APPLY-2026-10-20-quiet-hours.sql'));   // twice

// A member's choices: quiet hours on, after-hours alerts ring, unless turned off.
await db.query(`INSERT INTO member_push_prefs(business_id, contact_id, off) VALUES ($1,$2,'{live}')`, [b1, ana]);
let p = (await db.query('SELECT quiet, after_hours FROM member_push_prefs WHERE contact_id=$1', [ana])).rows[0];
assert.deepEqual(p, { quiet: true, after_hours: true }); checks++;
await db.query(`INSERT INTO member_push_prefs(business_id, contact_id, quiet) VALUES ($1,$2,false)
  ON CONFLICT (business_id, contact_id) DO UPDATE SET quiet = excluded.quiet`, [b1, ana]);
p = (await db.query('SELECT off, quiet, after_hours FROM member_push_prefs WHERE contact_id=$1', [ana])).rows[0];
assert.deepEqual(p, { off: ['live'], quiet: false, after_hours: true }); checks++;   // the kinds they turned off stay

// What waits: one note per person per thing, newest wins.
const hold = `INSERT INTO member_push_held(business_id, contact_id, kind, title, tag) VALUES ($1,$2,$3,$4,$5)
  ON CONFLICT (business_id, contact_id, tag) DO UPDATE SET title = excluded.title`;
await db.query(hold, [b1, ana, 'messages', 'New message in Sisters', 'chat-1']);
await db.query(hold, [b1, ana, 'messages', 'New message in Sisters (2)', 'chat-1']);
const held = (await db.query('SELECT title FROM member_push_held')).rows;
assert.deepEqual(held, [{ title: 'New message in Sisters (2)' }]); checks++;
await refuses(hold, [b1, elsewhere, 'groups', 'x', 'g-1'], /That person is not in this business/);
await refuses(hold, [b1, ana, 'live', 'x', 'live-1'], /check constraint/);
await refuses(hold, [b1, ana, 'groups', 'x'.repeat(61), 'g-2'], /check constraint/);
const grants = (await db.query(`SELECT grantee FROM information_schema.role_table_grants WHERE table_name='member_push_held'`)).rows.map(r => r.grantee);
assert.ok(!grants.includes('anon') && !grants.includes('authenticated'), grants.join(',')); checks++;

// Messages and Board posts are not alerts unless sent as one.
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const t = (await db.query(`INSERT INTO msg_threads(business_id, kind, group_id) VALUES ($1,'group',$2) RETURNING id`, [b1, g])).rows[0].id;
const m = (await db.query(`INSERT INTO msg_messages(business_id, thread_id, sender_contact_id, body) VALUES ($1,$2,$3,'hi') RETURNING after_hours`, [b1, t, ana])).rows[0];
assert.equal(m.after_hours, false); checks++;
const post = (await db.query(`INSERT INTO group_posts(business_id, group_id, body, posted_by) VALUES ($1,$2,'Potluck',$3) RETURNING after_hours`, [b1, g, ana])).rows[0];
assert.equal(post.after_hours, false); checks++;

console.log(`quiet hours db: ${checks} checks passed`);
