// The church register, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-register.sql. An entry's kind, status
// and source are the known words; membership says how exactly when it is
// membership; an entry names one to twelve people, who are its own
// church's; an app ask becomes one entry at most, and an imported baptism
// date comes in once per church; a deleted person or ask leaves the entry;
// a church that leaves takes its register; the browser's roles can't read
// or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_register_db.mjs
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
const b2 = '22222222-2222-4222-8222-222222222222';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);
  CREATE TABLE public.ministry_care_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-27-church-register.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-register.sql'));   // idempotent

const jordan = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const mia = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirs = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b2])).id;
const people = (...names) => JSON.stringify(names.map(n => ({ role: 'person', name: n })));
const add = `INSERT INTO church_register_entries(business_id, kind, membership, event_on, people, contact_ids)
  VALUES ($1, $2, $3, $4, $5::jsonb, $6::uuid[]) RETURNING *`;

// A baptism: done, from the office, unless it says otherwise.
const b = await one(add, [b1, 'baptism', null, '2026-10-18', people('Jordan Ellis', 'Mia Ellis'), [jordan, mia]]);
assert.equal(b.status, 'done'); assert.equal(b.source, 'office'); assert.equal(b.notes, '');
assert.equal(b.removed_at, null); checks++;
await refuses(add, [b1, 'christening', null, '2026-10-18', people('A'), []], /check constraint/);
await refuses(`UPDATE church_register_entries SET status = 'maybe' WHERE id = $1`, [b.id], /check constraint/);
await refuses(`UPDATE church_register_entries SET source = 'fax' WHERE id = $1`, [b.id], /check constraint/);
await refuses(add, [b1, 'baptism', null, null, people('A'), []], /not-null|null value/);

// Membership says how, and only membership does.
const joined = await one(add, [b1, 'membership', 'joined', '2026-09-06', people('Andre Cole'), []]);
assert.equal(joined.membership, 'joined'); checks++;
await refuses(add, [b1, 'membership', null, '2026-09-06', people('A'), []], /check constraint/);
await refuses(add, [b1, 'membership', 'left', '2026-09-06', people('A'), []], /check constraint/);
await refuses(add, [b1, 'wedding', 'joined', '2026-09-06', people('A'), []], /check constraint/);

// One to twelve people, as an array.
await refuses(add, [b1, 'funeral', null, '2026-09-12', '[]', []], /check constraint/);
await refuses(add, [b1, 'funeral', null, '2026-09-12', '{"name": "x"}', []], /check constraint/);
await refuses(add, [b1, 'baptism', null, '2026-09-12', people(...Array.from({ length: 13 }, (_, i) => `P${i}`)), []], /check constraint/);

// Its people are its own church's.
await refuses(add, [b1, 'baptism', null, '2026-10-18', people('Grace Member'), [theirs]], /not in this church/);
await refuses('UPDATE church_register_entries SET contact_ids = $2 WHERE id = $1', [b.id, [jordan, theirs]], /not in this church/);

// An ask from the member app becomes one entry at most, in its own church.
const ask = (await one('INSERT INTO ministry_care_requests(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirAsk = (await one('INSERT INTO ministry_care_requests(business_id) VALUES ($1) RETURNING id', [b2])).id;
const adopt = `INSERT INTO church_register_entries(business_id, kind, status, event_on, people, source, care_request_id)
  VALUES ($1, 'dedication', 'planned', '2026-11-15', '[{"role":"child","name":"Noah Price"}]', 'app', $2)`;
await db.query(adopt, [b1, ask]); checks++;
await refuses(adopt, [b1, ask], /duplicate key|unique/);
const again = await db.query(`${adopt} ON CONFLICT (care_request_id) DO NOTHING RETURNING id`, [b1, ask]);
assert.equal(again.rows.length, 0, 'two presses at once make one entry'); checks++;
await refuses(adopt, [b1, theirAsk], /not in this church/);

// An imported baptism date comes in once per church (and other churches have their own).
const imp = `INSERT INTO church_register_entries(business_id, kind, event_on, people, source, import_key)
  VALUES ($1, 'baptism', '2019-04-21', '[{"role":"person","name":"Dana"}]', 'import', $2)`;
await db.query(imp, [b1, 'subsplash-baptism:x']); checks++;
await refuses(imp, [b1, 'subsplash-baptism:x'], /duplicate key|unique/);
const twice = await db.query(`${imp} ON CONFLICT (business_id, import_key) DO NOTHING RETURNING id`, [b1, 'subsplash-baptism:x']);
assert.equal(twice.rows.length, 0); checks++;
await db.query(imp, [b2, 'subsplash-baptism:x']); checks++;
// Entries without a key are many.
await db.query(add, [b1, 'wedding', null, '2026-10-10', '[{"role":"spouse","name":"A"},{"role":"spouse","name":"B"}]', []]);
await db.query(add, [b1, 'wedding', null, '2026-10-11', '[{"role":"spouse","name":"C"},{"role":"spouse","name":"D"}]', []]); checks++;

// A person's page finds their milestones by id.
const mine = await db.query('SELECT id FROM church_register_entries WHERE business_id = $1 AND contact_ids @> ARRAY[$2]::uuid[]', [b1, mia]);
assert.equal(mine.rows.length, 1); checks++;

// Removing is a mark: the entry stays, and a removed entry can still be edited by the server.
await db.query('UPDATE church_register_entries SET removed_at = now() WHERE id = $1', [joined.id]);
assert.ok((await one('SELECT removed_at FROM church_register_entries WHERE id = $1', [joined.id])).removed_at); checks++;

// A deleted person or ask leaves the entry (its names stay as recorded).
await db.query('DELETE FROM contacts WHERE id = $1', [mia]);
assert.equal((await one('SELECT jsonb_array_length(people) AS n FROM church_register_entries WHERE id = $1', [b.id])).n, 2); checks++;
await db.query('DELETE FROM ministry_care_requests WHERE id = $1', [ask]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_register_entries WHERE source = 'app' AND care_request_id IS NULL`)).n, 1); checks++;
// …and the server can still save the entry once the dead id is dropped.
await db.query('UPDATE church_register_entries SET contact_ids = $2 WHERE id = $1', [b.id, [jordan]]); checks++;

// A church that leaves takes its register; the other keeps its own.
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_register_entries WHERE business_id = $1', [b1])).n, 0); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM church_register_entries WHERE business_id = $1', [b2])).n, 1); checks++;

// Server-only: RLS on, no policies, and the browser's roles get nothing.
const t = await one(`SELECT relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies WHERE tablename = $1) AS policies
  FROM pg_class WHERE relname = $1`, ['church_register_entries']);
assert.equal(t.rls, true); assert.equal(t.policies, 0); checks++;
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM church_register_entries', [], /permission denied/);
  await refuses(`INSERT INTO church_register_entries(business_id, kind, event_on, people) VALUES ('${b2}', 'baptism', '2026-01-01', '[{"name":"x"}]')`,
    [], /permission denied/);
  await refuses(`UPDATE church_register_entries SET notes = 'x'`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church register: ${checks} checks passed`);
