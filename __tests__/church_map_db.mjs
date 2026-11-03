// The church leaders map's data, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-04-church-map.sql over the church migrations it builds
// on (leaders, the role library, shepherding, areas, the board, worship
// ministries). Every role of the eight church types, the legacy four, the
// three test churches' libraries and the edges in
// __tests__/fixtures/church_map_backfill_vectors.json is seeded first; the
// file then backfills each role's switches with today's rules, and they must
// equal the vectors the Python oracle wrote (test_church_map_vectors.py), as
// must the office overseers. Holders, shepherds, follow-ups and the
// shepherding settings come out byte for byte as they went in. Running the
// file again changes nothing, schema or data, even after a church changed a
// switch. The guards refuse another church's people and things and a holder
// answering to themselves; the browser's roles can't read, write or run any
// of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_map_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const vectors = JSON.parse(await readFile(new URL('./fixtures/church_map_backfill_vectors.json', import.meta.url), 'utf8'));
const MIGRATION = 'APPLY-2026-11-04-church-map.sql';
const SWITCHES = ['can_shepherd', 'can_oversee', 'can_lead', 'can_board_yes', 'can_see_all', 'made_for'];
const db = new PGlite();
let checks = 0;
const q = async (text, args) => (await db.query(text, args)).rows;
const one = async (text, args) => (await q(text, args))[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
let n = 0;
const id = () => `${(++n).toString(16).padStart(8, '0')}-0000-4000-8000-000000000000`;

// What Supabase already has, as little of it as these migrations need.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, name text);
  CREATE TABLE public.academy_courses(id uuid PRIMARY KEY, business_id uuid NOT NULL, title text);
  CREATE TABLE public.ministry_care_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id), submission jsonb NOT NULL DEFAULT '{}');
  CREATE TABLE public.households(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE);
  CREATE TABLE public.children(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL, household_id uuid NOT NULL);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid());
  CREATE TABLE public.groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, name text NOT NULL,
    kind text NOT NULL DEFAULT 'small_group', active boolean NOT NULL DEFAULT true);
  GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;`);
for (const f of ['APPLY-2026-10-17-church-leaders.sql', 'APPLY-2026-10-17-church-leaders-trigger-fix.sql',
                 'APPLY-2026-10-17-church-role-library.sql', 'APPLY-2026-10-18-shepherding.sql',
                 'APPLY-2026-10-23-church-areas.sql', 'APPLY-2026-10-27-church-board.sql',
                 'APPLY-2026-10-26-worship-ministries.sql']) await db.exec(await sql(f));

// ─── The churches before the file: every vector role, people, holders ───
const church = {};                 // vector name -> {biz, role: key -> id}
for (const c of vectors.churches) {
  const biz = id();
  await db.query('INSERT INTO businesses VALUES ($1)', [biz]);
  church[c.church] = { biz, role: {} };
  for (const [i, r] of c.roles.entries()) {
    church[c.church].role[r.key] = (await one(`INSERT INTO church_role_defs(business_id, key, title, job, handles, status,
        catalog_key, source, sort) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id`,
      [biz, r.key, r.title, r.job, r.handles, r.status, r.catalog_key, c.church.startsWith('fixture') ? 'catalog' : 'custom',
       i * 10])).id;
  }
  const top = church[c.church].role.pastor || church[c.church].role.bishop;
  if (top) await db.query(`UPDATE church_role_defs SET reports_to = $2 WHERE business_id = $1 AND id <> $2`, [biz, top]);
  // Every church has its settings row but one: the backfill must make it.
  if (c.church !== 'type:nondenom') {
    await db.query(`INSERT INTO church_role_settings(business_id, church_type, guessed_type, set_by, seeded_at)
      VALUES ($1, 'nondenom', 'nondenom', 'chief', now())`, [biz]);
  }
}
const LC = church['fixture:love_city'], GR = church['fixture:grace'], NH = church['fixture:new_hope'];
// A role whose class was deleted (needs_class has no foreign key): the guard
// would refuse its row, so the backfill runs with the guard off.
const course = id();
await db.query('INSERT INTO academy_courses VALUES ($1, $2, $3)', [course, LC.biz, 'Membership class']);
await db.query('UPDATE church_role_defs SET needs_class = $2 WHERE id = $1', [LC.role.class_teachers, course]);
await db.query('DELETE FROM academy_courses WHERE id = $1', [course]);

const people = {};
for (const [name, c] of [['lc', LC], ['gr', GR], ['nh', NH]]) {
  const p = people[name] = [id(), id(), id(), id(), id()];
  for (const [i, pid] of p.entries()) await db.query('INSERT INTO contacts VALUES ($1, $2, $3)', [pid, c.biz, `${name} person ${i}`]);
  const second = name === 'gr' ? 'deacons' : 'elders', third = name === 'gr' ? 'associate_ministers' : 'ministers';
  await db.query(`INSERT INTO church_leader_roles(business_id, contact_id, role, scope, status, answered_at) VALUES
    ($1, $2, 'pastor', '', 'active', now()), ($1, $3, $6, '', 'active', now()), ($1, $4, $7, '', 'invited', null),
    ($1, $5, 'team_leader', 'Hospitality Team', 'active', now())`, [c.biz, p[0], p[1], p[2], p[3], second, third]);
  const home = id();
  await db.query('INSERT INTO households VALUES ($1, $2)', [home, c.biz]);
  await db.query(`INSERT INTO church_shepherds(household_id, business_id, shepherd_contact_id, reason) VALUES ($1, $2, $3, 'nearby')`,
    [home, c.biz, p[1]]);
  await db.query(`INSERT INTO church_follow_ups(business_id, contact_id, card_key, path_kind, leader_contact_id, leader_role,
      steps, due_at) VALUES ($1, $2, 'form:connect', 'connect', $3, 'pastor', '[{"title":"Reach out"}]', now() + interval '1 day')`,
    [c.biz, p[4], p[0]]);
  if (name !== 'gr') {
    await db.query('INSERT INTO church_shepherd_settings(business_id, ministers) VALUES ($1, $2)', [c.biz, name === 'nh']);
  }
}
await db.query(`INSERT INTO church_area_places(business_id, kind, key, area) VALUES ($1, 'role', 'pastor', 'office'),
  ($1, 'team', 'hospitality team', 'people_care')`, [LC.biz]);

// ─── Fingerprints of what's there now, by the columns there now ─────────
const columns = async table => (await q(`SELECT column_name FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = $1 ORDER BY ordinal_position`, [table])).map(r => r.column_name);
const md5 = async (table, cols, where = 'true', args = []) => (await one(`SELECT md5(coalesce(string_agg(x, '|' ORDER BY x), ''))
  AS h, count(*)::int AS n FROM (SELECT row(${cols.map(c => `"${c}"`).join(', ')})::text AS x FROM public.${table} WHERE ${where}) s`,
  args));
const KEPT = ['church_leader_roles', 'church_shepherds', 'church_follow_ups', 'church_shepherd_settings',
              'church_role_defs', 'church_area_places'];
const before = {};
for (const t of KEPT) before[t] = { cols: await columns(t), sum: null };
for (const t of KEPT) before[t].sum = await md5(t, before[t].cols);
const settingsBiz = (await q('SELECT business_id FROM church_role_settings')).map(r => r.business_id);
const settingsCols = await columns('church_role_settings');
const settingsBefore = await md5('church_role_settings', settingsCols, 'business_id = any($1)', [settingsBiz]);
assert.deepEqual([before.church_leader_roles.sum.n, before.church_shepherds.sum.n, before.church_follow_ups.sum.n,
  before.church_shepherd_settings.sum.n, before.church_role_defs.sum.n], [12, 3, 3, 2, 174], 'the rows the fingerprints cover');

const schema = async () => JSON.stringify([
  await q(`SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns
    WHERE table_schema = 'public' ORDER BY 1, 2`),
  await q(`SELECT conrelid::regclass::text AS t, conname, pg_get_constraintdef(oid) AS d FROM pg_constraint
    WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2`),
  await q(`SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1`),
  await q(`SELECT tgrelid::regclass::text AS t, tgname, tgenabled, pg_get_triggerdef(oid) AS d FROM pg_trigger
    WHERE NOT tgisinternal ORDER BY 1, 2`),
  await q(`SELECT proname, pg_get_functiondef(oid) AS d, proacl::text AS acl FROM pg_proc
    WHERE pronamespace = 'public'::regnamespace ORDER BY 1`),
  await q(`SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants
    WHERE table_schema = 'public' ORDER BY 1, 2, 3`),
  await q(`SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1`),
  await q('SELECT tablename, policyname FROM pg_policies ORDER BY 1, 2')]);
const pre = await schema();

// ─── Run 1 ───────────────────────────────────────────────────────────────
await db.exec(await sql(MIGRATION));

// Today's rules, frozen: every role's switches are the oracle's.
for (const c of vectors.churches) {
  for (const r of c.roles) {
    const got = await one(`SELECT ${SWITCHES.join(', ')} FROM church_role_defs WHERE id = $1`, [church[c.church].role[r.key]]);
    assert.deepEqual(got, Object.fromEntries(SWITCHES.map(k => [k, r[k]])), `${c.church} ${r.key}`); checks++;
  }
}
// The office overseers: the Executive Pastor's role where a church has one active; never set elsewhere.
const keyOf = Object.fromEntries(Object.values(church).flatMap(c => Object.entries(c.role).map(([k, v]) => [v, k])));
for (const c of vectors.churches) {
  const row = await one('SELECT office_overseer_roles AS o, church_type, seeded_at FROM church_role_settings WHERE business_id = $1',
    [church[c.church].biz]);
  assert.deepEqual(row?.o ? row.o.map(i => keyOf[i]).sort() : null, c.office_overseer_roles, c.church); checks++;
  if (c.church === 'type:nondenom') {
    assert.deepEqual([row.church_type, row.seeded_at], ['', null], 'a made row leaves the library to fill as before'); checks++;
  }
}
assert.equal((await one('SELECT count(*)::int AS n FROM church_role_settings')).n, settingsBiz.length + 1); checks++;

// Nothing that was there changed: holders, shepherds, follow-ups, the
// shepherding settings, the roles' own columns, the area picks, the settings.
for (const t of KEPT) {
  assert.deepEqual(await md5(t, before[t].cols), before[t].sum, `${t} unchanged`); checks++;
}
assert.deepEqual(await md5('church_role_settings', settingsCols, 'business_id = any($1)', [settingsBiz]), settingsBefore); checks++;
assert.deepEqual(await q(`SELECT DISTINCT by, word FROM church_area_places`), [{ by: 'church', word: '' }]); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM church_departments')).n, 0, 'no departments made'); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM church_leader_roles WHERE answers_to_contact_id IS NOT NULL')).n, 0); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM church_role_settings WHERE pastor_from_cents IS NOT NULL
  OR board_over_cents IS NOT NULL OR pastor_yes_roles IS NOT NULL OR map_by IS NOT NULL OR map_at IS NOT NULL`)).n, 0); checks++;

