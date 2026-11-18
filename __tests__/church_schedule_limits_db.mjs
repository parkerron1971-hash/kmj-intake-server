// The leaders schedule, step 2, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-20-church-schedule-limits.sql over step 1's file
// (APPLY-2026-11-19-church-schedule.sql), with step 1 already in use.
//
// What it pins:
//   - Nothing live moves. church_away_settle is the same function after the
//     file as before it (same id, same body, same grants); every ask, away
//     date and setting reads as it did; the calls and writes the deployed
//     code makes still work, in a session that had already used the function.
//   - One function a name. The six-name call (church_away_settle) and the
//     seven-name call (church_away_settle_excepted) both work, by named
//     arguments as PostgREST sends them; neither name is overloaded however
//     often, and in whatever order, the two files are run.
//   - The new function answers exactly as the old one for every decision,
//     and saves the exception only on a yes it just made; a bad exception is
//     refused by name and undoes the yes.
//   - Every constraint and trigger in the file: refused by a bad row,
//     accepted by a good one; another church's department, person or team is
//     refused.
//   - Twice is a no-op. The file's own Check block answers as it says, and
//     its Rollback block puts the catalog back as step 1 left it.
//   - Server-only: the three tables and both new functions.
//   - A person, a login, a department, a team or a church deleted takes what
//     it should and is never refused, in either order the foreign keys fire.
//   - The two ways not taken (an overload; drop and re-make) fail the way the
//     file's header says.
//   - Step 1's own check, not a line of it changed, passes with this file
//     applied straight after every run of step 1's.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_schedule_limits_db.mjs
import { pathToFileURL, fileURLToPath } from 'node:url';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const STEP1 = await sql('APPLY-2026-11-19-church-schedule.sql');
const FILE = await sql('APPLY-2026-11-20-church-schedule-limits.sql');
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const u2 = 'aaaaaaaa-2222-4222-8222-222222222222';
const leader = 'cccccccc-1111-4111-8111-111111111111';     // asks
const over = 'cccccccc-3333-4333-8333-333333333333';       // the person over them
const cover = 'cccccccc-4444-4444-8444-444444444444';      // who covers
const other = 'cccccccc-5555-4555-8555-555555555555';      // another leader, same church
const outsider = 'cccccccc-2222-4222-8222-222222222222';   // the other church's
const outsider2 = 'cccccccc-6666-4666-8666-666666666666';  // the other church's, a second person
const d1 = 'dddddddd-1111-4111-8111-111111111111';
const d1b = 'dddddddd-3333-4333-8333-333333333333';        // a second department, same church
const d2 = 'dddddddd-2222-4222-8222-222222222222';
const g1 = 'ffffffff-1111-4111-8111-111111111111';         // a team
const g1b = 'ffffffff-3333-4333-8333-333333333333';
const g2 = 'ffffffff-2222-4222-8222-222222222222';         // the other church's team
const nobody = 'eeeeeeee-9999-4999-8999-999999999999';
const TABLES = ['church_schedule_department_limits', 'church_protected_days', 'church_away_pairs'];
const OLD = 'church_away_settle';
const NEW = 'church_away_settle_excepted';

// What Supabase already has (as step 1's check stands it up): the three
// roles and its habit of handing every new table and function in public to
// all three, auth.users, businesses, contacts, groups, the map's
// departments, Who serves when (which makes serve_away), and step 1.
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
  await db.query('INSERT INTO contacts VALUES ($1, $7), ($2, $7), ($3, $7), ($4, $7), ($5, $8), ($6, $8)',
    [leader, over, cover, other, outsider, outsider2, b1, b2]);
  await db.query(`INSERT INTO church_departments VALUES ($1, $2, 'Youth'), ($3, $2, 'Music'), ($4, $5, 'Youth')`,
    [d1, b1, d1b, d2, b2]);
  await db.query(`INSERT INTO groups VALUES ($1, $2, 'team'), ($3, $2, 'team'), ($4, $5, 'team')`, [g1, b1, g1b, g2, b2]);
  await db.exec(STEP1);
  return db;
};

