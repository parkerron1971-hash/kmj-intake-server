// The leaders schedule, step 3 (meetings and one calendar), on a real
// Postgres (PGlite): supabase/APPLY-2026-11-21-church-meetings.sql over the
// files that made Board & minutes and Rooms & spaces
// (APPLY-2026-10-27-church-board.sql, APPLY-2026-10-27-church-spaces.sql),
// with boards, members, meetings, agenda, attendance, decisions, rooms and
// bookings already in use.
//
// What it pins:
//   - Nothing live moves. Every board, member, meeting, item, attendance mark,
//     decision, room and booking reads as it did (the new columns at their
//     defaults); the reads and writes the deployed code makes still work.
//   - Twice is a no-op, with rows there.
//   - Every constraint and trigger in the file: refused by a bad row,
//     accepted by a good one; another church's group, room, booking, series,
//     person or member refused.
//   - Deletes: a meeting, a member row, a series, a group, a room, a booking,
//     a person, a login and a church each take what they should and are never
//     refused, with a church's foreign keys firing both ways round.
//   - Server-only under Supabase's default grants: the four new tables and
//     the three functions.
//   - The file's own Check block answers as it says, and its Rollback block
//     puts the catalog back as the board and spaces files left it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_meetings_db.mjs
// (CHURCH_MEETINGS_SQL=<path> runs it against another copy of the file: how
// each rule was broken once to see this go red.)
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);
const { btree_gist } = await import(new URL('./contrib/btree_gist.js', base).href);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const FILE = process.env.CHURCH_MEETINGS_SQL
  ? await readFile(process.env.CHURCH_MEETINGS_SQL, 'utf8')
  : await sql('APPLY-2026-11-21-church-meetings.sql');
const BOARD = await sql('APPLY-2026-10-27-church-board.sql');
const SPACES = await sql('APPLY-2026-10-27-church-spaces.sql');
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const u2 = 'aaaaaaaa-2222-4222-8222-222222222222';
const deacon = 'cccccccc-1111-4111-8111-111111111111';     // sits on the Deacons
const elder = 'cccccccc-3333-4333-8333-333333333333';      // on the leaders list
const clerk = 'cccccccc-4444-4444-8444-444444444444';      // the office
const pastor = 'cccccccc-5555-4555-8555-555555555555';     // the owner's own person
const outsider = 'cccccccc-2222-4222-8222-222222222222';   // the other church's
const nobody = 'eeeeeeee-9999-4999-8999-999999999999';
const TABLES = ['church_calendar_links', 'church_meeting_answers', 'church_meeting_notices', 'church_meeting_series'];
const FUNCTIONS = ['church_board_members_follow_list', 'church_boards_audience_kept', 'church_meetings_same_business',
  'church_space_bookings_meeting_room'];
const BOARD_TABLES = ['church_boards', 'church_board_members', 'church_board_meetings', 'church_board_items',
  'church_board_attendance', 'church_board_decisions', 'church_spaces', 'church_space_bookings'];
const hash = c => c.repeat(64);

