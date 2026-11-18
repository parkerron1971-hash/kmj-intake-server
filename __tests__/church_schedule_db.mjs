// The leaders schedule, step 1, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-19-church-schedule.sql over the Who-serves-when
// files that made serve_away. Running it twice changes nothing, with rows
// already there; serve_away's old rows read as before and its two new rules
// go in NOT VALID and still refuse; church_away_settle is the one decision
// (a yes writes exactly one fact naming the ask, with its kind and an empty
// note; a second answer changes nothing; no leaves none; withdrawn takes the
// fact off; another church's id gets null; a bad state raises); a fact names
// only its own person's ask; one waiting ask a person a set of days; everyone
// an ask, a commitment or the add list names is the church's own; a person or
// a church deleted takes their rows and a login deleted leaves the ask; every
// new table and function is server-only.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_schedule_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const FILE = await sql('APPLY-2026-11-19-church-schedule.sql');
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const u2 = 'aaaaaaaa-2222-4222-8222-222222222222';
const leader = 'cccccccc-1111-4111-8111-111111111111';     // asks
const over = 'cccccccc-3333-4333-8333-333333333333';       // the person over them
const cover = 'cccccccc-4444-4444-8444-444444444444';      // who covers
const other = 'cccccccc-5555-4555-8555-555555555555';      // another leader, same church
const outsider = 'cccccccc-2222-4222-8222-222222222222';   // the other church's
const d1 = 'dddddddd-1111-4111-8111-111111111111';
const d2 = 'dddddddd-2222-4222-8222-222222222222';
const nobody = 'eeeeeeee-9999-4999-8999-999999999999';
const TABLES = ['church_schedule_settings', 'church_schedule_people', 'church_away_asks', 'church_away_commitments'];
const SETTLE = 'public.church_away_settle(uuid, uuid, text, uuid, uuid, text)';

