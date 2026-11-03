// The church leaders map's step 2 data, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-05-church-map-step2.sql over step 1's file and the
// church migrations it builds on. Four churches go in first. Love City (by its
// real id, so the ledger's queries run as written), Grace and New Hope have
// roles of every source, settings, holders and departments, among them a
// department a failed save left (an office draft with nothing hung from it)
// and one of each kind that isn't. Riverside has no settings row, no roles and
// no holders. The file marks exactly the half-made saves unfinished, and every
// row that was there comes out byte for byte as it went in, by the columns it
// had. Running the file again changes nothing, schema or data, even after a
// church saved a draft on purpose. The new values are taken and wrong ones
// refused; the browser's roles can't read or write any of it; the ledger's
// checks and the file's own closing check run as written; and the rollback
// puts the schema back as it found it, refusing while a role says 'template'.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_map_step2_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const MIGRATION = 'APPLY-2026-11-05-church-map-step2.sql';
const LOVE_CITY = '009e9a2c-3e81-4bfc-a92a-205a8806aa99';
const db = new PGlite();
let checks = 0;
const q = async (text, args) => (await db.query(text, args)).rows;
const one = async (text, args) => (await q(text, args))[0];
const ok = (got, want, why) => { assert.deepEqual(got, want, why); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
let n = 0;
const id = () => `${(++n).toString(16).padStart(8, '0')}-0000-4000-8000-000000000000`;

// What Supabase already has, as little of it as these migrations need: the
// browser's roles get every new table unless a file revokes them, as there.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
  CREATE SCHEMA auth;
  CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, name text);
  CREATE TABLE public.academy_courses(id uuid PRIMARY KEY, business_id uuid NOT NULL, title text);
  CREATE TABLE public.ministry_care_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id), submission jsonb NOT NULL DEFAULT '{}');
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid());
  CREATE TABLE public.groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, name text NOT NULL,
    kind text NOT NULL DEFAULT 'small_group', active boolean NOT NULL DEFAULT true);
  GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;`);
for (const f of ['APPLY-2026-10-17-church-leaders.sql', 'APPLY-2026-10-17-church-leaders-trigger-fix.sql',
                 'APPLY-2026-10-17-church-role-library.sql', 'APPLY-2026-10-23-church-areas.sql',
                 'APPLY-2026-10-27-church-board.sql', 'APPLY-2026-10-26-worship-ministries.sql',
                 'APPLY-2026-11-04-church-map.sql']) await db.exec(await sql(f));

// ─── The churches before the file ───────────────────────────────────────
const users = [id(), id(), id()];                 // an office login, Chief's turn, the owner
for (const u of users) await db.query('INSERT INTO auth.users VALUES ($1)', [u]);
const insert = async (table, row) => {
  const cols = Object.keys(row);
  return (await one(`INSERT INTO ${table}(${cols.join(', ')}) VALUES (${cols.map((_, i) => `$${i + 1}`).join(', ')})
    RETURNING id`, Object.values(row)))?.id;
};
const ROLES = [   // key, title, job, handles, status, source: every source a role had before
  ['pastor', 'Lead Pastor', 'senior', ['pastor_ask', 'baptism'], 'active', 'catalog'],
  ['executive_pastor', 'Executive Pastor', 'pastoral', [], 'active', 'catalog'],
  ['elders', 'Elders', 'pastoral', ['care_need'], 'active', 'catalog'],
  ['youth_pastor', 'Youth Pastor', 'ministry', [], 'active', 'catalog'],
  ['team_leader', 'Team leader', 'team', [], 'active', 'legacy'],
  ['prophets', 'Prophets', 'pastoral', [], 'active', 'custom'],
  ['greeters', 'Greeters', 'welcome', [], 'draft', 'chief'],
  ['old_board', 'Old Board', 'care', [], 'archived', 'custom']];
const church = {};
for (const [name, type] of [['lc', 'nondenom'], ['gr', 'baptist'], ['nh', 'nondenom']]) {
  const c = church[name] = { biz: name === 'lc' ? LOVE_CITY : id(), role: {}, p: [] };
  await db.query('INSERT INTO businesses VALUES ($1)', [c.biz]);
  for (let i = 0; i < 6; i++) {
    c.p.push(id());
    await db.query('INSERT INTO contacts VALUES ($1, $2, $3)', [c.p[i], c.biz, `${name} person ${i}`]);
  }
  for (const [i, [key, title, job, handles, status, source]] of ROLES.entries()) {
    c.role[key] = await insert('church_role_defs', { business_id: c.biz, key, title, job, handles, status, source,
      catalog_key: source === 'catalog' ? key : '', sort: i * 10 });
  }
  await db.query(`UPDATE church_role_defs SET reports_to = $2 WHERE business_id = $1 AND id <> $2`, [c.biz, c.role.pastor]);
  await db.query(`INSERT INTO church_role_settings(business_id, church_type, guessed_type, set_by, seeded_at, pastor_from_cents,
      board_over_cents, office_overseer_roles) VALUES ($1, $2, $2, 'chief', now(), $3, $4, $5)`,
    [c.biz, type, name === 'gr' ? 20000 : null, name === 'gr' ? 100000 : null, name === 'nh' ? [c.role.executive_pastor] : null]);
  await db.query(`INSERT INTO church_leader_roles(business_id, contact_id, role, scope, status, answered_at) VALUES
    ($1, $2, 'pastor', '', 'active', now()), ($1, $3, 'elders', '', 'active', now()), ($1, $4, 'youth_pastor', '', 'active', now()),
    ($1, $5, 'team_leader', 'Hospitality Team', 'active', now()), ($1, $6, 'executive_pastor', '', 'invited', null)`,
    [c.biz, ...c.p.slice(0, 5)]);
  c.group = await insert('groups', { business_id: c.biz, name: 'Youth', kind: 'ministry' });
  c.board = await insert('church_boards', { business_id: c.biz, name: 'Elder Board' });
  c.wm = await insert('worship_ministries', { business_id: c.biz, name: 'Worship' });
  await db.query(`INSERT INTO church_area_places(business_id, kind, key, area) VALUES ($1, 'role', 'prophets', 'people_care')`, [c.biz]);
}
const { lc: LC, gr: GR, nh: NH } = church;
await db.query(`UPDATE church_leader_roles SET answers_to_contact_id = $2 WHERE business_id = $1 AND role = 'elders'`, [LC.biz, LC.p[4]]);
const RV = { biz: id() };                        // Riverside: nobody set it up
await db.query('INSERT INTO businesses VALUES ($1)', [RV.biz]);
await db.query(`INSERT INTO contacts SELECT gen_random_uuid(), $1, 'rv person ' || g FROM generate_series(1, 60) g`, [RV.biz]);

// Departments, each kind once. Only an office draft with nothing hung from it is a half-made save.
const AT = '2026-11-03 15:00:00+00';
const dept = (c, name, more = {}) => insert('church_departments', { business_id: c.biz, name, updated_by: users[0],
  updated_at: AT, ...more });
const unit = (c, department_id, kind, more = {}) => insert('church_department_units', { business_id: c.biz, department_id, kind, ...more });
const lcYouth = await dept(LC, 'Youth', { leader_contact_id: LC.p[2], overseer_contact_id: LC.p[1], support_duty: 'youth',
                                          area: 'kids_youth' });
await unit(LC, lcYouth, 'group', { group_id: LC.group });
await unit(LC, lcYouth, 'role', { role_id: LC.role.youth_pastor });
await unit(LC, lcYouth, 'space', { label: 'youth' });
const halfLC = await dept(LC, 'Outreach', { status: 'draft', updated_at: '2026-11-03 16:20:05+00' });   // half made
const retryLC = await dept(LC, 'Care', { status: 'draft' });        // a retry whose last "make it active" failed
await unit(LC, retryLC, 'serve_option', { label: 'Care Team' });
const others = [lcYouth, retryLC,
  await dept(LC, 'Men\'s Ministry', { status: 'draft', source: 'chief' }),
  await dept(LC, 'Media & Production', { status: 'draft', source: 'template' }),
  await dept(LC, 'Old Prayer', { status: 'archived' }),
  await dept(LC, 'Welcome')];                                         // active on purpose, nothing in it yet
const grYouth = await dept(GR, 'Youth', { overseer_contact_id: GR.p[1] });
await unit(GR, grYouth, 'serve_option', { label: 'Youth Ministry' });
const halfGR = await dept(GR, 'Missions', { status: 'draft', updated_by: users[2], updated_at: '2026-11-04 09:30:00+00' });
const nh = {};
for (const [name, kind, more] of [['Worship', 'worship_ministry', { worship_ministry_id: NH.wm }],
    ['Youth', 'group', { group_id: NH.group }], ['Kids', 'space', { label: 'kids' }], ['Care', 'board', { board_id: NH.board }]]) {
  nh[name] = await dept(NH, name, { leader_contact_id: NH.p[1], overseer_contact_id: NH.p[0] });
  await unit(NH, nh[name], kind, more);
}
await unit(NH, nh.Care, 'check_line', { label: 'Care' });
others.push(grYouth, ...Object.values(nh));
const HALF = [halfLC, halfGR].sort();

// ─── Fingerprints of what's there now, by the columns there now ─────────
const tables = async () => (await q(`SELECT n.nspname || '.' || c.relname AS t FROM pg_class c JOIN pg_namespace n
  ON n.oid = c.relnamespace WHERE c.relkind = 'r' AND n.nspname IN ('public', 'auth') ORDER BY 1`)).map(r => r.t);
const columns = async t => (await q(`SELECT column_name FROM information_schema.columns WHERE table_schema = $1
  AND table_name = $2 ORDER BY ordinal_position`, t.split('.'))).map(r => r.column_name);
const md5 = async (t, cols) => one(`SELECT md5(coalesce(string_agg(x, '|' ORDER BY x), '')) AS h, count(*)::int AS n
  FROM (SELECT row(${cols.map(c => `"${c}"`).join(', ')})::text AS x FROM ${t}) s`);
const before = {};
for (const t of await tables()) before[t] = { cols: await columns(t) };
for (const t of Object.keys(before)) before[t].sum = await md5(t, before[t].cols);
ok(['businesses', 'contacts', 'church_role_defs', 'church_role_settings', 'church_leader_roles', 'church_departments',
    'church_department_units'].map(t => before[`public.${t}`].sum.n), [4, 78, 24, 3, 15, 13, 10], 'the rows the fingerprints cover');

const schema = async () => ({
  columns: await q(`SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns
    WHERE table_schema = 'public' ORDER BY 1, 2`),
  constraints: await q(`SELECT conrelid::regclass::text AS t, conname, pg_get_constraintdef(oid) AS d FROM pg_constraint
    WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2`),
  indexes: await q(`SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1`),
  triggers: await q(`SELECT tgrelid::regclass::text AS t, tgname, tgenabled, pg_get_triggerdef(oid) AS d FROM pg_trigger
    WHERE NOT tgisinternal ORDER BY 1, 2`),
  functions: await q(`SELECT proname, pg_get_functiondef(oid) AS d, proacl::text AS acl FROM pg_proc
    WHERE pronamespace = 'public'::regnamespace ORDER BY 1`),
  grants: await q(`SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants
    WHERE table_schema = 'public' ORDER BY 1, 2, 3`),
  rls: await q(`SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1`),
  policies: await q('SELECT tablename, policyname FROM pg_policies ORDER BY 1, 2')});
const pre = await schema();

// ─── The ledger's checks before applying, as written ────────────────────
const ledger = await readFile(new URL('../docs/MIGRATIONS.md', import.meta.url), 'utf8');
const row = ledger.split(/\r?\n/).find(l => l.startsWith(`| \`supabase/${MIGRATION}\``));
assert.ok(row, 'the ledger has the row');
const queries = [...row.matchAll(/`(select [^`]*?);?`/gi)].map(m => m[1]);
assert.equal(queries.length, 8, 'the ledger row has four checks before and four after');
const [srcCheck, deptTriggers, toMark, notThere, lcSettings, lcTemplates, marked, empty] = queries;
ok(await q(srcCheck), [{ conname: 'church_role_defs_source_check', pg_get_constraintdef:
  "CHECK ((source = ANY (ARRAY['catalog'::text, 'custom'::text, 'legacy'::text, 'chief'::text])))" }],
  'the source check by its real name, with the four values it has');
ok((await q(deptTriggers)).map(r => r.tgname), ['church_map_same_business'], 'the one trigger the backfill fires');
ok((await q(toMark)).map(r => r.id).sort(), HALF, 'the pre-check lists exactly the half-made saves');
ok(await one(notThere), { changes: null, tracks: null });

// ─── Run 1 ───────────────────────────────────────────────────────────────
await db.exec(await sql(MIGRATION));

// Nothing that was there changed, by the columns it had: every table, every row.
for (const t of Object.keys(before)) ok(await md5(t, before[t].cols), before[t].sum, `${t} unchanged`);
// The backfill marked exactly the half-made saves, each with its own last save.
ok(await q(`SELECT id, unfinished_at = updated_at AS same FROM church_departments WHERE unfinished_at IS NOT NULL
  ORDER BY id`), HALF.map(i => ({ id: i, same: true })), 'only an office draft with nothing hung from it');
ok((await q(`SELECT id FROM church_departments WHERE unfinished_at IS NULL ORDER BY id`)).map(r => r.id), others.sort());
// Every other new column is unset; every church already seeded reads as confirmed; nothing is made.
for (const t of ['church_departments', 'church_role_defs']) {
  ok((await one(`SELECT count(*)::int AS n FROM ${t} WHERE template_key IS NOT NULL OR template_version IS NOT NULL`)).n, 0, t);
}
ok(await q(`SELECT DISTINCT seeded_as, confirmed_at, shape_key, shape_version FROM church_role_settings`),
  [{ seeded_as: 'active', confirmed_at: null, shape_key: null, shape_version: null }]);
ok((await one(`SELECT count(*)::int AS n FROM church_role_settings WHERE business_id = $1`, [RV.biz])).n, 0,
  'Riverside still has no settings row');
ok((await one(`SELECT ((SELECT count(*) FROM church_map_changes) + (SELECT count(*) FROM church_setup_tracks))::int AS n`)).n, 0);

// ─── Shape ───────────────────────────────────────────────────────────────
const col = async (t, c) => one(`SELECT data_type AS type, is_nullable AS nulls, column_default AS def FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2`, [t, c]);
for (const t of ['church_departments', 'church_role_defs']) {
  ok(await col(t, 'template_key'), { type: 'text', nulls: 'YES', def: null }, t);
  ok(await col(t, 'template_version'), { type: 'smallint', nulls: 'YES', def: null }, t);
}
const TZ = 'timestamp with time zone';
ok(await col('church_departments', 'unfinished_at'), { type: TZ, nulls: 'YES', def: null });
ok(await col('church_role_settings', 'seeded_as'), { type: 'text', nulls: 'NO', def: `'active'::text` });
ok(await col('church_role_settings', 'confirmed_at'), { type: TZ, nulls: 'YES', def: null });
ok(await col('church_role_settings', 'shape_key'), { type: 'text', nulls: 'YES', def: null });
ok(await col('church_role_settings', 'shape_version'), { type: 'smallint', nulls: 'YES', def: null });
ok(await columns('public.church_map_changes'), ['id', 'business_id', 'status', 'origin', 'phase', 'said', 'parts', 'money',
  'made_by', 'made_at', 'applied_by', 'applied_at', 'undoes', 'undone_at', 'error']);
ok(await columns('public.church_setup_tracks'), ['business_id', 'status', 'started_from', 'current_phase', 'phases', 'asks',
  'rhythm', 'session_log', 'turns', 'launched_at', 'launched_by', 'created_at', 'updated_at']);
const cons = (await q(`SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace`)).map(r => r.conname);
for (const c of ['church_departments_template_key_shape', 'church_departments_template_version_range',
                 'church_role_defs_template_key_shape', 'church_role_defs_template_version_range', 'church_role_defs_source_check',
                 'church_role_settings_seeded_as_known', 'church_role_settings_shape_key_shape',
                 'church_role_settings_shape_version_range', 'church_map_changes_applied']) {
  assert.ok(cons.includes(c), c); checks++;
}
ok((await q(`SELECT conname FROM pg_constraint WHERE conrelid = 'public.church_role_defs'::regclass AND contype = 'c'
  AND pg_get_constraintdef(oid) ~ 'source'`)).map(r => r.conname), ['church_role_defs_source_check'], 'one source check');
ok(await q(`SELECT conrelid::regclass::text AS t, a.attname AS col, confrelid::regclass::text AS ref, confdeltype AS del
  FROM pg_constraint k JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
  WHERE contype = 'f' AND conrelid IN ('public.church_map_changes'::regclass, 'public.church_setup_tracks'::regclass) ORDER BY 1, 2`), [
  { t: 'church_map_changes', col: 'applied_by', ref: 'auth.users', del: 'n' },
  { t: 'church_map_changes', col: 'business_id', ref: 'businesses', del: 'c' },
  { t: 'church_map_changes', col: 'made_by', ref: 'auth.users', del: 'n' },
  { t: 'church_map_changes', col: 'undoes', ref: 'church_map_changes', del: 'n' },
  { t: 'church_setup_tracks', col: 'business_id', ref: 'businesses', del: 'c' },
  { t: 'church_setup_tracks', col: 'launched_by', ref: 'auth.users', del: 'n' }]);
const idx = Object.fromEntries((await q(`SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'`))
  .map(r => [r.indexname, r.indexdef]));
