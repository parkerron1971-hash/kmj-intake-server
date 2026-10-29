// Celebrations, on a real Postgres (PGlite): supabase/APPLY-2026-10-23-celebrations.sql
// on top of the church news tables. It applies twice without harm; a couple
// is one row whichever spouse asked; nobody marries themselves; a choice,
// a couple or a post's other spouse can't be another church's person; a
// month-and-day is a real one; and each person's celebration of a kind is
// one post a day.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/celebrations_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const darnell = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', lisa = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
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
  [darnell, b1, 'Darnell Grant', lisa, 'Lisa Grant', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-23-church-news.sql'));
await db.exec(await sql('APPLY-2026-10-23-celebrations.sql'));
await db.exec(await sql('APPLY-2026-10-23-celebrations.sql'));   // a second run changes nothing
checks++;

// What a member chose.
await db.query(`INSERT INTO member_celebrations(business_id, contact_id, birthday, birthday_md) VALUES ($1,$2,true,'10-23')`, [b1, lisa]);
checks++;
await refuses(`INSERT INTO member_celebrations(business_id, contact_id, birthday_md) VALUES ($1,$2,'13-01')`, [b1, darnell],
  /member_celebrations_birthday_md_check/);
await refuses(`INSERT INTO member_celebrations(business_id, contact_id, birthday) VALUES ($1,$2,true)`, [b1, elsewhere],
  /person is not in this business/);
await refuses(`INSERT INTO member_celebrations(business_id, contact_id, stopped) VALUES ($1,$2,'gone')`, [b1, darnell],
  /member_celebrations_stopped_check/);

// A couple: one row whichever spouse asked; never yourself; never another church's person.
await db.query(`INSERT INTO member_anniversaries(business_id, a_id, b_id, married_on, a_yes) VALUES ($1,$2,$3,'2006-10-23',true)`,
  [b1, darnell, lisa]);
checks++;
await refuses(`INSERT INTO member_anniversaries(business_id, a_id, b_id, married_on) VALUES ($1,$2,$3,'2006-10-23')`,
  [b1, lisa, darnell], /duplicate key/);
await refuses(`INSERT INTO member_anniversaries(business_id, a_id, b_id, married_on) VALUES ($1,$2,$2,'2006-10-23')`,
  [b1, darnell], /member_anniversaries_check/);
await refuses(`INSERT INTO member_anniversaries(business_id, a_id, b_id, married_on) VALUES ($1,$2,$3,'2006-10-23')`,
  [b1, darnell, elsewhere], /person is not in this business/);

// A day's celebration is one post per person and kind; its other spouse is this church's.
const post = `INSERT INTO church_posts(business_id, kind, person_id, partner_id, celebrate_on, status) VALUES ($1,'celebration',$2,$3,'2026-10-23','posted')`;
await db.query(post, [b1, darnell, lisa]);
checks++;
await refuses(post, [b1, darnell, lisa], /duplicate key/);
await refuses(`INSERT INTO church_posts(business_id, kind, person_id, partner_id, celebrate_on) VALUES ($1,'celebration',$2,$3,'2026-10-24')`,
  [b1, lisa, elsewhere], /person is not in this business/);
// "This week we celebrate" has no person: more than one week's can exist.
await db.query(`INSERT INTO church_posts(business_id, kind, celebrate_on, body) VALUES ($1,'celebration','2026-10-25','A'),($1,'celebration','2026-11-01','B')`, [b1]);
checks++;

for (const t of ['member_celebrations', 'member_anniversaries']) {
  const rls = (await db.query(`SELECT relrowsecurity FROM pg_class WHERE relname=$1`, [t])).rows[0].relrowsecurity;
  assert.equal(rls, true, `${t} has row security`);
  const grants = (await db.query(`SELECT grantee, privilege_type FROM information_schema.role_table_grants
    WHERE table_name=$1 AND grantee IN ('anon','authenticated')`, [t])).rows.map(r => `${r.grantee}:${r.privilege_type}`).sort();
  assert.deepEqual(grants, ['authenticated:SELECT'], `${t}: seats read, nobody writes`);
  checks += 2;
}

console.log(`celebrations_db: ${checks} checks passed`);