let db = await stand();
let checks = 0;
const one = async (text, args = []) => (await db.query(text, args)).rows[0];
const all = async (text, args = []) => (await db.query(text, args)).rows;
const n = async (text, args = []) => (await one(`SELECT count(*)::int AS n FROM ${text}`, args)).n;
const ok = async (text, args) => { await db.query(text, args); checks++; };
const same = (got, want) => { assert.deepEqual(got, want); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
// A new set of days each time, so no two asks here are the same waiting ask.
let days = 0;
const day = () => new Date(Date.UTC(2028, 0, 1 + days++)).toISOString().slice(0, 10);
// An ask, as the server writes one: asked, nothing decided.
const ask = async (biz, who, more = {}) => {
  const on = day();
  const row = { business_id: biz, contact_id: who, grp: 'leaders', kind: 'time_off', starts_on: on, ends_on: on, ...more };
  const keys = Object.keys(row);
  return (await one(`INSERT INTO church_away_asks(${keys.join(', ')})
    VALUES (${keys.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING id`, keys.map(k => row[k]))).id;
};
// A call by argument names, which is how PostgREST makes one.
const named = (fn, args) => {
  const keys = Object.keys(args);
  return [`SELECT public.${fn}(${keys.map((k, i) => `${k} := $${i + 1}`).join(', ')}) AS r`, keys.map(k => args[k])];
};
const six = (biz, id, state, by = {}) => ({ p_business_id: biz, p_ask_id: id, p_state: state,
  p_by_user: by.user ?? null, p_by_contact: by.contact ?? null, p_note: by.note ?? null });
// The six names the deployed code sends, to step 1's function.
const settle = async (biz, id, state, by = {}) => (await one(...named(OLD, six(biz, id, state, by)))).r;
// The seven names step 2 will send, to the new one.
const excepting = async (biz, id, state, by = {}, excepted = []) =>
  (await one(...named(NEW, { ...six(biz, id, state, by), p_excepted: excepted }))).r;
const facts = id => n('serve_away WHERE ask_id = $1', [id]);
const row = id => one('SELECT state, excepted, flags FROM church_away_asks WHERE id = $1', [id]);
const fn = name => one(`SELECT p.oid::int AS oid, md5(pg_get_functiondef(p.oid)) AS body, p.proacl::text AS acl,
  p.pronargs::int AS args FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname = $1`, [name]);
const fns = async () => (await all(`SELECT proname, count(*)::int AS n FROM pg_proc
  WHERE pronamespace = 'public'::regnamespace AND proname LIKE 'church_away_settle%' GROUP BY 1 ORDER BY 1`))
  .map(r => [r.proname, r.n]);
// Everything in public, as the catalog holds it.
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
                      AND NOT a.attisdropped AND col_description(c.oid, a.attnum) IS NOT NULL),
  'policies', (SELECT count(*) FROM pg_policies)) AS s`)).s;
// One table's own part of the catalog: serve_away must not move at all.
const table = async name => (await one(`SELECT jsonb_build_object(
  'columns', (SELECT jsonb_agg(jsonb_build_array(column_name, data_type, is_nullable, column_default) ORDER BY ordinal_position)
                FROM information_schema.columns WHERE table_schema = 'public' AND table_name = $1),
  'constraints', (SELECT jsonb_agg(jsonb_build_array(conname, pg_get_constraintdef(oid), convalidated) ORDER BY conname)
                    FROM pg_constraint WHERE conrelid = ('public.' || $1)::regclass),
  'indexes', (SELECT jsonb_agg(indexdef ORDER BY indexname) FROM pg_indexes WHERE schemaname = 'public' AND tablename = $1),
  'triggers', (SELECT jsonb_agg(jsonb_build_array(tgname, pg_get_triggerdef(oid)) ORDER BY tgname)
                 FROM pg_trigger WHERE tgrelid = ('public.' || $1)::regclass AND NOT tgisinternal)) AS s`, [name])).s;
// The commented Check and Rollback blocks at the end of the file, as written.
const block = (from, to) => {
  const lines = FILE.replace(/\r\n/g, '\n').split('\n');
  const a = lines.findIndex(l => l.startsWith(from));
  const z = to ? lines.findIndex(l => l.startsWith(to)) : lines.length;
  assert.ok(a >= 0 && z > a);
  return lines.slice(a + 1, z).map(l => l.replace(/^-- {0,3}/, '')).filter(l => !l.startsWith('-- ')).join('\n')
    .split(';').map(s => s.trim()).filter(Boolean);
};

// ─── Step 1 in use, before the file ─────────────────────────────────────
// Asks in every state, an away date from before step 1, a setting, and the
// decision function already used in this session (so it is compiled against
// the table as it is now, as it is on the live database's connections).
await db.query(`INSERT INTO serve_away(business_id, contact_id, starts_on, ends_on) VALUES ($1, $2, '2027-03-01', '2027-03-07')`,
  [b1, other]);
await db.query(`INSERT INTO church_schedule_settings(business_id, notice_days, updated_by) VALUES ($1, 21, $2)`, [b1, u1]);
const waiting = await ask(b1, leader, { reason: 'A private reason', to_contact_id: over, cover_contact_id: cover,
  department_id: d1, flags: ['short_notice'] });
const yes0 = await ask(b1, leader, { to_contact_id: over });
const no0 = await ask(b1, leader, { to_user_id: u1 });
const gone0 = await ask(b1, other, { to_user_id: u1 });
let r = await settle(b1, yes0, 'yes', { contact: over, note: 'Enjoy it.' });
same([r.changed, r.ask.state, await facts(yes0)], [true, 'yes', 1]);
await settle(b1, no0, 'no', { user: u1 });
await settle(b1, gone0, 'withdrawn');
const snap = async () => ({
  asks: (await all(`SELECT to_jsonb(a) - 'excepted' - 'team_group_id' AS j FROM church_away_asks a ORDER BY id`)).map(x => x.j),
  away: (await all(`SELECT to_jsonb(s) AS j FROM serve_away s ORDER BY id`)).map(x => x.j),
  settings: (await all(`SELECT to_jsonb(s) - 'leaders_limit' - 'office_limit' - 'service_weekdays' AS j
    FROM church_schedule_settings s ORDER BY business_id`)).map(x => x.j) });
const rows0 = await snap();
const cat0 = await catalog();
const away0 = await table('serve_away');
const old0 = await fn(OLD);
same([old0.args, (await fns())], [6, [[OLD, 1]]]);

// ─── The file ───────────────────────────────────────────────────────────
await db.exec(FILE);
const cat1 = await catalog();
// church_away_settle was not touched: the same function, body and grants.
same(await fn(OLD), old0);
same(await fns(), [[OLD, 1], [NEW, 1]]);
same((await fn(NEW)).args, 7);
// Nothing that was there reads differently, and serve_away is as it was.
same(await snap(), rows0);
same(await table('serve_away'), away0);
same(await all(`SELECT DISTINCT excepted, team_group_id FROM church_away_asks`), [{ excepted: [], team_group_id: null }]);
same(await one(`SELECT notice_days, leaders_limit, office_limit, service_weekdays FROM church_schedule_settings WHERE business_id = $1`,
  [b1]), { notice_days: 21, leaders_limit: null, office_limit: null, service_weekdays: null });

// ─── What the deployed code does still works, the moment it has run ─────
// The six-name call, in the session that had already used the function.
r = await settle(b1, waiting, 'yes', { contact: over, note: '  Go well.  ' });
same([r.changed, r.ask.id, r.ask.state, r.ask.decided_by_contact_id, r.ask.decided_by_user_id, r.ask.decided_note,
  r.ask.decided_at !== null, r.ask.withdrawn_at, r.ask.flags], [true, waiting, 'yes', over, null, 'Go well.', true, null, ['short_notice']]);
// The row it answers with now has the two new columns too, empty.
same([r.ask.excepted, r.ask.team_group_id], [[], null]);
same(await all(`SELECT business_id, contact_id, note, ask_id, kind FROM serve_away WHERE ask_id = $1`, [waiting]),
  [{ business_id: b1, contact_id: leader, note: '', ask_id: waiting, kind: 'time_off' }]);
r = await settle(b1, waiting, 'yes', { user: u1 });                              // a second yes: nothing, and one fact
same([r.changed, r.ask.state, r.ask.decided_by_contact_id, await facts(waiting)], [false, 'yes', over, 1]);
r = (await one(...named(OLD, { p_business_id: b1, p_ask_id: waiting, p_state: 'withdrawn' }))).r;   // three names
same([r.changed, r.ask.state, r.ask.withdrawn_at !== null, r.ask.decided_at !== null, await facts(waiting)],
  [true, 'withdrawn', true, true, 0]);
same(await settle(b2, yes0, 'withdrawn'), null);                                 // another church's id
same(await settle(b1, nobody, 'yes', { user: u1 }), null);                       // no such ask
for (const bad of ['maybe', 'asked', 'YES', '', null]) {
  await refuses(...named(OLD, six(b1, yes0, bad)), /answered yes or no, or withdrawn/);
}
// It never makes a fact again for an ask that is already a yes.
await ok(`DELETE FROM serve_away WHERE ask_id = $1`, [yes0]);
r = await settle(b1, yes0, 'yes', { contact: over });
same([r.changed, r.ask.state, await facts(yes0)], [false, 'yes', 0]);
// An ask as the server writes one (these columns and no others), then the
// writes that follow it: the notice marks, sent on to someone else, the
// reason cleared, an ask that didn't settle taken back, the notice days.
const sent = { business_id: b1, contact_id: other, made_by: u1, grp: 'leaders', department_id: d1, kind: 'time_off',
  starts_on: '2027-09-01', ends_on: '2027-09-03', reason: 'Why', cover_contact_id: cover, cover_name: null,
  to_user_id: null, to_contact_id: over, flags: ['short_notice', 'serving'] };
const made = await one(`INSERT INTO church_away_asks(${Object.keys(sent).join(', ')})
  VALUES (${Object.keys(sent).map((_, i) => `$${i + 1}`).join(', ')}) RETURNING *`, Object.values(sent));
same([made.state, made.excepted, made.team_group_id], ['asked', [], null]);
await refuses(`INSERT INTO church_away_asks(business_id, contact_id, grp, kind, starts_on, ends_on)
  VALUES ($1, $2, 'leaders', 'commitment', '2027-09-01', '2027-09-03')`, [b1, other], /church_away_asks_one_open/);
await ok(`UPDATE church_away_asks SET told_at = now() WHERE id = $1 AND told_at IS NULL`, [made.id]);
await ok(`UPDATE church_away_asks SET to_contact_id = null, to_user_id = $1, told_at = null, updated_at = now()
  WHERE id = $2 AND state = 'asked'`, [u2, made.id]);
await ok(`UPDATE church_away_asks SET reason = null, decided_note = null WHERE id = $1`, [made.id]);
await refuses(`UPDATE church_away_asks SET to_user_id = null, to_contact_id = $1 WHERE id = $2`, [outsider, made.id],
  /person it goes to is not in this church/);                                    // step 1's own guard still stands
await ok(`DELETE FROM church_away_asks WHERE id = $1 AND state = 'asked'`, [made.id]);
const notice = `INSERT INTO church_schedule_settings(business_id, notice_days, updated_by, updated_at) VALUES ($1, $2, $3, now())
  ON CONFLICT (business_id) DO UPDATE SET notice_days = excluded.notice_days, updated_by = excluded.updated_by,
    updated_at = excluded.updated_at`;
await ok(notice, [b1, 10, u1]);
same((await one(`SELECT notice_days FROM church_schedule_settings WHERE business_id = $1`, [b1])).notice_days, 10);

// ─── Twice, and in any order with step 1's file: nothing changes ────────
const rows1 = await snap();
await db.exec(FILE);
same(await catalog(), cat1);
same([await snap(), await fns()], [rows1, [[OLD, 1], [NEW, 1]]]);
await db.exec(STEP1);                                                            // step 1's file again, after this one
same(await catalog(), cat1);
same([await fn(OLD), await fns()], [old0, [[OLD, 1], [NEW, 1]]]);
await db.exec(FILE);
same(await catalog(), cat1);
same(await snap(), rows1);

// ─── The new function: the same decision ────────────────────────────────
// Every decision on an ask in every state, through the old name and through
// the new one with no exception: the same answer and the same rows.
const brought = async to => {
  const id = await ask(b1, leader, { to_contact_id: over, flags: ['over_limit'] });
  if (to === 'yes' || to === 'yes then withdrawn') await settle(b1, id, 'yes', { contact: over });
  if (to === 'no') await settle(b1, id, 'no', { contact: over });
  if (to === 'withdrawn' || to === 'yes then withdrawn') await settle(b1, id, 'withdrawn');
  return id;
};
const told = async (got, id) => got === null ? null : [got.changed, got.ask.id === id, got.ask.state,
  got.ask.decided_at !== null, got.ask.withdrawn_at !== null, got.ask.decided_by_user_id, got.ask.decided_by_contact_id,
  got.ask.decided_note, got.ask.excepted, got.ask.answer_told_at, await facts(id), (await row(id)).state];
for (const was of ['asked', 'yes', 'no', 'withdrawn', 'yes then withdrawn']) {
  for (const state of ['yes', 'no', 'withdrawn']) {
    const a = await brought(was), b = await brought(was);
    const by = { user: u1, note: '  A note.  ' };
    const first = await told(await settle(b1, a, state, by), a);
    same(await told((await one(...named(NEW, six(b1, b, state, by)))).r, b), first);   // six names, to the new one
    assert.ok(first !== null);
  }
}
same((await one(...named(NEW, six(b2, yes0, 'withdrawn')))).r, null);            // another church's id
same(await excepting(b1, nobody, 'yes', { user: u1 }, ['over_limit']), null);    // no such ask
for (const bad of ['maybe', 'asked', 'YES', '', null]) {
  await refuses(...named(NEW, six(b1, yes0, bad)), /answered yes or no, or withdrawn/);
}
// It never makes a fact again for an ask that is already a yes (yes0's is gone).
r = await excepting(b1, yes0, 'yes', { contact: over });
same([r.changed, r.ask.state, await facts(yes0)], [false, 'yes', 0]);
const a1 = await ask(b1, leader);
await refuses(...named(NEW, six(b1, a1, 'yes', { user: u1, contact: over })), /church_away_asks_by_one/);
await refuses(...named(NEW, six(b1, a1, 'yes', { contact: outsider })), /who answered is not in this church/);
await refuses(...named(NEW, six(b1, a1, 'yes', { user: nobody })), /foreign key/);
same([(await row(a1)).state, await facts(a1)], ['asked', 0]);                    // a refused answer wrote nothing
r = (await one(...named(NEW, { p_business_id: b1, p_ask_id: a1, p_state: 'withdrawn' }))).r;      // three names
same([r.changed, r.ask.state], [true, 'withdrawn']);

// ─── The new function: the exception ────────────────────────────────────
// A yes over the limit, by a login: the exception is on the ask, and the
// fact is the one fact, with no note.
const e1 = await ask(b1, leader, { to_user_id: u1, flags: ['short_notice', 'over_limit', 'pair', 'serving'] });
r = await excepting(b1, e1, 'yes', { user: u1, note: 'This once.' }, ['over_limit']);
same([r.changed, r.ask.state, r.ask.excepted, r.ask.decided_by_user_id, r.ask.decided_note, r.ask.decided_at !== null,
  r.ask.flags], [true, 'yes', ['over_limit'], u1, 'This once.', true, ['short_notice', 'over_limit', 'pair', 'serving']]);
same(await row(e1), { state: 'yes', excepted: ['over_limit'], flags: ['short_notice', 'over_limit', 'pair', 'serving'] });
same(await all(`SELECT contact_id, note, kind FROM serve_away WHERE ask_id = $1`, [e1]),
  [{ contact_id: leader, note: '', kind: 'time_off' }]);
// A second yes, with another exception: nothing changes, the first stands.
r = await excepting(b1, e1, 'yes', { user: u1 }, ['pair']);
same([r.changed, r.ask.excepted, (await row(e1)).excepted, await facts(e1)], [false, ['over_limit'], ['over_limit'], 1]);
// Taken back: the fact goes, and the ask still says an exception was given.
r = await excepting(b1, e1, 'withdrawn', {}, ['pair']);
same([r.changed, r.ask.state, r.ask.excepted, await facts(e1)], [true, 'withdrawn', ['over_limit'], 0]);
// Each flag once, in order, whatever was passed.
const e2 = await ask(b1, leader, { flags: ['pair', 'protected_day', 'over_limit'] });
r = await excepting(b1, e2, 'yes', { contact: over }, ['protected_day', 'pair', 'over_limit', 'pair']);
same([r.changed, r.ask.excepted, r.ask.decided_by_contact_id], [true, ['over_limit', 'pair', 'protected_day'], over]);
const e3 = await ask(b1, leader, { flags: ['pair'] });
r = (await one(`SELECT public.${NEW}($1, $2, 'yes', $3, null, null, '{{pair}, {pair}}') AS r`, [b1, e3, u1])).r;   // a list of lists
same([r.changed, r.ask.excepted], [true, ['pair']]);
// No exception passed (left out, empty, or null): a plain yes.
for (const none of [undefined, [], null]) {
  const id = await ask(b1, leader, { flags: ['over_limit'] });
  const args = six(b1, id, 'yes', { user: u1 });
  r = (await one(...named(NEW, none === undefined ? args : { ...args, p_excepted: none }))).r;
  same([r.changed, r.ask.state, r.ask.excepted, await facts(id)], [true, 'yes', [], 1]);
}
// A no never carries one, and a take-back of a waiting ask doesn't either.
const e4 = await ask(b1, leader, { flags: ['over_limit'] });
r = await excepting(b1, e4, 'no', { user: u1 }, ['over_limit']);
same([r.changed, r.ask.state, r.ask.excepted, await facts(e4)], [true, 'no', [], 0]);
const e5 = await ask(b1, leader, { flags: ['over_limit'] });
r = await excepting(b1, e5, 'withdrawn', {}, ['over_limit']);
same([r.changed, r.ask.state, r.ask.excepted], [true, 'withdrawn', []]);
// Refused by name, and the yes and its away date are undone with it: a flag
// the ask doesn't have, short notice, serving, something made up, a null.
const e6 = await ask(b1, leader, { flags: ['short_notice', 'over_limit', 'serving'] });
for (const bad of [['pair'], ['over_limit', 'protected_day'], ['short_notice'], ['serving'], ['made_up'], [null], ['']]) {
  await refuses(...named(NEW, { ...six(b1, e6, 'yes', { user: u1 }), p_excepted: bad }), /An exception is for a flag the ask has/);
  same([await row(e6), await facts(e6), (await one(`SELECT decided_at FROM church_away_asks WHERE id = $1`, [e6])).decided_at],
    [{ state: 'asked', excepted: [], flags: ['short_notice', 'over_limit', 'serving'] }, 0, null]);
}
r = await excepting(b1, e6, 'yes', { user: u1 }, ['over_limit']);                 // and the right one still lands
same([r.changed, r.ask.excepted, await facts(e6)], [true, ['over_limit'], 1]);
// "Can't make it" is never blocked: a yes nobody gave, flags and all.
const e7 = await ask(b1, leader, { kind: 'cant', flags: ['short_notice', 'over_limit', 'protected_day'] });
r = await excepting(b1, e7, 'yes');
same([r.changed, r.ask.state, r.ask.excepted, r.ask.decided_by_user_id, r.ask.decided_by_contact_id],
  [true, 'yes', [], null, null]);
same(await one('SELECT kind, note FROM serve_away WHERE ask_id = $1', [e7]), { kind: 'cant', note: '' });

// ─── What an ask's exception may hold, whoever writes the row ───────────
const held = await ask(b1, other, { flags: ['over_limit', 'serving', 'short_notice'] });
await refuses(`UPDATE church_away_asks SET excepted = '{over_limit}' WHERE id = $1`, [held], /church_away_asks_excepted/);   // still waiting
await settle(b1, held, 'yes', { user: u1 });
await refuses(`UPDATE church_away_asks SET excepted = '{pair}' WHERE id = $1`, [held], /church_away_asks_excepted/);          // not a flag it has
await refuses(`UPDATE church_away_asks SET excepted = '{serving}' WHERE id = $1`, [held], /church_away_asks_excepted/);       // has it, but never an exception
await refuses(`UPDATE church_away_asks SET excepted = '{short_notice}' WHERE id = $1`, [held], /church_away_asks_excepted/);
await refuses(`UPDATE church_away_asks SET excepted = null WHERE id = $1`, [held], /not-null|null value/);
await ok(`UPDATE church_away_asks SET excepted = '{over_limit}' WHERE id = $1`, [held]);
await refuses(`UPDATE church_away_asks SET flags = '{serving}' WHERE id = $1`, [held], /church_away_asks_excepted/);         // its flag can't be taken away under it
await ok(`UPDATE church_away_asks SET flags = flags || '{pair}'::text[] WHERE id = $1`, [held]);
const refused = await ask(b1, other, { flags: ['over_limit'] });
await settle(b1, refused, 'no', { user: u1 });
await refuses(`UPDATE church_away_asks SET excepted = '{over_limit}' WHERE id = $1`, [refused], /church_away_asks_excepted/); // a no
same((await one(`SELECT convalidated FROM pg_constraint WHERE conname = 'church_away_asks_excepted'`)).convalidated, true);

// ─── A volunteer's team ─────────────────────────────────────────────────
const put = (more, who = leader, biz = b1) => {
  const on = day();
  const rec = { business_id: biz, contact_id: who, grp: 'volunteers', kind: 'time_off', starts_on: on, ends_on: on, ...more };
  const keys = Object.keys(rec);
  return [`INSERT INTO church_away_asks(${keys.join(', ')}) VALUES (${keys.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING id`,
    keys.map(k => rec[k])];
};
await refuses(...put({ team_group_id: g2 }), /That team is not in this church/);
await refuses(...put({ team_group_id: nobody }), /That team is not in this church/);
const teamed = (await one(...put({ team_group_id: g1, department_id: d1, flags: ['over_limit'] }))).id; checks++;
await refuses(`UPDATE church_away_asks SET team_group_id = $1 WHERE id = $2`, [g2, teamed], /That team is not in this church/);
await ok(`UPDATE church_away_asks SET team_group_id = $1 WHERE id = $2`, [g1b, teamed]);
await ok(`UPDATE church_away_asks SET told_at = now() WHERE id = $1`, [teamed]);
const theirs = (await one(...put({ team_group_id: g2 }, outsider, b2))).id; checks++;   // the other church's own team
await ok('DELETE FROM groups WHERE id = $1', [g1b]);                              // a team deleted leaves the ask
same(await one(`SELECT state, team_group_id FROM church_away_asks WHERE id = $1`, [teamed]), { state: 'asked', team_group_id: null });
same((await one(`SELECT convalidated FROM pg_constraint WHERE conname = 'church_away_asks_team_group_id_fkey'`)).convalidated, true);

// ─── The church's numbers and its usual service days ────────────────────
const set = (column, value) => [`UPDATE church_schedule_settings SET ${column} = $1 WHERE business_id = $2`, [value, b1]];
for (const column of ['leaders_limit', 'office_limit']) {
  for (const bad of [0, -1, 100]) await refuses(...set(column, bad), /church_schedule_settings_limits/);
  for (const good of [1, 99, null, 3]) await ok(...set(column, good));
}
for (const bad of ['{}', '{0}', '{8}', '{1,2,3,4,5,6,7,1}', '{7,NULL}', '{NULL}', '{{6,7}}', '{{6},{7}}']) {
  await refuses(...set('service_weekdays', bad), /church_schedule_settings_weekdays/);
}
for (const good of ['{7}', '{6,7}', '{3,7}', '{1,2,3,4,5,6,7}', null, '{6,7}']) await ok(...set('service_weekdays', good));
// Saving the notice days, as the deployed code does, leaves the numbers alone.
await ok(notice, [b1, 14, u2]);
same(await one(`SELECT notice_days, leaders_limit, office_limit, service_weekdays, updated_by FROM church_schedule_settings
  WHERE business_id = $1`, [b1]), { notice_days: 14, leaders_limit: 3, office_limit: 3, service_weekdays: [6, 7], updated_by: u2 });
await ok(`INSERT INTO church_schedule_settings(business_id, leaders_limit) VALUES ($1, 2)`, [b2]);   // a church that never set its notice
same((await one(`SELECT notice_days FROM church_schedule_settings WHERE business_id = $1`, [b2])).notice_days, 14);

// ─── One number a department ────────────────────────────────────────────
const limit = `INSERT INTO church_schedule_department_limits(department_id, business_id, at_most, set_by_user_id, set_by_contact_id)
  VALUES ($1, $2, $3, $4, $5)`;
await ok(limit, [d1, b1, 2, u1, null]);
await ok(limit, [d1b, b1, 99, null, over]);                                       // set by one of the church's people
await ok(limit, [d2, b2, 1, null, null]);
for (const bad of [0, -1, 100]) await refuses(limit, [d1, b1, bad, u1, null], /check constraint/);
await refuses(limit, [d1, b1, 3, u1, null], /duplicate key/);                     // one number a department
await refuses(limit, [d2, b1, 3, u1, null], /That department is not in this church/);
await refuses(limit, [nobody, b1, 3, u1, null], /That department is not in this church/);
await ok(`DELETE FROM church_schedule_department_limits WHERE department_id = $1`, [d2]);
await refuses(limit, [d2, b2, 3, null, over], /The person who set it is not in this church/);
await refuses(limit, [d2, b2, 3, u1, outsider], /church_schedule_department_limits_by_one/);
await ok(limit, [d2, b2, 1, null, outsider]);
await refuses(`UPDATE church_schedule_department_limits SET business_id = $1 WHERE department_id = $2`, [b2, d1],
  /That department is not in this church/);
await refuses(`UPDATE church_schedule_department_limits SET department_id = $1 WHERE department_id = $2`, [d2, d1],
  /duplicate key|That department is not in this church/);
await refuses(`UPDATE church_schedule_department_limits SET set_by_user_id = null, set_by_contact_id = $1 WHERE department_id = $2`,
  [outsider, d1], /The person who set it is not in this church/);
await refuses(`UPDATE church_schedule_department_limits SET set_by_contact_id = $1 WHERE department_id = $2`, [over, d1],
  /church_schedule_department_limits_by_one/);
// Setting it again, as an upsert would: the number, who, and when.
await ok(`INSERT INTO church_schedule_department_limits(department_id, business_id, at_most, set_by_user_id, set_by_contact_id)
  VALUES ($1, $2, 4, null, $3) ON CONFLICT (department_id) DO UPDATE SET business_id = excluded.business_id,
    at_most = excluded.at_most, set_by_user_id = excluded.set_by_user_id, set_by_contact_id = excluded.set_by_contact_id,
    updated_at = now()`, [d1, b1, cover]);
same(await one(`SELECT at_most, set_by_user_id, set_by_contact_id FROM church_schedule_department_limits WHERE department_id = $1`,
  [d1]), { at_most: 4, set_by_user_id: null, set_by_contact_id: cover });
same(await n('church_schedule_department_limits WHERE business_id = $1', [b1]), 2);   // no row = no limit; two have one

// ─── A day nobody takes off ─────────────────────────────────────────────
const guard = `INSERT INTO church_protected_days(business_id, day, name, created_by) VALUES ($1, $2, $3, $4)`;
await ok(guard, [b1, '2028-04-16', 'Easter', u1]);
await ok(guard, [b1, '2028-04-14', 'x'.repeat(80), null]);
await ok(guard, [b2, '2028-04-16', 'Easter', null]);                              // the same date at another church
await refuses(guard, [b1, '2028-04-16', 'Easter again', u1], /church_protected_days_one/);   // one row a date a church
await refuses(guard, [b1, '2028-12-25', '   ', u1], /check constraint/);
await refuses(guard, [b1, '2028-12-25', 'x'.repeat(81), u1], /check constraint/);
await refuses(guard, [b1, '2028-12-25', null, u1], /null value/);
await refuses(guard, [b1, null, 'A day', u1], /null value/);
await refuses(guard, [nobody, '2028-12-25', 'A day', null], /foreign key/);
await ok(`INSERT INTO church_protected_days(business_id, day, name) VALUES ($1, '2028-04-16', 'Easter Sunday')
  ON CONFLICT (business_id, day) DO UPDATE SET name = excluded.name`, [b1]);     // named again, still one row
same(await all(`SELECT day::text, name FROM church_protected_days WHERE business_id = $1 ORDER BY day`, [b1]),
  [{ day: '2028-04-14', name: 'x'.repeat(80) }, { day: '2028-04-16', name: 'Easter Sunday' }]);

// ─── Two people who can't be away together ──────────────────────────────
const pair = `INSERT INTO church_away_pairs(business_id, a_contact_id, b_contact_id, note, created_by) VALUES ($1, $2, $3, $4, $5)`;
// leader (…1111) < over (…3333) < cover (…4444) < other (…5555)
await ok(pair, [b1, leader, over, 'Both lead the same service', u1]);
await ok(pair, [b1, leader, cover, null, null]);                                  // one person in two pairs
await ok(pair, [b1, over, other, 'n'.repeat(140), u1]);
await refuses(pair, [b1, over, leader, null, u1], /church_away_pairs_ordered/);   // the other way round
await refuses(pair, [b1, leader, over, 'again', u1], /church_away_pairs_one/);    // the same pair twice
await refuses(pair, [b1, leader, leader, null, u1], /A pair is two people in this church/);   // a person with themself
await refuses(pair, [b1, leader, outsider, null, u1], /A pair is two people in this church/);
await refuses(pair, [b1, outsider, over, null, u1], /A pair is two people in this church/);
await refuses(pair, [b1, outsider, outsider2, null, u1], /A pair is two people in this church/);   // another church's two
await refuses(pair, [b2, leader, over, null, u1], /A pair is two people in this church/);
await refuses(pair, [b1, leader, nobody, null, u1], /A pair is two people in this church/);
await refuses(pair, [b1, cover, other, 'n'.repeat(141), u1], /check constraint/);
await ok(pair, [b2, outsider, outsider2, null, null]);                            // the other church's own pair
await refuses(`UPDATE church_away_pairs SET b_contact_id = $1 WHERE a_contact_id = $2 AND b_contact_id = $3`,
  [outsider2, leader, over], /A pair is two people in this church/);
await refuses(`UPDATE church_away_pairs SET business_id = $1 WHERE a_contact_id = $2 AND b_contact_id = $3`,
  [b2, leader, over], /A pair is two people in this church/);
await refuses(`UPDATE church_away_pairs SET a_contact_id = $1, b_contact_id = $2 WHERE a_contact_id = $2 AND b_contact_id = $3`,
  [other, leader, over], /church_away_pairs_ordered/);
await ok(`UPDATE church_away_pairs SET note = 'A new note' WHERE a_contact_id = $1 AND b_contact_id = $2`, [leader, over]);
// Without the trigger the constraint alone still keeps a person from being paired with themself.
await db.exec('ALTER TABLE church_away_pairs DISABLE TRIGGER church_schedule_limits_same_business');
await refuses(pair, [b1, leader, leader, null, u1], /church_away_pairs_ordered/);
await db.exec('ALTER TABLE church_away_pairs ENABLE TRIGGER church_schedule_limits_same_business');
// Either person finds their pairs, and the order Postgres keeps is the order
// of the two ids as lower-case text, which is how the server will sort them.
same(await n('church_away_pairs WHERE business_id = $1 AND (a_contact_id = $2 OR b_contact_id = $2)', [b1, over]), 2);
same(await one(`SELECT count(*)::int AS n, bool_and((a < b) = (a::text COLLATE "C" < b::text COLLATE "C")) AS same
  FROM (SELECT gen_random_uuid() AS a, gen_random_uuid() AS b FROM generate_series(1, 500)) x`), { n: 500, same: true });
same((await all(`SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY($1) ORDER BY 1`, [TABLES]))
  .map(x => x.indexname), ['church_away_pairs_b', 'church_away_pairs_one', 'church_away_pairs_pkey',
  'church_protected_days_one', 'church_protected_days_pkey', 'church_schedule_department_limits_by_church',
  'church_schedule_department_limits_pkey']);

// ─── The file's own Check block, as written ─────────────────────────────
const asked = block('-- Check:', '-- Rollback');
same(asked.length, 5);
same(await all(asked[0]), TABLES.slice().sort().map(relname =>
  ({ relname, relrowsecurity: true, policies: 0, browser_reads: false, anon_reads: false })));
same((await all(asked[1])).map(x => `${x.table_name}.${x.column_name}`), ['church_away_asks.excepted',
  'church_away_asks.team_group_id', 'church_schedule_settings.leaders_limit', 'church_schedule_settings.office_limit',
  'church_schedule_settings.service_weekdays']);
same(await all(asked[2]), ['church_away_asks_excepted', 'church_away_asks_team_group_id_fkey',
  'church_schedule_settings_limits', 'church_schedule_settings_weekdays'].map(conname => ({ conname, convalidated: true })));
same(await all(asked[3]), [
  { proname: OLD, pronargs: 6, browser_runs: false, anon_runs: false, server_runs: true },
  { proname: NEW, pronargs: 7, browser_runs: false, anon_runs: false, server_runs: true }]);
assert.ok(Number((await one(asked[4])).count) > 0); checks++;      // here exceptions have been given; on the live database it is 0

// ─── Server-only ────────────────────────────────────────────────────────
for (const t of TABLES) {
  const got = await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policies,
      (SELECT bool_or(has_table_privilege(r, c.oid, p)) FROM unnest(array['anon', 'authenticated']) r,
         unnest(array['select', 'insert', 'update', 'delete', 'truncate', 'references', 'trigger']) p) AS browser,
      (SELECT bool_and(has_table_privilege('service_role', c.oid, p))
         FROM unnest(array['select', 'insert', 'update', 'delete']) p) AS server
    FROM pg_class c WHERE c.oid = $1::regclass`, [`public.${t}`]);
  same(got, { rls: true, policies: 0, browser: false, server: true });
}
same((await all(`SELECT p.proname, has_function_privilege('anon', p.oid, 'execute') AS anon,
    has_function_privilege('authenticated', p.oid, 'execute') AS authed,
    has_function_privilege('public', p.oid, 'execute') AS everyone
  FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace
    AND p.proname IN ('church_away_settle', 'church_away_settle_excepted', 'church_schedule_limits_same_business')
  ORDER BY 1`)), [OLD, NEW, 'church_schedule_limits_same_business'].map(proname =>
  ({ proname, anon: false, authed: false, everyone: false })));