assert.match(idx.church_map_changes_recent, /^CREATE INDEX .*\(business_id, made_at DESC\)$/); checks++;
assert.match(idx.church_map_changes_pending, /\(business_id\) WHERE \(status = 'pending'::text\)$/); checks++;
assert.match(idx.church_map_changes_undoes, /\(undoes\) WHERE \(undoes IS NOT NULL\)$/); checks++;
assert.match(idx.church_setup_tracks_pkey, /^CREATE UNIQUE INDEX .*\(business_id\)$/); checks++;
const post = await schema();
ok(post.triggers, pre.triggers, 'no trigger added or changed');
ok(post.functions, pre.functions, 'no function added or changed');
ok(post.policies, pre.policies, 'no policy');

// The file's own closing check, and the ledger's checks after applying, as written.
const text = await sql(MIGRATION);
const block = (from, to) => text.slice(text.indexOf(from), to ? text.indexOf(to) : undefined).split(/\r?\n/)
  .filter(l => l.startsWith('--   ')).map(l => l.slice(2)).join('\n');
const statements = s => s.split(';').map(x => x.trim()).filter(Boolean);
const [cols9, srcDef, rls2, markedRows] = statements(block('-- Check after applying', '-- Rollback'));
ok((await q(cols9)).length, 9, 'the closing check names 9 columns');
assert.match((await one(srcDef)).pg_get_constraintdef, /'catalog'.*'custom'.*'legacy'.*'chief'.*'template'::text\]/); checks++;
ok((await q(rls2)).map(r => [r.relname, r.relrowsecurity, Number(r.policies), r.browser_reads]),
  [['church_map_changes', true, 0, false], ['church_setup_tracks', true, 0, false]]);
