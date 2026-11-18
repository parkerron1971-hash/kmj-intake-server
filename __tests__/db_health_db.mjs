// The weekly database health check's tables and db_health_pg()
// (supabase/APPLY-2026-11-18-db-health.sql), in PGlite:
//   - safe twice; both tables server-only (RLS on, no policies, the
//     browser's roles refused), the function service role only;
//   - a slot is claimed once (unique), the kinds and shapes are checked;
//   - db_health_pg answers without pg_stat_statements (a plain note, never
//     an error), and with it lists only normalized DML, literals masked,
//     cut to 160 characters, the biggest writers first.
// Run with: node __tests__/db_health_db.mjs
// (PGLITE_MODULE points at an @electric-sql/pglite install, as in CI.)
const { PGlite } = await import(process.env.PGLITE_MODULE || '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const db = new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;`);
const sql = await readFile(new URL('../supabase/APPLY-2026-11-18-db-health.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);

const one = async (q, args = []) => (await db.query(q, args)).rows[0];

// Server-only.
for (const t of ['db_health_samples', 'db_health_weeks']) {
  assert.equal((await one(`SELECT relrowsecurity r FROM pg_class WHERE oid = 'public.${t}'::regclass`)).r, true, t);
  assert.equal((await one(`SELECT count(*)::int n FROM pg_policies WHERE tablename = $1`, [t])).n, 0, t);
  for (const role of ['anon', 'authenticated']) {
    assert.equal((await one(`SELECT has_table_privilege($1, 'public.${t}', 'select') p`, [role])).p, false, `${role} ${t}`);
  }
}
for (const role of ['anon', 'authenticated']) {
  assert.equal((await one(`SELECT has_function_privilege($1, 'public.db_health_pg(integer)', 'execute') p`, [role])).p, false, role);
  await db.exec(`SET ROLE ${role}`);
  await assert.rejects(db.query('SELECT public.db_health_pg(5)'), role);
  await assert.rejects(db.query('SELECT * FROM public.db_health_samples'), role);
  await db.exec('RESET ROLE');
}
assert.equal((await one(`SELECT has_function_privilege('service_role', 'public.db_health_pg(integer)', 'execute') p`)).p, true);

// A slot is claimed once; kinds and shapes are checked.
await db.query(`INSERT INTO db_health_samples(slot, kind) VALUES ('2026-11-22T13:00:00Z', 'sunday')`);
const again = await db.query(`INSERT INTO db_health_samples(slot, kind) VALUES ('2026-11-22T13:00:00Z', 'sunday')
  ON CONFLICT (slot) DO NOTHING RETURNING id`);
assert.equal(again.rows.length, 0);
await assert.rejects(db.query(`INSERT INTO db_health_samples(slot, kind) VALUES (now(), 'monday')`));
await assert.rejects(db.query(`INSERT INTO db_health_samples(slot, kind, metrics) VALUES (now(), 'manual', '[1]')`));
await assert.rejects(db.query(`INSERT INTO db_health_weeks(week, size, level, headline) VALUES ('2026-11-22', 'huge', 'fine', 'x')`));
await assert.rejects(db.query(`INSERT INTO db_health_weeks(week, size, level, headline) VALUES ('2026-11-22', 'small', 'bad', 'x')`));
await db.query(`INSERT INTO db_health_weeks(week, size, level, headline) VALUES ('2026-11-22', 'small', 'fine', 'Fine at Small')`);
const told1 = await db.query(`UPDATE db_health_weeks SET told_at = now() WHERE week = '2026-11-22' AND told_at IS NULL RETURNING week`);
const told2 = await db.query(`UPDATE db_health_weeks SET told_at = now() WHERE week = '2026-11-22' AND told_at IS NULL RETURNING week`);
assert.equal(told1.rows.length, 1);
assert.equal(told2.rows.length, 0);

// Without pg_stat_statements: the counts and a note, never an error.
await db.exec('SET ROLE service_role');
const bare = (await one('SELECT public.db_health_pg(5) j')).j;
await db.exec('RESET ROLE');
assert.equal(typeof bare.max_connections, 'number');
assert.equal(typeof bare.connections, 'number');
assert.ok(Number(bare.db_bytes) > 0);
assert.match(bare.top_problem, /aren't readable/);
assert.equal(bare.top_wal, undefined);
const noTops = (await one('SELECT public.db_health_pg(0) j')).j;
assert.equal(noTops.top_problem, undefined);

// With it (a stand-in with the columns the function reads).
await db.exec(`CREATE SCHEMA extensions;
CREATE TABLE extensions.pg_stat_statements(dbid oid, query text, calls bigint, wal_bytes numeric, temp_blks_written bigint);
CREATE TABLE extensions.pg_stat_statements_info(stats_reset timestamptz);
INSERT INTO extensions.pg_stat_statements_info VALUES ('2026-11-01T00:00:00Z');`);
const dbid = (await one('SELECT oid FROM pg_database WHERE datname = current_database()')).oid;
const rows = [
  [`insert into public.sol_news_items (id, title) values ($1, $2)`, 900, 5000000, 0],
  [`UPDATE public.contacts SET note = 'secret text' WHERE id = $1`, 40, 3000000, 0],
  [`ALTER ROLE someone PASSWORD 'hunter2'`, 1, 9999999999, 0],
  [`select * from public.big_report order by x`, 12, 0, 800],
  [`  WITH t AS (SELECT 1)\n   SELECT   *\n FROM t ${'x'.repeat(300)}`, 3, 100, 10],
  [`delete from public.other`, 2, 10, 0],
];
for (const [q, calls, wal, temp] of rows) {
  await db.query('INSERT INTO extensions.pg_stat_statements VALUES ($1, $2, $3, $4, $5)', [dbid, q, calls, wal, temp]);
}
await db.query('INSERT INTO extensions.pg_stat_statements VALUES (0, $1, 1, 99999999999, 99999)', ['insert into elsewhere values ($1)']);
await db.exec('SET ROLE service_role');
const full = (await one('SELECT public.db_health_pg(3) j')).j;
await db.exec('RESET ROLE');
assert.equal(full.top_problem, undefined);
assert.equal(full.top_wal.length, 3);
assert.deepEqual(full.top_wal.map(t => Number(t.calls)), [900, 40, 3]);
assert.match(full.top_wal[0].query, /^insert into public\.sol_news_items/);
assert.equal(Number(full.top_wal[0].wal_bytes), 5000000);
assert.equal(full.top_wal[1].query, "UPDATE public.contacts SET note = '…' WHERE id = $1");
for (const t of full.top_wal) {
  assert.doesNotMatch(t.query, /hunter2|secret text|ALTER ROLE|elsewhere/);
  assert.ok(t.query.length <= 160);
}
assert.equal(full.top_wal[2].query.slice(0, 32), 'WITH t AS (SELECT 1) SELECT * FR');
assert.equal(full.top_temp.length, 2);
assert.match(full.top_temp[0].query, /big_report/);
assert.equal(Number(full.top_temp[0].temp_bytes), 800 * 8192);
assert.equal(new Date(full.since).toISOString(), '2026-11-01T00:00:00.000Z');
// p_top is held to 0..10.
const capped = (await one('SELECT public.db_health_pg(500) j')).j;
assert.ok(capped.top_wal.length <= 10);
const negative = (await one('SELECT public.db_health_pg(-3) j')).j;
assert.equal(negative.top_wal, undefined);

console.log('db_health_db: ok');