// What Supabase already has: the three roles, and its habit of handing every
// new table and function in public to all three (so the file's own revokes
// are what keep the browser out); auth.users, businesses, contacts, the
// map's departments, and Who serves when (which makes serve_away and its own
// one-church trigger).
const stand = async () => {
  const db = new PGlite();
  await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
    CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
    CREATE TABLE public.businesses(id uuid PRIMARY KEY);
    CREATE TABLE public.contacts(id uuid PRIMARY KEY,
      business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE);
    CREATE TABLE public.groups(id uuid PRIMARY KEY,
      business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, kind text NOT NULL);
    CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
      business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE);
    CREATE TABLE public.church_departments(id uuid PRIMARY KEY,
      business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, name text);`);
  await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
  await db.exec(await sql('APPLY-2026-10-23-serving-member.sql'));
  await db.query('INSERT INTO businesses VALUES ($1), ($2)', [b1, b2]);
  await db.query('INSERT INTO auth.users VALUES ($1), ($2)', [u1, u2]);
  await db.query('INSERT INTO contacts VALUES ($1, $6), ($2, $6), ($3, $6), ($4, $6), ($5, $7)',
    [leader, over, cover, other, outsider, b1, b2]);
  await db.query(`INSERT INTO church_departments VALUES ($1, $2, 'Youth'), ($3, $4, 'Youth')`, [d1, b1, d2, b2]);
  return db;
};

let db = await stand();
let checks = 0;
const one = async (text, args = []) => (await db.query(text, args)).rows[0];
const n = async (text, args = []) => (await one(`SELECT count(*)::int AS n FROM ${text}`, args)).n;
const ok = async (text, args) => { await db.query(text, args); checks++; };
const same = (got, want) => { assert.deepEqual(got, want); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
// An ask, as the server will write one: asked, nothing decided.
const ask = async (biz, who, from, to, more = {}) => {
  const row = { business_id: biz, contact_id: who, grp: 'leaders', kind: 'time_off', starts_on: from, ends_on: to, ...more };
  const keys = Object.keys(row);
  return (await one(`INSERT INTO church_away_asks(${keys.join(', ')})
    VALUES (${keys.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING id`, keys.map(k => row[k]))).id;
};
const settle = async (biz, id, state, by = {}) =>
  (await one(`SELECT ${SETTLE.split('(')[0]}($1, $2, $3, $4, $5, $6) AS r`,
    [biz, id, state, by.user ?? null, by.contact ?? null, by.note ?? null])).r;
const facts = id => n('serve_away WHERE ask_id = $1', [id]);
const state = async id => (await one('SELECT state FROM church_away_asks WHERE id = $1', [id])).state;
// Everything the file makes or touches, as the catalog holds it.
const catalog = async () => (await one(`SELECT jsonb_build_object(
  'columns', (SELECT jsonb_agg(jsonb_build_array(table_name, column_name, data_type, is_nullable, column_default)
                ORDER BY table_name, ordinal_position) FROM information_schema.columns WHERE table_schema = 'public'),
  'constraints', (SELECT jsonb_agg(jsonb_build_array(conrelid::regclass::text, conname, pg_get_constraintdef(oid), convalidated)
                    ORDER BY conrelid::regclass::text, conname) FROM pg_constraint WHERE connamespace = 'public'::regnamespace),
  'indexes', (SELECT jsonb_agg(indexdef ORDER BY indexname) FROM pg_indexes WHERE schemaname = 'public'),
  'triggers', (SELECT jsonb_agg(jsonb_build_array(tgrelid::regclass::text, tgname, pg_get_triggerdef(oid))
                 ORDER BY tgrelid::regclass::text, tgname) FROM pg_trigger WHERE NOT tgisinternal),
  'functions', (SELECT jsonb_agg(jsonb_build_array(p.oid::regprocedure::text, md5(pg_get_functiondef(p.oid)), p.proacl::text)
                  ORDER BY p.oid::regprocedure::text) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace),
  'tables', (SELECT jsonb_agg(jsonb_build_array(relname, relrowsecurity, relacl::text, obj_description(oid, 'pg_class'))
               ORDER BY relname) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'),
  'column_notes', (SELECT jsonb_agg(jsonb_build_array(c.relname, a.attname, col_description(c.oid, a.attnum))
                     ORDER BY c.relname, a.attnum) FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
                    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND a.attnum > 0
                      AND col_description(c.oid, a.attnum) IS NOT NULL),
  'policies', (SELECT count(*) FROM pg_policies)) AS s`)).s;

// An away date from before the file: it reads as it always did afterwards.
await db.query(`INSERT INTO serve_away(business_id, contact_id, starts_on, ends_on) VALUES ($1, $2, '2027-03-01', '2027-03-07')`,
  [b1, other]);

await db.exec(FILE);
const before = await catalog();
assert.ok(JSON.stringify(before).includes('church_away_settle')); checks++;
same(await one(`SELECT ask_id, kind, note, starts_on::text, ends_on::text FROM serve_away`),
  { ask_id: null, kind: null, note: '', starts_on: '2027-03-01', ends_on: '2027-03-07' });

// ─── One decision: yes ──────────────────────────────────────────────────
const a1 = await ask(b1, leader, '2027-01-08', '2027-01-15',
  { reason: 'A private reason', to_contact_id: over, cover_contact_id: cover, department_id: d1 });
same(await one(`SELECT state, flags, decided_at, withdrawn_at, told_at FROM church_away_asks WHERE id = $1`, [a1]),
  { state: 'asked', flags: [], decided_at: null, withdrawn_at: null, told_at: null });
let r = await settle(b1, a1, 'yes', { contact: over, note: '  Enjoy it.  ' });
same([r.changed, r.ask.id, r.ask.state, r.ask.decided_by_contact_id, r.ask.decided_by_user_id, r.ask.decided_note,
  r.ask.decided_at !== null, r.ask.withdrawn_at], [true, a1, 'yes', over, null, 'Enjoy it.', true, null]);
// Exactly one fact: the ask's person, days and kind, an empty note, never the reason.
same((await db.query(`SELECT business_id, contact_id, starts_on::text, ends_on::text, note, ask_id, kind
  FROM serve_away WHERE ask_id IS NOT NULL`)).rows,
  [{ business_id: b1, contact_id: leader, starts_on: '2027-01-08', ends_on: '2027-01-15', note: '', ask_id: a1, kind: 'time_off' }]);
same(await n(`serve_away WHERE note <> ''`), 0);

// Twice, with rows there: nothing changes, nothing fails, nothing is lost.
await db.exec(FILE);
same(await catalog(), before);
same([await n('serve_away'), await n('church_away_asks'), await facts(a1), await state(a1)], [2, 1, 1, 'yes']);

// A second yes, or a no after the yes: changed false, and no second fact.
r = await settle(b1, a1, 'yes', { user: u1 });
same([r.changed, r.ask.state, r.ask.decided_by_user_id, r.ask.decided_by_contact_id], [false, 'yes', null, over]);
r = await settle(b1, a1, 'no', { user: u1 });
same([r.changed, r.ask.state, await facts(a1)], [false, 'yes', 1]);

// The two rules on serve_away went in NOT VALID, once each, and still refuse.
const cons = (await db.query(`SELECT conname, convalidated FROM pg_constraint WHERE conrelid = 'public.serve_away'::regclass
  AND conname IN ('serve_away_ask_id_fkey', 'serve_away_kind') ORDER BY conname`)).rows;
same(cons, [{ conname: 'serve_away_ask_id_fkey', convalidated: false }, { conname: 'serve_away_kind', convalidated: false }]);
const away = `INSERT INTO serve_away(business_id, contact_id, starts_on, ends_on, ask_id, kind) VALUES ($1, $2, $3, $4, $5, $6)`;
await refuses(away, [b1, other, '2027-04-01', '2027-04-02', null, 'holiday'], /serve_away_kind/);
await ok(away, [b1, other, '2027-04-01', '2027-04-02', null, null]);          // a plain away date, as always

// ─── One decision: no ───────────────────────────────────────────────────
const a2 = await ask(b1, leader, '2027-02-01', '2027-02-03', { to_user_id: u1 });
r = await settle(b1, a2, 'no', { user: u1, note: '   ' });
same([r.changed, r.ask.state, r.ask.decided_by_user_id, r.ask.decided_note, r.ask.decided_at !== null, await facts(a2)],
  [true, 'no', u1, null, true, 0]);
r = await settle(b1, a2, 'yes', { user: u1 });                                 // a no is not answered again
same([r.changed, r.ask.state, await facts(a2)], [false, 'no', 0]);
r = await settle(b1, a2, 'withdrawn');                                         // and can't be withdrawn
same([r.changed, r.ask.state, r.ask.withdrawn_at], [false, 'no', null]);
const a3 = await ask(b1, leader, '2027-02-10', '2027-02-11');
r = await settle(b1, a3, 'no', { user: u1, note: 'x'.repeat(400) });
same([r.changed, r.ask.decided_note.length], [true, 300]);

// ─── One decision: withdrawn ────────────────────────────────────────────
const a4 = await ask(b1, leader, '2027-05-01', '2027-05-02');                  // from asked
r = await settle(b1, a4, 'withdrawn');
same([r.changed, r.ask.state, r.ask.withdrawn_at !== null, r.ask.decided_at, await facts(a4)],
  [true, 'withdrawn', true, null, 0]);
r = await settle(b1, a4, 'withdrawn');
same([r.changed, r.ask.state], [false, 'withdrawn']);
r = await settle(b1, a4, 'yes', { user: u1 });                                 // an answer after a withdraw
same([r.changed, r.ask.state, await facts(a4)], [false, 'withdrawn', 0]);
r = await settle(b1, a1, 'withdrawn');                                         // from yes: the fact goes
same([r.changed, r.ask.state, r.ask.withdrawn_at !== null, r.ask.decided_at !== null, r.ask.decided_by_contact_id,
  await facts(a1)], [true, 'withdrawn', true, true, over, 0]);
same(await n('serve_away'), 2);                                                // the plain away dates stay

// ─── Not this church's, not there, not a state ──────────────────────────
const a5 = await ask(b1, leader, '2027-06-01', '2027-06-02');
same(await settle(b2, a5, 'yes', { user: u1 }), null);                         // another church's id
same(await settle(b1, nobody, 'yes', { user: u1 }), null);                     // no such ask
same([await state(a5), await facts(a5)], ['asked', 0]);
for (const bad of ['maybe', 'asked', 'YES', '']) {
  await refuses(`SELECT ${SETTLE.split('(')[0]}($1, $2, $3)`, [b1, a5, bad], /answered yes or no, or withdrawn/);
}
await refuses(`SELECT ${SETTLE.split('(')[0]}($1, $2, null)`, [b1, a5], /answered yes or no, or withdrawn/);
// Answered by a login or by a person, never both; and the person is the church's own.
await refuses(`SELECT ${SETTLE.split('(')[0]}($1, $2, 'yes', $3, $4)`, [b1, a5, u1, over], /church_away_asks_by_one/);
await refuses(`SELECT ${SETTLE.split('(')[0]}($1, $2, 'yes', null, $3)`, [b1, a5, outsider], /who answered is not in this church/);
await refuses(`SELECT ${SETTLE.split('(')[0]}($1, $2, 'yes', $3)`, [b1, a5, nobody], /foreign key/);
same([await state(a5), await facts(a5)], ['asked', 0]);                        // a refused answer wrote nothing

// "Can't make it" is a yes nobody gave: the fact carries the kind.
const a6 = await ask(b1, leader, '2027-06-10', '2027-06-10', { kind: 'cant', flags: ['short_notice'] });
r = await settle(b1, a6, 'yes');
same([r.changed, r.ask.decided_by_user_id, r.ask.decided_by_contact_id, r.ask.decided_at !== null],
  [true, null, null, true]);
same(await one('SELECT kind, note FROM serve_away WHERE ask_id = $1', [a6]), { kind: 'cant', note: '' });
// A fact already there for the ask (a retry): the yes still lands, and there is still one.
await ok(away, [b1, leader, '2027-06-01', '2027-06-02', a5, 'time_off']);
r = await settle(b1, a5, 'yes', { user: u1 });
same([r.changed, r.ask.state, await facts(a5)], [true, 'yes', 1]);

// ─── A fact names only its own person's ask ─────────────────────────────
const a7 = await ask(b1, leader, '2027-07-01', '2027-07-02');
const theirs = await ask(b2, outsider, '2027-07-01', '2027-07-02', { to_user_id: u1 });
await refuses(away, [b1, other, '2027-07-01', '2027-07-02', a7, 'time_off'], /not this person's/);       // another person's
await refuses(away, [b1, leader, '2027-07-01', '2027-07-02', theirs, 'time_off'], /not this person's/);  // another church's
await refuses(away, [b2, outsider, '2027-07-01', '2027-07-02', a7, 'time_off'], /not this person's/);
await refuses(away, [b1, leader, '2027-07-01', '2027-07-02', nobody, 'time_off'], /not this person's/);
await refuses(`UPDATE serve_away SET ask_id = $1 WHERE contact_id = $2 AND ask_id IS NULL`, [a7, other], /not this person's/);
await refuses(`UPDATE serve_away SET contact_id = $1 WHERE ask_id = $2`, [other, a5], /not this person's/);
await refuses(away, [b1, leader, '2027-06-01', '2027-06-02', a5, 'time_off'], /serve_away_one_per_ask/);  // one fact an ask
await ok(`UPDATE serve_away SET note = 'x' WHERE ask_id IS NULL AND starts_on = '2027-04-01'`);          // other writes pass
await ok(`UPDATE serve_away SET note = '' WHERE note = 'x'`);

// ─── One waiting ask a person a set of days ─────────────────────────────
await refuses(`INSERT INTO church_away_asks(business_id, contact_id, grp, kind, starts_on, ends_on)
  VALUES ($1, $2, 'leaders', 'commitment', '2027-07-01', '2027-07-02')`, [b1, leader], /church_away_asks_one_open/);
await ask(b1, leader, '2027-07-01', '2027-07-03');                             // other days
await ask(b1, other, '2027-07-01', '2027-07-02'); checks += 2;                 // another person
await settle(b1, a7, 'no', { user: u1 });
await ask(b1, leader, '2027-07-01', '2027-07-02'); checks++;                   // answered: the days can be asked again

// ─── What an ask may hold ───────────────────────────────────────────────
const put = (more, who = leader, biz = b1) => {
  const row = { business_id: biz, contact_id: who, grp: 'leaders', kind: 'time_off', starts_on: '2027-08-01',
    ends_on: '2027-08-02', ...more };
  const keys = Object.keys(row);
  return [`INSERT INTO church_away_asks(${keys.join(', ')}) VALUES (${keys.map((_, i) => `$${i + 1}`).join(', ')})`,
    keys.map(k => row[k])];
};
await refuses(...put({}, outsider), /That person is not in this church/);
await refuses(...put({ cover_contact_id: outsider }), /person covering is not in this church/);
await refuses(...put({ to_contact_id: outsider }), /person it goes to is not in this church/);
await refuses(...put({ department_id: d2 }), /department is not in this church/);
await refuses(...put({ cover_contact_id: leader }), /church_away_asks_cover_other/);
await refuses(...put({ to_user_id: u1, to_contact_id: over }), /church_away_asks_to_one/);
await refuses(...put({ ends_on: '2027-07-31' }), /church_away_asks_days/);
await refuses(...put({ ends_on: '2028-08-03' }), /church_away_asks_days/);
await refuses(...put({ kind: 'holiday' }), /check constraint/);
await refuses(...put({ grp: 'everyone' }), /check constraint/);
await refuses(...put({ reason: 'r'.repeat(501) }), /check constraint/);
await refuses(...put({ cover_name: '   ' }), /check constraint/);
await refuses(...put({ flags: ['short_notice', 'made_up'] }), /check constraint/);
// A state and its marks agree, whoever writes the row.
await refuses(...put({ state: 'yes' }), /church_away_asks_decided/);
await refuses(...put({ state: 'no' }), /church_away_asks_decided/);
await refuses(...put({ decided_at: '2027-01-01T00:00:00Z' }), /church_away_asks_decided/);
await refuses(...put({ state: 'withdrawn' }), /church_away_asks_decided/);
await refuses(...put({ withdrawn_at: '2027-01-01T00:00:00Z' }), /church_away_asks_decided/);
await refuses(...put({ state: 'yes', decided_at: '2027-01-01T00:00:00Z', withdrawn_at: '2027-01-02T00:00:00Z' }),
  /church_away_asks_decided/);
const [full, values] = put({ reason: 'r'.repeat(500), cover_name: 'A friend', to_contact_id: over, department_id: d1,
  flags: ['short_notice', 'over_limit', 'protected_day', 'pair', 'serving'] });
const a8 = (await one(`${full} RETURNING id`, values)).id; checks++;
// It stays with its church and its person; who it names later is the church's own too.
await refuses(`UPDATE church_away_asks SET business_id = $1 WHERE id = $2`, [b2, a8], /stays with its church and its person/);
await refuses(`UPDATE church_away_asks SET contact_id = $1 WHERE id = $2`, [other, a8], /stays with its church and its person/);
await refuses(`UPDATE church_away_asks SET cover_contact_id = $1 WHERE id = $2`, [outsider, a8], /person covering is not in this church/);
await refuses(`UPDATE church_away_asks SET to_contact_id = $1 WHERE id = $2`, [outsider, a8], /person it goes to is not in this church/);
await refuses(`UPDATE church_away_asks SET department_id = $1 WHERE id = $2`, [d2, a8], /department is not in this church/);
await ok(`UPDATE church_away_asks SET to_contact_id = null, to_user_id = $1, told_at = now(), nudged_at = now() WHERE id = $2`,
  [u2, a8]);                                                                   // re-addressed to a login

// ─── The add list, the remove list, the notice days, what repeats ───────
const list = `INSERT INTO church_schedule_people(business_id, contact_id, listed, grp, set_by) VALUES ($1, $2, $3, $4, $5)`;
await ok(list, [b1, cover, 'add', 'office', u2]);
await ok(list, [b1, other, 'remove', null, u2]);
await refuses(list, [b1, cover, 'remove', null, u1], /duplicate key/);          // one row a person
await refuses(list, [b1, over, 'add', null, u1], /church_schedule_people_group/);
await refuses(list, [b1, over, 'remove', 'leaders', u1], /church_schedule_people_group/);
await refuses(list, [b1, over, 'add', 'volunteers', u1], /check constraint/);
await refuses(list, [b1, outsider, 'add', 'leaders', u1], /That person is not in this church/);
await refuses(`UPDATE church_schedule_people SET business_id = $1 WHERE contact_id = $2`, [b2, cover], /stays with its church/);
await refuses(`UPDATE church_schedule_people SET contact_id = $1 WHERE contact_id = $2`, [outsider, cover],
  /That person is not in this church/);
await ok(`INSERT INTO church_schedule_settings(business_id, updated_by) VALUES ($1, $2)`, [b1, u2]);
same((await one(`SELECT notice_days FROM church_schedule_settings WHERE business_id = $1`, [b1])).notice_days, 14);
await refuses(`INSERT INTO church_schedule_settings(business_id) VALUES ($1)`, [b1], /duplicate key/);
await refuses(`UPDATE church_schedule_settings SET notice_days = 91`, [], /check constraint/);
await refuses(`UPDATE church_schedule_settings SET notice_days = -1`, [], /check constraint/);
await ok(`UPDATE church_schedule_settings SET notice_days = 0`, []);
const often = `INSERT INTO church_away_commitments(business_id, contact_id, label, weekday, pattern, nth, starts_on, until_on)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`;
await ok(often, [b1, leader, 'Work', 6, 'weekly', null, '2027-01-04', null]);                 // any start
await ok(often, [b1, leader, 'Work', 6, 'every_other', null, '2027-01-02', '2027-12-31']);    // a Saturday
await ok(often, [b1, leader, 'Board', 2, 'month_nth', 5, '2027-01-01', null]);                // the last Tuesday
await refuses(often, [b1, leader, 'Work', 6, 'every_other', null, '2027-01-03', null], /church_away_commitments_anchor/);
await refuses(often, [b1, leader, 'Board', 2, 'month_nth', null, '2027-01-01', null], /church_away_commitments_nth/);
await refuses(often, [b1, leader, 'Work', 6, 'weekly', 2, '2027-01-01', null], /church_away_commitments_nth/);
await refuses(often, [b1, leader, 'Board', 2, 'month_nth', 6, '2027-01-01', null], /check constraint/);
await refuses(often, [b1, leader, 'Work', 8, 'weekly', null, '2027-01-01', null], /check constraint/);
await refuses(often, [b1, leader, 'Work', 6, 'daily', null, '2027-01-01', null], /check constraint/);
await refuses(often, [b1, leader, '  ', 6, 'weekly', null, '2027-01-01', null], /check constraint/);
await refuses(often, [b1, leader, 'Work', 6, 'weekly', null, '2027-01-08', '2027-01-01'], /church_away_commitments_until/);
await refuses(often, [b1, outsider, 'Work', 6, 'weekly', null, '2027-01-01', null], /That person is not in this church/);
await refuses(`UPDATE church_away_commitments SET business_id = $1`, [b2], /stays with its church/);

// ─── Server-only ────────────────────────────────────────────────────────
for (const t of TABLES) {
  const row = await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policies,
      (SELECT bool_or(has_table_privilege(r, c.oid, p)) FROM unnest(array['anon', 'authenticated']) r,
         unnest(array['select', 'insert', 'update', 'delete', 'truncate', 'references', 'trigger']) p) AS browser,
      (SELECT bool_and(has_table_privilege('service_role', c.oid, p))
         FROM unnest(array['select', 'insert', 'update', 'delete']) p) AS server
    FROM pg_class c WHERE c.oid = $1::regclass`, [`public.${t}`]);
  same(row, { rls: true, policies: 0, browser: false, server: true });
}
const fns = (await db.query(`SELECT p.oid::regprocedure::text AS f, has_function_privilege('anon', p.oid, 'execute') AS anon,
    has_function_privilege('authenticated', p.oid, 'execute') AS authed
  FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname IN ('church_away_settle',
    'church_away_asks_same_business', 'serve_away_ask_guard', 'church_schedule_person_same_business') ORDER BY 1`)).rows;
same(fns.map(f => [f.f.replace('public.', '').split('(')[0], f.anon, f.authed]), [['church_away_asks_same_business', false, false],
  ['church_away_settle', false, false], ['church_schedule_person_same_business', false, false],
  ['serve_away_ask_guard', false, false]]);
same((await one(`SELECT count(*)::int AS n FROM pg_proc WHERE proname = 'church_away_settle'`)).n, 1);   // never two to choose between
same((await one(`SELECT has_function_privilege('service_role', '${SETTLE}', 'execute') AS can`)).can, true);
const a9 = await ask(b1, other, '2027-09-01', '2027-09-02');
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  try {
    for (const t of TABLES) await refuses(`SELECT * FROM ${t}`, [], /permission denied/);
    await refuses(`INSERT INTO church_away_asks(business_id, contact_id, grp, kind, starts_on, ends_on)
      VALUES ($1, $2, 'leaders', 'cant', '2027-09-09', '2027-09-09')`, [b1, other], /permission denied/);
    await refuses(`SELECT ${SETTLE.split('(')[0]}($1, $2, 'yes')`, [b1, a9], /permission denied for function/);
  } finally { await db.exec('RESET ROLE'); }
}
await db.exec('SET ROLE service_role');                                          // the server's own role can
try {
  r = await settle(b1, a9, 'yes', { user: u1 });
  same([r.changed, r.ask.state, await facts(a9)], [true, 'yes', 1]);
} finally { await db.exec('RESET ROLE'); }