ok((await q(markedRows)).map(r => r.id).sort(), HALF);
ok(await q(srcCheck), [{ conname: 'church_role_defs_source_check', pg_get_constraintdef:
  "CHECK ((source = ANY (ARRAY['catalog'::text, 'custom'::text, 'legacy'::text, 'chief'::text, 'template'::text])))" }]);
ok(await q(lcSettings), [{ seeded_as: 'active', confirmed_at: null, shape_key: null, shape_version: null }], 'Love City is confirmed');
ok(Number((await one(lcTemplates)).count), 0, 'Love City has no role from a ready-made');
ok(Number((await one(marked)).count), HALF.length, 'as many marked as the pre-check listed');
ok(Object.values(await one(empty)).map(Number), [0, 0]);

// ─── Server-only ────────────────────────────────────────────────────────
for (const t of ['church_map_changes', 'church_setup_tracks']) {
  ok(await one(`SELECT c.relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS policies,
      has_table_privilege('anon', c.oid, 'select, insert, update, delete') AS anon,
      has_table_privilege('authenticated', c.oid, 'select, insert, update, delete') AS authed,
      has_table_privilege('service_role', c.oid, 'select') AND has_table_privilege('service_role', c.oid, 'insert')
        AND has_table_privilege('service_role', c.oid, 'update') AND has_table_privilege('service_role', c.oid, 'delete') AS server
    FROM pg_class c WHERE c.relname = $1`, [t]), { rls: true, policies: 0, anon: false, authed: false, server: true }, t);
}
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const t of ['church_map_changes', 'church_setup_tracks']) {
    await refuses(`SELECT * FROM ${t}`, [], /permission denied/);
    await refuses(`INSERT INTO ${t}(business_id) VALUES ($1)`, [RV.biz], /permission denied/);
  }
  await refuses('SELECT unfinished_at FROM church_departments', [], /permission denied/);
  await refuses('SELECT template_key FROM church_role_defs', [], /permission denied/);
  await refuses('SELECT seeded_as FROM church_role_settings', [], /permission denied/);
  await db.exec('RESET ROLE');
}