same((await one(`SELECT prosecdef FROM pg_proc WHERE proname = $1`, [NEW])).prosecdef, false);   // runs as the server's own role
const s1 = await ask(b1, other, { flags: ['pair'] });
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  try {
    for (const t of TABLES) {
      await refuses(`SELECT * FROM ${t}`, [], /permission denied/);
      await refuses(`DELETE FROM ${t}`, [], /permission denied/);
    }
    await refuses(pair, [b1, cover, other, null, null], /permission denied/);
    await refuses(guard, [b1, '2029-01-01', 'A day', null], /permission denied/);
    await refuses(limit, [d1, b1, 5, null, null], /permission denied/);
    await refuses(`SELECT excepted FROM church_away_asks`, [], /permission denied/);
    await refuses(`SELECT leaders_limit FROM church_schedule_settings`, [], /permission denied/);
    await refuses(...named(NEW, { ...six(b1, s1, 'yes'), p_excepted: ['pair'] }), /permission denied for function/);
    await refuses(...named(OLD, six(b1, s1, 'yes')), /permission denied for function/);
  } finally { await db.exec('RESET ROLE'); }
}
await db.exec('SET ROLE service_role');                                          // the server's own role can, both names
try {
  r = await excepting(b1, s1, 'yes', { user: u1 }, ['pair']);
  same([r.changed, r.ask.state, r.ask.excepted, await facts(s1)], [true, 'yes', ['pair'], 1]);
  r = await settle(b1, s1, 'withdrawn');
  same([r.changed, r.ask.state, r.ask.excepted, await facts(s1)], [true, 'withdrawn', ['pair'], 0]);
  await ok(pair, [b1, cover, other, null, null]);
  same(await n('church_away_pairs WHERE business_id = $1', [b1]), 4);
  await ok(`DELETE FROM church_away_pairs WHERE a_contact_id = $1 AND b_contact_id = $2`, [cover, other]);
} finally { await db.exec('RESET ROLE'); }