// ─── What goes with what ────────────────────────────────────────────────
// A login deleted leaves the ask, with nobody in its place.
const a10 = await ask(b1, other, '2027-10-01', '2027-10-02', { made_by: u2, to_user_id: u2 });
await settle(b1, a10, 'yes', { user: u2 });
await ok('DELETE FROM auth.users WHERE id = $1', [u2]);
same(await one(`SELECT state, made_by, to_user_id, decided_by_user_id, decided_at IS NOT NULL AS decided
  FROM church_away_asks WHERE id = $1`, [a10]), { state: 'yes', made_by: null, to_user_id: null, decided_by_user_id: null, decided: true });
same([await facts(a10), (await one('SELECT to_user_id FROM church_away_asks WHERE id = $1', [a8])).to_user_id], [1, null]);
same(await one(`SELECT (SELECT count(*)::int FROM church_schedule_people WHERE set_by IS NULL) AS listed,
  (SELECT updated_by FROM church_schedule_settings WHERE business_id = $1) AS updated_by`, [b1]), { listed: 2, updated_by: null });
// A department deleted, or the person covering, or the person it went to: the ask stays.
const a11 = await ask(b1, other, '2027-11-01', '2027-11-02',
  { to_contact_id: over, cover_contact_id: cover, department_id: d1 });
