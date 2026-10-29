// A church group's news by email, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-email.sql. A post isn't emailed unless the
// leader asked; its email count never goes below zero; the one-hour
// follow-up claims a post once; a member's email follow-up is off until they
// turn it on. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_email_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', tasha = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text,
    birthdate date);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_manager(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query('INSERT INTO contacts(id, business_id, name) VALUES ($1,$2,$3)', [tasha, b1, 'Tasha Williams']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-14-member-push.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-space.sql'));
await db.exec(await sql('APPLY-2026-10-20-quiet-hours.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-email.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-email.sql'));   // twice

const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const post = (await db.query(`INSERT INTO group_posts(business_id, group_id, body, posted_by) VALUES ($1,$2,'Potluck',$3)
  RETURNING id, email_rest, emailed, missed_checked_at`, [b1, g, tasha])).rows[0];
assert.deepEqual([post.email_rest, post.emailed, post.missed_checked_at], [false, 0, null]); checks++;
await refuses(`UPDATE group_posts SET emailed = -1 WHERE id=$1`, [post.id], /check constraint/);

// The one-hour follow-up claims a post once.
const claim = `UPDATE group_posts SET missed_checked_at = now() WHERE id=$1 AND missed_checked_at IS NULL RETURNING id`;
assert.equal((await db.query(claim, [post.id])).rows.length, 1); checks++;
assert.equal((await db.query(claim, [post.id])).rows.length, 0); checks++;

// A member's email follow-up is off until they turn it on, and turning it
// on leaves their other choices alone.
await db.query(`INSERT INTO member_push_prefs(business_id, contact_id, off, quiet) VALUES ($1,$2,'{live}',false)`, [b1, tasha]);
let p = (await db.query('SELECT email_missed FROM member_push_prefs WHERE contact_id=$1', [tasha])).rows[0];
assert.equal(p.email_missed, false); checks++;
await db.query(`INSERT INTO member_push_prefs(business_id, contact_id, email_missed) VALUES ($1,$2,true)
  ON CONFLICT (business_id, contact_id) DO UPDATE SET email_missed = excluded.email_missed`, [b1, tasha]);
p = (await db.query('SELECT off, quiet, email_missed FROM member_push_prefs WHERE contact_id=$1', [tasha])).rows[0];
assert.deepEqual(p, { off: ['live'], quiet: false, email_missed: true }); checks++;

console.log(`group email db: ${checks} checks passed`);
