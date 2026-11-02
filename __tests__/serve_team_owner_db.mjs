// Whose Sunday team it is, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-02-serve-team-owner.sql. The teams already there
// are sorted once by name (worship, production, the booth and the like are
// ChurchSavvy's; greeters, ushers, kids, parking and the rest are
// Volunteers'); a new team is Volunteers' unless it's given an owner; an
// owner is only ever one of the two, never empty; running the file again
// changes nothing, so a team a church moved by hand stays where it was put;
// the browser's roles still can't read any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/serve_team_owner_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, kind text NOT NULL, name text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const team = async name => {
  const g = await one(`INSERT INTO groups(business_id, kind, name) VALUES ($1, 'team', $2) RETURNING id`, [b1, name]);
  await db.query('INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)', [g.id, b1]);
  return g.id;
};
const ownerOf = async gid => (await one('SELECT owner FROM serve_teams WHERE group_id = $1', [gid])).owner;

// The teams a church already has, before the column.
const named = {
  'Worship Team': 'churchsavvy', 'Praise Band': 'churchsavvy', 'Choir': 'churchsavvy', 'Production': 'churchsavvy',
  'Sound & Lights': 'churchsavvy', 'Livestream': 'churchsavvy', 'Media Team': 'churchsavvy', 'Tech Booth': 'churchsavvy',
  'Slides': 'churchsavvy', 'CAMERA crew': 'churchsavvy', 'Projection': 'churchsavvy', 'Singers': 'churchsavvy',
  'Audio': 'churchsavvy', 'Music Ministry': 'churchsavvy',
  'Greeters': 'volunteers', 'Ushers': 'volunteers', 'Kids Ministry': 'volunteers', 'Parking': 'volunteers',
  'Hospitality': 'volunteers', 'Outreach': 'volunteers', 'Prayer Team': 'volunteers',
};
const ids = {};
for (const name of Object.keys(named)) ids[name] = await team(name);

await db.exec(await sql('APPLY-2026-11-02-serve-team-owner.sql'));
for (const [name, owner] of Object.entries(named)) {
  assert.equal(await ownerOf(ids[name]), owner, name); checks++;
}

// The church moves one by hand: running the file again leaves it, and every other team, as it is.
await db.query(`UPDATE serve_teams SET owner = 'volunteers' WHERE group_id = $1`, [ids.Choir]);
await db.query(`UPDATE serve_teams SET owner = 'churchsavvy' WHERE group_id = $1`, [ids.Hospitality]);
await db.exec(await sql('APPLY-2026-11-02-serve-team-owner.sql'));
assert.equal(await ownerOf(ids.Choir), 'volunteers'); checks++;
assert.equal(await ownerOf(ids.Hospitality), 'churchsavvy'); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM serve_teams WHERE owner = 'churchsavvy'`)).n, 14); checks++;

// A new team nobody gave an owner is Volunteers'; one given ChurchSavvy keeps it.
const welcome = await team('Welcome');
assert.equal(await ownerOf(welcome), 'volunteers'); checks++;
const band = await one(`INSERT INTO groups(business_id, kind, name) VALUES ($1, 'team', 'Youth Band') RETURNING id`, [b1]);
assert.equal((await one(`INSERT INTO serve_teams(group_id, business_id, owner) VALUES ($1, $2, 'churchsavvy') RETURNING owner`,
  [band.id, b1])).owner, 'churchsavvy'); checks++;

// Only the two owners, never none.
await refuses(`UPDATE serve_teams SET owner = 'production' WHERE group_id = $1`, [welcome], /check constraint/);
await refuses(`UPDATE serve_teams SET owner = NULL WHERE group_id = $1`, [welcome], /null value|not-null/);
await refuses(`UPDATE serve_teams SET owner = '' WHERE group_id = $1`, [welcome], /check constraint/);

// The browser's roles still can't read the teams, their owner included.
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT owner FROM serve_teams', [], /permission denied/);
  await refuses(`UPDATE serve_teams SET owner = 'churchsavvy'`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`serve team owner db: ${checks} checks passed`);
