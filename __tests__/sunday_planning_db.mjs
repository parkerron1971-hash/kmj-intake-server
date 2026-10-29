// ChurchSavvy Planning's tables on a real Postgres (PGlite):
// supabase/APPLY-2026-10-23-sunday-planning.sql. Rows go through every
// check: a Sunday team is a serving team (a group of kind 'team') of the
// same church, and only once; a place's name is on a team once while it's
// active, and a retired one frees the name; trained, asked, and away rows
// stay inside one church (a place, service or person from another is
// refused); an offered place has nobody on it and an asked one has someone;
// one spot holds one ask; a church or a person that leaves takes their rows;
// the browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/sunday_planning_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const team = '33333333-3333-4333-8333-333333333333';
const study = '44444444-4444-4444-8444-444444444444';
const theirs = '55555555-5555-4555-8555-555555555555';
const kendra = '66666666-6666-4666-8666-666666666666';
const jo = '77777777-7777-4777-8777-777777777777';
const outsider = '88888888-8888-4888-8888-888888888888';
const sunday = '99999999-9999-4999-8999-999999999999';
const elsewhere = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE,
    kind text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query(`INSERT INTO groups(id, business_id, kind) VALUES ($1, $4, 'team'), ($2, $4, 'group'), ($3, $5, 'team')`,
  [team, study, theirs, b1, b2]);
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $3), ($2, $3), ($4, $5)', [kendra, jo, b1, outsider, b2]);
await db.query('INSERT INTO worship_services(id, business_id) VALUES ($1, $2), ($3, $4)', [sunday, b1, elsewhere, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const count = async (table, where = 'true', args = []) =>
  (await db.query(`SELECT count(*)::int AS n FROM ${table} WHERE ${where}`, args)).rows[0].n;

await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));   // idempotent

// A Sunday team: a serving team of this church, once.
const addTeam = 'INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2) RETURNING *';
const t = (await db.query(addTeam, [team, b1])).rows[0];
assert.equal(t.max_month, 2); assert.equal(t.families, true); assert.equal(t.swap_needs_ok, false); checks += 3;
await refuses(addTeam, [team, b1], /duplicate key|unique/);
await refuses(addTeam, [study, b1], /not in this business/);          // a study group isn't a serving team
await refuses(addTeam, [theirs, b1], /not in this business/);         // another church's team
await refuses('UPDATE serve_teams SET max_month = 6 WHERE group_id = $1', [team], /check constraint/);

// Places: a name once per team while active; a retired one frees it.
const addPlace = 'INSERT INTO serve_positions(business_id, group_id, name, needed) VALUES ($1, $2, $3, $4) RETURNING *';
const sound = (await db.query(addPlace, [b1, team, 'Sound', 1])).rows[0];
const vocals = (await db.query(addPlace, [b1, team, 'Vocals', 3])).rows[0];
await refuses(addPlace, [b1, team, ' sound ', 1], /duplicate key|unique/);
await refuses(addPlace, [b1, team, '  ', 1], /check constraint/);
await refuses(addPlace, [b1, team, 'Lights', 11], /check constraint/);
await refuses(addPlace, [b2, team, 'Lights', 1], /not in this business/);
await db.query('UPDATE serve_positions SET active = false WHERE id = $1', [sound.id]);
const sound2 = (await db.query(addPlace, [b1, team, 'Sound', 1])).rows[0]; checks++;

// Trained: this church's people on this church's places.
const addTrained = 'INSERT INTO serve_trained(position_id, contact_id, business_id, level) VALUES ($1, $2, $3, $4)';
await db.query(addTrained, [sound2.id, kendra, b1, 'trained']); checks++;
await db.query(addTrained, [vocals.id, jo, b1, 'learning']); checks++;
await refuses(addTrained, [sound2.id, kendra, b1, 'trained'], /duplicate key|unique/);
await refuses(addTrained, [sound2.id, jo, b1, 'expert'], /check constraint/);
await refuses(addTrained, [sound2.id, outsider, b1, 'trained'], /not in this business/);
await refuses(addTrained, [sound2.id, outsider, b2, 'trained'], /not in this business/);

// Asks: one spot holds one; offered has nobody, asked has someone.
const addAsk = `INSERT INTO serve_assignments(business_id, service_id, position_id, slot, contact_id, status)
  VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`;
const a = (await db.query(addAsk, [b1, sunday, sound2.id, 1, kendra, 'asked'])).rows[0];
assert.equal(a.notified_at, null); assert.equal(a.answered_at, null); checks += 2;
// A new ask waits for the sweep: it's in the index the sweep reads.
assert.equal(await count('serve_assignments', `notified_at IS NULL AND status IN ('asked', 'offered')`), 1); checks++;
await refuses(addAsk, [b1, sunday, sound2.id, 1, jo, 'asked'], /duplicate key|unique/);
await db.query(addAsk, [b1, sunday, vocals.id, 2, null, 'offered']); checks++;
await refuses(addAsk, [b1, sunday, vocals.id, 1, null, 'asked'], /check constraint/);
await refuses(addAsk, [b1, sunday, vocals.id, 3, jo, 'offered'], /check constraint/);
await refuses(addAsk, [b1, sunday, vocals.id, 11, jo, 'asked'], /check constraint/);
await refuses(addAsk, [b1, sunday, vocals.id, 1, jo, 'maybe'], /check constraint/);
await refuses(addAsk, [b1, elsewhere, vocals.id, 1, jo, 'asked'], /not in this business/);
await refuses(addAsk, [b1, sunday, vocals.id, 1, outsider, 'asked'], /not in this business/);
await refuses(`UPDATE serve_assignments SET business_id = $2 WHERE id = $1`, [a.id, b2], /not in this business/);

// Away: a person of this church, the end on or after the start, a year at most.
const addAway = 'INSERT INTO serve_away(business_id, contact_id, starts_on, ends_on) VALUES ($1, $2, $3, $4)';
await db.query(addAway, [b1, jo, '2026-11-01', '2026-11-08']); checks++;
await refuses(addAway, [b1, jo, '2026-11-08', '2026-11-01'], /check constraint/);
await refuses(addAway, [b1, jo, '2026-01-01', '2027-06-01'], /check constraint/);
await refuses(addAway, [b1, outsider, '2026-11-01', '2026-11-08'], /not in this business/);

// A person who leaves takes their asks, trainings and away days with them;
// a retired place keeps who served there; a church that leaves takes it all.
await db.query('DELETE FROM contacts WHERE id = $1', [jo]);
assert.equal(await count('serve_trained', 'contact_id = $1', [jo]), 0);
assert.equal(await count('serve_away', 'contact_id = $1', [jo]), 0); checks += 2;
await db.query('UPDATE serve_positions SET active = false WHERE id = $1', [sound2.id]);
assert.equal(await count('serve_assignments', 'position_id = $1', [sound2.id]), 1); checks++;
// Stopping a team on Sundays takes its places and asks, never the group.
await db.query('DELETE FROM serve_teams WHERE group_id = $1', [team]);
assert.equal(await count('serve_positions'), 0); assert.equal(await count('serve_assignments'), 0);
assert.equal(await count('groups', 'id = $1', [team]), 1); checks += 3;
await db.query(addTeam, [team, b1]);
await db.query(addPlace, [b1, team, 'Greeter', 2]);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['serve_teams', 'serve_positions', 'serve_trained', 'serve_assignments', 'serve_away']) {
  assert.equal(await count(table), 0, table); checks++;
}

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['serve_teams', 'serve_assignments']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await db.exec('RESET ROLE');
}

console.log(`sunday_planning: ${checks} checks passed`);
