// The Giving keeper in the database, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-keys-gift-rows.sql over the 2026-09-29
// gift rule and the keys tables. With no keeper the owner, an admin and the
// outside accountant see the gifts. Once the church names a Giving keeper,
// only the keeper and someone holding an open key see a gift row, a giving
// event, a gift alert or the bank, the owner too; a key that ended, an ask
// not yet answered, a keeper not yet in or already out opens nothing. A
// locked person can't write a gift or relabel a bill as one. Bills, other
// events and other alerts stay; a business with no keeper, and a stranger's
// answer, never change; the rollback puts the 2026-09-29 rule back.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_keys_gift_rows_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const church = '11111111-1111-4111-8111-111111111111';
const shop = '22222222-2222-4222-8222-222222222222';
const u = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const [owner, treasurer, pastor, member, accountant, stranger, barber] = [1, 2, 3, 4, 5, 6, 7].map(u);
let checks = 0;

// What Supabase already has: the roles, auth.uid() from the JWT, the
// business tables with their own (permissive) owner-and-team policies.
await db.exec(`
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid, type text);
CREATE TABLE public.business_users(business_id uuid, user_id uuid, role text, status text);
CREATE TABLE public.business_collaborators(business_id uuid, user_id uuid, role text, status text);
CREATE TABLE public.invoices(id text PRIMARY KEY, business_id uuid, is_gift boolean NOT NULL DEFAULT false, total numeric);
CREATE TABLE public.events(id text PRIMARY KEY, business_id uuid, event_type text);
CREATE TABLE public.chief_notifications(id text PRIMARY KEY, business_id uuid, data jsonb);
CREATE TABLE public.plaid_transactions(id text PRIMARY KEY, business_id uuid);
CREATE TABLE public.plaid_accounts(id text PRIMARY KEY, business_id uuid);
CREATE FUNCTION public.belongs(b uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM businesses WHERE id = b AND owner_id = auth.uid())
      OR exists(SELECT 1 FROM business_users WHERE business_id = b AND user_id = auth.uid() AND status = 'active')
      OR exists(SELECT 1 FROM business_collaborators WHERE business_id = b AND user_id = auth.uid() AND status = 'active') $$;
`);
for (const t of ['invoices', 'events', 'chief_notifications', 'plaid_transactions', 'plaid_accounts']) {
  await db.exec(`ALTER TABLE public.${t} ENABLE ROW LEVEL SECURITY;
    CREATE POLICY team ON public.${t} FOR ALL TO authenticated USING (public.belongs(business_id)) WITH CHECK (public.belongs(business_id));
    GRANT SELECT, INSERT, UPDATE, DELETE ON public.${t} TO authenticated;`);
}
await db.exec('GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role');

// The 2026-09-29 rule, taken from its own file: the two functions, the gift
// policy, the relabel trigger, the giving events and alerts.
const readiness = await sql('APPLY-2026-09-29-ministry-readiness.sql');
const cut = (from, to) => {
  const a = readiness.indexOf(from), b = readiness.indexOf(to, a);
  assert.ok(a >= 0 && b > a, `the 2026-09-29 file still has ${from}`);
  return readiness.slice(a, b);
};
await db.exec(cut('create or replace function public.ministry_finance_access', '-- Restrictive policies'));
await db.exec(cut('-- Gifts stay private', '\ncreate table if not exists public.ministry_care_requests'));
await db.exec(cut('-- Keep financial notifications/events', '\n-- Every roster write'));
await db.exec(await sql('APPLY-2026-10-27-church-keys.sql'));

await db.query('INSERT INTO businesses VALUES ($1, $2, $3), ($4, $5, $6)', [church, owner, 'church', shop, barber, 'barber']);
for (const [who, role] of [[treasurer, 'admin'], [pastor, 'admin'], [member, 'member']]) {
  await db.query(`INSERT INTO business_users VALUES ($1, $2, $3, 'active')`, [church, who, role]);
}
await db.query(`INSERT INTO business_collaborators VALUES ($1, $2, 'accountant', 'active')`, [church, accountant]);
await db.exec(`
INSERT INTO invoices VALUES ('gift', '${church}', true, 50), ('bill', '${church}', false, 200), ('cut', '${shop}', false, 30);
INSERT INTO events VALUES ('given', '${church}', 'giving_received'), ('visit', '${church}', 'contact_created');
INSERT INTO chief_notifications VALUES ('gift alert', '${church}', '{"kind":"gift_received"}'),
  ('ended alert', '${church}', '{"kind":"recurring_gift_ended"}'), ('other alert', '${church}', '{"kind":"task_due"}');
INSERT INTO plaid_transactions VALUES ('deposit', '${church}'), ('shop deposit', '${shop}');
INSERT INTO plaid_accounts VALUES ('checking', '${church}'), ('shop checking', '${shop}');
`);