// ─── What goes with what ────────────────────────────────────────────────
// A login deleted leaves the number, the day and the pair, with nobody in its place.
await ok('DELETE FROM auth.users WHERE id = $1', [u1]);
same(await one(`SELECT (SELECT count(*)::int FROM church_protected_days WHERE business_id = $1) AS days,
  (SELECT count(*)::int FROM church_protected_days WHERE created_by IS NOT NULL) AS days_by,
  (SELECT count(*)::int FROM church_away_pairs WHERE business_id = $1) AS pairs,
  (SELECT count(*)::int FROM church_away_pairs WHERE created_by IS NOT NULL) AS pairs_by,
  (SELECT count(*)::int FROM church_schedule_department_limits WHERE business_id = $1) AS limits`, [b1]),
  { days: 2, days_by: 0, pairs: 3, pairs_by: 0, limits: 2 });
same((await row(e6)).excepted, ['over_limit']);                                   // the exception stays when who gave it is gone
// The person who set a number deleted: the number stays, with nobody.
await ok('DELETE FROM contacts WHERE id = $1', [cover]);
same(await one(`SELECT at_most, set_by_contact_id FROM church_schedule_department_limits WHERE department_id = $1`, [d1]),
  { at_most: 4, set_by_contact_id: null });
same(await n('church_away_pairs WHERE business_id = $1', [b1]), 2);               // and the pair they were in went with them
// A department deleted takes its number.
await ok('DELETE FROM church_departments WHERE id = $1', [d1]);
same([await n('church_schedule_department_limits WHERE department_id = $1', [d1]),
  (await one(`SELECT department_id FROM church_away_asks WHERE id = $1`, [teamed])).department_id], [0, null]);