// The rest runs as the server does.
await db.exec('SET ROLE service_role');

// ─── Roles and departments from a ready-made; every old source still fits ──
for (const s of ['catalog', 'custom', 'legacy', 'chief']) {
  await insert('church_role_defs', { business_id: GR.biz, key: `new_${s}`, title: `New ${s}`, job: 'team', source: s }); checks++;
}
const role = (key, more) => insert('church_role_defs', { business_id: RV.biz, key, title: 'Usher Board', job: 'welcome',
  status: 'draft', source: 'template', template_key: 'ame.usher_board', template_version: 1, ...more });
ok((await one(`SELECT source, template_key, template_version, can_lead FROM church_role_defs WHERE id = $1`, [await role('usher_board')])),
  { source: 'template', template_key: 'ame.usher_board', template_version: 1, can_lead: true }, 'a copy, with today\'s switches');
await refuses(`INSERT INTO church_role_defs(business_id, key, title, job, source) VALUES ($1, 'imported', 'Imported', 'team', 'import')`,
  [GR.biz], /church_role_defs_source_check/);
await assert.rejects(role('a', { template_key: 'AME Usher Board' }), /church_role_defs_template_key_shape/); checks++;
await assert.rejects(role('b', { template_key: 'x' }), /church_role_defs_template_key_shape/); checks++;
await assert.rejects(role('c', { template_version: 0 }), /church_role_defs_template_version_range/); checks++;
await assert.rejects(role('d', { template_version: 1000 }), /church_role_defs_template_version_range/); checks++;
const rvYouth = await dept(RV, 'Youth', { status: 'draft', source: 'template', template_key: 'youth', template_version: 2 }); checks++;
await assert.rejects(dept(RV, 'Kids', { template_key: 'kids-church' }), /church_departments_template_key_shape/); checks++;
await assert.rejects(dept(RV, 'Kids', { template_version: 0 }), /church_departments_template_version_range/); checks++;
// A library seeded as drafts, from a shape (B7's new church).
await db.query(`INSERT INTO church_role_settings(business_id, church_type, seeded_at, seeded_as, shape_key, shape_version)
  VALUES ($1, 'ame', now(), 'draft', 'pastor_deacons', 1)`, [RV.biz]); checks++;
