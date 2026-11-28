// The one Sunday hub's migration, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-27-sunday-hub.sql (M-7). Every row already there
// keeps its meaning (no Sunday open for live changes, every team closed to
// ministry operations, no word or team areas chosen, no post linked); the
// word is "Sunday" or "service" and nothing else; team areas are an object;
// a linked announcement's removal leaves the post; running the file again
// changes nothing; the browser's roles still read none of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/sunday_hub_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const FILE = 'APPLY-2026-11-27-sunday-hub.sql';
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const u1 = '33333333-3333-4333-8333-333333333333';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, kind text NOT NULL, name text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.group_members(group_id uuid, contact_id uuid, business_id uuid, role text);
  CREATE FUNCTION public.is_business_member(uuid) RETURNS boolean LANGUAGE sql AS 'SELECT false';
  GRANT ALL ON public.businesses TO service_role;`);
await db.query('INSERT INTO businesses(id, owner_id) VALUES ($1, $2)', [b1, u1]);
await db.query('INSERT INTO auth.users(id) VALUES ($1)', [u1]);
await db.exec(await sql('APPLY-2026-10-19-worship-show.sql'));
await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-26-worship-announcements.sql'));

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

// church_posts as the News file makes it, the columns this file touches.
await db.exec(`CREATE TABLE IF NOT EXISTS public.church_posts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, kind text NOT NULL DEFAULT 'news', body text);
  ALTER TABLE public.church_posts ENABLE ROW LEVEL SECURITY;
  REVOKE ALL ON public.church_posts FROM anon, authenticated;`);

// Before the file: a Sunday, a team, the church's settings and a post.
const sunday = await one(`INSERT INTO worship_services(business_id, title, starts_at, items)
  VALUES ($1, 'Sunday service', '2026-11-29T16:05:00Z', '[]') RETURNING id`, [b1]);
const team = await one(`INSERT INTO groups(business_id, kind, name) VALUES ($1, 'team', 'Production') RETURNING id`, [b1]);
await db.query(`INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)`, [team.id, b1]);
await db.query(`INSERT INTO worship_settings(business_id) VALUES ($1)`, [b1]);
const post = await one(`INSERT INTO church_posts(business_id, kind, body) VALUES ($1, 'announcement', 'Hi') RETURNING id`, [b1]);

await db.exec(await sql(FILE));

// Every row already there keeps its meaning.
const s = await one('SELECT live_ok_until, live_ok_by FROM worship_services WHERE id = $1', [sunday.id]);
assert.equal(s.live_ok_until, null); assert.equal(s.live_ok_by, null); checks += 2;
assert.equal((await one('SELECT open_to_ops FROM serve_teams WHERE group_id = $1', [team.id])).open_to_ops, false); checks++;
const w = await one('SELECT service_word, team_areas FROM worship_settings WHERE business_id = $1', [b1]);
assert.equal(w.service_word, null); assert.equal(w.team_areas, null); checks += 2;
assert.equal((await one('SELECT screen_announcement_id FROM church_posts WHERE id = $1', [post.id])).screen_announcement_id, null); checks++;

// A new team starts closed to ministry operations too.
const team2 = await one(`INSERT INTO groups(business_id, kind, name) VALUES ($1, 'team', 'Welcome') RETURNING id`, [b1]);
await db.query(`INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)`, [team2.id, b1]);
assert.equal((await one('SELECT open_to_ops FROM serve_teams WHERE group_id = $1', [team2.id])).open_to_ops, false); checks++;

// The pastor opens a Sunday; their login going away keeps the mark's time.
await db.query(`UPDATE worship_services SET live_ok_until = '2026-11-30T05:59:59Z', live_ok_by = $2 WHERE id = $1`, [sunday.id, u1]);
await db.query('DELETE FROM auth.users WHERE id = $1', [u1]);
const kept = await one('SELECT live_ok_until, live_ok_by FROM worship_services WHERE id = $1', [sunday.id]);
assert.ok(kept.live_ok_until); assert.equal(kept.live_ok_by, null); checks += 2;

// The word is "Sunday" or "service"; team areas are a small object.
await db.query(`UPDATE worship_settings SET service_word = 'service' WHERE business_id = $1`, [b1]);
await refuses(`UPDATE worship_settings SET service_word = 'Saturday' WHERE business_id = $1`, [b1], /worship_settings_service_word/);
await db.query(`UPDATE worship_settings SET team_areas = '{"song": "x"}' WHERE business_id = $1`, [b1]);
await refuses(`UPDATE worship_settings SET team_areas = '["song"]' WHERE business_id = $1`, [b1], /worship_settings_team_areas/);

// A post linked to its screens announcement keeps itself when the announcement goes.
const ann = await one(`INSERT INTO worship_announcements(business_id, title) VALUES ($1, 'Community Day') RETURNING id`, [b1]);
await db.query('UPDATE church_posts SET screen_announcement_id = $2 WHERE id = $1', [post.id, ann.id]);
await db.query('DELETE FROM worship_announcements WHERE id = $1', [ann.id]);
assert.equal((await one('SELECT screen_announcement_id FROM church_posts WHERE id = $1', [post.id])).screen_announcement_id, null); checks++;
await refuses('UPDATE church_posts SET screen_announcement_id = gen_random_uuid() WHERE id = $1', [post.id], /foreign key/);

// Running it again changes nothing.
await db.exec(await sql(FILE));
assert.equal((await one('SELECT service_word FROM worship_settings WHERE business_id = $1', [b1])).service_word, 'service'); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_constraint WHERE conname IN
  ('worship_settings_service_word', 'worship_settings_team_areas')`)).n, 2); checks++;

// The browser's roles read none of it.
for (const t of ['worship_services', 'serve_teams', 'worship_settings', 'church_posts']) {
  for (const role of ['anon', 'authenticated']) {
    assert.equal((await one(`SELECT has_table_privilege($1, $2, 'SELECT') AS ok`, [role, `public.${t}`])).ok, false); checks++;
  }
}

console.log(`sunday_hub_db: ${checks} checks passed`);
