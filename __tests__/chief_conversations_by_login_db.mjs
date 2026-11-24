// Chief's saved conversations, one login's apart from another's, on a real
// Postgres (PGlite): supabase/APPLY-2026-11-24-chief-conversations-by-login.sql.
//
// Before the file: one rule, the business's owner only (APPLY-2026-09-08), and
// no login on a row. After it: who asked is kept; the owner reads and writes the
// owner's own rows and the ones with no login; any other login reads its own
// while it is on the team (a seat, or an accountant); nobody reads another
// login's; nobody but the owner writes as themselves (the server writes every
// turn). Running the file twice changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/chief_conversations_by_login_db.mjs
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
const jessica = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';   // a Manager seat at b1
const tiara = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';     // another seat at b1
const books = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';     // b1's outside accountant
const other = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';     // owns b2
const gone = 'ffffffff-ffff-4fff-8fff-ffffffffffff';      // was on b1's team

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ select nullif(current_setting('app.uid', true), '')::uuid $$;
  GRANT USAGE ON SCHEMA auth TO authenticated;
  GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid NOT NULL);
  CREATE TABLE public.business_users(business_id uuid, user_id uuid, role text, status text);
  CREATE TABLE public.business_collaborators(business_id uuid, user_id uuid, role text, status text);
  -- The helpers as __migrations__/2026_06_10_hotfix_rls_recursion.sql makes them.
  CREATE FUNCTION public.is_business_member(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = public AS $$ select exists (select 1 from public.business_users
      where business_id = b_id and user_id = auth.uid() and status = 'active') $$;
  CREATE FUNCTION public.is_business_collaborator(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = public AS $$ select exists (select 1 from public.business_collaborators
      where business_id = b_id and user_id = auth.uid() and status = 'active') $$;
  GRANT EXECUTE ON FUNCTION public.is_business_member(uuid), public.is_business_collaborator(uuid) TO authenticated;
  -- The table as it is today: no login, the one owner-only rule (APPLY-2026-09-08-conversation-desk.sql).
  CREATE TABLE public.chief_conversations(
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL REFERENCES public.businesses(id),
    messages jsonb, summary text, ended_at timestamptz DEFAULT now(), metadata jsonb NOT NULL DEFAULT '{}'::jsonb);
  ALTER TABLE public.chief_conversations ENABLE ROW LEVEL SECURITY;
  CREATE POLICY chief_conversations_business_owner ON public.chief_conversations
    FOR ALL TO authenticated
    USING (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()))
    WITH CHECK (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.chief_conversations TO authenticated;
  GRANT SELECT ON public.businesses TO authenticated;
  GRANT ALL ON public.chief_conversations TO service_role;`);
await db.query('INSERT INTO businesses(id, owner_id) VALUES ($1, $2), ($3, $4)', [b1, owner, b2, other]);
await db.query(`INSERT INTO business_users(business_id, user_id, role, status) VALUES
  ($1, $2, 'manager', 'active'), ($1, $3, 'manager', 'active'), ($1, $4, 'member', 'removed')`, [b1, jessica, tiara, gone]);
await db.query(`INSERT INTO business_collaborators(business_id, user_id, role, status) VALUES ($1, $2, 'accountant', 'active')`,
  [b1, books]);

let checks = 0;
const as = async (who, fn) => {
  await db.exec(`SET app.uid = '${who}'; SET ROLE authenticated;`);
  try { return await fn(); } finally { await db.exec(`RESET ROLE; SET app.uid = '';`); }
};
const sees = (who) => as(who, async () => (await db.query(
  'SELECT summary FROM chief_conversations ORDER BY summary')).rows.map(r => r.summary));
const refused = async (who, text, args) => {
  await as(who, () => assert.rejects(db.query(text, args), /row-level security|permission denied/)); checks++;
};
const touched = (who, text, args) => as(who, async () => (await db.query(text, args)).affectedRows ?? 0);

// ── Before the file: the owner alone, and a seat's save is refused (why nothing of the team's was kept).
await as(owner, () => db.query(`INSERT INTO chief_conversations(business_id, summary) VALUES ($1, 'owner, before')`, [b1]));
await refused(jessica, `INSERT INTO chief_conversations(business_id, summary) VALUES ($1, 'jessica, before')`, [b1]);
assert.deepEqual(await sees(jessica), []); checks++;

const file = await readFile(new URL('../supabase/APPLY-2026-11-24-chief-conversations-by-login.sql', import.meta.url), 'utf8');
await db.exec(file);
await db.exec(file);                                       // safe to run twice

const col = (await db.query(`SELECT data_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='chief_conversations' AND column_name='user_id'`)).rows;
assert.deepEqual(col, [{ data_type: 'uuid' }]); checks++;
const policies = (await db.query(`SELECT policyname, cmd FROM pg_policies
  WHERE schemaname='public' AND tablename='chief_conversations' ORDER BY 1`)).rows;
assert.deepEqual(policies, [{ policyname: 'chief_conversations_business_owner', cmd: 'ALL' },
                            { policyname: 'chief_conversations_own_read', cmd: 'SELECT' }]); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_indexes
  WHERE tablename='chief_conversations' AND indexname='chief_conversations_business_user'`)).rows[0].n, 1); checks++;