// A person in a pair deleted takes the pair, either side of it; nobody else's.
await ok('DELETE FROM contacts WHERE id = $1', [over]);
same([await n('church_away_pairs WHERE business_id = $1', [b1]), await n('church_away_pairs WHERE business_id = $1', [b2]),
  await n('church_schedule_department_limits WHERE department_id = $1', [d1b])], [0, 1, 1]);
same((await one(`SELECT set_by_contact_id FROM church_schedule_department_limits WHERE department_id = $1`, [d1b])).set_by_contact_id,
  null);
// A church deleted takes everything of its own; the other church keeps its own.
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
same([await n('church_schedule_department_limits'), await n('church_protected_days'), await n('church_away_pairs'),
  await n('church_away_asks'), await n('serve_away'), await n('church_schedule_settings')], [1, 1, 1, 1, 0, 1]);
same(await one(`SELECT team_group_id FROM church_away_asks WHERE id = $1`, [theirs]), { team_group_id: g2 });
await db.close();

// ─── The same deletes when the foreign keys fire the other way ──────────
// Postgres fires a delete's foreign keys in the order they were made. Above,
// a church's people went before its departments. Here the people's own key
// to the church is made again last, so the departments (and their numbers)
// go first: the church still goes, taking everything.
const firing = async () => (await db.query(`SELECT c.conrelid::regclass::text AS t
  FROM pg_trigger g JOIN pg_constraint c ON c.oid = g.tgconstraint
  WHERE g.tgrelid = 'public.businesses'::regclass AND g.tgtype & 8 = 8 AND c.confdeltype = 'c'
    AND c.conrelid IN ('public.contacts'::regclass, 'public.church_departments'::regclass) ORDER BY g.tgname`)).rows.map(x => x.t);