// ─── Shape ───────────────────────────────────────────────────────────────
const col = async (t, c) => one(`SELECT data_type AS type, is_nullable AS nulls, column_default AS def FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2`, [t, c]);
assert.deepEqual(await col('church_role_defs', 'can_shepherd'), { type: 'boolean', nulls: 'YES', def: null }); checks++;
for (const c of ['can_oversee', 'can_lead', 'can_board_yes', 'can_see_all']) {
  assert.deepEqual(await col('church_role_defs', c), { type: 'boolean', nulls: 'NO', def: 'false' }, c); checks++;
}
assert.deepEqual(await col('church_role_defs', 'made_for'), { type: 'ARRAY', nulls: 'NO', def: `'{}'::text[]` }); checks++;
assert.deepEqual(await col('church_leader_roles', 'answers_to_contact_id'), { type: 'uuid', nulls: 'YES', def: null }); checks++;
for (const [c, type] of [['pastor_from_cents', 'integer'], ['board_over_cents', 'integer'], ['pastor_yes_roles', 'ARRAY'],
                         ['office_overseer_roles', 'ARRAY'], ['map_by', 'uuid'], ['map_at', 'timestamp with time zone']]) {
  assert.deepEqual(await col('church_role_settings', c), { type, nulls: 'YES', def: null }, c); checks++;
}
assert.deepEqual(await col('church_area_places', 'by'), { type: 'text', nulls: 'NO', def: `'church'::text` }); checks++;
assert.deepEqual(await col('church_area_places', 'word'), { type: 'text', nulls: 'NO', def: `''::text` }); checks++;
assert.deepEqual(await columns('church_departments'), ['id', 'business_id', 'name', 'leader_contact_id', 'overseer_contact_id',
  'support_duty', 'area', 'status', 'source', 'sort', 'updated_by', 'created_at', 'updated_at']); checks++;