// What Supabase already has: the three roles, and its habit of handing every
// new table and function in public to all three (so the files' own revokes
// are what keep the browser out); auth.users, businesses, contacts, tasks,
// invoices; then Board & minutes and Rooms & spaces, as they were applied.
const stand = async () => {
  const db = new PGlite({ extensions: { btree_gist } });
  await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
    CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
    CREATE SCHEMA extensions;
    CREATE TABLE public.businesses(id uuid PRIMARY KEY);
    CREATE TABLE public.contacts(id uuid PRIMARY KEY,
      business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE, name text);
    CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      business_id uuid REFERENCES public.businesses(id) ON DELETE CASCADE, title text);
    CREATE TABLE public.invoices(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      business_id uuid REFERENCES public.businesses(id) ON DELETE CASCADE);`);
  await db.exec(BOARD);
  await db.exec(SPACES);
  await db.query('INSERT INTO businesses VALUES ($1), ($2)', [b1, b2]);
  await db.query('INSERT INTO auth.users VALUES ($1), ($2)', [u1, u2]);
  await db.query(`INSERT INTO contacts VALUES ($1, $6, 'Dana Hayes'), ($2, $6, 'Eli Grant'), ($3, $6, 'Cora Lane'),
    ($4, $6, 'Pastor Reed'), ($5, $7, 'Their person')`, [deacon, elder, clerk, pastor, outsider, b1, b2]);
  return db;
};

let db;
let checks = 0;
const one = async (text, args = []) => (await db.query(text, args)).rows[0];
const all = async (text, args = []) => (await db.query(text, args)).rows;
const n = async (text, args = []) => (await one(`SELECT count(*)::int AS n FROM ${text}`, args)).n;
const ok = async (text, args) => { await db.query(text, args); checks++; };
const same = (got, want) => { assert.deepEqual(got, want); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
// A row as the server writes one: these columns and no others.
const put = (table, row) => {
  const keys = Object.keys(row);
  return [`INSERT INTO ${table}(${keys.join(', ')}) VALUES (${keys.map((_, i) => `$${i + 1}`).join(', ')}) RETURNING *`,
    keys.map(k => row[k])];
};
const add = async (table, row) => (await db.query(...put(table, row))).rows[0];
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
// The commented Check and Rollback blocks at the end of the file, as written.
const block = (from, to) => {
  const lines = FILE.replace(/\r\n/g, '\n').split('\n');
  const a = lines.findIndex(l => l.startsWith(from));
  const z = to ? lines.findIndex(l => l.startsWith(to)) : lines.length;
  assert.ok(a >= 0 && z > a);
  return lines.slice(a + 1, z).map(l => l.replace(/^-- {0,3}/, '')).filter(l => !l.startsWith('-- ')).join('\n')
    .split(';').map(s => s.trim()).filter(Boolean);
};
// Every old row as it reads, without the keys this file adds.
const NEW_KEYS = { church_boards: ['kind', 'audience'], church_board_members: ['from_list'],
  church_board_meetings: ['series_id', 'series_day', 'length_minutes', 'space_id', 'booking_id', 'cancelled_at',
    'cancelled_by', 'changed_alone_at'] };
const snap = async () => {
  const out = {};
  for (const t of BOARD_TABLES) {
    const drop = (NEW_KEYS[t] || []).map(k => ` - '${k}'`).join('');
    out[t] = (await all(`SELECT j FROM (SELECT to_jsonb(x)${drop} AS j FROM ${t} x) s ORDER BY j::text`)).map(r => r.j);
  }
  return out;
};
// What the deployed code selects (church_board.MEMBER_FIELDS, MEETING_FIELDS and
// the boards' own list), byte for byte.
const deployedReads = async () => ({
  boards: await all(`SELECT id, name, quorum_kind, quorum_count, sort, archived, created_at FROM church_boards
    WHERE business_id = $1 AND archived = false ORDER BY sort, created_at`, [b1]),
  members: await all(`SELECT id, board_id, contact_id, user_id, name, title, active, created_at FROM church_board_members
    WHERE business_id = $1 ORDER BY created_at, id`, [b1]),
  meetings: await all(`SELECT id, board_id, title, starts_at, place, video_url, status, sent_at, sent_count, approved_at,
    approved_by, approved_in, created_at, updated_at FROM church_board_meetings WHERE business_id = $1 ORDER BY starts_at DESC`, [b1]),
  attendance: await all(`SELECT meeting_id, member_id, status FROM church_board_attendance WHERE business_id = $1
    ORDER BY meeting_id, member_id`, [b1]),
});

// ─── Board & minutes and Rooms & spaces in use, before the file ─────────
db = await stand();
const start = await catalog();
const deacons = await add('church_boards', { business_id: b1, name: 'Deacons' });
const theirBoard = await add('church_boards', { business_id: b2, name: 'Their elders' });
const mDeacon = await add('church_board_members', { business_id: b1, board_id: deacons.id, contact_id: deacon, name: 'Dana Hayes',
  title: 'Chair' });
const mLogin = await add('church_board_members', { business_id: b1, board_id: deacons.id, user_id: u1, name: 'A login' });
const mTheirs = await add('church_board_members', { business_id: b2, board_id: theirBoard.id, contact_id: outsider, name: 'Their person' });
const sep = await add('church_board_meetings', { business_id: b1, board_id: deacons.id, starts_at: '2026-09-24T23:00:00Z',
  status: 'drafted', created_by: u1 });
const roof = await add('church_board_items', { business_id: b1, meeting_id: sep.id, title: 'Roof bids', status: 'tabled' });
await add('church_board_attendance', { business_id: b1, meeting_id: sep.id, member_id: mDeacon.id, status: 'present' });
await add('church_board_attendance', { business_id: b1, meeting_id: sep.id, member_id: mLogin.id, status: 'excused' });
await add('church_board_decisions', { business_id: b1, board_id: deacons.id, meeting_id: sep.id, item_id: roof.id,
  item_title: 'Roof bids', motion: 'Take the second bid', moved_by: mDeacon.id, votes_for: 2, result: 'carried',
  decided_on: '2026-09-24' });
const theirMeeting = await add('church_board_meetings', { business_id: b2, board_id: theirBoard.id, starts_at: '2026-10-01T23:00:00Z' });
const hall = await add('church_spaces', { business_id: b1, name: 'Fellowship hall' });
const van = await add('church_spaces', { business_id: b1, name: 'The van', kind: 'vehicle' });
const theirRoom = await add('church_spaces', { business_id: b2, name: 'Their sanctuary' });
await add('church_space_bookings', { business_id: b1, space_id: hall.id, title: 'Funeral meal', start_at: '2026-12-05T17:00:00Z',
  end_at: '2026-12-05T20:00:00Z', status: 'booked' });
const rows0 = await snap();
const reads0 = await deployedReads();

// ─── The file ───────────────────────────────────────────────────────────
await db.exec(FILE);
const cat1 = await catalog();
// Every old row reads as it did, and the new columns sit at their defaults.
same(await snap(), rows0);
same(await deployedReads(), reads0);
same(await all(`SELECT DISTINCT kind, audience FROM church_boards`), [{ kind: 'board', audience: 'members' }]);
same(await all(`SELECT DISTINCT from_list FROM church_board_members`), [{ from_list: false }]);
same(await all(`SELECT DISTINCT series_id, series_day, length_minutes, space_id, booking_id, cancelled_at, cancelled_by,
  changed_alone_at FROM church_board_meetings`), [{ series_id: null, series_day: null, length_minutes: null, space_id: null,
  booking_id: null, cancelled_at: null, cancelled_by: null, changed_alone_at: null }]);
// The file's Check block, run on the live database's shape (old rows only): it answers as it says.
const asked = block('-- Check:', '-- Rollback');
same(asked.length, 7);
const CHECKED = ['church_board_meetings', 'church_board_members', 'church_boards', ...TABLES];
same(await all(asked[0]), CHECKED.map(relname => ({ relname, relrowsecurity: true, policies: 0, browser_reads: false,
  browser_writes: false, anon_reads: false, anon_writes: false })));
// …and it would say so if the browser could read or change one: each role's
// read, insert, update and delete, given and taken back, on a new table and an old one.
for (const t of ['church_calendar_links', 'church_board_meetings']) {
  for (const [role, who] of [['anon', 'anon'], ['authenticated', 'browser']]) {
    for (const [grant, key] of [['SELECT', 'reads'], ['INSERT', 'writes'], ['UPDATE', 'writes'], ['DELETE', 'writes']]) {
      await db.exec(`GRANT ${grant} ON public.${t} TO ${role}`);
      same((await all(asked[0])).filter(r => r[`${who}_${key}`]).map(r => r.relname), [t]);
      await db.exec(`REVOKE ${grant} ON public.${t} FROM ${role}`);
    }
  }
}
same((await all(asked[1])).map(x => `${x.table_name}.${x.column_name}`), ['church_board_meetings.booking_id',
  'church_board_meetings.cancelled_at', 'church_board_meetings.cancelled_by', 'church_board_meetings.changed_alone_at',
  'church_board_meetings.length_minutes', 'church_board_meetings.series_day', 'church_board_meetings.series_id',
  'church_board_meetings.space_id', 'church_board_members.from_list', 'church_boards.audience', 'church_boards.kind']);
same(await all(asked[2]), ['church_board_meetings_alone', 'church_board_meetings_booking_id_fkey',
  'church_board_meetings_called_off', 'church_board_meetings_cancelled_by_fkey', 'church_board_meetings_length',
  'church_board_meetings_series_day', 'church_board_meetings_series_id_fkey', 'church_board_meetings_space_id_fkey',
  'church_boards_audience', 'church_boards_kind', 'church_boards_list_is_meeting'].map(conname => ({ conname, convalidated: true })));
// The unique indexes the guards rest on, and which are partial (never named in on_conflict).
const UNIQUE = [['church_board_meetings_one_a_day', false], ['church_board_meetings_one_booking', false],
  ['church_board_members_one_from_list', true], ['church_boards_one_list_name', true],
  ['church_calendar_links_one_live', true], ['church_calendar_links_token', false], ['church_meeting_notices_once', false]];
same(await all(asked[3]), UNIQUE.map(([indexname, partial]) => ({ indexname, partial })));
// The triggers, each on its table and enabled; one turned off shows.
const TRIGGERS = [['church_board_meetings', 'church_meetings_same_business'], ['church_board_members', 'church_board_members_follow_list'],
  ['church_boards', 'church_boards_audience_kept'], ['church_calendar_links', 'church_meetings_same_business'],
  ['church_meeting_answers', 'church_meetings_same_business'], ['church_meeting_notices', 'church_meetings_same_business'],
  ['church_meeting_series', 'church_meetings_same_business'], ['church_space_bookings', 'church_space_bookings_meeting_room']];
same(await all(asked[4]), TRIGGERS.map(([on_table, tgname]) => ({ on_table, tgname, tgenabled: 'O' })));
await db.exec('ALTER TABLE church_boards DISABLE TRIGGER church_boards_audience_kept');
same((await all(asked[4])).filter(r => r.tgenabled !== 'O').map(r => r.tgname), ['church_boards_audience_kept']);
await db.exec('ALTER TABLE church_boards ENABLE TRIGGER church_boards_audience_kept');
same(await all(asked[5]), FUNCTIONS.map(proname => ({ proname, browser_runs: false, anon_runs: false })));
same(await one(asked[6]), { groups: 0, list_rows: 0, meetings: 0 });

// The indexes it makes, by name, and a word on each new table and on the private note.
same((await all(`SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND (tablename = ANY($1)
    OR indexname IN ('church_board_members_one_from_list', 'church_board_meetings_one_a_day', 'church_board_meetings_one_booking',
                     'church_board_meetings_coming', 'church_boards_one_list_name')) ORDER BY 1`, [TABLES])).map(x => x.indexname),
  ['church_board_meetings_coming', 'church_board_meetings_one_a_day', 'church_board_meetings_one_booking',
   'church_board_members_one_from_list', 'church_boards_one_list_name', 'church_calendar_links_one_live', 'church_calendar_links_pkey',
   'church_calendar_links_token', 'church_meeting_answers_member', 'church_meeting_answers_pkey',
   'church_meeting_notices_member', 'church_meeting_notices_once', 'church_meeting_notices_pkey',
   'church_meeting_notices_unsent', 'church_meeting_series_by_group', 'church_meeting_series_pkey']);
same((await all(`SELECT indexname, indexdef LIKE 'CREATE UNIQUE%' AS one FROM pg_indexes WHERE indexname = ANY($1)
  ORDER BY 1`, [UNIQUE.map(u => u[0])])).map(x => x.one), UNIQUE.map(() => true));
same((await all(`SELECT relname FROM pg_class WHERE relname = ANY($1) AND obj_description(oid, 'pg_class') IS NOT NULL
  ORDER BY 1`, [TABLES])).map(x => x.relname), TABLES);
assert.match((await one(`SELECT col_description('public.church_meeting_answers'::regclass,
  (SELECT attnum FROM pg_attribute WHERE attrelid = 'public.church_meeting_answers'::regclass AND attname = 'note')::int) AS d`)).d,
  /^Private/); checks++;

// Twice, with rows there: nothing changes, nothing fails, nothing is lost.
await db.exec(FILE);
same(await catalog(), cat1);
same([await snap(), await deployedReads()], [rows0, reads0]);

// ─── What the deployed code does still works ────────────────────────────
// A board, its seats, a meeting through its steps, attendance, the agenda
// carried forward, a decision, a meeting deleted: church_board.py's own writes.
const elders = await add('church_boards', { business_id: b1, name: 'Elders', quorum_kind: 'count', quorum_count: 3,
  created_by: u1 });
same([elders.kind, elders.audience], ['board', 'members']);
await ok(`UPDATE church_boards SET name = 'Elders board', quorum_kind = 'majority', quorum_count = null, archived = false,
  updated_at = now() WHERE id = $1 AND business_id = $2`, [elders.id, b1]);
const mElder = await add('church_board_members', { business_id: b1, board_id: elders.id, contact_id: elder, user_id: null,
  name: 'Eli Grant', title: '', active: true });
same(mElder.from_list, false);
await ok(`UPDATE church_board_members SET active = false, updated_at = now() WHERE id = $1 AND business_id = $2`, [mElder.id, b1]);
await ok(`UPDATE church_board_members SET active = true, title = 'Secretary', contact_id = $3, user_id = $4, name = 'Eli Grant',
  updated_at = now() WHERE id = $1 AND business_id = $2`, [mElder.id, b1, elder, u2]);
const oct = await add('church_board_meetings', { business_id: b1, board_id: deacons.id, title: '', place: 'Room 2',
  video_url: '', starts_at: '2026-10-29T23:00:00Z', status: 'planned', created_by: u1 });
await ok(`INSERT INTO church_board_items(business_id, meeting_id, position, title, status, carried_from)
  VALUES ($1, $2, 1, 'Roof bids', 'open', $3) ON CONFLICT (carried_from) DO NOTHING`, [b1, oct.id, roof.id]);
for (const [from, to] of [['planned', 'in_progress'], ['in_progress', 'drafted'], ['drafted', 'in_progress'],
  ['in_progress', 'planned']]) {
  same((await all(`UPDATE church_board_meetings SET status = $3, updated_at = now() WHERE id = $1 AND business_id = $2
    AND status = $4 RETURNING id`, [oct.id, b1, to, from])).length, 1);
}
await ok(`INSERT INTO church_board_attendance(business_id, meeting_id, member_id, status, marked_by) VALUES ($1, $2, $3, 'present', $4)
  ON CONFLICT (meeting_id, member_id) DO UPDATE SET status = excluded.status`, [b1, oct.id, mDeacon.id, u1]);
await ok(`INSERT INTO church_board_attendance(business_id, meeting_id, member_id, status, marked_by) VALUES ($1, $2, $3, 'absent', $4)
  ON CONFLICT (meeting_id, member_id) DO UPDATE SET status = excluded.status`, [b1, oct.id, mDeacon.id, u1]);
const carried = (await one(`SELECT id FROM church_board_items WHERE meeting_id = $1`, [oct.id])).id;
await ok(...put('church_board_decisions', { business_id: b1, board_id: deacons.id, meeting_id: oct.id, item_id: carried,
  item_title: 'Roof bids', motion: 'Take the first bid', moved_by: mDeacon.id, seconded_by: null,
  votes_for: 3, votes_against: 1, votes_abstain: 0, result: 'failed', decided_on: '2026-10-29', created_by: u1 }));
await ok(`UPDATE church_board_decisions SET result = 'tabled', updated_at = now() WHERE meeting_id = $1`, [oct.id]);
const doomed = await add('church_board_meetings', { business_id: b1, board_id: deacons.id, starts_at: '2026-11-05T23:00:00Z' });
await add('church_board_items', { business_id: b1, meeting_id: doomed.id, title: 'Gone with it' });
await ok(`DELETE FROM church_board_meetings WHERE id = $1 AND business_id = $2`, [doomed.id, b1]);
same(await n('church_board_items WHERE meeting_id = $1', [doomed.id]), 0);
// Another church's board is still refused as the board's own key always refused it.
await refuses(...put('church_board_meetings', { business_id: b1, board_id: theirBoard.id, starts_at: '2026-11-05T23:00:00Z' }),
  /foreign key/);

// ─── A group that meets: a board or a meeting, and who comes ────────────
const huddle = await add('church_boards', { business_id: b1, name: 'Staff huddle', kind: 'meeting', audience: 'office' });
const leaders = await add('church_boards', { business_id: b1, name: 'Leaders meeting', kind: 'meeting', audience: 'leaders' });
const checkins = await add('church_boards', { business_id: b1, name: 'Pastor check-ins', kind: 'meeting' });
same(checkins.audience, 'members');
checks += 3;
await refuses(...put('church_boards', { business_id: b1, name: 'x', kind: 'committee' }), /church_boards_kind/);
await refuses(...put('church_boards', { business_id: b1, name: 'x', kind: 'meeting', audience: 'everyone' }), /church_boards_audience/);
await refuses(...put('church_boards', { business_id: b1, name: 'x', kind: 'board', audience: 'leaders' }), /church_boards_list_is_meeting/);
await refuses(...put('church_boards', { business_id: b1, name: 'x', audience: 'office' }), /church_boards_list_is_meeting/);
await refuses(...put('church_boards', { business_id: b1, name: 'x', kind: null }), /null value/);
await refuses(...put('church_boards', { business_id: b1, name: 'x', kind: 'meeting', audience: null }), /null value/);
// A group keeps who it is for; a meeting of its own people may become a board and back.
await refuses(`UPDATE church_boards SET audience = 'leaders' WHERE id = $1`, [huddle.id], /keeps who it is for/);
await refuses(`UPDATE church_boards SET audience = 'members', kind = 'meeting' WHERE id = $1`, [huddle.id], /keeps who it is for/);
await refuses(`UPDATE church_boards SET audience = 'office' WHERE id = $1`, [checkins.id], /keeps who it is for/);
await refuses(`UPDATE church_boards SET audience = 'office', kind = 'meeting' WHERE id = $1`, [deacons.id], /keeps who it is for/);
await ok(`UPDATE church_boards SET audience = audience, name = 'The staff huddle' WHERE id = $1`, [huddle.id]);
await ok(`UPDATE church_boards SET kind = 'board' WHERE id = $1`, [checkins.id]);
await ok(`UPDATE church_boards SET kind = 'meeting' WHERE id = $1`, [checkins.id]);
await refuses(`UPDATE church_boards SET kind = 'board' WHERE id = $1`, [huddle.id], /church_boards_list_is_meeting/);
// One open group for the list a name, whatever its case; a closed one frees the name; boards may share one.
await refuses(...put('church_boards', { business_id: b1, name: 'LEADERS MEETING', kind: 'meeting', audience: 'leaders' }),
  /church_boards_one_list_name/);
const sameName = await add('church_boards', { business_id: b1, name: 'Leaders meeting', kind: 'meeting', audience: 'office' });
await ok(...put('church_boards', { business_id: b2, name: 'Leaders meeting', kind: 'meeting', audience: 'leaders' }));
await ok(...put('church_boards', { business_id: b1, name: 'Deacons' }));                   // a second board of one name, as always
await ok(...put('church_boards', { business_id: b1, name: 'Leaders meeting', kind: 'meeting' }));   // a meeting of its own people
await ok(`UPDATE church_boards SET archived = true WHERE id = $1`, [sameName.id]);
const again2 = await add('church_boards', { business_id: b1, name: 'leaders meeting', kind: 'meeting', audience: 'office' });
await refuses(`UPDATE church_boards SET archived = false WHERE id = $1`, [sameName.id], /church_boards_one_list_name/);
await refuses(`UPDATE church_boards SET name = 'THE STAFF HUDDLE' WHERE id = $1`, [again2.id], /church_boards_one_list_name/);
await ok(`DELETE FROM church_boards WHERE id IN ($1, $2)`, [sameName.id, again2.id]);
await ok(`DELETE FROM church_boards WHERE business_id = $1 AND name = 'Deacons' AND id <> $2`, [b1, deacons.id]);
await ok(`DELETE FROM church_boards WHERE name = 'Leaders meeting' AND audience = 'members'`);
same(await one(`SELECT count(*)::int AS n FROM church_boards WHERE business_id = $1`, [b1]), { n: 5 });

// ─── Its people: the list's rows, or rows added by hand ─────────────────
const fromList = (board, who, more = {}) => put('church_board_members', { business_id: b1, board_id: board.id,
  contact_id: who, name: 'Someone', from_list: true, ...more });
const byHand = (board, who, more = {}) => put('church_board_members', { business_id: b1, board_id: board.id,
  contact_id: who, name: 'Someone', ...more });
const hClerk = (await db.query(...fromList(huddle, clerk))).rows[0]; checks++;
const hPastor = (await db.query(...fromList(huddle, pastor, { user_id: u1 }))).rows[0]; checks++;
const lElder = (await db.query(...fromList(leaders, elder))).rows[0]; checks++;
const lClerk = (await db.query(...fromList(leaders, clerk))).rows[0]; checks++;      // the same person on another group
const cPastor = (await db.query(...byHand(checkins, pastor))).rows[0]; checks++;     // a meeting of its own people
await refuses(...byHand(huddle, elder), /follows the leaders list: add them there/);
await refuses(...byHand(huddle, null, { user_id: u2 }), /follows the leaders list: add them there/);
await refuses(...fromList(deacons, elder), /Only a meeting for every leader or the office follows the list/);
await refuses(...fromList(checkins, elder), /Only a meeting for every leader or the office follows the list/);
await refuses(...fromList(huddle, null, { user_id: u2 }), /one of the church's people/);
await refuses(...fromList(huddle, clerk), /church_board_members_one_from_list/);     // once a person a group
await refuses(...fromList(huddle, outsider), /not in this church/);                  // the board's own guard
await refuses(...put('church_board_members', { business_id: b1, board_id: theirBoard.id, contact_id: elder, name: 'x',
  from_list: true }), /foreign key/);
await ok(...byHand(deacons, elder));                                                  // a board's seats, as always
await ok(...byHand(deacons, elder));                                                  // twice by hand, as the board always allowed
await refuses(`UPDATE church_board_members SET from_list = false WHERE id = $1`, [hClerk.id], /follows the leaders list/);
await refuses(`UPDATE church_board_members SET from_list = true WHERE id = $1`, [mDeacon.id], /Only a meeting for every leader/);
await refuses(`UPDATE church_board_members SET board_id = $1 WHERE id = $2`, [deacons.id, hClerk.id], /Only a meeting for every leader/);
await refuses(`UPDATE church_board_members SET board_id = $1 WHERE id = $2`, [huddle.id, mDeacon.id], /follows the leaders list/);
await refuses(`UPDATE church_board_members SET board_id = $1 WHERE id = $2`, [huddle.id, lClerk.id], /church_board_members_one_from_list/);
await ok(`UPDATE church_board_members SET active = false, updated_at = now() WHERE id = $1`, [lClerk.id]);   // off the list
await ok(`UPDATE church_board_members SET active = true, name = 'Cora Lane' WHERE id = $1`, [lClerk.id]);   // back on it
await ok(`UPDATE church_board_members SET title = 'Note taker' WHERE id = $1`, [hClerk.id]);
// A list seat stays its person's: never moved to someone else (a person deleted sets it to nobody, below).
await refuses(`UPDATE church_board_members SET contact_id = $1 WHERE id = $2`, [elder, hClerk.id], /stays its person's/);
await refuses(`UPDATE church_board_members SET contact_id = $1, name = 'x' WHERE id = $2`, [deacon, lElder.id], /stays its person's/);
await ok(`UPDATE church_board_members SET contact_id = $1 WHERE id = $2`, [clerk, hClerk.id]);            // the same person: a no-op
await ok(`UPDATE church_board_members SET contact_id = $1 WHERE id = $2`, [deacon, cPastor.id]);          // a hand seat, as always
await ok(`UPDATE church_board_members SET contact_id = $1 WHERE id = $2`, [pastor, cPastor.id]);
// Two replicas keeping it in step at once, the way PostgREST can write it: one
// person a request, and the second plain insert of the same person is a 23505
// (a 409), read as "already seated". PostgREST's on_conflict names columns and
// no predicate, so it can't land on this partial index at all (42P10).
await refuses(...fromList(huddle, clerk), /duplicate key value violates unique constraint "church_board_members_one_from_list"/);
await assert.rejects(db.query(...fromList(huddle, clerk)), e => e.code === '23505'); checks++;
await refuses(`INSERT INTO church_board_members(business_id, board_id, contact_id, name, from_list) VALUES ($1, $2, $3, 'x', true)
  ON CONFLICT (board_id, contact_id) DO NOTHING`, [b1, huddle.id, clerk], /no unique or exclusion constraint matching/);
// The same for an open group for the list of the same name: a 23505, then read it again.
await assert.rejects(db.query(...put('church_boards', { business_id: b1, name: 'THE STAFF HUDDLE', kind: 'meeting',
  audience: 'office' })), e => e.code === '23505' && /church_boards_one_list_name/.test(e.message)); checks++;
same((await one(`SELECT id FROM church_boards WHERE business_id = $1 AND audience = 'office' AND lower(name) = 'the staff huddle'
  AND NOT archived`, [b1])).id, huddle.id);

// ─── A meeting that repeats ─────────────────────────────────────────────
const series = more => put('church_meeting_series', { business_id: b1, board_id: huddle.id, weekday: 2, pattern: 'weekly',
  starts_on: '2026-12-01', at_time: '09:00', ...more });
const sHuddle = (await db.query(...series({ created_by: u1 }))).rows[0]; checks++;       // every Tuesday at 9
same([sHuddle.length_minutes, sHuddle.title, sHuddle.place, sHuddle.video_url, sHuddle.made_through, sHuddle.until_on],
  [60, '', '', '', null, null]);
const sLeaders = (await db.query(...series({ board_id: leaders.id, weekday: 6, pattern: 'month_nth', nth: 3,
  starts_on: '2026-12-19', at_time: '10:00', length_minutes: 90, space_id: hall.id, title: 'Leaders meeting' }))).rows[0];
checks++;                                                                               // the third Saturday at 10, in the hall
const sCheckins = (await db.query(...series({ board_id: checkins.id, weekday: 4, pattern: 'every_other',
  starts_on: '2026-12-03', at_time: '14:30', until_on: '2027-06-30', place: 'The study', video_url: 'https://meet.example/x' }))).rows[0];
checks++;                                                                               // every other Thursday, from a Thursday
await ok(...series({ board_id: deacons.id, weekday: 7, pattern: 'month_nth', nth: 5, starts_on: '2026-12-27', at_time: '12:15',
  length_minutes: 5 }));                                                                // a board's own; the last Sunday
for (const [bad, message] of [
  [{ weekday: 0 }, /check constraint/], [{ weekday: 8 }, /check constraint/], [{ pattern: 'daily' }, /check constraint/],
  [{ pattern: 'month_nth' }, /church_meeting_series_nth/], [{ nth: 2 }, /church_meeting_series_nth/],
  [{ pattern: 'month_nth', nth: 6 }, /check constraint/], [{ pattern: 'month_nth', nth: 0 }, /check constraint/],
  [{ pattern: 'every_other', starts_on: '2026-12-02' }, /church_meeting_series_anchor/],
  [{ until_on: '2026-11-30' }, /church_meeting_series_until/],
  [{ length_minutes: 4 }, /check constraint/], [{ length_minutes: 721 }, /check constraint/],
  [{ title: 't'.repeat(121) }, /check constraint/], [{ place: 'p'.repeat(161) }, /check constraint/],
  [{ video_url: 'v'.repeat(501) }, /check constraint/], [{ at_time: null }, /null value/],
  [{ board_id: theirBoard.id }, /church_meeting_series_group/], [{ board_id: nobody }, /church_meeting_series_group/],
  [{ space_id: theirRoom.id }, /That room is not in this church/], [{ space_id: nobody }, /That room is not in this church/],
]) await refuses(...series(bad), message);
await ok(...series({ title: 't'.repeat(120), place: 'p'.repeat(160), length_minutes: 720, until_on: '2026-12-01' }));
await refuses(`UPDATE church_meeting_series SET space_id = $1 WHERE id = $2`, [theirRoom.id, sHuddle.id], /That room is not in this church/);
await ok(`UPDATE church_meeting_series SET space_id = $1, made_through = '2027-03-02', updated_at = now() WHERE id = $2`,
  [van.id, sHuddle.id]);
await ok(`UPDATE church_meeting_series SET space_id = null WHERE id = $1`, [sHuddle.id]);
// A series stays with its group and its church, with meetings or without.
// First to another group of the same church, which nothing else would refuse.
await refuses(`UPDATE church_meeting_series SET board_id = $1 WHERE id = $2`, [leaders.id, sCheckins.id], /A series stays with its group/);
await refuses(`UPDATE church_meeting_series SET board_id = $1 WHERE id = $2`, [leaders.id, sHuddle.id], /A series stays with its group/);
await refuses(`UPDATE church_meeting_series SET business_id = $1 WHERE id = $2`, [b2, sHuddle.id], /A series stays with its group/);
await refuses(`UPDATE church_meeting_series SET board_id = $1, business_id = $2 WHERE id = $3`, [theirBoard.id, b2, sHuddle.id],
  /A series stays with its group/);
await ok(`UPDATE church_meeting_series SET board_id = $1, title = 'Huddle', until_on = '2027-12-31' WHERE id = $2`,
  [huddle.id, sHuddle.id]);                                                               // its own group named again: nothing moves

// ─── A meeting: its series, its length, its room, called off ────────────
const meeting = more => put('church_board_meetings', { business_id: b1, board_id: huddle.id,
  starts_at: '2026-12-01T14:00:00Z', ...more });
const tue1 = (await db.query(...meeting({ series_id: sHuddle.id, series_day: '2026-12-01', length_minutes: 60 }))).rows[0]; checks++;
const tue2 = (await db.query(...meeting({ series_id: sHuddle.id, series_day: '2026-12-08', starts_at: '2026-12-08T14:00:00Z',
  length_minutes: 60 }))).rows[0]; checks++;
await refuses(...meeting({ series_id: sHuddle.id }), /church_board_meetings_series_day/);
await refuses(...meeting({ series_id: sHuddle.id, series_day: '2026-12-01' }), /church_board_meetings_one_a_day/);
// Made ahead the way PostgREST writes it (on_conflict=series_id,series_day,
// ignore duplicates: a column list and no predicate): the day already made
// adds nothing and fails nothing, and a new day lands. A partial index here
// would make this a 42P10 for every call.
const makeAhead = `INSERT INTO church_board_meetings(business_id, board_id, starts_at, series_id, series_day) VALUES
  ($1, $2, '2026-12-01T14:00:00Z', $3, '2026-12-01'), ($1, $2, '2026-12-15T14:00:00Z', $3, '2026-12-15')
  ON CONFLICT (series_id, series_day) DO NOTHING RETURNING series_day::text`;
same((await all(makeAhead, [b1, huddle.id, sHuddle.id])).map(r => r.series_day), ['2026-12-15']);
same((await all(makeAhead, [b1, huddle.id, sHuddle.id])).length, 0);
await ok(`DELETE FROM church_board_meetings WHERE series_id = $1 AND series_day = '2026-12-15'`, [sHuddle.id]);
same((await one(`SELECT indexdef FROM pg_indexes WHERE indexname = 'church_board_meetings_one_a_day'`)).indexdef.includes(' WHERE '),
  false);
// One-off meetings (no series) never clash with each other under the plain index.
same(await n(`church_board_meetings WHERE series_id IS NULL AND business_id = $1`, [b1]) >= 2, true);
await refuses(...meeting({ board_id: leaders.id, series_id: sHuddle.id, series_day: '2026-12-15' }), /That series is not this meeting's/);
const theirSeries = await add('church_meeting_series', { business_id: b2, board_id: theirBoard.id, weekday: 1, pattern: 'weekly',
  starts_on: '2026-12-07', at_time: '19:00' });
await refuses(...meeting({ series_id: theirSeries.id, series_day: '2026-12-15' }), /That series is not this meeting's/);
await refuses(...meeting({ series_id: nobody, series_day: '2026-12-15' }), /That series is not this meeting's/);
// …and the same when a meeting already there is given a series.
await refuses(`UPDATE church_board_meetings SET series_id = $1, series_day = '2026-12-15' WHERE id = $2`, [theirSeries.id, oct.id],
  /That series is not this meeting's/);
await refuses(`UPDATE church_board_meetings SET series_id = $1, series_day = '2026-12-15' WHERE id = $2`, [sHuddle.id, oct.id],
  /That series is not this meeting's/);                                                  // oct is the deacons'
const sat = (await db.query(...meeting({ board_id: leaders.id, series_id: sLeaders.id, series_day: '2026-12-01',
  starts_at: '2026-12-19T15:00:00Z', length_minutes: 90 }))).rows[0]; checks++;          // the same day of another series
for (const [bad, message] of [[4, /church_board_meetings_length/], [721, /church_board_meetings_length/]]) {
  await refuses(...meeting({ length_minutes: bad }), message);
}
await ok(...meeting({ length_minutes: 5, starts_at: '2026-12-02T14:00:00Z' }));
await ok(...meeting({ length_minutes: 720, starts_at: '2026-12-03T14:00:00Z' }));
await ok(...meeting({ starts_at: '2026-12-04T14:00:00Z' }));                            // a one-off, no length: an hour where one is needed
// The room, and the booking made for it.
const booking = async (space, from, to, status = 'booked', biz = b1) => (await add('church_space_bookings', {
  business_id: biz, space_id: space.id, title: 'Leaders meeting', start_at: from, end_at: to, status, booked_by: u1 })).id;
const kHall = await booking(hall, '2026-12-19T15:00:00Z', '2026-12-19T16:30:00Z');
const kVan = await booking(van, '2026-12-19T15:00:00Z', '2026-12-19T16:30:00Z');
const kTheirs = await booking(theirRoom, '2026-12-19T15:00:00Z', '2026-12-19T16:30:00Z', 'booked', b2);
const kWaiting = await booking(hall, '2026-12-22T15:00:00Z', '2026-12-22T16:00:00Z', 'requested');
await refuses(`UPDATE church_board_meetings SET space_id = $1 WHERE id = $2`, [theirRoom.id, sat.id], /That room is not in this church/);
await refuses(`UPDATE church_board_meetings SET space_id = $1 WHERE id = $2`, [nobody, sat.id], /That room is not in this church/);
await refuses(`UPDATE church_board_meetings SET booking_id = $1 WHERE id = $2`, [kHall, sat.id], /not for this meeting's room/);   // no room
await refuses(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, kVan, sat.id],
  /not for this meeting's room/);
await refuses(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, kTheirs, sat.id],
  /not for this meeting's room/);
await refuses(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, nobody, sat.id],
  /not for this meeting's room/);
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, kHall, sat.id]);
await refuses(...meeting({ space_id: hall.id, booking_id: kHall, starts_at: '2026-12-20T15:00:00Z' }),
  /church_board_meetings_one_booking/);                                                  // one meeting a booking
await ok(...meeting({ space_id: hall.id, booking_id: kWaiting, starts_at: '2026-12-22T15:00:00Z' }));   // a request waits as a booking
// Moved to another room with its booking, in one update, and back.
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [van.id, kVan, sat.id]);
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, kHall, sat.id]);
// The room changed alone, its booking still the old room's: refused. With the booking let go in the same update: fine.
await refuses(`UPDATE church_board_meetings SET space_id = $1 WHERE id = $2`, [van.id, sat.id], /not for this meeting's room/);
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = null WHERE id = $2`, [van.id, sat.id]);
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, kHall, sat.id]);
await ok(`UPDATE church_board_meetings SET space_id = $1 WHERE id = $2`, [hall.id, sat.id]);                    // the same room again
// From Rooms & spaces' side: a booking a meeting names keeps its room; one no meeting names moves as always.
const chapel = await add('church_spaces', { business_id: b1, name: 'Chapel' });                 // a free room: only the rule refuses
await refuses(`UPDATE church_space_bookings SET space_id = $1 WHERE id = $2`, [chapel.id, kHall], /change its room from the meeting/);
await refuses(`UPDATE church_space_bookings SET space_id = $1, title = 'Moved' WHERE id = $2`, [chapel.id, kHall],
  /change its room from the meeting/);
