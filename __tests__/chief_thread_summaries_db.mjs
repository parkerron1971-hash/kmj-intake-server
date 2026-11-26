// A long chat's running summary, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-25-chief-thread-summaries.sql.
//
// One server-only table (RLS on, no policies, the browser's roles can't read or
// write it); one row a chat, keyed by business, login and the app's chat id; a
// write that names the version it read can't land twice; the shapes the code
// sends are the shapes the checks take; running the file twice changes nothing;
// a business that goes takes its rows.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/chief_thread_summaries_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const jessica = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

const file = await readFile(new URL('../supabase/APPLY-2026-11-25-chief-thread-summaries.sql', import.meta.url), 'utf8');
await db.exec(file);
await db.exec(file);   // safe to run twice

const t = await one(`SELECT c.relrowsecurity AS rls,
    (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS policies,
    has_table_privilege('authenticated', c.oid, 'select') AS browser_reads,
    has_table_privilege('authenticated', c.oid, 'insert') AS browser_writes,
    has_table_privilege('anon', c.oid, 'select') AS anon_reads,
    has_table_privilege('service_role', c.oid, 'insert') AS server_writes
  FROM pg_class c WHERE c.relname = 'chief_thread_summaries'`);
assert.deepEqual(t, { rls: true, policies: 0, browser_reads: false, browser_writes: false, anon_reads: false,
                      server_writes: true }); checks++;

// A row as chief_thread_summary.fold sends it the first time.
const add = (biz, who, chat, summary = 'The person asked about Sunday.', folded = ['a1', 'b2', 'c3']) => db.query(
  `INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id, summary, folded, folded_count, version, updated_at)
   VALUES ($1, $2, $3, $4, $5::jsonb, $6, 1, now()) RETURNING *`,
  [biz, who, chat, summary, JSON.stringify(folded), folded.length]);
const row = (await add(b1, jessica, 'chat-1')).rows[0];
assert.equal(row.version, 1); assert.deepEqual(row.folded, ['a1', 'b2', 'c3']); checks++;

// One row a chat: the same business, login and chat can't have two.
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id) VALUES ($1, $2, 'chat-1')`,
  [b1, jessica], /duplicate key/);
// Another login's chat under the same id is its own row, and so is another business's.
await add(b1, owner, 'chat-1', 'The owner asked about giving.');
await add(b2, jessica, 'chat-1');
assert.equal((await one(`SELECT count(*)::int AS n FROM chief_thread_summaries`)).n, 3); checks++;

// A write names the version it read: the first lands, the second (the same read) changes nothing.
const patch = (version, summary) => db.query(
  `UPDATE chief_thread_summaries SET summary = $1, version = $2 + 1, updated_at = now()
    WHERE business_id = $3 AND user_id = $4 AND conversation_id = 'chat-1' AND version = $2`,
  [summary, version, b1, jessica]);
assert.equal((await patch(1, 'first fold')).affectedRows, 1); checks++;
assert.equal((await patch(1, 'second fold, same read')).affectedRows, 0); checks++;
assert.deepEqual(await one(`SELECT summary, version FROM chief_thread_summaries
  WHERE business_id = $1 AND user_id = $2 AND conversation_id = 'chat-1'`, [b1, jessica]),
  { summary: 'first fold', version: 2 }); checks++;

// The checks: an id of 1 to 120, a summary of 4000 at most, a list of fingerprints, counts that aren't negative.
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id) VALUES ($1, $2, '')`,
  [b1, jessica], /chief_thread_summaries_id_len/);
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id) VALUES ($1, $2, $3)`,
  [b1, jessica, 'x'.repeat(121)], /chief_thread_summaries_id_len/);
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id, summary) VALUES ($1, $2, 'c2', $3)`,
  [b1, jessica, 'x'.repeat(4001)], /chief_thread_summaries_summary_len/);
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id, folded) VALUES ($1, $2, 'c3', '{}'::jsonb)`,
  [b1, jessica], /chief_thread_summaries_folded_list/);
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id, folded_count) VALUES ($1, $2, 'c4', -1)`,
  [b1, jessica], /chief_thread_summaries_counts/);
await refuses(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id) VALUES ($1, $2, 'c5')`,
  ['33333333-3333-4333-8333-333333333333', jessica], /foreign key/);
// The longest the code sends fits (chief_thread_summary.SUMMARY_CHARS is 3200).
await add(b1, jessica, 'chat-long', 'x'.repeat(3200), Array.from({ length: 40 }, (_, i) => `f${i}`)); checks++;

// The browser's roles can't touch it, with or without a login.
for (const role of ['authenticated', 'anon']) {
  await db.exec(`SET ROLE ${role};`);
  try {
    await assert.rejects(db.query('SELECT 1 FROM chief_thread_summaries'), /permission denied/); checks++;
    await assert.rejects(db.query(`INSERT INTO chief_thread_summaries(business_id, user_id, conversation_id)
      VALUES ('${b1}', '${jessica}', 'mine')`), /permission denied/); checks++;
  } finally { await db.exec('RESET ROLE;'); }
}

// A business that goes takes its rows, and only its own.
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.deepEqual((await db.query(`SELECT business_id FROM chief_thread_summaries`)).rows, [{ business_id: b2 }]); checks++;

console.log(`chief thread summaries: ${checks} checks passed`);