assert.deepEqual(await columns('church_department_units'), ['id', 'business_id', 'department_id', 'kind', 'group_id', 'role_id',
  'board_id', 'worship_ministry_id', 'label', 'created_at']); checks++;
const cons = (await q(`SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace`)).map(r => r.conname);
for (const c of ['church_role_defs_made_for', 'church_leader_roles_answers_to_fkey', 'church_role_settings_levels',
                 'church_role_settings_pastor_from_range', 'church_role_settings_board_over_range',
                 'church_role_settings_pastor_yes_size', 'church_role_settings_office_overseer_size',
                 'church_departments_two', 'church_department_units_shape', 'church_area_places_by_known',
                 'church_area_places_word_len']) {
  assert.ok(cons.includes(c), c); checks++;
}
assert.equal((await one(`SELECT confdeltype FROM pg_constraint WHERE conname = 'church_leader_roles_answers_to_fkey'`)).confdeltype, 'n'); checks++;
const idx = Object.fromEntries((await q(`SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'`))
  .map(r => [r.indexname, r.indexdef]));
for (const [i, unique] of [['church_departments_name', true], ['church_departments_leader', false],
    ['church_departments_overseer', false], ['church_department_units_group', true], ['church_department_units_role', true],
    ['church_department_units_board', true], ['church_department_units_worship_ministry', true],
    ['church_department_units_label', true], ['church_department_units_department', false],
    ['church_leader_roles_answers_to', false]]) {
  assert.ok(idx[i], i); assert.equal(idx[i].startsWith('CREATE UNIQUE'), unique, i); checks++;
}
assert.match(idx.church_departments_name, /lower\(btrim\(name\)\).*WHERE \(status <> 'archived'::text\)/); checks++;
const trig = Object.fromEntries((await q(`SELECT tgrelid::regclass::text || '.' || tgname AS t, tgenabled AS on
  FROM pg_trigger WHERE NOT tgisinternal`)).map(r => [r.t, r.on]));
