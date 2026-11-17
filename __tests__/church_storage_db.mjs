// A church's storage allowance on a real Postgres (PGlite):
// supabase/APPLY-2026-11-17-church-storage.sql over a stand-in for
// storage.objects and the stream relay's stream_sessions as production has it.
// Holds what a string check can't: the files sum counts only paths under
// "<business id>/" (any bucket, any depth), skips a size that isn't a number,
// only the server may call it, the new columns default safely, a warning count
// past 3 is refused, and the app's logins can't read church_storage_notes.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_storage_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const db = new PGlite();
const church = '11111111-1111-4111-8111-111111111111', other = '22222222-2222-4222-8222-222222222222';

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA storage;
  CREATE TABLE storage.objects(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bucket_id text, name text, metadata jsonb);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  -- APPLY-2026-10-16-stream-relay.sql, as applied.
  CREATE TABLE public.stream_sessions(
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'live',
    playlist_path text NOT NULL DEFAULT '',
    duration_s integer NOT NULL DEFAULT 0,
    bytes bigint NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz);
  ALTER TABLE public.stream_sessions ENABLE ROW LEVEL SECURITY;
  -- Supabase gives the app's roles these on every new public table and function.
  GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;`);

await db.query('INSERT INTO businesses VALUES ($1, null), ($2, null)', [church, other]);
await db.query(`INSERT INTO stream_sessions(business_id, status, bytes) VALUES ($1, 'ended', 6000000000)`, [church]);
const objects = [
  ['business-assets', `${church}/logo.png`, { size: 1000 }],
  ['program-media', `${church}/sermons/2026/week-1.mp4`, { size: 2500 }],
  ['receipts', `${church}/receipts/a.pdf`, { size: '500' }],
  ['business-assets', `${church}/broken.bin`, { size: 'abc' }],     // not a number: skipped
  ['business-assets', `${church}/nosize.bin`, {}],                   // no size: skipped
  ['business-assets', `${other}/logo.png`, { size: 99999 }],         // another church
  ['business-assets', `x${church}/sneaky.png`, { size: 7777 }],      // not under the prefix
  ['business-assets', church, { size: 4444 }],                       // the bare id, no folder
  ['business-assets', `users/${church}/a.png`, { size: 3333 }],      // the id deeper in a path
];
for (const [bucket, name, metadata] of objects) {
  await db.query('INSERT INTO storage.objects(bucket_id, name, metadata) VALUES ($1, $2, $3)', [bucket, name, metadata]);
}

const sql = await readFile(new URL('../supabase/APPLY-2026-11-17-church-storage.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);   // idempotent

let checks = 0;
const files = async (who, id) => {
  await db.exec(`SET ROLE ${who};`);
  try {
    return Number((await db.query('SELECT public.church_storage_files_bytes($1) AS n', [id])).rows[0].n);
  } finally {
    await db.exec('RESET ROLE;');
  }
};

// The server reads the church's files: every bucket, any depth, sizes as text too.
assert.equal(await files('service_role', church), 4000); checks++;
assert.equal(await files('service_role', other), 99999); checks++;
assert.equal(await files('service_role', '33333333-3333-4333-8333-333333333333'), 0, 'nothing stored is 0'); checks++;

// Only the server: the app's logins can't call it.
for (const who of ['anon', 'authenticated']) {
  await assert.rejects(files(who, church), /permission denied/, who); checks++;
}

// The new columns: a session made the old way (the relay's functions name
// their columns) is counted, not kept, never warned.
const s = (await db.query('SELECT removed_at, keep_until, warnings_sent, last_warned_at FROM stream_sessions')).rows[0];
assert.deepEqual(s, { removed_at: null, keep_until: null, warnings_sent: 0, last_warned_at: null }); checks++;
await db.query(`INSERT INTO stream_sessions(business_id, status, playlist_path) VALUES ($1, 'live', 'live/x')`, [church]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM stream_sessions WHERE warnings_sent = 0')).rows[0].n, 2); checks++;
await assert.rejects(db.query('UPDATE stream_sessions SET warnings_sent = 4'), /stream_sessions_warnings_sent/); checks++;
await db.query('UPDATE stream_sessions SET warnings_sent = 3'); checks++;

// The heads-up record is the server's alone; it goes with its church.
await db.query('INSERT INTO church_storage_notes(business_id, near_noted_at) VALUES ($1, now())', [church]);
for (const who of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${who};`);
  await assert.rejects(db.query('SELECT * FROM church_storage_notes'), /permission denied/, who); checks++;
  await db.exec('RESET ROLE;');
}
await db.exec('SET ROLE service_role;');
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_storage_notes')).rows[0].n, 1); checks++;
await db.exec('RESET ROLE;');
await db.query('DELETE FROM businesses WHERE id = $1', [church]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_storage_notes')).rows[0].n, 0, 'cascade'); checks++;

// The function reads nothing but storage.objects and pins its search path.
const fn = (await db.query(`SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'church_storage_files_bytes'`)).rows[0];
assert.equal(fn.prosecdef, true); checks++;
assert.deepEqual(fn.proconfig, ['search_path=""']); checks++;

console.log(`church storage database checks passed (${checks})`);