const filled = async () => {
  await db.exec(FILE);
  await db.query(limit, [d1, b1, 2, null, over]);
  await db.query(limit, [d1b, b1, 2, null, leader]);
  await db.query(pair, [b1, leader, over, null, u1]);
  await db.query(guard, [b1, '2028-04-16', 'Easter', u1]);
  const id = await ask(b1, leader, { grp: 'volunteers', team_group_id: g1, department_id: d1, to_contact_id: over, flags: ['over_limit'] });
  await excepting(b1, id, 'yes', { contact: over }, ['over_limit']);
  await db.query(pair, [b2, outsider, outsider2, null, null]);
};
db = await stand();
await filled();
same(await firing(), ['contacts', 'church_departments']);
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
same([await n('church_schedule_department_limits'), await n('church_protected_days'), await n('church_away_pairs'),
  await n('church_away_asks'), await n('serve_away')], [0, 0, 1, 0, 0]);
await db.close();
db = await stand();
const key = await one(`SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint
  WHERE conrelid = 'public.contacts'::regclass AND contype = 'f' AND confrelid = 'public.businesses'::regclass`);
await db.exec(`ALTER TABLE public.contacts DROP CONSTRAINT ${key.conname}`);
await db.exec(`ALTER TABLE public.contacts ADD CONSTRAINT ${key.conname} ${key.def}`);
await filled();
same(await firing(), ['church_departments', 'contacts']);
await ok('DELETE FROM groups WHERE id = $1', [g1]);                               // a team, with an approved ask naming it
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
same([await n('church_schedule_department_limits'), await n('church_protected_days'), await n('church_away_pairs'),
  await n('church_away_asks'), await n('serve_away')], [0, 0, 1, 0, 0]);