const a12 = await ask(b1, leader, '2027-11-01', '2027-11-02', { to_contact_id: over });
await settle(b1, a12, 'yes', { contact: over });
await ok('DELETE FROM church_departments WHERE id = $1', [d1]);
await ok('DELETE FROM contacts WHERE id = $1', [cover]);
await ok('DELETE FROM contacts WHERE id = $1', [over]);
same(await one(`SELECT state, department_id, cover_contact_id, to_contact_id FROM church_away_asks WHERE id = $1`, [a11]),
  { state: 'asked', department_id: null, cover_contact_id: null, to_contact_id: null });
same(await one(`SELECT state, decided_by_contact_id, to_contact_id FROM church_away_asks WHERE id = $1`, [a12]),
  { state: 'yes', decided_by_contact_id: null, to_contact_id: null });
same([await facts(a12), await n('church_schedule_people WHERE contact_id = $1', [cover])], [1, 0]);
// An ask deleted by hand leaves its fact as a plain away date.
await ok('DELETE FROM church_away_asks WHERE id = $1', [a10]);
same(await n(`serve_away WHERE contact_id = $1 AND starts_on = '2027-10-01' AND ask_id IS NULL`, [other]), 1);
// A person deleted takes their asks, their facts and what repeats; nobody else's.
assert.ok(await n('church_away_asks WHERE contact_id = $1', [leader]) >= 5); checks++;
assert.ok(await n('serve_away WHERE contact_id = $1', [leader]) >= 3); checks++;
const others = await n('church_away_asks WHERE contact_id <> $1', [leader]);
await ok('DELETE FROM contacts WHERE id = $1', [leader]);
same([await n('church_away_asks WHERE contact_id = $1', [leader]), await n('serve_away WHERE contact_id = $1', [leader]),
  await n('church_away_commitments'), await n('church_away_asks'), await n('serve_away WHERE ask_id IS NOT NULL')],
  [0, 0, 0, others, 1]);