await ok(`UPDATE church_space_bookings SET status = 'cancelled', updated_at = now() WHERE id = $1`, [kHall]);   // decided there
await ok(`UPDATE church_space_bookings SET status = 'booked', start_at = start_at + interval '0 minutes' WHERE id = $1`, [kHall]);
await ok(`UPDATE church_space_bookings SET space_id = $1 WHERE id = $2`, [hall.id, kHall]);                       // the same room
const kLoose = await booking(van, '2026-12-26T15:00:00Z', '2026-12-26T16:00:00Z');
await ok(`UPDATE church_space_bookings SET space_id = $1 WHERE id = $2`, [hall.id, kLoose]);
// Called off: only a meeting not yet held, and who called it off goes with when.
await ok(`UPDATE church_board_meetings SET cancelled_at = now(), cancelled_by = $1 WHERE id = $2`, [u1, tue2.id]);
await refuses(`UPDATE church_board_meetings SET status = 'in_progress' WHERE id = $1 AND status = 'planned'`, [tue2.id],
  /church_board_meetings_called_off/);                                                  // the deployed "start it", on one called off
await refuses(`UPDATE church_board_meetings SET cancelled_at = null WHERE id = $1`, [tue2.id], /church_board_meetings_called_off/);
await ok(`UPDATE church_board_meetings SET cancelled_at = null, cancelled_by = null WHERE id = $1`, [tue2.id]);   // back on
await refuses(`UPDATE church_board_meetings SET cancelled_by = $1 WHERE id = $2`, [u1, tue2.id], /church_board_meetings_called_off/);
await refuses(`UPDATE church_board_meetings SET cancelled_at = now() WHERE id = $1`, [sep.id], /church_board_meetings_called_off/);   // held
await ok(`UPDATE church_board_meetings SET status = 'in_progress' WHERE id = $1`, [tue1.id]);
await refuses(`UPDATE church_board_meetings SET cancelled_at = now() WHERE id = $1`, [tue1.id], /church_board_meetings_called_off/);
await ok(`UPDATE church_board_meetings SET status = 'planned' WHERE id = $1`, [tue1.id]);
await ok(`UPDATE church_board_meetings SET cancelled_at = now() WHERE id = $1`, [tue2.id]);                       // skipped, by the sweep
// Changed by itself: only a meeting made from a series.
await ok(`UPDATE church_board_meetings SET changed_alone_at = now(), starts_at = '2026-12-01T15:00:00Z' WHERE id = $1`, [tue1.id]);
await refuses(`UPDATE church_board_meetings SET changed_alone_at = now() WHERE id = $1`, [oct.id], /church_board_meetings_alone/);
// The series' meetings in the reminders' window: the partial index serves the read.
same((await all(`SELECT id FROM church_board_meetings WHERE status = 'planned' AND cancelled_at IS NULL AND board_id = $1
  ORDER BY starts_at`, [huddle.id])).map(r => r.id).includes(tue2.id), false);