for (const t of ['church_role_defs.church_role_defs_guard', 'church_role_defs.church_role_defs_switches',
                 'church_leader_roles.church_answers_to_guard', 'church_leader_roles.church_leaders_same_business',
                 'church_role_settings.church_role_settings_guard', 'church_departments.church_map_same_business',
                 'church_department_units.church_map_same_business']) {
  assert.equal(trig[t], 'O', `${t} on`); checks++;
}

// The file's own closing check, and the ledger's Love City query, as written.
const text = await sql(MIGRATION);
const block = (from, to) => text.slice(text.indexOf(from), to ? text.indexOf(to) : undefined).split(/\r?\n/)
  .filter(l => l.startsWith('--   ')).map(l => l.slice(2)).join('\n').split(';').map(x => x.trim()).filter(Boolean);
const [cols15, rls2, trig2] = block('-- Check after applying', '-- Rollback');
assert.equal((await q(cols15)).length, 15, 'the closing check names 15 columns'); checks++;
assert.deepEqual((await q(rls2)).map(r => [r.relrowsecurity, r.policies, r.browser_reads]), [[true, 0, false], [true, 0, false]]); checks++;
assert.deepEqual((await q(trig2)).map(r => `${r.tgname} ${r.tgenabled}`).sort(),
  ['church_role_defs_guard O', 'church_role_defs_switches O']); checks++;
