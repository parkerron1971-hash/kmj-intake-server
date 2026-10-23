// Phone alerts and the week's email for the church's news, on a real
// Postgres (PGlite): supabase/APPLY-2026-10-23-news-alerts.sql. A member's
// News choice is one of Important, Everything or Off (empty is the
// default); a post is marked once it rang; the week's email is once per
// person per week, this church's own person; the email log is
// server-written. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/news_alerts_db.mjs
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
await db.exec(await sql('APPLY-2026-10-14-member-push.sql'));
await db.exec(await sql('APPLY-2026-10-23-church-news.sql'));
await db.exec(await sql('APPLY-2026-10-23-news-alerts.sql'));
await db.exec(await sql('APPLY-2026-10-23-news-alerts.sql'));   // a second run changes nothing
checks++;

// A member's choice: empty is the default; Important, Everything or Off only.
await db.query(`INSERT INTO member_push_prefs(business_id, contact_id) VALUES ($1,$2)`, [b1, ana]);
const fresh = (await db.query(`SELECT news_level, news_birthdays, news_replies, news_email FROM member_push_prefs WHERE contact_id=$1`, [ana])).rows[0];
assert.deepEqual(fresh, { news_level: null, news_birthdays: null, news_replies: null, news_email: null }); checks++;
for (const level of ['important', 'everything', 'off']) {
  await db.query(`UPDATE member_push_prefs SET news_level=$1 WHERE contact_id=$2`, [level, ana]); checks++;
}
await refuses(`UPDATE member_push_prefs SET news_level='loud' WHERE contact_id=$1`, [ana], /member_push_prefs_news_level_check/);
await db.query(`UPDATE member_push_prefs SET news_birthdays=false, news_replies=true, news_email=true WHERE contact_id=$1`, [ana]);
checks++;

// A post rings once: claimed by setting alerted_at where it's still empty.
const p = (await db.query(`INSERT INTO church_posts(business_id, body) VALUES ($1,'Baptism Sunday') RETURNING id`, [b1])).rows[0].id;
const first = await db.query(`UPDATE church_posts SET alerted_at=now() WHERE id=$1 AND alerted_at IS NULL RETURNING id`, [p]);
const second = await db.query(`UPDATE church_posts SET alerted_at=now() WHERE id=$1 AND alerted_at IS NULL RETURNING id`, [p]);
assert.equal(first.rows.length, 1); assert.equal(second.rows.length, 0); checks += 2;

// The week's email: once per person per week, this church's own person.
await db.query(`INSERT INTO church_news_digests(business_id, contact_id, week_of, posts) VALUES ($1,$2,'2026-10-19',3)`, [b1, ana]);
const again = await db.query(`INSERT INTO church_news_digests(business_id, contact_id, week_of) VALUES ($1,$2,'2026-10-19')
  ON CONFLICT (business_id, contact_id, week_of) DO NOTHING RETURNING contact_id`, [b1, ana]);
assert.equal(again.rows.length, 0); checks++;
await refuses(`INSERT INTO church_news_digests(business_id, contact_id, week_of) VALUES ($1,$2,'2026-10-19')`,
  [b1, elsewhere], /not in this church/);
const rls = (await db.query(`SELECT relrowsecurity FROM pg_class WHERE relname='church_news_digests'`)).rows[0].relrowsecurity;
const grants = (await db.query(`SELECT count(*)::int n FROM information_schema.role_table_grants
  WHERE table_name='church_news_digests' AND grantee IN ('anon','authenticated')`)).rows[0].n;
assert.equal(rls, true); assert.equal(grants, 0); checks += 2;

// A person going away takes their week's email record with them.
await db.query('DELETE FROM member_push_prefs WHERE contact_id=$1', [ana]);
await db.query('DELETE FROM contacts WHERE id=$1', [ana]);
assert.equal((await db.query('SELECT count(*)::int n FROM church_news_digests')).rows[0].n, 0); checks++;

console.log(`news_alerts_db: ${checks} checks passed`);