const rvSet = (cols, args) => db.query(`UPDATE church_role_settings SET ${cols} WHERE business_id = $1`, [RV.biz, ...args]);
await assert.rejects(rvSet(`seeded_as = 'pending'`, []), /church_role_settings_seeded_as_known/); checks++;
await assert.rejects(rvSet(`seeded_as = null`, []), /null value/); checks++;
await assert.rejects(rvSet(`shape_key = 'pastor.deacons'`, []), /church_role_settings_shape_key_shape/); checks++;
await assert.rejects(rvSet(`shape_version = 1000`, []), /church_role_settings_shape_version_range/); checks++;

// ─── A change to a map ──────────────────────────────────────────────────
const PART = '[{"kind":"role","id":"r","before":{"can_oversee":false},"after":{"can_oversee":true}}]';
const change = (more = {}) => insert('church_map_changes', { business_id: LC.biz, status: 'pending', origin: 'chief', parts: PART,
  ...more });
const first = await change({ phase: 'leaders', said: 'Deacons oversee Youth', made_by: users[1] });
ok(await one(`SELECT said, money, error, applied_at, undoes, made_at IS NOT NULL AS stamped FROM church_map_changes WHERE id = $1`,
  [first]), { said: 'Deacons oversee Youth', money: false, error: '', applied_at: null, undoes: null, stamped: true });