// What was there keeps no login: it is the owner's.
assert.equal((await db.query(`SELECT count(*)::int AS n FROM chief_conversations WHERE user_id IS NOT NULL`)).rows[0].n, 0); checks++;

// ── The server writes every turn, with the login it verified.
const save = (biz, who, summary) => db.query(
  `INSERT INTO chief_conversations(business_id, user_id, summary) VALUES ($1, $2, $3)`, [biz, who, summary]);
await save(b1, owner, 'owner, by the server');
await save(b1, jessica, 'jessica 1');
await save(b1, jessica, 'jessica 2');
await save(b1, tiara, 'tiara 1');
await save(b1, books, 'books 1');
await save(b1, gone, 'gone 1');
await save(b2, other, 'other church');

// ── Who reads what.
assert.deepEqual(await sees(owner), ['owner, before', 'owner, by the server']); checks++;   // never the team's, unnamed
assert.deepEqual(await sees(jessica), ['jessica 1', 'jessica 2']); checks++;
assert.deepEqual(await sees(tiara), ['tiara 1']); checks++;
assert.deepEqual(await sees(books), ['books 1']); checks++;                                 // the accountant, its own
assert.deepEqual(await sees(gone), []); checks++;                                           // off the team: nothing
assert.deepEqual(await sees(other), ['other church']); checks++;                            // another church's owner
assert.deepEqual(await as('99999999-9999-4999-8999-999999999999', async () =>
  (await db.query('SELECT 1 FROM chief_conversations')).rows), []); checks++;               // a stranger

// ── Who writes what as themselves: the owner, the owner's own; nobody else, anything.
await refused(jessica, `INSERT INTO chief_conversations(business_id, user_id, summary) VALUES ($1, $2, 'mine')`, [b1, jessica]);
await refused(jessica, `INSERT INTO chief_conversations(business_id, summary) VALUES ($1, 'no login')`, [b1]);
assert.equal(await touched(jessica, `UPDATE chief_conversations SET summary = 'changed' WHERE summary = 'jessica 1'`), 0); checks++;
assert.equal(await touched(jessica, `DELETE FROM chief_conversations WHERE summary = 'jessica 1'`), 0); checks++;
assert.equal(await touched(jessica, `UPDATE chief_conversations SET summary = 'x' WHERE summary = 'owner, before'`), 0); checks++;
// The owner's own app saves with no login (its four-hour sweep) and over a row the server wrote for the owner.
await as(owner, () => db.query(`INSERT INTO chief_conversations(business_id, summary) VALUES ($1, 'owner, by the app')`, [b1]));
assert.equal(await touched(owner, `UPDATE chief_conversations SET metadata = '{"t":1}' WHERE summary = 'owner, by the server'`), 1); checks++;
// The owner can't put another login's name on a row, take one over, or change or remove the team's.
await refused(owner, `INSERT INTO chief_conversations(business_id, user_id, summary) VALUES ($1, $2, 'as jessica')`, [b1, jessica]);
await refused(owner, `UPDATE chief_conversations SET user_id = $1 WHERE summary = 'owner, before'`, [jessica]);
assert.equal(await touched(owner, `UPDATE chief_conversations SET summary = 'x' WHERE summary = 'jessica 1'`), 0); checks++;
assert.equal(await touched(owner, `DELETE FROM chief_conversations WHERE summary = 'tiara 1'`), 0); checks++;
// Another church's owner reaches nothing here.
await refused(other, `INSERT INTO chief_conversations(business_id, summary) VALUES ($1, 'reach')`, [b1]);

// ── Nothing was lost or changed by any of the refused tries.
assert.deepEqual((await db.query('SELECT summary FROM chief_conversations ORDER BY summary')).rows.map(r => r.summary),
  ['books 1', 'gone 1', 'jessica 1', 'jessica 2', 'other church', 'owner, before', 'owner, by the app',
   'owner, by the server', 'tiara 1']); checks++;

console.log(`chief conversations by login: ${checks} checks passed`);
