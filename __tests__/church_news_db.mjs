// The church's news in the member app, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-23-church-news.sql. It applies twice without harm;
// a post, reaction, "seen", comment, Love, report or poster can't point at
// another church's group, person, post or comment; a reply answers a comment
// on the same post; the kinds, statuses and comment modes are the ones the
// app knows; and every table is server-written, seats read only.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_news_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const tasha = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', monique = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
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
  [tasha, b1, 'Tasha Williams', monique, 'Monique Brown', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
const g = async (name, biz) => (await db.query(
  `INSERT INTO groups(business_id, name, kind, open_to_join) VALUES ($1,$2,'ministry',true) RETURNING id`, [biz, name])).rows[0].id;
const women = await g('Women', b1);
const theirs = await g('Theirs', b2);

await db.exec(await sql('APPLY-2026-10-23-church-news.sql'));
await db.exec(await sql('APPLY-2026-10-23-church-news.sql'));   // a second run changes nothing
checks++;

const post = async (fields) => {
  const cols = Object.keys(fields), vals = Object.values(fields);
  return (await db.query(`INSERT INTO church_posts(${cols.join(',')}) VALUES (${cols.map((_, i) => '$' + (i + 1)).join(',')}) RETURNING id`, vals)).rows[0].id;
};
const p1 = await post({ business_id: b1, title: 'Baptism Sunday', body: 'Sign up by Nov 2', posted_by: tasha });
const p2 = await post({ business_id: b1, title: 'Women only', body: 'Tea Saturday', group_id: women });
const theirPost = await post({ business_id: b2, title: 'Theirs', body: 'x' });
checks += 3;

// A post can't name another church's group or person.
await refuses(`INSERT INTO church_posts(business_id, body, group_id) VALUES ($1,'x',$2)`, [b1, theirs], /group is not in this business/);
await refuses(`INSERT INTO church_posts(business_id, body, posted_by) VALUES ($1,'x',$2)`, [b1, elsewhere], /person is not in this business/);
await refuses(`INSERT INTO church_posts(business_id, body, person_id) VALUES ($1,'x',$2)`, [b1, elsewhere], /person is not in this business/);
// Only the kinds, statuses and comment modes the app knows.
await refuses(`INSERT INTO church_posts(business_id, body, kind) VALUES ($1,'x','rumor')`, [b1], /church_posts_kind_check/);
await refuses(`INSERT INTO church_posts(business_id, body, status) VALUES ($1,'x','draft')`, [b1], /church_posts_status_check/);
await refuses(`INSERT INTO church_posts(business_id, body, comments) VALUES ($1,'x','some')`, [b1], /church_posts_comments_check/);
await refuses(`INSERT INTO church_posts(business_id, title) VALUES ($1,$2)`, [b1, 'x'.repeat(121)], /church_posts_title_check/);

// Reactions and "seen": this church's post and person, one of each kind.
await db.query(`INSERT INTO church_post_reactions(post_id, contact_id, business_id, kind) VALUES ($1,$2,$3,'amen')`, [p1, monique, b1]);
checks++;
await refuses(`INSERT INTO church_post_reactions(post_id, contact_id, business_id, kind) VALUES ($1,$2,$3,'amen')`,
  [p1, monique, b1], /duplicate key/);
await refuses(`INSERT INTO church_post_reactions(post_id, contact_id, business_id, kind) VALUES ($1,$2,$3,'wow')`,
  [p1, monique, b1], /church_post_reactions_kind_check/);
await refuses(`INSERT INTO church_post_reactions(post_id, contact_id, business_id, kind) VALUES ($1,$2,$3,'love')`,
  [theirPost, monique, b1], /post is not in this business/);
await refuses(`INSERT INTO church_post_seen(post_id, contact_id, business_id) VALUES ($1,$2,$3)`,
  [p1, elsewhere, b1], /person is not in this business/);

// Comments: on this church's post, by this church's person; a reply answers
// a comment on the SAME post; never empty.
const c1 = (await db.query(`INSERT INTO church_post_comments(business_id, post_id, contact_id, body) VALUES ($1,$2,$3,'We will be there')
  RETURNING id`, [b1, p1, monique])).rows[0].id;
await db.query(`INSERT INTO church_post_comments(business_id, post_id, contact_id, body, reply_to) VALUES ($1,$2,$3,'Amen',$4)`,
  [b1, p1, tasha, c1]);
checks += 2;
await refuses(`INSERT INTO church_post_comments(business_id, post_id, contact_id, body, reply_to) VALUES ($1,$2,$3,'Hi',$4)`,
  [b1, p2, tasha, c1], /reply answers a comment on the same post/);
await refuses(`INSERT INTO church_post_comments(business_id, post_id, contact_id, body) VALUES ($1,$2,$3,'   ')`,
  [b1, p1, monique], /church_post_comments_body_check/);
await refuses(`INSERT INTO church_post_comments(business_id, post_id, contact_id, body) VALUES ($1,$2,$3,'x')`,
  [b1, theirPost, monique], /post is not in this business/);
await refuses(`INSERT INTO church_post_comments(business_id, post_id, contact_id, body, status) VALUES ($1,$2,$3,'x','hidden')`,
  [b1, p1, monique], /church_post_comments_status_check/);
await refuses(`INSERT INTO church_post_comment_loves(comment_id, contact_id, business_id) VALUES ($1,$2,$3)`,
  [c1, elsewhere, b1], /person is not in this business/);
await refuses(`INSERT INTO church_post_reports(business_id, comment_id, reported_by) VALUES ($1,$2,$3)`,
  [b2, c1, elsewhere], /comment is not in this business/);
await db.query(`INSERT INTO church_post_reports(business_id, comment_id, reported_by) VALUES ($1,$2,$3)`, [b1, c1, tasha]);
await refuses(`INSERT INTO church_post_reports(business_id, comment_id, reported_by) VALUES ($1,$2,$3)`,
  [b1, c1, tasha], /duplicate key/);

// Who posts to the whole church: this church's people only.
await db.query(`INSERT INTO church_news_posters(business_id, contact_id) VALUES ($1,$2)`, [b1, monique]);
await refuses(`INSERT INTO church_news_posters(business_id, contact_id) VALUES ($1,$2)`, [b1, elsewhere], /person is not in this business/);

// A post going away takes its reactions, comments and reports with it.
await db.query('DELETE FROM church_posts WHERE id=$1', [p1]);
const left = (await db.query(`SELECT (SELECT count(*) FROM church_post_reactions)::int r, (SELECT count(*) FROM church_post_comments)::int c,
  (SELECT count(*) FROM church_post_reports)::int p`)).rows[0];
assert.deepEqual(left, { r: 0, c: 0, p: 0 }); checks++;

// Every table: row security on, seats read only, nothing for anon.
for (const t of ['church_posts', 'church_post_reactions', 'church_post_seen', 'church_post_comments',
                 'church_post_comment_loves', 'church_post_reports', 'church_news_posters']) {
  const rls = (await db.query(`SELECT relrowsecurity FROM pg_class WHERE relname=$1`, [t])).rows[0].relrowsecurity;
  assert.equal(rls, true, `${t} has row security`);
  const grants = (await db.query(`SELECT grantee, privilege_type FROM information_schema.role_table_grants
    WHERE table_name=$1 AND grantee IN ('anon','authenticated')`, [t])).rows.map(r => `${r.grantee}:${r.privilege_type}`).sort();
  assert.deepEqual(grants, ['authenticated:SELECT'], `${t}: seats read, nobody writes`);
  checks += 2;
}

console.log(`church_news_db: ${checks} checks passed`);