await change({ origin: 'office', status: 'failed', error: 'Youth\'s overseer could not be saved' }); checks++;   // no phase
for (const [more, message] of [
    [{ status: 'done' }, /church_map_changes_status_check/], [{ origin: 'sheet' }, /church_map_changes_origin_check/],
    [{ phase: 'money' }, /church_map_changes_phase_check/], [{ parts: '{}' }, /church_map_changes_parts_check/],
    [{ parts: '"x"' }, /church_map_changes_parts_check/], [{ parts: '[]' }, /church_map_changes_parts_check/],
    [{ parts: JSON.stringify(Array(81).fill({ kind: 'role' })) }, /church_map_changes_parts_check/],
    [{ said: 'x'.repeat(401) }, /church_map_changes_said_check/], [{ error: 'x'.repeat(401) }, /church_map_changes_error_check/],
    [{ status: 'applied' }, /church_map_changes_applied/], [{ status: 'undone' }, /church_map_changes_applied/]]) {
  await assert.rejects(change(more), message); checks++;
}
// Applied, then undone by a change of its own.
await db.query(`UPDATE church_map_changes SET status = 'applied', applied_by = $2, applied_at = now() WHERE id = $1`, [first, users[2]]);
const undo = await change({ origin: 'office', status: 'applied', applied_by: users[2], applied_at: new Date(), undoes: first });
await db.query(`UPDATE church_map_changes SET status = 'undone', undone_at = now() WHERE id = $1`, [first]); checks++;
await refuses(`INSERT INTO church_map_changes(business_id, status, origin, parts, undoes) VALUES ($1, 'pending', 'chief', $2, $3)`,
  [LC.biz, PART, id()], /foreign key/);