await db.close();

// ─── The file's own Rollback block, as written ──────────────────────────
// With rows in everything: the catalog is back as step 1 left it, every ask
// and away date is still there, the six-name call still answers, and the
// file goes in again afterwards.
db = await stand();
const start = await catalog();
const kept = await ask(b1, leader, { to_contact_id: over, flags: ['over_limit'] });
await db.exec(FILE);
const applied = await catalog();
await filled();
await excepting(b1, kept, 'yes', { contact: over }, ['over_limit']);
const before = [await n('church_away_asks'), await n('serve_away')];
const undo = block('-- Rollback');
assert.ok(undo.length >= 6); checks++;
for (const statement of undo) await db.exec(statement);
same(await catalog(), start);
same([await n('church_away_asks'), await n('serve_away'), await fns()], [...before, [[OLD, 1]]]);
r = await settle(b1, kept, 'withdrawn');
same([r.changed, r.ask.state, 'excepted' in r.ask, await facts(kept)], [true, 'withdrawn', false, 0]);
await db.exec(FILE);
same(await catalog(), applied);
r = await excepting(b1, await ask(b1, leader, { flags: ['pair'] }), 'yes', { contact: over }, ['pair']);
same([r.changed, r.ask.excepted], [true, ['pair']]);
await db.close();

