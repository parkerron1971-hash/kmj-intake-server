// What's New in the database, on a real Postgres (PGlite): supabase/APPLY-2026-11-27-whats-new.sql.
//
// Three server-only tables (RLS on, no policies, the browser's roles can't read or
// write them); the rows platform_updates.py writes are the rows the checks take;
// a login sees an update once (the upsert keeps the first); an update that goes
// takes its seen rows and leaves its news drafts without it; a business that goes
// takes its seen rows; running the file twice changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/whats_new_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

const file = await readFile(new URL('../supabase/APPLY-2026-11-27-whats-new.sql', import.meta.url), 'utf8');
await db.exec(file);
await db.exec(file);   // safe to run twice

for (const name of ['platform_updates', 'platform_update_seen', 'platform_news_drafts']) {
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

// The row platform_updates.create writes, and one imported from the old ledger.
await db.query(`INSERT INTO platform_updates(id, date, status, source, area, page, kinds, areas, roles, weight,
    group_key, title, line, body, church_line, tour)
  VALUES ('2026-11-27-chief-on-your-phone', '2026-11-27', 'published', 'ledger', 'Chief', null, '{}', '{}', '{}', 'big',
    'chief-phone', 'Chief on your phone', 'Between sessions, ask Chief.', 'Long words.', 'Between visits, ask Chief.',
    '[{"text":"Ask looks things up."}]'::jsonb)`);
await db.query(`INSERT INTO platform_updates(id, date, title, page, kinds, roles)
  VALUES ('2026-11-26-quarterly', '2026-11-26', 'Pay every three months', 'build:settings', '{}', '{owner}')`);
const d = await one(`SELECT status, source, weight, line, tour FROM platform_updates WHERE id = '2026-11-26-quarterly'`);
assert.deepEqual(d, { status: 'draft', source: 'editor', weight: 'normal', line: '', tour: [] }); checks++;

await refuses(`INSERT INTO platform_updates(id, date, title) VALUES ('Not An Id', '2026-11-27', 'x')`, [], /id_shape/);
await refuses(`INSERT INTO platform_updates(id, date, title, status) VALUES ('2026-11-27-a', '2026-11-27', 'x', 'live')`, [], /status/);
await refuses(`INSERT INTO platform_updates(id, date, title, weight) VALUES ('2026-11-27-b', '2026-11-27', 'x', 'huge')`, [], /weight/);
await refuses(`INSERT INTO platform_updates(id, date, title, page) VALUES ('2026-11-27-c', '2026-11-27', 'x', 'Members page')`, [], /page_shape/);
await refuses(`INSERT INTO platform_updates(id, date, title) VALUES ('2026-11-27-d', '2026-11-27', '')`, [], /title_len/);
await refuses(`INSERT INTO platform_updates(id, date, title, line) VALUES ('2026-11-27-e', '2026-11-27', 'x', repeat('a', 301))`, [], /line_len/);
await refuses(`INSERT INTO platform_updates(id, date, title, tour) VALUES ('2026-11-27-f', '2026-11-27', 'x', '{}'::jsonb)`, [], /tour_list/);
await refuses(`INSERT INTO platform_updates(id, date, title, source) VALUES ('2026-11-27-g', '2026-11-27', 'x', 'nightly')`, [], /source/);
await refuses(`INSERT INTO platform_updates(id, date, title, source_repo) VALUES ('2026-11-27-h', '2026-11-27', 'x', 'other')`, [], /repo/);

// Seen: the upsert platform_updates.mark_seen sends keeps the first.
const seen = `INSERT INTO platform_update_seen(user_id, business_id, update_id, how) VALUES ($1, $2, $3, $4)
  ON CONFLICT (user_id, business_id, update_id) DO NOTHING`;
await db.query(seen, [u1, b1, '2026-11-27-chief-on-your-phone', 'card']);
await db.query(seen, [u1, b1, '2026-11-27-chief-on-your-phone', 'list']);
const s = await one(`SELECT count(*)::int AS n, min(how) AS how FROM platform_update_seen`);
assert.deepEqual(s, { n: 1, how: 'card' }); checks++;
await refuses(seen, [u1, b1, '2026-11-26-quarterly', 'shouted'], /how/);
await refuses(seen, [u1, b1, '2026-01-01-missing', 'card'], /foreign key/);

// News drafts: one a PR at most; an update that goes leaves the draft.
const news = `INSERT INTO platform_news_drafts(update_id, headline, audience, source_repo, source_pr) VALUES ($1, $2, $3, $4, $5)`;
await db.query(news, ['2026-11-27-chief-on-your-phone', 'Chief on your phone', 'all', 'solutionist-studio', 1713]);
await refuses(news, [null, 'Again', 'all', 'solutionist-studio', 1713], /duplicate key/);
await refuses(news, [null, 'x', 'martians', null, null], /audience/);
await refuses(news, [null, '', 'all', null, null], /headline_len/);

await db.query(`DELETE FROM platform_updates WHERE id = '2026-11-27-chief-on-your-phone'`);
const after = await one(`SELECT (SELECT count(*)::int FROM platform_update_seen) AS seen,
  (SELECT update_id FROM platform_news_drafts LIMIT 1) AS news_update`);
assert.deepEqual(after, { seen: 0, news_update: null }); checks++;

await db.query(seen, [u1, b1, '2026-11-26-quarterly', 'list']);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM platform_update_seen')).n, 0); checks++;

console.log(`whats_new_db: ${checks} checks passed`);