// ─── A church's setup sessions ──────────────────────────────────────────
await db.query('INSERT INTO church_setup_tracks(business_id) VALUES ($1)', [RV.biz]);
ok(await one(`SELECT status, started_from, current_phase, phases, asks, rhythm, session_log, turns, launched_at
  FROM church_setup_tracks WHERE business_id = $1`, [RV.biz]), { status: 'in_progress', started_from: 'blank',
  current_phase: 'church', phases: {}, asks: [], rhythm: {}, session_log: [], turns: 0, launched_at: null });
await refuses('INSERT INTO church_setup_tracks(business_id) VALUES ($1)', [RV.biz], /duplicate key/);   // one a church
const track = (cols, args = []) => db.query(`UPDATE church_setup_tracks SET ${cols} WHERE business_id = $1`, [RV.biz, ...args]);
for (const from of ['live', 'shape:pastor_deacons']) { await track('started_from = $2', [from]); checks++; }
await track(`current_phase = 'leaders', phases = '{"church":{"state":"saved","note":"Pastor and deacons"}}', turns = 18,
  asks = '[{"person":"p","role":"usher_board"}]', session_log = '[{"at":"2026-11-05"}]', rhythm = '{"weekly":"Tue"}'`); checks++;
for (const [cols, message] of [[`status = 'done'`, /church_setup_tracks_status_check/],
    [`started_from = 'shape:Pastor'`, /church_setup_tracks_started_from_check/],
    [`started_from = 'somewhere'`, /church_setup_tracks_started_from_check/],
    [`current_phase = 'money'`, /church_setup_tracks_current_phase_check/],
    [`phases = '[]'`, /church_setup_tracks_phases_check/], [`asks = '{}'`, /church_setup_tracks_asks_check/],
    [`asks = (SELECT jsonb_agg(g) FROM generate_series(1, 201) g)`, /church_setup_tracks_asks_check/],
    [`rhythm = '[]'`, /church_setup_tracks_rhythm_check/], [`session_log = '{}'`, /church_setup_tracks_session_log_check/],
    [`turns = 1000`, /church_setup_tracks_turns_check/], [`turns = -1`, /church_setup_tracks_turns_check/]]) {
  await assert.rejects(track(cols), message); checks++;
}
await track(`status = 'launched', launched_at = now(), launched_by = $2`, [users[2]]); checks++;

