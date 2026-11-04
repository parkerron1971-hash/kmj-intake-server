// "Is this right?"'s data, on a real Postgres (PGlite): supabase/APPLY-2026-11-05-church-map-asks.sql over
// as much of Supabase and step 2 as it needs (auth.users, businesses, church_map_changes). The file makes the
// table, its checks, its indexes and its locks; a second run changes nothing; each kind of ask goes in and
// wrong ones are refused; deleting a change lets go of the link; the browser's roles can't read or write it;
// the file's closing check runs as written; and the rollback takes it out.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_map_asks_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const file = await readFile(new URL('../supabase/APPLY-2026-11-05-church-map-asks.sql', import.meta.url), 'utf8');
const db = new PGlite();
let checks = 0;
const q = async (text, args) => (await db.query(text, args)).rows;
const ok = (got, want, why) => { assert.deepEqual(got, want, why); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const B = '00000000-0000-4000-8000-00000000000b', U = '00000000-0000-4000-8000-00000000000a';
const C = '00000000-0000-4000-8000-00000000000c';

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.church_map_changes(id uuid PRIMARY KEY, business_id uuid NOT NULL);
  INSERT INTO auth.users VALUES ('${U}'); INSERT INTO public.businesses VALUES ('${B}');
  INSERT INTO public.church_map_changes VALUES ('${C}', '${B}');`);

const shape = async () => JSON.stringify(await q(`select column_name, data_type, is_nullable, column_default
  from information_schema.columns where table_name = 'church_map_asks' order by ordinal_position`)) +
  JSON.stringify(await q(`select conname, pg_get_constraintdef(oid) as def from pg_constraint
    where conrelid = 'public.church_map_asks'::regclass order by 1`)) +
  JSON.stringify(await q(`select indexname, indexdef from pg_indexes where tablename = 'church_map_asks' order by 1`));
await db.exec(file);
const first = await shape();
await db.exec(file);
ok(await shape(), first, 'a second run changes nothing');

const put = (cols, vals) => q(`insert into church_map_asks(business_id, ${cols}) values ('${B}', ${vals}) returning *`);
const [fix] = await put('kind, said, asked_by, change_id, duty_move',
                        `'fix', 'Kids check-in is Laquesha''s now', '${U}', '${C}', '{"duty": "kids"}'`);
ok([fix.status, fix.told_at, fix.resolved_at], ['open', null, null], 'a fix waits, untold');
await put('kind, said', `'gap', 'Who handles weddings?'`);
await put('kind, work, status, resolved_at', `'confirmed', '{"duties": []}', 'done', now()`);
await refuses(`insert into church_map_asks(business_id, kind, said) values ('${B}', 'fix', '  ')`, [], /church_map_asks_words/);
await refuses(`insert into church_map_asks(business_id, kind, said, change_id) values ('${B}', 'gap', 'x', '${C}')`, [],
              /church_map_asks_parts/);
await refuses(`insert into church_map_asks(business_id, kind) values ('${B}', 'confirmed')`, [], /church_map_asks_checked/);
await refuses(`update church_map_asks set status = 'applied' where id = '${fix.id}'`, [], /church_map_asks_resolved/);
await refuses(`insert into church_map_asks(business_id, kind, said) values ('${B}', 'fix', repeat('a', 401))`, [],
              /check/);
await refuses(`insert into church_map_asks(business_id, kind, said) values ('${B}', 'wish', 'x')`, [], /check/);
await refuses(`insert into church_map_asks(business_id, kind, said, duty_move) values ('${B}', 'fix', 'x', '[1]')`, [],
              /check/);
await db.exec(`delete from church_map_changes where id = '${C}'`);
ok((await q(`select change_id from church_map_asks where id = '${fix.id}'`))[0].change_id, null,
   'a change taken out lets go of the link, never the ask');

ok((await q(`select c.relrowsecurity as rls, (select count(*)::int from pg_policies p where p.tablename = c.relname) as policies,
    has_table_privilege('authenticated', c.oid, 'select') as browser_reads, has_table_privilege('anon', c.oid, 'insert') as anon_writes
    from pg_class c where c.relname = 'church_map_asks'`))[0],
   { rls: true, policies: 0, browser_reads: false, anon_writes: false }, 'server-only');
ok((await q(`select count(*)::int as n from information_schema.columns where table_schema = 'public'
    and table_name = 'church_map_asks'`))[0].n, 13, "the file's closing check: 13 columns");
ok((await q(`select indexname from pg_indexes where tablename = 'church_map_asks' order by 1`)).map(r => r.indexname),
   ['church_map_asks_change', 'church_map_asks_mine', 'church_map_asks_open', 'church_map_asks_pkey'], 'its indexes');

await db.exec(`begin; drop table if exists public.church_map_asks; commit;`);
ok((await q(`select to_regclass('public.church_map_asks') as t`))[0].t, null, 'the rollback takes it out');
console.log(`church_map_asks_db: ${checks} checks passed`);
