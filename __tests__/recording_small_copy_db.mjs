// A recording's smaller copy on a real Postgres (PGlite):
// supabase/APPLY-2026-11-17-recording-small-copy.sql over stream_sessions as
// production has it (the stream relay's table plus the storage allowance's
// columns). Holds what a string check can't: it runs twice, a session the
// relay makes the old way gets safe defaults, only the four states are taken,
// the full-quality recording can be marked removed only with a ready copy, a
// copy is never 0 bytes, tries stay in range, the job's two reads use their
// partial indexes' conditions, and the app's logins still read no session.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/recording_small_copy_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const db = new PGlite();
const church = '11111111-1111-4111-8111-111111111111';

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
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
  -- APPLY-2026-11-17-church-storage.sql's columns.
  ALTER TABLE public.stream_sessions ADD COLUMN removed_at timestamptz, ADD COLUMN keep_until timestamptz,
    ADD COLUMN warnings_sent smallint NOT NULL DEFAULT 0, ADD COLUMN last_warned_at timestamptz;
  GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
  GRANT ALL ON public.stream_sessions TO anon, authenticated, service_role;`);

await db.query('INSERT INTO businesses VALUES ($1, null)', [church]);
const ended = (await db.query(
  `INSERT INTO stream_sessions(business_id, status, bytes, duration_s, ended_at)
   VALUES ($1, 'ended', 6000000000, 7200, now() - interval '20 days') RETURNING id`, [church])).rows[0].id;

const sql = await readFile(new URL('../supabase/APPLY-2026-11-17-recording-small-copy.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);   // idempotent

let checks = 0;
const one = async (id) => (await db.query(
  `SELECT copy_state, copy_job, copy_tries, copy_at, copy_bytes, copy_seconds, copy_made_at, copy_error,
          full_removed_at FROM stream_sessions WHERE id = $1`, [id])).rows[0];

// A session from before, and one the relay makes now (its functions name their columns): no copy yet.
const blank = { copy_state: null, copy_job: null, copy_tries: 0, copy_at: null, copy_bytes: null,
  copy_seconds: null, copy_made_at: null, copy_error: null, full_removed_at: null };
assert.deepEqual(await one(ended), blank); checks++;
const fresh = (await db.query(`INSERT INTO stream_sessions(business_id, status, playlist_path)
  VALUES ($1, 'live', 'live/x') RETURNING id`, [church])).rows[0].id;
assert.deepEqual(await one(fresh), blank); checks++;

// Only the four states.
for (const state of ['queued', 'working', 'ready', 'failed']) {
  await db.query('UPDATE stream_sessions SET copy_state = $2 WHERE id = $1', [fresh, state]);
}
checks++;
await assert.rejects(db.query(`UPDATE stream_sessions SET copy_state = 'done' WHERE id = $1`, [fresh]),
  /stream_sessions_copy_state/); checks++;

// A copy is never 0 bytes; tries stay in range.
await assert.rejects(db.query('UPDATE stream_sessions SET copy_bytes = 0 WHERE id = $1', [ended]),
  /stream_sessions_copy_bytes/); checks++;
await assert.rejects(db.query('UPDATE stream_sessions SET copy_tries = 21 WHERE id = $1', [ended]),
  /stream_sessions_copy_tries/); checks++;
await assert.rejects(db.query('UPDATE stream_sessions SET copy_tries = -1 WHERE id = $1', [ended]),
  /stream_sessions_copy_tries/); checks++;

// The full-quality recording is marked removed only with a ready copy.
await assert.rejects(db.query('UPDATE stream_sessions SET full_removed_at = now() WHERE id = $1', [ended]),
  /stream_sessions_full_removed/); checks++;
await db.query(`UPDATE stream_sessions SET copy_state = 'working', copy_job = gen_random_uuid(), copy_tries = 1
  WHERE id = $1`, [ended]);
await assert.rejects(db.query('UPDATE stream_sessions SET full_removed_at = now() WHERE id = $1', [ended]),
  /stream_sessions_full_removed/); checks++;
await db.query(`UPDATE stream_sessions SET copy_state = 'ready', copy_bytes = 1400000000, copy_seconds = 7199.97,
  copy_made_at = now() WHERE id = $1`, [ended]);
await db.query('UPDATE stream_sessions SET full_removed_at = now() WHERE id = $1', [ended]); checks++;
assert.equal(Number((await one(ended)).copy_seconds), 7199.97); checks++;
// And once it is removed, the copy can't be taken out from under it.
await assert.rejects(db.query(`UPDATE stream_sessions SET copy_state = 'failed', copy_bytes = null WHERE id = $1`,
  [ended]), /stream_sessions_full_removed/); checks++;

// The job's reads, as written in recording_copy.py, see what they should.
const todo = await db.query(`SELECT id FROM stream_sessions WHERE status = 'ended' AND removed_at IS NULL
  AND full_removed_at IS NULL AND copy_state IS NULL`);
assert.equal(todo.rows.length, 0, 'the trimmed one is done'); checks++;
const idx = (await db.query(`SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'stream_sessions'
  AND indexname IN ('stream_sessions_copy_todo', 'stream_sessions_copy_busy') ORDER BY 1`)).rows;
assert.equal(idx.length, 2); checks++;
assert.match(idx[1].indexdef, /WHERE \(\(status = 'ended'::text\) AND \(removed_at IS NULL\) AND \(full_removed_at IS NULL\)\)/); checks++;

// Still the server's alone: RLS with no policy shows the app's logins nothing.
for (const who of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${who};`);
  assert.equal((await db.query('SELECT count(*)::int AS n FROM stream_sessions')).rows[0].n, 0, who); checks++;
  await db.exec('RESET ROLE;');
}

console.log(`recording small copy database checks passed (${checks})`);