// The guards from step 1 still hold.
await refuses('UPDATE church_departments SET leader_contact_id = $2 WHERE id = $1', [lcYouth, GR.p[0]], /That leader is not in this business/);

// A login that goes leaves its changes with no one named; a change that goes frees its undo; a church takes everything.
await db.exec('RESET ROLE');
await db.query('DELETE FROM auth.users WHERE id = $1', [users[1]]);
ok((await one('SELECT made_by FROM church_map_changes WHERE id = $1', [first])).made_by, null);
const gone = id();
await db.query('INSERT INTO businesses VALUES ($1)', [gone]);
const goneChange = await insert('church_map_changes', { business_id: gone, status: 'pending', origin: 'chief', parts: PART });
await insert('church_map_changes', { business_id: gone, status: 'pending', origin: 'office', parts: PART, undoes: goneChange });
await db.query('INSERT INTO church_setup_tracks(business_id) VALUES ($1)', [gone]);
await db.query('DELETE FROM church_map_changes WHERE id = $1', [first]);
ok((await one('SELECT undoes FROM church_map_changes WHERE id = $1', [undo])).undoes, null);
await db.query('DELETE FROM businesses WHERE id = $1', [gone]);
ok((await one(`SELECT ((SELECT count(*) FROM church_map_changes WHERE business_id = $1)
  + (SELECT count(*) FROM church_setup_tracks WHERE business_id = $1))::int AS n`, [gone])).n, 0);

// ─── A church saves a draft on purpose, a retry finishes one; run 2 changes nothing ──
const onPurpose = await dept(GR, 'Prayer', { status: 'draft' });
await db.query(`UPDATE church_departments SET status = 'active', unfinished_at = null WHERE id = $1`, [halfGR]);
const data = async () => { const out = {}; for (const t of await tables()) out[t] = await md5(t, await columns(t)); return out; };
const [schema1, data1] = [JSON.stringify(await schema()), await data()];
await db.exec(await sql(MIGRATION));
ok(JSON.stringify(await schema()), schema1, 'a second run changes no schema');
ok(await data(), data1, 'a second run changes no row');
ok((await q(`SELECT id FROM church_departments WHERE unfinished_at IS NOT NULL`)).map(r => r.id), [halfLC],
  'the backfill ran once: a draft made on purpose since, and one its retry finished, stay unmarked');
assert.ok(onPurpose && rvYouth);

// ─── The rollback block puts the schema back as it was ──────────────────
const rollback = block('-- Rollback');
const steps = statements(rollback);
ok([steps[0], steps.at(-1)], ['begin', 'commit'], 'the rollback is one transaction');
// While a role says 'template' the old check can't go back, so nothing goes.
await assert.rejects(db.exec(rollback), /church_role_defs_source_check/); checks++;
await db.exec('ROLLBACK');
ok(JSON.stringify(await schema()), schema1, 'a refused rollback leaves everything');
await db.query(`DELETE FROM church_role_defs WHERE source = 'template'`);
await db.exec(rollback);
ok(await schema(), pre, 'the rollback leaves the schema as it found it');

console.log(`church map step 2 db: ${checks} checks passed`);
