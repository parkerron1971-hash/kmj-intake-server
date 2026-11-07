// Ten a day, held by the database, on a real Postgres (PGlite): supabase/APPLY-2026-11-06-church-map-asks-cap.sql
// over APPLY-2026-11-05-church-map-asks.sql and as much of Supabase as it needs. The eleventh fix or gap one
// login sends inside 24 hours is refused with the trigger's own SQLSTATE (PT429) and message; a confirmed check,
// another login, another church and an ask older than a day aren't counted; the file's closing check runs as
// written; a second run changes nothing; the rollback takes it out and the table is as it was.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_map_asks_cap_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const asksFile = await readFile(new URL('../supabase/APPLY-2026-11-05-church-map-asks.sql', import.meta.url), 'utf8');
const file = await readFile(new URL('../supabase/APPLY-2026-11-06-church-map-asks-cap.sql', import.meta.url), 'utf8');
const db = new PGlite();
let checks = 0;
const q = async (text, args) => (await db.query(text, args)).rows;
const ok = (got, want, why) => { assert.deepEqual(got, want, why); checks++; };
const B = '00000000-0000-4000-8000-00000000000b', B2 = '00000000-0000-4000-8000-0000000000b2';
const U = '00000000-0000-4000-8000-00000000000a', U2 = '00000000-0000-4000-8000-0000000000a2';

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.church_map_changes(id uuid PRIMARY KEY, business_id uuid NOT NULL);
  INSERT INTO auth.users VALUES ('${U}'), ('${U2}'); INSERT INTO public.businesses VALUES ('${B}'), ('${B2}');`);
await db.exec(asksFile);

const table = async () => JSON.stringify(await q(`select column_name, data_type, is_nullable, column_default
  from information_schema.columns where table_name = 'church_map_asks' order by ordinal_position`)) +
  JSON.stringify(await q(`select conname, pg_get_constraintdef(oid) as def from pg_constraint
    where conrelid = 'public.church_map_asks'::regclass order by 1`)) +
  JSON.stringify(await q(`select indexname, indexdef from pg_indexes where tablename = 'church_map_asks' order by 1`)) +
  JSON.stringify(await q(`select c.relrowsecurity, (select count(*)::int from pg_policies p where p.tablename = c.relname)
    as policies from pg_class c where c.relname = 'church_map_asks'`));
const before = await table();
const triggers = () => q(`select t.tgname, t.tgenabled, p.proname, p.prosecdef, p.provolatile, p.proconfig,
    has_function_privilege('authenticated', p.oid, 'execute') as browser_runs
  from pg_trigger t join pg_proc p on p.oid = t.tgfoid
 where t.tgrelid = 'public.church_map_asks'::regclass and not t.tgisinternal`);

await db.exec(file);
const first = JSON.stringify(await triggers()) + await table();
await db.exec(file);
ok(JSON.stringify(await triggers()) + await table(), first, 'a second run changes nothing');
ok(await table(), before, 'no column, check, index or policy on the table changed');
ok(await triggers(), [{ tgname: 'church_map_asks_cap', tgenabled: 'O', proname: 'church_map_asks_cap', prosecdef: false,
                       provolatile: 'v', proconfig: ['search_path=""'], browser_runs: false }],
   "the file's closing check: one trigger, security invoker, an empty search_path, no browser runs it");

// The trigger runs as whoever inserts: the server's service role, as in production.
await db.exec('SET ROLE service_role');
const put = (biz, who, kind, said, at = 'now()') => q(
  `insert into public.church_map_asks(business_id, asked_by, kind, said, asked_at${kind === 'confirmed' ? ', status, resolved_at' : ''})
   values ('${biz}', '${who}', '${kind}', '${said}', ${at}${kind === 'confirmed' ? `, 'done', now()` : ''}) returning id`);
const refused = async (biz, who, kind, said, why) => {
  await assert.rejects(put(biz, who, kind, said), e => {
    assert.equal(e.code, 'PT429', why);
    assert.match(e.message, /^church_map_asks_cap: /, why);
    return true;
  });
  checks++;
};

await put(B, U, 'gap', 'A day old', `now() - interval '25 hours'`);      // outside the day: not counted
for (let n = 0; n < 9; n++) await put(B, U, n % 2 ? 'fix' : 'gap', `Ask ${n}`);
await put(B, U, 'confirmed', '');                                         // a check isn't counted
await put(B, U, 'fix', 'The tenth');
ok((await q(`select count(*)::int as n from public.church_map_asks where asked_by = '${U}' and kind in ('fix', 'gap')
             and asked_at >= now() - interval '24 hours'`))[0].n, 10, 'ten in the day, the old one aside');
await refused(B, U, 'fix', 'The eleventh', 'an eleventh fix is the cap');
await refused(B, U, 'gap', 'Another', 'and so is a gap');
await put(B, U, 'confirmed', '');
await put(B, U2, 'gap', 'Another login');
await put(B2, U, 'gap', 'Another church');
ok((await q(`select count(*)::int as n from public.church_map_asks where said in ('The eleventh', 'Another')`))[0].n, 0,
   'nothing past the cap was saved');
ok((await q(`select count(*)::int as n from public.church_map_asks`))[0].n, 15, 'every other ask went in');
await db.exec('RESET ROLE');

await db.exec(`begin; drop trigger if exists church_map_asks_cap on public.church_map_asks;
  drop function if exists public.church_map_asks_cap(); commit;`);
ok(await triggers(), [], 'the rollback takes the trigger out');
ok((await q(`select to_regprocedure('public.church_map_asks_cap()') as f`))[0].f, null, 'and its function');
ok(await table(), before, 'and the table is as it was');
await db.query(`insert into public.church_map_asks(business_id, asked_by, kind, said) values ('${B}', '${U}', 'fix', 'x')`);
checks++;
console.log(`church_map_asks_cap_db: ${checks} checks passed`);