await db.exec(await sql('APPLY-2026-10-27-church-keys-gift-rows.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-keys-gift-rows.sql'));   // idempotent

async function as(uid, fn) {
  await db.exec('SET ROLE authenticated');
  await db.query(`SELECT set_config('request.jwt.claim.sub', $1, false)`, [uid]);
  try { return await fn(); } finally { await db.exec('RESET ROLE'); }
}
const ids = async (table, uid) => as(uid, async () =>
  (await db.query(`SELECT id FROM ${table} ORDER BY id`)).rows.map(r => r.id));
// Everything guarded at the church, as this person sees it.
const guarded = async uid => ({
  gifts: (await ids('invoices', uid)).includes('gift'),
  given: (await ids('events', uid)).includes('given'),
  alerts: (await ids('chief_notifications', uid)).filter(i => i !== 'other alert').length,
  bank: (await ids('plaid_transactions', uid)).includes('deposit') && (await ids('plaid_accounts', uid)).includes('checking'),
});
const OPEN = { gifts: true, given: true, alerts: 2, bank: true };
const SHUT = { gifts: false, given: false, alerts: 0, bank: false };
const service = async text => { await db.exec('SET ROLE service_role'); try { await db.exec(text); } finally { await db.exec('RESET ROLE'); } };

// No keeper, no lock: the 2026-09-29 rule (a member never saw gifts).
for (const who of [owner, treasurer, pastor, accountant]) {
  assert.deepEqual(await guarded(who), OPEN); checks++;
}
assert.equal((await guarded(member)).gifts, false); checks++;

// The church names its treasurer. Everyone else is locked, the owner too.
await service(`INSERT INTO church_keepers(business_id, area, user_id) VALUES ('${church}', 'giving_money', '${treasurer}')`);
assert.deepEqual(await guarded(treasurer), OPEN); checks++;
for (const who of [owner, pastor, accountant]) {
  assert.deepEqual(await guarded(who), SHUT); checks++;
  // The rest of the church's books, events and alerts are still theirs.
  assert.ok((await ids('invoices', who)).includes('bill')); checks++;
  assert.ok((await ids('events', who)).includes('visit')); checks++;
  assert.ok((await ids('chief_notifications', who)).includes('other alert')); checks++;
}
// A Kids keeper locks nothing here.
await service(`INSERT INTO church_keepers(business_id, area, user_id) VALUES ('${church}', 'kids_youth', '${pastor}')`);
assert.deepEqual(await guarded(pastor), SHUT); checks++;

// A key opens it until it ends; an ask, a no, or a key that ended doesn't.
const key = (who, status, until) => service(`INSERT INTO church_area_keys(business_id, area, user_id, status, opens_until)
  VALUES ('${church}', 'giving_money', '${who}', '${status}', ${until})`);
await key(pastor, 'asked', 'null');
await key(pastor, 'declined', 'null');
await key(pastor, 'open', `now() - interval '1 minute'`);
assert.deepEqual(await guarded(pastor), SHUT); checks++;
await service(`INSERT INTO church_area_keys(business_id, area, user_id, status, opens_until)
  VALUES ('${church}', 'kids_youth', '${pastor}', 'open', now() + interval '1 hour')`);
assert.deepEqual(await guarded(pastor), SHUT, 'a Kids key opens nothing in Giving'); checks++;
await key(pastor, 'open', `now() + interval '1 hour'`);
assert.deepEqual(await guarded(pastor), OPEN); checks++;
await key(accountant, 'open', `now() + interval '1 hour'`);
assert.deepEqual(await guarded(accountant), OPEN); checks++;
assert.deepEqual(await guarded(owner), SHUT, "someone else's key opens nothing for the owner"); checks++;
// A key never opens it to someone the 2026-09-29 rule keeps out.
await key(member, 'open', `now() + interval '1 hour'`);
assert.equal((await guarded(member)).gifts, false); checks++;