// A church deleted takes everything of its own; the other church keeps its ask.
await ok(`INSERT INTO church_schedule_settings(business_id, notice_days) VALUES ($1, 21)`, [b2]);
await ok(often, [b1, other, 'Work', 6, 'weekly', null, '2027-01-04', null]);
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
same([await n('church_away_asks'), await state(theirs), await n('serve_away'), await n('church_schedule_people'),
  await n('church_away_commitments'), await n('church_schedule_settings')], [1, 'asked', 0, 0, 0, 1]);
await db.close();

// ─── The same deletes when the ask happens to go before its fact ────────
// Postgres fires a delete's foreign keys in the order of their trigger
// names. Above, a person's facts went before their asks; here serve_away's
// own keys are made after the ask tables', so an approved ask is deleted
// before its fact is: the person and the church still go, taking both.
const fired = async () => (await db.query(`SELECT c.conrelid::regclass::text AS t
  FROM pg_trigger g JOIN pg_constraint c ON c.oid = g.tgconstraint
  WHERE g.tgrelid = 'public.contacts'::regclass AND g.tgtype & 8 = 8 AND c.confdeltype = 'c'
    AND c.conrelid IN ('public.serve_away'::regclass, 'public.church_away_asks'::regclass) ORDER BY g.tgname`)).rows.map(x => x.t);
db = await stand();
const keys = (await db.query(`SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint
  WHERE conrelid = 'public.serve_away'::regclass AND contype = 'f'`)).rows;
same(keys.length, 2);
for (const k of keys) await db.exec(`ALTER TABLE public.serve_away DROP CONSTRAINT ${k.conname}`);
await db.exec(FILE);
for (const k of keys) await db.exec(`ALTER TABLE public.serve_away ADD CONSTRAINT ${k.conname} ${k.def}`);
same(await fired(), ['church_away_asks', 'serve_away']);
for (const who of [leader, other]) {
  const id = await ask(b1, who, '2027-01-08', '2027-01-15', { to_contact_id: over });
  await settle(b1, id, 'yes', { contact: over });
}
same(await n('serve_away WHERE ask_id IS NOT NULL'), 2);
await ok('DELETE FROM contacts WHERE id = $1', [leader]);
same([await n('church_away_asks'), await n('serve_away')], [1, 1]);
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
same([await n('church_away_asks'), await n('serve_away')], [0, 0]);
await db.close();

console.log(`church schedule db: ${checks} checks passed`);