const ledger = await readFile(new URL('../docs/MIGRATIONS.md', import.meta.url), 'utf8');
const mismatch = ledger.match(/`(select count\(\*\) from church_role_defs d left join church_shepherd_settings s[^`]*);`/);
assert.ok(mismatch, 'the ledger keeps its Love City check');
for (const c of [LC, GR, NH]) {
  const n = (await one(mismatch[1].replaceAll("'009e9a2c-3e81-4bfc-a92a-205a8806aa99'", '$1'), [c.biz])).count;
  assert.equal(Number(n), 0, 'can_shepherd is the Shepherding page, the Ministers setting on or off'); checks++;
}

// ─── Server-only ────────────────────────────────────────────────────────
for (const t of ['church_departments', 'church_department_units']) {
  assert.deepEqual(await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS policies,
      has_table_privilege('anon', c.oid, 'select') OR has_table_privilege('anon', c.oid, 'insert') AS anon,
      has_table_privilege('authenticated', c.oid, 'select') OR has_table_privilege('authenticated', c.oid, 'insert') AS authed,
      has_table_privilege('service_role', c.oid, 'select') AND has_table_privilege('service_role', c.oid, 'insert')
        AND has_table_privilege('service_role', c.oid, 'update') AND has_table_privilege('service_role', c.oid, 'delete') AS server
    FROM pg_class c WHERE c.relname = $1`, [t]), { rls: true, policies: 0, anon: false, authed: false, server: true }, t); checks++;
}
const FUNCS = ['church_role_switches_today(text, text, text, text[])', 'church_role_defs_switches()', 'church_answers_to_guard()',
               'church_role_settings_guard()', 'church_map_same_business()'];
for (const f of FUNCS) {
  assert.deepEqual(await one(`SELECT has_function_privilege('anon', $1, 'execute') AS anon,
    has_function_privilege('authenticated', $1, 'execute') AS authed`, [`public.${f}`]), { anon: false, authed: false }, f); checks++;
}
const serverRuns = (await one(`SELECT has_function_privilege('service_role',
  'public.church_role_switches_today(text, text, text, text[])', 'execute') AS ok`)).ok;