// A locked owner can't write a gift, change one, or relabel a bill as one.
const refuses = async (uid, text, message) => {
  await assert.rejects(as(uid, () => db.query(text)), e => { assert.match(e.message, message); return true; }); checks++;
};
await refuses(owner, `INSERT INTO invoices VALUES ('new gift', '${church}', true, 10)`, /row-level security/);
await refuses(owner, `UPDATE invoices SET is_gift = true WHERE id = 'bill'`, /finance access/);
assert.equal(await as(owner, async () => (await db.query(`UPDATE invoices SET total = 1 WHERE id = 'gift'`)).affectedRows), 0); checks++;
assert.equal(await as(owner, async () => (await db.query(`DELETE FROM invoices WHERE id = 'gift'`)).affectedRows), 0); checks++;
assert.equal((await db.query(`SELECT total::int AS total FROM invoices WHERE id = 'gift'`)).rows[0].total, 50); checks++;
// The keeper still can.
assert.equal(await as(treasurer, async () => (await db.query(`UPDATE invoices SET total = 55 WHERE id = 'gift'`)).affectedRows), 1); checks++;

// A keeper not yet in (a change waiting its 7 days), or already out, isn't one.
await service(`DELETE FROM church_keepers WHERE area = 'giving_money';
  INSERT INTO church_keepers(business_id, area, user_id, starts_at) VALUES ('${church}', 'giving_money', '${treasurer}', now() + interval '7 days');
  INSERT INTO church_keepers(business_id, area, user_id, starts_at, ends_at) VALUES ('${church}', 'giving_money', '${pastor}', now() - interval '9 days', now() - interval '1 day')`);
assert.deepEqual(await guarded(owner), OPEN, 'no active keeper, no lock'); checks++;
await service(`UPDATE church_keepers SET ends_at = now() + interval '7 days' WHERE user_id = '${pastor}' AND area = 'giving_money'`);
assert.deepEqual(await guarded(owner), SHUT, 'a keeper on the way out still keeps it'); checks++;
assert.deepEqual(await guarded(pastor), OPEN); checks++;

// A business with no keeper never changes; a stranger's answer is a
// constant and shows them nothing; the browser's anon role can't ask.
assert.deepEqual(await ids('invoices', barber), ['cut']); checks++;
assert.deepEqual(await ids('plaid_transactions', barber), ['shop deposit']); checks++;
const open = async (uid, fn = 'church_giving_open') => as(uid, async () =>
  (await db.query(`SELECT public.${fn}($1) AS v`, [church])).rows[0].v);
assert.equal(await open(stranger), true); checks++;
assert.equal(await open(owner), false); checks++;
assert.equal(await open(stranger, 'ministry_giving_access'), false); checks++;
assert.deepEqual(await guarded(stranger), { gifts: false, given: false, alerts: 0, bank: false }); checks++;
await db.exec('SET ROLE anon');
await assert.rejects(db.query(`SELECT public.church_giving_open('${church}')`), /permission denied/); checks++;
await db.exec('RESET ROLE');
// The server (service role) reads everything, as before.
await db.exec('SET ROLE service_role');
assert.equal((await db.query(`SELECT count(*)::int AS n FROM invoices WHERE is_gift`)).rows[0].n, 1); checks++;
await db.exec('RESET ROLE');

// The rollback: the 2026-09-29 rule again, keeper or not.
await db.exec(await sql('ROLLBACK-2026-10-27-church-keys-gift-rows.sql'));
await db.exec(await sql('ROLLBACK-2026-10-27-church-keys-gift-rows.sql'));   // idempotent
assert.deepEqual(await guarded(owner), OPEN); checks++;
assert.equal((await guarded(member)).gifts, false); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_proc WHERE proname IN ('church_giving_open', 'ministry_giving_access')`)).rows[0].n, 0); checks++;
await refuses(member, `UPDATE invoices SET is_gift = true WHERE id = 'bill'`, /finance access/);

console.log(`church keys on gift rows: ${checks} checks passed`);