// ─── "I'll be there" or "I can't" ───────────────────────────────────────
const answer = more => put('church_meeting_answers', { business_id: b1, meeting_id: tue1.id, member_id: hClerk.id,
  answer: 'yes', for_starts_at: '2026-12-01T15:00:00Z', ...more });
const yes1 = (await db.query(...answer({ by_contact_id: clerk }))).rows[0]; checks++;
same([yes1.note, yes1.by_user_id, yes1.answered_at !== null], [null, null, true]);
await ok(...answer({ member_id: hPastor.id, answer: 'cant', note: 'Hospital visit', by_user_id: u1 }));
await refuses(...answer({ member_id: hClerk.id }), /duplicate key/);                     // one a person a meeting
await refuses(...answer({ member_id: hPastor.id, meeting_id: tue2.id, answer: 'yes', note: 'Glad to' }), /church_meeting_answers_note/);
await refuses(...answer({ member_id: hPastor.id, meeting_id: tue2.id, answer: 'cant', note: '   ' }), /check constraint/);
await refuses(...answer({ member_id: hPastor.id, meeting_id: tue2.id, answer: 'cant', note: 'n'.repeat(201) }), /check constraint/);
await ok(...answer({ member_id: hPastor.id, meeting_id: tue2.id, answer: 'cant', note: 'n'.repeat(200) }));
await refuses(...answer({ meeting_id: tue2.id, answer: 'maybe' }), /check constraint/);
await refuses(...answer({ meeting_id: tue2.id, answer: null }), /null value/);
await refuses(...answer({ meeting_id: tue2.id, for_starts_at: null }), /null value/);
await refuses(...answer({ meeting_id: tue2.id, by_user_id: u1, by_contact_id: clerk }), /church_meeting_answers_by_one/);
await refuses(...answer({ meeting_id: tue2.id, by_contact_id: outsider }), /person who answered is not in this church/);
await refuses(...answer({ meeting_id: tue2.id, by_contact_id: nobody }), /person who answered is not in this church|foreign key/);
await refuses(...answer({ meeting_id: tue2.id, member_id: mDeacon.id }), /not one of this meeting's people/);   // another group's seat
await refuses(...answer({ meeting_id: tue2.id, member_id: lElder.id }), /not one of this meeting's people/);
await refuses(...answer({ meeting_id: tue2.id, member_id: mTheirs.id }), /not one of this meeting's people|foreign key/);
await refuses(...answer({ meeting_id: theirMeeting.id }), /not one of this meeting's people|foreign key/);
await refuses(...answer({ business_id: b2, meeting_id: theirMeeting.id, member_id: mTheirs.id, by_contact_id: clerk }),
  /person who answered is not in this church/);
await ok(...answer({ business_id: b2, meeting_id: theirMeeting.id, member_id: mTheirs.id, by_contact_id: outsider }));
await ok(...answer({ meeting_id: sat.id, member_id: lClerk.id }));                      // someone off the list and back: their seat
// Answered again, as the server will: one row, the latest word; a note never outlives "I can't".
const again = `INSERT INTO church_meeting_answers(business_id, meeting_id, member_id, answer, note, for_starts_at, by_contact_id)
  VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (meeting_id, member_id) DO UPDATE SET answer = excluded.answer,
  note = excluded.note, for_starts_at = excluded.for_starts_at, by_contact_id = excluded.by_contact_id, answered_at = now()`;
await ok(again, [b1, tue1.id, hClerk.id, 'cant', 'Out of town', '2026-12-01T15:00:00Z', clerk]);
same(await one(`SELECT answer, note FROM church_meeting_answers WHERE meeting_id = $1 AND member_id = $2`, [tue1.id, hClerk.id]),
  { answer: 'cant', note: 'Out of town' });
await refuses(`UPDATE church_meeting_answers SET answer = 'yes' WHERE meeting_id = $1 AND member_id = $2`, [tue1.id, hClerk.id],
  /church_meeting_answers_note/);
await ok(again, [b1, tue1.id, hClerk.id, 'yes', null, '2026-12-01T15:00:00Z', clerk]);
await refuses(`UPDATE church_meeting_answers SET member_id = $1 WHERE meeting_id = $2 AND member_id = $3`,
  [mDeacon.id, tue1.id, hClerk.id], /not one of this meeting's people/);
await refuses(`UPDATE church_meeting_answers SET meeting_id = $1 WHERE meeting_id = $2 AND member_id = $3`,
  [oct.id, tue1.id, hClerk.id], /not one of this meeting's people/);
await refuses(`UPDATE church_meeting_answers SET by_user_id = null, by_contact_id = $1 WHERE meeting_id = $2 AND member_id = $3`,
  [outsider, tue1.id, hClerk.id], /person who answered is not in this church/);
// The meeting moved since: the answer stays, for the time it was given for.
await ok(`UPDATE church_board_meetings SET starts_at = '2026-12-01T16:00:00Z' WHERE id = $1`, [tue1.id]);
same(await n(`church_meeting_answers a JOIN church_board_meetings m ON m.id = a.meeting_id
  WHERE a.meeting_id = $1 AND a.for_starts_at = m.starts_at`, [tue1.id]), 0);

// ─── The reminders' ledger ──────────────────────────────────────────────
const notice = more => put('church_meeting_notices', { business_id: b1, meeting_id: tue1.id, member_id: hClerk.id,
  kind: 'day_before', for_day: '2026-11-30', ...more });
// Claimed as it is made: the second claim for the same reminder gets nothing.
const claim = `INSERT INTO church_meeting_notices(business_id, meeting_id, member_id, kind, for_day, claimed_at)
  VALUES ($1, $2, $3, 'day_before', $4, now()) ON CONFLICT (meeting_id, member_id, kind, for_day) DO NOTHING RETURNING id`;
const got = await all(claim, [b1, tue1.id, hClerk.id, '2026-11-30']);
same([got.length, (await all(claim, [b1, tue1.id, hClerk.id, '2026-11-30'])).length], [1, 0]);
await ok(`UPDATE church_meeting_notices SET sent_at = now(), how = 'app' WHERE id = $1 AND sent_at IS NULL`, [got[0].id]);
await ok(claim, [b1, tue1.id, hClerk.id, '2026-12-03']);                                // the meeting moved to another day: one more
// Pressed in quiet hours: made unclaimed, sent later; a release lets go of the claim.
const nudge = (await db.query(...notice({ kind: 'nudge', for_day: '2026-11-28', made_by: u1, member_id: hPastor.id }))).rows[0];
checks++;
await refuses(...notice({ kind: 'nudge', for_day: '2026-11-28', made_by: u2, member_id: hPastor.id }), /church_meeting_notices_once/);
await ok(...notice({ kind: 'nudge', for_day: '2026-11-29', made_by: u2, member_id: hPastor.id }));   // once a day
await ok(`UPDATE church_meeting_notices SET claimed_at = now(), tries = tries + 1 WHERE id = $1 AND claimed_at IS NULL`, [nudge.id]);
await ok(`UPDATE church_meeting_notices SET claimed_at = null WHERE id = $1 AND sent_at IS NULL`, [nudge.id]);
// Each bad row on a day nothing else holds, so only the rule it breaks can refuse it.
for (const [bad, message] of [
  [{ kind: 'text' }, /check constraint/], [{ kind: null }, /null value/], [{ for_day: null }, /null value/],
  [{ made_by: u1 }, /church_meeting_notices_made_by/],
  [{ sent_at: '2026-11-30T15:00:00Z', how: 'app' }, /church_meeting_notices_sent/],
  [{ claimed_at: '2026-11-30T15:00:00Z', how: 'app' }, /church_meeting_notices_sent/],
  [{ claimed_at: '2026-11-30T15:00:00Z', sent_at: '2026-11-30T15:00:00Z' }, /church_meeting_notices_sent/],
  [{ claimed_at: '2026-11-30T15:00:00Z', sent_at: '2026-11-30T15:00:00Z', how: 'sms' }, /check constraint/],
  [{ tries: 21 }, /check constraint/], [{ tries: -1 }, /check constraint/],
  [{ member_id: mDeacon.id }, /not one of this meeting's people/],
  [{ member_id: lElder.id }, /not one of this meeting's people/],
  [{ meeting_id: theirMeeting.id }, /not one of this meeting's people|foreign key/],
]) await refuses(...notice({ for_day: '2026-12-31', ...bad }), message);
same(await n(`church_meeting_notices WHERE for_day = '2026-12-31'`), 0);
await ok(...notice({ member_id: hPastor.id, claimed_at: '2026-11-30T15:00:00Z', sent_at: '2026-11-30T15:00:01Z', how: 'email',
  tries: 20 }));
await ok(...notice({ member_id: hPastor.id, for_day: '2026-12-01', claimed_at: '2026-11-30T15:00:00Z',
  sent_at: '2026-11-30T15:00:01Z', how: 'nobody' }));
// The time changed after the day-before reminder went: one "moved" notice a person for the new day.
await ok(...notice({ member_id: hPastor.id, kind: 'moved', for_day: '2026-12-01' }));
await refuses(...notice({ member_id: hPastor.id, kind: 'moved', for_day: '2026-12-09', made_by: u1 }), /church_meeting_notices_made_by/);
await refuses(...notice({ member_id: hPastor.id, kind: 'moved', for_day: '2026-12-01' }), /church_meeting_notices_once/);
await refuses(`UPDATE church_meeting_notices SET member_id = $1 WHERE id = $2`, [mDeacon.id, nudge.id], /not one of this meeting's people/);
await refuses(`UPDATE church_meeting_notices SET how = null WHERE id = $1`, [got[0].id], /church_meeting_notices_sent/);
await refuses(`UPDATE church_meeting_notices SET claimed_at = null WHERE id = $1`, [got[0].id], /church_meeting_notices_sent/);

// ─── A private link for a phone's calendar ──────────────────────────────
const link = more => put('church_calendar_links', { business_id: b1, contact_id: elder, token_hash: hash('a'), ...more });
const l1 = (await db.query(...link({}))).rows[0]; checks++;
same([l1.revoked_at, l1.last_read_at, l1.made_by], [null, null, null]);
// Each bad row is for someone with no link yet, so only the rule it breaks can refuse it.
for (const [bad, message] of [
  [{ contact_id: pastor, token_hash: hash('A') }, /check constraint/],
  [{ contact_id: pastor, token_hash: '7'.repeat(63) }, /check constraint/],
  [{ contact_id: pastor, token_hash: '7'.repeat(65) }, /check constraint/],
  [{ contact_id: pastor, token_hash: hash('g') }, /check constraint/],
  [{ contact_id: pastor, token_hash: null }, /null value/],
  [{ contact_id: outsider, token_hash: hash('b') }, /That person is not in this church/],
  [{ contact_id: nobody, token_hash: hash('b') }, /That person is not in this church/],
  [{ token_hash: hash('b') }, /church_calendar_links_one_live/],                         // one working link a person
  [{ contact_id: clerk }, /church_calendar_links_token/],                                // a key is one link's, anywhere
]) await refuses(...link(bad), message);
await refuses(...link({ business_id: b2, contact_id: outsider }), /church_calendar_links_token/);
// A new link: the old one stops first, then the new one goes in.
await ok(`UPDATE church_calendar_links SET revoked_at = now() WHERE business_id = $1 AND contact_id = $2 AND revoked_at IS NULL`,
  [b1, elder]);
const l2 = (await db.query(...link({ token_hash: hash('b'), made_by: u2 }))).rows[0]; checks++;
same(await n('church_calendar_links WHERE contact_id = $1 AND revoked_at IS NULL', [elder]), 1);
await ok(...link({ contact_id: clerk, token_hash: hash('c') }));
await ok(...link({ business_id: b2, contact_id: outsider, token_hash: hash('d') }));     // the other church's own
await ok(`UPDATE church_calendar_links SET last_read_at = now() WHERE id = $1`, [l2.id]);
await ok(`UPDATE church_calendar_links SET last_read_at = now() WHERE id = $1`, [l1.id]);   // read after it stopped: still stopped
// Moved to someone with no link, to another church, or given another key: each would otherwise land.
for (const [change, args] of [['contact_id = $1', [pastor]], ['business_id = $1', [b2]], ['token_hash = $1', [hash('e')]]]) {
  await refuses(`UPDATE church_calendar_links SET ${change} WHERE id = $2`, [...args, l2.id], /keeps its church, its person and its key/);
}
// A stopped link, its person with no other: started again, or stopped at another time, is refused.
const lp = (await db.query(...link({ contact_id: pastor, token_hash: hash('9') }))).rows[0]; checks++;
await ok(`UPDATE church_calendar_links SET revoked_at = now() WHERE id = $1`, [lp.id]);
await refuses(`UPDATE church_calendar_links SET revoked_at = null WHERE id = $1`, [lp.id], /stays stopped/);
await refuses(`UPDATE church_calendar_links SET revoked_at = now() + interval '1 day' WHERE id = $1`, [lp.id], /stays stopped/);
await refuses(`UPDATE church_calendar_links SET revoked_at = null, last_read_at = now() WHERE id = $1`, [lp.id], /stays stopped/);
same(await one(`SELECT contact_id FROM church_calendar_links WHERE token_hash = $1 AND revoked_at IS NULL`, [hash('b')]),
  { contact_id: elder });
same(await one(`SELECT count(*)::int AS n FROM church_calendar_links WHERE token_hash = $1 AND revoked_at IS NULL`, [hash('a')]),
  { n: 0 });                                                                              // the old key opens nothing

// ─── Twice again, with every new kind of row in place ───────────────────
// Meeting groups for the list and of their own people, list seats (one left
// the list and came back), series, meetings made from them, one changed by
// itself and one skipped, rooms and bookings, answers with a note, reminders
// sent, waiting and claimed, live and stopped calendar links: the file once
// more changes nothing, in the catalog or in any row.
const everything = async () => {
  const out = {};
  for (const { relname } of await all(`SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'
    ORDER BY relname`)) {
    out[relname] = (await all(`SELECT j FROM (SELECT to_jsonb(x) AS j FROM public.${relname} x) s ORDER BY j::text`)).map(r => r.j);
  }
  return out;
};
same([await n(`church_boards WHERE kind = 'meeting'`) >= 3, await n(`church_board_members WHERE from_list`) >= 4,
  await n(`church_board_meetings WHERE cancelled_at IS NOT NULL`) >= 1, await n(`church_board_meetings WHERE changed_alone_at IS NOT NULL`) >= 1,
  await n(`church_calendar_links WHERE revoked_at IS NOT NULL`) >= 1, await n(`church_meeting_notices WHERE sent_at IS NULL`) >= 1,
  await n(`church_meeting_answers WHERE note IS NOT NULL`) >= 1], [true, true, true, true, true, true, true]);
const rowsNow = await everything();
await db.exec(FILE);
same(await catalog(), cat1);
same(await everything(), rowsNow);

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
same(await all(`SELECT p.proname, has_function_privilege('anon', p.oid, 'execute') AS anon,
    has_function_privilege('authenticated', p.oid, 'execute') AS authed,
    has_function_privilege('public', p.oid, 'execute') AS everyone, p.prosecdef AS definer
  FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname = ANY($1) ORDER BY 1`, [FUNCTIONS]),
  FUNCTIONS.map(proname => ({ proname, anon: false, authed: false, everyone: false, definer: false })));
// The board's and the rooms' tables are as server-only as they were.
for (const t of BOARD_TABLES) {
  same((await one(`SELECT c.relrowsecurity AS rls, (SELECT bool_or(has_table_privilege(r, c.oid, 'select'))
    FROM unnest(array['anon', 'authenticated']) r) AS browser FROM pg_class c WHERE c.oid = $1::regclass`, [`public.${t}`])),
    { rls: true, browser: false });
}
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  try {
    for (const t of TABLES) {
      await refuses(`SELECT * FROM ${t}`, [], /permission denied/);
      await refuses(`DELETE FROM ${t}`, [], /permission denied/);
    }
    await refuses(...link({ contact_id: pastor, token_hash: hash('f') }), /permission denied/);
    await refuses(...answer({ meeting_id: sat.id, member_id: hClerk.id }), /permission denied/);
    await refuses(`SELECT kind, audience FROM church_boards`, [], /permission denied/);
    await refuses(`SELECT series_id FROM church_board_meetings`, [], /permission denied/);
  } finally { await db.exec('RESET ROLE'); }
}
await db.exec('SET ROLE service_role');                                                  // the server's own role can
try {
  await ok(...link({ contact_id: pastor, token_hash: hash('f') }));
  await ok(`DELETE FROM church_calendar_links WHERE token_hash = $1`, [hash('f')]);
  await ok(`UPDATE church_boards SET name = 'Staff huddle' WHERE id = $1`, [huddle.id]);
} finally { await db.exec('RESET ROLE'); }

// ─── What goes with what ────────────────────────────────────────────────
// A login deleted leaves everything it named, with nobody in its place.
await ok(`UPDATE church_board_meetings SET cancelled_by = $1 WHERE id = $2`, [u2, tue2.id]);
await ok(...answer({ meeting_id: tue2.id, member_id: hClerk.id, by_user_id: u2 }));
await ok('DELETE FROM auth.users WHERE id = $1', [u2]);
same(await one(`SELECT (SELECT cancelled_by FROM church_board_meetings WHERE id = $1) AS cancelled_by,
  (SELECT cancelled_at IS NOT NULL FROM church_board_meetings WHERE id = $1) AS still_off,
  (SELECT by_user_id FROM church_meeting_answers WHERE meeting_id = $1 AND member_id = $2) AS answered_by,
  (SELECT count(*)::int FROM church_meeting_notices WHERE made_by IS NOT NULL AND for_day = '2026-11-29') AS pressed_by,
  (SELECT made_by FROM church_calendar_links WHERE id = $3) AS link_by`, [tue2.id, hClerk.id, l2.id]),
  { cancelled_by: null, still_off: true, answered_by: null, pressed_by: 0, link_by: null });
// A booking deleted leaves its meeting, with no booking; a room deleted leaves
// its meetings and series with no room, and its bookings go with it.
await ok(`DELETE FROM church_space_bookings WHERE id = $1`, [kWaiting]);
same(await n(`church_board_meetings WHERE booking_id = $1`, [kWaiting]), 0);
same(await n(`church_board_meetings WHERE space_id = $1 AND starts_at = '2026-12-22T15:00:00Z'`, [hall.id]), 1);
await ok(`UPDATE church_meeting_series SET space_id = $1 WHERE id = $2`, [van.id, sCheckins.id]);
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [van.id, kVan, sat.id]);
await ok(`DELETE FROM church_spaces WHERE id = $1`, [van.id]);
same(await one(`SELECT space_id, booking_id, series_id FROM church_board_meetings WHERE id = $1`, [sat.id]),
  { space_id: null, booking_id: null, series_id: sLeaders.id });
same(await one(`SELECT space_id FROM church_meeting_series WHERE id = $1`, [sCheckins.id]), { space_id: null });
same(await n(`church_space_bookings WHERE id = $1`, [kVan]), 0);
// A meeting deleted takes its answers and its reminders; its room's booking is Rooms & spaces' own.
await ok(`UPDATE church_board_meetings SET space_id = $1, booking_id = $2 WHERE id = $3`, [hall.id, kHall, sat.id]);
await ok(...notice({ meeting_id: sat.id, member_id: lClerk.id, for_day: '2026-12-18' }));
same([await n('church_meeting_answers WHERE meeting_id = $1', [sat.id]), await n('church_meeting_notices WHERE meeting_id = $1', [sat.id])],
  [1, 1]);
await ok(`DELETE FROM church_board_meetings WHERE id = $1`, [sat.id]);
same([await n('church_meeting_answers WHERE meeting_id = $1', [sat.id]), await n('church_meeting_notices WHERE meeting_id = $1', [sat.id]),
  await n('church_space_bookings WHERE id = $1', [kHall])], [0, 0, 1]);
// A member row deleted takes its answers and reminders, nobody else's.
const others = await n('church_meeting_answers WHERE member_id <> $1', [hPastor.id]);
await ok(`DELETE FROM church_board_members WHERE id = $1`, [hPastor.id]);
same([await n('church_meeting_answers WHERE member_id = $1', [hPastor.id]), await n('church_meeting_notices WHERE member_id = $1', [hPastor.id]),
  await n('church_meeting_answers WHERE member_id <> $1', [hPastor.id])], [0, 0, others]);
// A series deleted leaves its meetings, as one-offs that keep their day and what was changed by itself.
await ok(`DELETE FROM church_meeting_series WHERE id = $1`, [sHuddle.id]);
same(await all(`SELECT series_id, series_day::text, changed_alone_at IS NOT NULL AS alone, cancelled_at IS NOT NULL AS off
  FROM church_board_meetings WHERE id IN ($1, $2) ORDER BY starts_at`, [tue1.id, tue2.id]),
  [{ series_id: null, series_day: '2026-12-01', alone: true, off: false },
   { series_id: null, series_day: '2026-12-08', alone: false, off: true }]);
same(await n('church_meeting_answers WHERE meeting_id = $1', [tue1.id]), 1);
// A person deleted: their link goes; their seats stay with no person (the board's
// rule, for old minutes), and so do the answers given from them, with no one named.
await ok(`UPDATE church_meeting_answers SET by_user_id = null, by_contact_id = $1 WHERE member_id = $2`, [clerk, hClerk.id]);
same(await n('church_meeting_answers WHERE member_id = $1 AND by_contact_id = $2', [hClerk.id, clerk]), 2);
await ok('DELETE FROM contacts WHERE id = $1', [clerk]);
same(await one(`SELECT (SELECT count(*)::int FROM church_calendar_links WHERE contact_id = $1) AS links,
  (SELECT count(*)::int FROM church_board_members WHERE id IN ($2, $3) AND contact_id IS NULL AND from_list) AS seats,
  (SELECT count(*)::int FROM church_meeting_answers WHERE member_id = $2 AND by_contact_id IS NULL) AS answers`,
  [clerk, hClerk.id, lClerk.id]), { links: 0, seats: 2, answers: 2 });
// Two seats with no person on one group never clash, and the list seats someone new beside them.
await ok(...fromList(huddle, pastor));
await ok('DELETE FROM contacts WHERE id = $1', [pastor]);
same(await n('church_board_members WHERE board_id = $1 AND from_list AND contact_id IS NULL', [huddle.id]), 2);
await ok(...fromList(huddle, elder));
// A group deleted takes its series, meetings, seats, answers and reminders; the rooms stay.
same(await n('church_meeting_series WHERE board_id = $1', [leaders.id]), 1);
await ok(`DELETE FROM church_boards WHERE id = $1`, [leaders.id]);
same([await n('church_meeting_series WHERE board_id = $1', [leaders.id]), await n('church_board_meetings WHERE board_id = $1', [leaders.id]),
  await n('church_board_members WHERE board_id = $1', [leaders.id]), await n('church_spaces WHERE id = $1', [hall.id])], [0, 0, 0, 1]);
same(await n(`church_meeting_answers WHERE member_id = $1`, [lClerk.id]), 0);
await db.close();

// ─── A church deleted, its foreign keys firing both ways round ──────────
// Postgres fires a delete's foreign keys in the order they were made. In the
// first run the rooms' keys to the church are made again last, so a church's
// groups and meetings go before its rooms; in the second the board tables'
// keys are, so its rooms and bookings go first and set its meetings' room and
// booking to nothing (an update the file's trigger sees) before the meetings
// themselves go. Either way the church goes, taking everything of its own, and
// the other church keeps its own.
const remake = async (tables) => {
  for (const t of tables) {
    const keys = await all(`SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint
      WHERE conrelid = $1::regclass AND contype = 'f' AND confrelid = 'public.businesses'::regclass`, [`public.${t}`]);
    for (const k of keys) {
      await db.exec(`ALTER TABLE public.${t} DROP CONSTRAINT ${k.conname}; ALTER TABLE public.${t} ADD CONSTRAINT ${k.conname} ${k.def}`);
    }
  }
};
const firing = async () => (await all(`SELECT DISTINCT ON (c.conrelid) c.conrelid::regclass::text AS t, g.tgname
  FROM pg_trigger g JOIN pg_constraint c ON c.oid = g.tgconstraint
  WHERE g.tgrelid = 'public.businesses'::regclass AND g.tgtype & 8 = 8 AND c.confdeltype = 'c'
    AND c.conrelid IN ('public.church_spaces'::regclass, 'public.church_board_meetings'::regclass)
  ORDER BY c.conrelid, g.tgname`)).sort((x, y) => (x.tgname < y.tgname ? -1 : 1)).map(x => x.t);
const filled = async () => {
  const g = await add('church_boards', { business_id: b1, name: 'Leaders meeting', kind: 'meeting', audience: 'leaders' });
  const bd = await add('church_boards', { business_id: b1, name: 'Deacons' });
  const room = await add('church_spaces', { business_id: b1, name: 'Fellowship hall' });
  const s = await add('church_meeting_series', { business_id: b1, board_id: g.id, weekday: 6, pattern: 'month_nth', nth: 3,
    starts_on: '2031-01-18', at_time: '10:00', space_id: room.id, created_by: u1 });
  const seat = await add('church_board_members', { business_id: b1, board_id: g.id, contact_id: elder, name: 'Eli', from_list: true });
  const seat2 = await add('church_board_members', { business_id: b1, board_id: bd.id, contact_id: deacon, name: 'Dana' });
  for (const [day, at] of [['2031-01-18', '2031-01-18T15:00:00Z'], ['2031-02-15', '2031-02-15T15:00:00Z']]) {
    const k = (await add('church_space_bookings', { business_id: b1, space_id: room.id, title: 'Leaders meeting', start_at: at,
      end_at: new Date(Date.parse(at) + 3600e3).toISOString(), status: 'booked' })).id;
    const m = await add('church_board_meetings', { business_id: b1, board_id: g.id, starts_at: at, series_id: s.id, series_day: day,
      space_id: room.id, booking_id: k, length_minutes: 60 });
    await add('church_meeting_answers', { business_id: b1, meeting_id: m.id, member_id: seat.id, answer: 'cant', note: 'Away',
      for_starts_at: at, by_contact_id: elder });
    await add('church_meeting_notices', { business_id: b1, meeting_id: m.id, member_id: seat.id, kind: 'day_before', for_day: day });
  }
  const bm = await add('church_board_meetings', { business_id: b1, board_id: bd.id, starts_at: '2031-03-10T23:00:00Z',
    space_id: room.id });
  await add('church_board_attendance', { business_id: b1, meeting_id: bm.id, member_id: seat2.id, status: 'present' });
  await add('church_calendar_links', { business_id: b1, contact_id: elder, token_hash: hash('1') });
  // the other church's own
  const tg = await add('church_boards', { business_id: b2, name: 'Their huddle', kind: 'meeting', audience: 'office' });
  const tseat = await add('church_board_members', { business_id: b2, board_id: tg.id, contact_id: outsider, name: 'x', from_list: true });
  const ts = await add('church_meeting_series', { business_id: b2, board_id: tg.id, weekday: 2, pattern: 'weekly',
    starts_on: '2031-01-07', at_time: '09:00' });
  const tm = await add('church_board_meetings', { business_id: b2, board_id: tg.id, starts_at: '2031-01-07T14:00:00Z',
    series_id: ts.id, series_day: '2031-01-07' });
  await add('church_meeting_answers', { business_id: b2, meeting_id: tm.id, member_id: tseat.id, answer: 'yes',
    for_starts_at: '2031-01-07T14:00:00Z' });
  await add('church_calendar_links', { business_id: b2, contact_id: outsider, token_hash: hash('2') });
};
const counts = async () => {
  const out = {};
  for (const t of [...TABLES, 'church_boards', 'church_board_members', 'church_board_meetings', 'church_spaces',
    'church_space_bookings']) out[t] = await n(t);
  return out;
};
const theirs = { church_calendar_links: 1, church_meeting_answers: 1, church_meeting_notices: 0, church_meeting_series: 1,
  church_boards: 1, church_board_members: 1, church_board_meetings: 1, church_spaces: 0, church_space_bookings: 0 };
for (const [last, order] of [
  [['church_spaces', 'church_space_bookings'], ['church_board_meetings', 'church_spaces']],
  [['church_boards', 'church_board_members', 'church_board_meetings', 'church_board_items', 'church_board_attendance',
    'church_board_decisions', 'church_meeting_series', 'church_meeting_answers', 'church_meeting_notices'],
   ['church_spaces', 'church_board_meetings']]]) {
  db = await stand();
  await db.exec(FILE);
  await remake(last);
  same(await firing(), order);
  await filled();
  await ok('DELETE FROM businesses WHERE id = $1', [b1]);
  same(await counts(), theirs);
  await db.close();
}

// ─── The file's own Rollback block, as written ──────────────────────────
// With rows in everything (meetings far enough ahead that they are still to
// come whenever this runs): before the columns go, every room held for a
// meeting that won't happen is let go (a meeting group's meetings still to
// come, called-off ones, a series' empty ones ahead), those meetings with
// nothing recorded are taken out, every meeting group is closed and every list
// seat let go; a board's own meetings ahead with an agenda, and its one-off
// meetings, keep their rooms. Afterwards the catalog is back as the board and
// spaces files left it, every board, member, item, attendance mark, decision,
// room and booking is still there, and the file goes in again.
db = await stand();
const before = await catalog();
await db.exec(FILE);
const applied = await catalog();
same(applied, cat1);
await filled();
const G = (await one(`SELECT id FROM church_boards WHERE business_id = $1 AND kind = 'meeting'`, [b1])).id;
const BD = (await one(`SELECT id FROM church_boards WHERE business_id = $1 AND name = 'Deacons'`, [b1])).id;
const room2 = (await add('church_spaces', { business_id: b1, name: 'Room 2' })).id;
const BS = (await add('church_meeting_series', { business_id: b1, board_id: BD, weekday: 4, pattern: 'month_nth', nth: 1,
  starts_on: '2031-01-02', at_time: '19:00', space_id: room2 })).id;
const roomFor = async at => (await add('church_space_bookings', { business_id: b1, space_id: room2, title: 'A meeting',
  start_at: at, end_at: new Date(Date.parse(at) + 3600e3).toISOString(), status: 'booked' })).id;
const meetingAt = async (board, at, more = {}) => {
  const k = await roomFor(at);
  return { id: (await add('church_board_meetings', { business_id: b1, board_id: board, starts_at: at, space_id: room2,
    booking_id: k, ...more })).id, k };
};
const gEmpty = await meetingAt(G, '2031-04-01T15:00:00Z');                                   // a meeting group's, ahead, empty
const gAgenda = await meetingAt(G, '2031-04-08T15:00:00Z');                                  // a meeting group's, ahead, with an agenda
await add('church_board_items', { business_id: b1, meeting_id: gAgenda.id, title: 'Kept' });
const gPast = await meetingAt(G, '2020-06-01T15:00:00Z');                                    // a meeting group's, long past, not held
const bSeriesEmpty = await meetingAt(BD, '2031-01-02T23:00:00Z', { series_id: BS, series_day: '2031-01-02' });
const bSeriesAgenda = await meetingAt(BD, '2031-02-06T23:00:00Z', { series_id: BS, series_day: '2031-02-06' });
await add('church_board_items', { business_id: b1, meeting_id: bSeriesAgenda.id, title: 'The roof' });
const bOneOff = await meetingAt(BD, '2031-05-01T23:00:00Z');                                 // a board's own one-off, ahead, empty
const offEmpty = await meetingAt(BD, '2031-06-01T23:00:00Z', { cancelled_at: '2026-11-20T15:00:00Z' });
const offKept = await meetingAt(BD, '2031-06-08T23:00:00Z', { cancelled_at: '2026-11-20T15:00:00Z' });
await add('church_board_items', { business_id: b1, meeting_id: offKept.id, title: 'An item kept' });
const filledRooms = (await all(`SELECT booking_id FROM church_board_meetings WHERE board_id = $1 AND series_id IS NOT NULL
  ORDER BY starts_at`, [G])).map(r => r.booking_id);
same(filledRooms.length, 2);
const listSeats = (await all(`SELECT id FROM church_board_members WHERE from_list AND active`)).map(r => r.id);
same(listSeats.length >= 2, true);
const tally = async () => ({ boards: await n('church_boards'), members: await n('church_board_members'),
  meetings: await n('church_board_meetings'), items: await n('church_board_items'), attendance: await n('church_board_attendance'),
  spaces: await n('church_spaces'), bookings: await n('church_space_bookings') });
const kept = await tally();
const undo = block('-- Rollback');
assert.ok(undo.length >= 14); checks++;
for (const statement of undo) await db.exec(statement);
same(await catalog(), before);
// Nothing lost but the meetings that won't happen and had nothing in them: the
// group's two empty series meetings and its empty one ahead, the board's empty
// series meeting ahead, the empty one called off, and the other church's
// group's empty series meeting ahead (the rollback is the whole database's).
same(await tally(), { ...kept, meetings: kept.meetings - 6 });
const there = async m => n('church_board_meetings WHERE id = $1', [m.id]);
same([await there(gEmpty), await there(gAgenda), await there(gPast), await there(bSeriesEmpty), await there(bSeriesAgenda),
  await there(bOneOff), await there(offEmpty), await there(offKept)], [0, 1, 1, 0, 1, 1, 0, 1]);
// Rooms: let go for everything that won't happen; kept for what will, and for the past.
const status = async k => (await one(`SELECT status FROM church_space_bookings WHERE id = $1`, [k])).status;
same([await status(gEmpty.k), await status(gAgenda.k), await status(gPast.k), await status(bSeriesEmpty.k),
  await status(bSeriesAgenda.k), await status(bOneOff.k), await status(offEmpty.k), await status(offKept.k)],
  ['cancelled', 'cancelled', 'booked', 'cancelled', 'booked', 'booked', 'cancelled', 'cancelled']);
same([await status(filledRooms[0]), await status(filledRooms[1])], ['cancelled', 'cancelled']);
// Every list seat let go; every meeting group closed; the board as it was.
same(await all(`SELECT DISTINCT active FROM church_board_members WHERE id = ANY($1)`, [listSeats]), [{ active: false }]);
same(await all(`SELECT name, archived FROM church_boards WHERE business_id = $1 ORDER BY name`, [b1]),
  [{ name: 'Deacons', archived: false }, { name: 'Leaders meeting', archived: true }]);
await db.exec(FILE);
same(await catalog(), applied);
same(await all(`SELECT DISTINCT kind, audience FROM church_boards`), [{ kind: 'board', audience: 'members' }]);
await db.close();

console.log(`church meetings db: ${checks} checks passed`);