assert.equal(serverRuns, true, 'the server can run the rule its own writes fire'); checks++;
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const t of ['church_departments', 'church_department_units']) await refuses(`SELECT * FROM ${t}`, [], /permission denied/);
  await refuses('SELECT can_shepherd FROM church_role_defs', [], /permission denied/);
  await refuses('SELECT answers_to_contact_id FROM church_leader_roles', [], /permission denied/);
  await refuses('SELECT office_overseer_roles FROM church_role_settings', [], /permission denied/);
  await refuses(`SELECT * FROM church_role_switches_today('senior', 'pastor', 'Pastor', '{}')`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

// ─── A church changes a switch; run 2 changes nothing ───────────────────
await db.query('UPDATE church_role_defs SET can_shepherd = true, can_oversee = true WHERE id = $1', [GR.role.deacons]);
await db.query(`UPDATE church_role_settings SET office_overseer_roles = '{}' WHERE business_id = $1`, [NH.biz]);
const ALL = ['church_role_defs', 'church_role_settings', 'church_leader_roles', 'church_area_places', 'church_departments',
             'church_department_units', 'church_shepherds', 'church_follow_ups', 'church_shepherd_settings'];
const data = async () => { const out = {}; for (const t of ALL) out[t] = await md5(t, await columns(t)); return out; };
const [schema1, data1] = [await schema(), await data()];
await db.exec(await sql(MIGRATION));
assert.equal(await schema(), schema1, 'a second run changes no schema'); checks++;
assert.deepEqual(await data(), data1, 'a second run changes no row'); checks++;
assert.deepEqual(await one('SELECT can_shepherd, can_oversee FROM church_role_defs WHERE id = $1', [GR.role.deacons]),
  { can_shepherd: true, can_oversee: true }, 'the church\'s flip stands'); checks++;
assert.deepEqual((await one('SELECT office_overseer_roles AS o FROM church_role_settings WHERE business_id = $1', [NH.biz])).o, []); checks++;

// The rest runs as the server does.
await db.exec('SET ROLE service_role');

// ─── A role added later gets today's rule unless it says otherwise ──────
for (const c of vectors.churches) {
  const biz = id();
  await db.query('INSERT INTO businesses VALUES ($1)', [biz]);
  for (const r of c.roles) {
    const got = await one(`INSERT INTO church_role_defs(business_id, key, title, job, handles, status, catalog_key)
      VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING ${SWITCHES.join(', ')}`, [biz, r.key, r.title, r.job, r.handles, r.status, r.catalog_key]);
    assert.deepEqual(got, Object.fromEntries(SWITCHES.map(k => [k, r[k]])), `added later: ${c.church} ${r.key}`); checks++;
  }
}
const said = await one(`INSERT INTO church_role_defs(business_id, key, title, job, handles, can_lead)
  VALUES ($1, 'ministers_two', 'Ministers', 'pastoral', '{baptism}', true) RETURNING ${SWITCHES.join(', ')}`, [LC.biz]);
assert.deepEqual(said, { can_shepherd: null, can_oversee: false, can_lead: true, can_board_yes: false, can_see_all: false,
  made_for: [] }, 'a role that says a switch keeps what it says'); checks++;

// ─── made_for stays part of handles ─────────────────────────────────────
assert.deepEqual((await one(`UPDATE church_role_defs SET handles = '{leftover}' WHERE id = $1 RETURNING made_for`,
  [LC.role.pastor])).made_for, [], 'today\'s handles edit still saves, and made_for follows'); checks++;
assert.deepEqual((await one(`UPDATE church_role_defs SET made_for = '{baptism,pastor_ask}', handles = '{pastor_ask,baptism}'
  WHERE id = $1 RETURNING made_for`, [LC.role.associate_pastor])).made_for, ['baptism', 'pastor_ask']); checks++;
assert.deepEqual((await one(`UPDATE church_role_defs SET made_for = '{care_need}' WHERE id = $1 RETURNING made_for`,
  [LC.role.elders])).made_for, []); checks++;
await db.exec('RESET ROLE');
await db.exec('ALTER TABLE church_role_defs DISABLE TRIGGER church_role_defs_switches');
await refuses(`UPDATE church_role_defs SET made_for = '{care_need}' WHERE id = $1`, [LC.role.elders], /church_role_defs_made_for/);
await db.exec('ALTER TABLE church_role_defs ENABLE TRIGGER church_role_defs_switches');
await db.exec('SET ROLE service_role');
await refuses('UPDATE church_role_defs SET reports_to = $2 WHERE id = $1', [LC.role.elders, GR.role.pastor], /not in this business/);

// ─── Answers to: a person of this church, never themselves ──────────────
const [lc0, lc1, lc2] = people.lc, gr0 = people.gr[0];
const holder = (await one(`SELECT id FROM church_leader_roles WHERE contact_id = $1`, [lc1])).id;
await refuses('UPDATE church_leader_roles SET answers_to_contact_id = contact_id WHERE id = $1', [holder], /answer to themselves/);
await refuses('UPDATE church_leader_roles SET answers_to_contact_id = $2 WHERE id = $1', [holder, gr0],
  /they answer to is not in this business/);
await refuses(`INSERT INTO church_leader_roles(business_id, contact_id, role, answers_to_contact_id) VALUES ($1, $2, 'elders', $3)`,
  [LC.biz, lc2, gr0], /they answer to is not in this business/);
await db.query('UPDATE church_leader_roles SET answers_to_contact_id = $2 WHERE id = $1', [holder, lc0]); checks++;
await db.query(`UPDATE church_leader_roles SET status = 'active' WHERE contact_id = $1`, [lc2]); checks++;   // other writes unchanged

// ─── Settings: the church's own roles, sane levels ──────────────────────
const set = (cols, args) => db.query(`UPDATE church_role_settings SET ${cols} WHERE business_id = $1`, [LC.biz, ...args]);
await refuses('UPDATE church_role_settings SET pastor_yes_roles = $2 WHERE business_id = $1', [LC.biz, [GR.role.pastor]],
  /pastor's yes is not in this business/);
await refuses('UPDATE church_role_settings SET office_overseer_roles = $2 WHERE business_id = $1', [LC.biz, [GR.role.pastor]],
  /oversee the office is not in this business/);
await refuses(`UPDATE church_role_settings SET office_overseer_roles = array[$2::uuid, null] WHERE business_id = $1`,
  [LC.biz, LC.role.executive_pastor], /oversee the office is not in this business/);
const fresh = id();
await db.query('INSERT INTO businesses VALUES ($1)', [fresh]);
await refuses('INSERT INTO church_role_settings(business_id, pastor_yes_roles) VALUES ($1, $2)', [fresh, [GR.role.pastor]],
  /pastor's yes is not in this business/);
await set('pastor_yes_roles = $2, pastor_from_cents = 20000, board_over_cents = 100000, map_at = now()', [[LC.role.pastor]]); checks++;
await refuses('UPDATE church_role_settings SET board_over_cents = 10000 WHERE business_id = $1', [LC.biz], /church_role_settings_levels/);
await refuses('UPDATE church_role_settings SET pastor_from_cents = -1 WHERE business_id = $1', [LC.biz], /pastor_from_range/);
await refuses('UPDATE church_role_settings SET office_overseer_roles = array_fill($2::uuid, array[21]) WHERE business_id = $1',
  [LC.biz, LC.role.pastor], /office_overseer_size/);
// A role deleted since never blocks a later save; a new pick is still checked.
await db.exec('RESET ROLE');
await db.query('DELETE FROM church_role_defs WHERE id = $1', [LC.role.executive_pastor]);
await db.exec('SET ROLE service_role');
await set(`church_type = 'nondenom', office_overseer_roles = office_overseer_roles || $2::uuid`, [LC.role.associate_pastor]); checks++;
await refuses('UPDATE church_role_settings SET office_overseer_roles = office_overseer_roles || $2::uuid WHERE business_id = $1',
  [LC.biz, NH.role.pastor], /oversee the office is not in this business/);

// ─── Departments and what hangs from them ──────────────────────────────
const g = {}, board = {}, wm = {};
for (const [name, c] of [['lc', LC], ['gr', GR]]) {
  g[name] = (await one(`INSERT INTO groups(business_id, name, kind) VALUES ($1, 'Youth', 'ministry') RETURNING id`, [c.biz])).id;
  board[name] = (await one(`INSERT INTO church_boards(business_id, name) VALUES ($1, 'Elder Board') RETURNING id`, [c.biz])).id;
  wm[name] = (await one(`INSERT INTO worship_ministries(business_id, name) VALUES ($1, 'Youth') RETURNING id`, [c.biz])).id;
}
const insert = async (table, row) => {
  const cols = Object.keys(row), vals = Object.values(row);
  return db.query(`INSERT INTO ${table}(${cols.join(', ')}) VALUES (${cols.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING id`, vals);
};
const dept = async (biz, name, more = {}) => (await insert('church_departments', { business_id: biz, name, ...more })).rows[0].id;
const unit = (kind, more = {}, d = youth, biz = LC.biz) =>
  insert('church_department_units', { business_id: biz, department_id: d, kind, ...more });
const no = async (promise, message) => { await assert.rejects(promise, message); checks++; };
await no(dept(LC.biz, 'Youth', { leader_contact_id: gr0 }), /That leader is not in this business/);
await no(dept(LC.biz, 'Youth', { overseer_contact_id: gr0 }), /That overseer is not in this business/);
await no(dept(LC.biz, 'Youth', { leader_contact_id: lc1, overseer_contact_id: lc1 }), /church_departments_two/);
const youth = await dept(LC.biz, 'Youth', { leader_contact_id: lc1, overseer_contact_id: lc0, support_duty: 'youth',
                                            area: 'kids_youth' }); checks++;
await no(dept(LC.biz, '  youth '), /duplicate key/);
await no(dept(LC.biz, '   '), /check constraint/);
await no(dept(LC.biz, 'Care', { support_duty: 'Youth Duty' }), /check constraint/);
await no(dept(LC.biz, 'Care', { area: 'nowhere' }), /check constraint/);
await no(dept(LC.biz, 'Care', { status: 'gone' }), /check constraint/);
await no(dept(LC.biz, 'Care', { source: 'import' }), /check constraint/);
await refuses('UPDATE church_departments SET business_id = $2 WHERE id = $1', [youth, GR.biz], /stays with its church/);
const oldPrayer = await dept(LC.biz, 'Prayer', { status: 'archived' });
await dept(LC.biz, 'prayer', { status: 'draft', source: 'chief' }); checks++;   // an archived department's name is free again
await no(unit('space', { label: 'youth' }, youth, GR.biz), /That department is not in this business/);
await no(unit('group', { group_id: g.gr }), /That group is not in this business/);
await no(unit('role', { role_id: GR.role.youth_minister }), /That role is not in this business/);
await no(unit('board', { board_id: board.gr }), /That board is not in this business/);
await no(unit('worship_ministry', { worship_ministry_id: wm.gr }), /That ministry is not in this business/);
await no(unit('group'), /church_department_units_shape/);                                  // a group unit with no group
await no(unit('space', { label: 'adults' }), /church_department_units_shape/);             // a space is youth or kids
await no(unit('serve_option'), /church_department_units_shape/);                           // a serve option has a name
await no(unit('check_line', { group_id: g.lc, label: 'Youth' }), /church_department_units_shape/);   // a loose one links nothing
await no(unit('role', { role_id: LC.role.youth_pastor, group_id: g.lc }), /church_department_units_shape/);   // one thing a unit
for (const [kind, more] of [['group', { group_id: g.lc }], ['role', { role_id: LC.role.youth_pastor }],
    ['board', { board_id: board.lc }], ['worship_ministry', { worship_ministry_id: wm.lc }],
    ['serve_option', { label: 'Youth Ministry (YWD)' }], ['space', { label: 'youth' }], ['check_line', { label: 'Youth' }]]) {
  await unit(kind, more);
}
assert.equal((await one('SELECT count(*)::int AS n FROM church_department_units WHERE department_id = $1', [youth])).n, 7); checks++;
// One department per thing.
const care = await dept(LC.biz, 'Care', { leader_contact_id: lc2, overseer_contact_id: lc0 });
await no(unit('group', { group_id: g.lc }, care), /duplicate key/);
await no(unit('role', { role_id: LC.role.youth_pastor }, care), /duplicate key/);
await no(unit('serve_option', { label: 'youth ministry (ywd)' }, care), /duplicate key/);
await no(unit('space', { label: 'youth' }, care), /duplicate key/);
await unit('space', { label: 'kids' }, care); checks++;
// What goes takes its link; a person who goes leaves the seat empty; a church that goes takes its map.
await db.query('DELETE FROM groups WHERE id = $1', [g.lc]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_department_units WHERE kind = 'group' AND business_id = $1`, [LC.biz])).n, 0); checks++;
await db.exec('RESET ROLE');
await db.query('DELETE FROM contacts WHERE id = $1', [lc0]);
assert.deepEqual(await one('SELECT leader_contact_id AS l, overseer_contact_id AS o FROM church_departments WHERE id = $1', [youth]),
  { l: lc1, o: null }); checks++;
assert.equal((await one('SELECT answers_to_contact_id AS a FROM church_leader_roles WHERE id = $1', [holder])).a, null); checks++;
await db.query('DELETE FROM church_departments WHERE id = $1', [care]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_department_units WHERE department_id = $1', [care])).n, 0); checks++;
await db.query('DELETE FROM businesses WHERE id = $1', [LC.biz]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_departments WHERE id = any($1)', [[youth, oldPrayer]])).n, 0); checks++;

// ─── Areas: a stored guess is marked as one ─────────────────────────────
await db.query(`INSERT INTO church_area_places(business_id, kind, key, area, by, word) VALUES ($1, 'role', 'deacons', 'people_care', 'guess', 'deacon')`,
  [GR.biz]); checks++;
await refuses(`INSERT INTO church_area_places(business_id, kind, key, area, by) VALUES ($1, 'role', 'pastor', 'office', 'chief')`,
  [GR.biz], /church_area_places_by_known/);
await refuses(`INSERT INTO church_area_places(business_id, kind, key, area, word) VALUES ($1, 'role', 'pastor', 'office', repeat('w', 41))`,
  [GR.biz], /church_area_places_word_len/);

// ─── The rollback block puts the schema back as it was ──────────────────
await db.exec('RESET ROLE');
const rollback = block('-- Rollback');
assert.deepEqual([rollback[0], rollback.at(-1)], ['begin', 'commit'], 'the rollback is one transaction');
await db.exec(rollback.join(';\n') + ';');
assert.equal(await schema(), pre, 'the rollback leaves the schema as it found it'); checks++;

console.log(`church map db: ${checks} checks passed`);