// ─── The two ways not taken ─────────────────────────────────────────────
// What the file's header says of them, run for real. `seventh` is the
// function the first draft had: step 1's own, one more argument with a
// default, under the same name.
const seventh = STEP1.slice(STEP1.indexOf('create or replace function public.church_away_settle('),
  STEP1.indexOf('revoke all on function public.church_away_settle('))
  .replace('p_note text default null)', `p_note text default null, p_excepted text[] default '{}')`);
assert.ok(seventh.includes('p_excepted') && seventh.trimEnd().endsWith('end $$;')); checks++;
// 1. Both under one name: every call that leaves the seventh out is refused.
db = await stand();
const w1 = await ask(b1, leader);
await db.exec(seventh);
same(await fns(), [[OLD, 2]]);
await refuses(...named(OLD, six(b1, w1, 'yes', { contact: over })), /is not unique/);
await refuses(...named(OLD, { p_business_id: b1, p_ask_id: w1, p_state: 'withdrawn' }), /is not unique/);
same((await one('SELECT state FROM church_away_asks WHERE id = $1', [w1])).state, 'asked');
await db.close();
// 2. Drop the six-argument one and make the seven: it answers a six-name
// call on the day, and step 1's file run once more brings back case 1.
db = await stand();
const w2 = await ask(b1, leader), w3 = await ask(b1, leader);
await db.exec(`drop function public.church_away_settle(uuid, uuid, text, uuid, uuid, text); ${seventh}`);
same(await fns(), [[OLD, 1]]);
r = await settle(b1, w2, 'yes', { contact: over });
same([r.changed, r.ask.state], [true, 'yes']);
await db.exec(STEP1);
same(await fns(), [[OLD, 2]]);
await refuses(...named(OLD, six(b1, w3, 'yes', { contact: over })), /is not unique/);
// This file's way, from the same start: step 1's file and this one, in any
// order and any number of times, leave one function a name.
await db.close();
db = await stand();
for (const f of [FILE, STEP1, STEP1, FILE, FILE, STEP1]) {
  await db.exec(f);
  same(await fns(), [[OLD, 1], [NEW, 1]]);
}
const w4 = await ask(b1, leader, { flags: ['over_limit'] });
r = await excepting(b1, w4, 'yes', { contact: over }, ['over_limit']);
same([r.changed, r.ask.excepted], [true, ['over_limit']]);
r = await settle(b1, w4, 'withdrawn');
same([r.changed, r.ask.state], [true, 'withdrawn']);
await db.close();

// ─── Step 1's own check, unchanged, with this file applied after it ─────
// church_schedule_db.mjs is run as it is. It is handed a PGlite that applies
// this file straight after every run of step 1's file, so each of its checks
// (and its own "twice changes nothing") is made on a database that has both.
const theirCheck = fileURLToPath(new URL('./church_schedule_db.mjs', import.meta.url));
const runs = (await readFile(theirCheck, 'utf8')).split('db.exec(FILE)').length - 1;
assert.ok(runs >= 2); checks++;
const dir = await mkdtemp(join(tmpdir(), 'church-schedule-limits-'));
try {
  const shim = join(dir, 'pglite-then-limits.mjs');
  await writeFile(shim, `import { PGlite as Real } from ${JSON.stringify(base)};
const STEP1 = ${JSON.stringify(STEP1)};
const LIMITS = ${JSON.stringify(FILE)};
export class PGlite extends Real {
  async exec(text, ...rest) {
    const got = await super.exec(text, ...rest);
    if (text === STEP1) { await super.exec(LIMITS); console.error('after step 1: the limits file'); }
    return got;
  }
}
`);
  const ran = spawnSync(process.execPath, [theirCheck], { env: { ...process.env, PGLITE_MODULE: shim }, encoding: 'utf8' });
  assert.equal(ran.status, 0, `step 1's check failed after the limits file:\n${ran.stdout}\n${ran.stderr}`); checks++;
  assert.match(ran.stdout, /church schedule db: \d+ checks passed/); checks++;
  same(ran.stderr.split('after step 1: the limits file').length - 1, runs);
  console.log(`  step 1's own check, after the limits file: ${ran.stdout.trim()}`);
} finally { await rm(dir, { recursive: true, force: true }); }

console.log(`church schedule limits db: ${checks} checks passed`);
