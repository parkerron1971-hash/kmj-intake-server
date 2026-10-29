// Pledges and campaigns, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-pledges.sql. A campaign's dates run
// forward and its goal is real; a pledge is a total or per x periods (and
// then the total is exactly that), one per giver per campaign, only to a
// campaign of the same church; a retried save lands once; a church that
// leaves takes its campaigns and pledges with it; the browser's roles can't
// read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_pledges_db.mjs
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
const ann = '00000000-0000-4000-8000-000000000001';
const ben = '00000000-0000-4000-8000-000000000002';
const cal = '00000000-0000-4000-8000-000000000003';
const req = '00000000-0000-4000-8000-0000000000aa';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid REFERENCES public.businesses(id) ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $4), ($2, $4), ($3, $4)', [ann, ben, cal, b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-27-church-pledges.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-pledges.sql'));   // idempotent

// Campaigns: a name, a real goal, a fund, dates that run forward.
const camp = `INSERT INTO church_campaigns(business_id, name, goal_cents, fund, starts_on, ends_on)
  VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`;
const building = (await db.query(camp, [b1, 'Building fund', 25000000, 'Building', '2026-11-01', '2027-10-31'])).rows[0];
assert.equal(building.note, ''); checks++;
const other = (await db.query(camp, [b2, 'Missions', 500000, 'Missions', '2026-11-01', '2026-12-31'])).rows[0];
await refuses(camp, [b1, 'Backwards', 1000, 'Building', '2026-12-01', '2026-11-01'], /church_campaigns_dates/);
await refuses(camp, [b1, 'No goal', 0, 'Building', '2026-11-01', '2026-12-01'], /check constraint/);
await refuses(camp, [b1, '', 1000, 'Building', '2026-11-01', '2026-12-01'], /check constraint/);

// Pledges: a total, or per x periods with the total exactly that.
const pledge = `INSERT INTO church_pledges(business_id, campaign_id, contact_id, total_cents, per_period_cents, period, periods, request_id)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *`;
const one = (await db.query(pledge, [b1, building.id, ann, 520000, 10000, 'weekly', 52, req])).rows[0];
assert.equal(one.period, 'weekly'); checks++;
await refuses(pledge, [b1, building.id, ben, 520001, 10000, 'weekly', 52, null], /church_pledges_amount/);
await refuses(pledge, [b1, building.id, ben, 520000, 10000, null, 52, null], /church_pledges_amount/);
await refuses(pledge, [b1, building.id, ben, 520000, 10000, 'daily', 52, null], /check constraint/);
// One pledge per giver per campaign; a retried save lands once.
await refuses(pledge, [b1, building.id, ann, 100000, null, null, null, null], /church_pledges_one_per_giver/);
await refuses(pledge, [b1, building.id, ben, 100000, null, null, null, req], /church_pledges_request/);
await db.query(pledge, [b1, building.id, ben, 100000, null, null, null, null]);
// Only to a campaign of the same church.
await refuses(pledge, [b1, other.id, cal, 100000, null, null, null, null], /church_pledges_campaign/);
await refuses(pledge, [b2, building.id, cal, 100000, null, null, null, null], /church_pledges_campaign/);

// The browser's roles can't read or write any of it.
for (const role of ['anon', 'authenticated']) {
  for (const table of ['church_campaigns', 'church_pledges']) {
    await db.exec(`SET ROLE ${role}`);
    await assert.rejects(db.query(`SELECT * FROM ${table}`), /permission denied/); checks++;
    await db.exec('RESET ROLE');
  }
}
const rls = (await db.query(`SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('church_campaigns', 'church_pledges')`)).rows;
assert.equal(rls.length, 2); assert.ok(rls.every(r => r.relrowsecurity)); checks++;
assert.equal(Number((await db.query(`SELECT count(*) FROM pg_policies WHERE tablename IN ('church_campaigns', 'church_pledges')`)).rows[0].count), 0); checks++;

// A giver who leaves takes their pledge; a church that leaves takes everything.
await db.query('DELETE FROM contacts WHERE id = $1', [ben]);
assert.equal(Number((await db.query('SELECT count(*) FROM church_pledges WHERE business_id = $1', [b1])).rows[0].count), 1); checks++;
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['church_campaigns', 'church_pledges']) {
  assert.equal(Number((await db.query(`SELECT count(*) FROM ${table} WHERE business_id = $1`, [b1])).rows[0].count), 0); checks++;
}
console.log(`church pledges db: ${checks} checks passed`);
