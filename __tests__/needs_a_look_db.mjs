// "Needs a look", on a real Postgres (PGlite): supabase/APPLY-2026-11-27-needs-a-look.sql.
//
// Four server-only tables (RLS on, no policies, the browser's roles can't read or
// write them); the rows inbound_hold sends are the rows the checks take; a retried
// card is one row; a church's memory of a sender is one row a hash (an upsert
// replaces it); the shared list is one row a hash; running the file twice changes
// nothing; a contact that goes leaves its checks without a contact and takes its
// decisions; a business that goes takes everything of its own.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/needs_a_look_db.mjs
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
const sara = 'cccccccc-1111-4111-8111-111111111111';
const dana = 'cccccccc-2222-4222-8222-222222222222';
const h = c => c.repeat(64);
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid REFERENCES businesses(id) ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $2), ($3, $2)', [sara, b1, dana]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

const file = await readFile(new URL('../supabase/APPLY-2026-11-27-needs-a-look.sql', import.meta.url), 'utf8');
await db.exec(file);
await db.exec(file);   // safe to run twice

const TABLES = ['inbound_checks', 'inbound_decisions', 'inbound_senders', 'inbound_shared_list'];
for (const name of TABLES) {
  const t = await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS policies,
      has_table_privilege('authenticated', c.oid, 'select') AS browser_reads,
      has_table_privilege('authenticated', c.oid, 'insert') AS browser_writes,
      has_table_privilege('anon', c.oid, 'select') AS anon_reads,
      has_table_privilege('service_role', c.oid, 'insert') AS server_writes
    FROM pg_class c WHERE c.relname = $1`, [name]);
  assert.deepEqual(t, { rls: true, policies: 0, browser_reads: false, browser_writes: false, anon_reads: false,
                        server_writes: true }, name); checks++;
}

// A held card, as inbound_hold.begin sends it, then its contact (attach).
const check = (id, receipt, state = 'held', extra = {}) => db.query(
  `INSERT INTO inbound_checks(id, business_id, receipt, door, verdict, score, reasons, second_opinion,
     email_hash, domain_hash, phone_hash, text_hash, state, pending)
   VALUES ($1, $2, $3, 'connect_card', $4, 7, $5::jsonb, $6, $7, $8, NULL, $9, $10, $11::jsonb)
   ON CONFLICT DO NOTHING RETURNING id`,
  [id, extra.biz || b1, receipt, extra.verdict || 'needs_look',
   JSON.stringify([{ code: 'junk_phone', points: 2, words: "The phone number isn't real" }]),
   extra.second ?? null, h('a'), h('b'), h('c'), state, JSON.stringify(extra.pending || { receipt, texts_ok: false })]);
const k1 = 'dddddddd-1111-4111-8111-111111111111';
assert.equal((await check(k1, 'eeeeeeee-1111-4111-8111-111111111111')).rows.length, 1); checks++;
assert.equal((await check(k1, 'eeeeeeee-1111-4111-8111-111111111111')).rows.length, 0); checks++;   // a retry
await db.query(`UPDATE inbound_checks SET contact_id = $1 WHERE id = $2 AND contact_id IS NULL`, [sara, k1]);
for (const state of ['clear', 'watched', 'flagged', 'released', 'closed']) {
  await check(crypto.randomUUID(), crypto.randomUUID(), state, { verdict: 'clear' });
}
await check(crypto.randomUUID(), crypto.randomUUID(), 'clear', { verdict: 'clear', second: 'pitch' });
checks++;

await refuses(`INSERT INTO inbound_checks(id, business_id, receipt, state) VALUES ($1, $2, 'r', 'waiting')`,
  [crypto.randomUUID(), b1], /inbound_checks_state/);
await refuses(`INSERT INTO inbound_checks(id, business_id, receipt, verdict) VALUES ($1, $2, 'r', 'spam')`,
  [crypto.randomUUID(), b1], /inbound_checks_verdict/);
await refuses(`INSERT INTO inbound_checks(id, business_id, receipt, second_opinion) VALUES ($1, $2, 'r', 'maybe')`,
  [crypto.randomUUID(), b1], /inbound_checks_second/);
await refuses(`INSERT INTO inbound_checks(id, business_id, receipt) VALUES ($1, $2, '')`,
  [crypto.randomUUID(), b1], /inbound_checks_receipt_len/);
await refuses(`INSERT INTO inbound_checks(id, business_id, receipt, reasons) VALUES ($1, $2, 'r', '{}'::jsonb)`,
  [crypto.randomUUID(), b1], /inbound_checks_reasons_list/);
await refuses(`INSERT INTO inbound_checks(id, business_id, receipt, pending) VALUES ($1, $2, 'r', '[]'::jsonb)`,
  [crypto.randomUUID(), b1], /inbound_checks_pending_obj/);

// A decision, as inbound_hold.decide sends it; undone later.
const d1 = 'ffffffff-1111-4111-8111-111111111111';
await db.query(`INSERT INTO inbound_decisions(id, business_id, contact_id, verdict, via, by_user, by_name, before)
  VALUES ($1, $2, $3, 'scam', 'app', $4, 'kevin', $5::jsonb)`,
  [d1, b1, sara, 'aaaaaaaa-1111-4111-8111-111111111111', JSON.stringify({ status: 'lead', closed: ['x'] })]);
await db.query(`UPDATE inbound_decisions SET undone_at = now() WHERE id = $1`, [d1]); checks++;
await refuses(`INSERT INTO inbound_decisions(id, business_id, contact_id, verdict) VALUES ($1, $2, $3, 'spam')`,
  [crypto.randomUUID(), b1, sara], /inbound_decisions_verdict/);
await refuses(`INSERT INTO inbound_decisions(id, business_id, contact_id, verdict, via) VALUES ($1, $2, $3, 'real', 'bot')`,
  [crypto.randomUUID(), b1, sara], /inbound_decisions_via/);
await db.query(`INSERT INTO inbound_decisions(id, business_id, contact_id, verdict, via) VALUES ($1, $2, $3, 'real', 'chief')`,
  [crypto.randomUUID(), b1, dana]); checks++;

// A church's memory of a sender: one row a hash, and Real replaces Scam (merge-duplicates).
const remember = (biz, kind, hash, verdict) => db.query(
  `INSERT INTO inbound_senders(business_id, kind, hash, verdict, at, decision_id) VALUES ($1, $2, $3, $4, now(), $5)
   ON CONFLICT (business_id, kind, hash) DO UPDATE SET verdict = excluded.verdict, at = excluded.at,
     decision_id = excluded.decision_id`, [biz, kind, hash, verdict, d1]);
await remember(b1, 'email', h('a'), 'scam');
await remember(b1, 'email', h('a'), 'real');
await remember(b2, 'email', h('a'), 'scam');
assert.deepEqual((await db.query(`SELECT business_id, verdict FROM inbound_senders ORDER BY business_id`)).rows,
  [{ business_id: b1, verdict: 'real' }, { business_id: b2, verdict: 'scam' }]); checks++;
await refuses(`INSERT INTO inbound_senders(business_id, kind, hash, verdict) VALUES ($1, 'name', $2, 'scam')`,
  [b1, h('z')], /inbound_senders_kind/);
await refuses(`INSERT INTO inbound_senders(business_id, kind, hash, verdict) VALUES ($1, 'email', 'abc', 'scam')`,
  [b1], /inbound_senders_hash_len/);
await refuses(`INSERT INTO inbound_senders(business_id, kind, hash, verdict) VALUES ($1, 'email', $2, 'not_a_guest')`,
  [b1, h('y')], /inbound_senders_verdict/);

// The shared list: one row a hash; an upsert refreshes it.
const share = (hash, source, churches) => db.query(
  `INSERT INTO inbound_shared_list(kind, hash, source, churches, last_tap_at, expires_at)
   VALUES ('email', $1, $2, $3, now(), now() + interval '90 days')
   ON CONFLICT (kind, hash) DO UPDATE SET source = excluded.source, churches = excluded.churches,
     last_tap_at = excluded.last_tap_at, expires_at = excluded.expires_at`, [hash, source, churches]);
await share(h('a'), 'churches', 2);
await share(h('a'), 'platform', 2);
assert.deepEqual(await one(`SELECT count(*)::int AS n, max(source) AS source FROM inbound_shared_list`),
  { n: 1, source: 'platform' }); checks++;
await refuses(`INSERT INTO inbound_shared_list(kind, hash, source, expires_at) VALUES ('email', $1, 'one church', now())`,
  [h('q')], /inbound_shared_source/);
await refuses(`INSERT INTO inbound_shared_list(kind, hash) VALUES ('email', $1)`, [h('r')], /null value|not-null/);

// The browser's roles can't touch any of it, with or without a login.
for (const role of ['authenticated', 'anon']) {
  await db.exec(`SET ROLE ${role};`);
  try {
    for (const name of TABLES) {
      await assert.rejects(db.query(`SELECT 1 FROM ${name}`), /permission denied/); checks++;
    }
  } finally { await db.exec('RESET ROLE;'); }
}

// A contact that goes: its checks stay (hashes for repeats) without it; its decisions go.
await db.query('DELETE FROM contacts WHERE id = $1', [sara]);
assert.equal((await one(`SELECT contact_id FROM inbound_checks WHERE id = $1`, [k1])).contact_id, null); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM inbound_decisions WHERE contact_id = $1`, [sara])).n, 0); checks++;
// A business that goes takes its own rows, and only its own.
await check(crypto.randomUUID(), crypto.randomUUID(), 'held', { biz: b2 });
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.deepEqual((await db.query(`SELECT DISTINCT business_id FROM inbound_checks`)).rows, [{ business_id: b2 }]); checks++;
assert.deepEqual((await db.query(`SELECT business_id FROM inbound_senders`)).rows, [{ business_id: b2 }]); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM inbound_shared_list`)).n, 1); checks++;   // no church's

console.log(`needs a look: ${checks} checks passed`);
