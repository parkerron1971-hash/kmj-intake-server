// Giving as its own tick, in the database, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-18-church-money-holders.sql over the 2026-09-29
// money wall, the 2026-07-31 team policies and the 2026-10-27 Giving keeper.
//
// 1. WITH NO HOLDER NOTHING CHANGES. For an owner, an Admin, the outside
//    accountant, a Manager, a Member, a Viewer, a stranger, and a shop's own
//    people, every select, insert, update and delete on every money table,
//    the gift row, the giving events and the gift alerts answers the same
//    before the file and after it (run twice).
// 2. WITH A HOLDER the right parts open and no others: a See tick reads the
//    books and writes nothing, even on a Manager seat that the team policy
//    lets write; who gave and the bank each take their own tick; Work writes;
//    a Viewer never writes. The seat ending ends it, and being invited again
//    does not bring it back.
// 3. Only the owner's word makes a holder (the two server functions), the
//    browser's roles can read or run none of it, the instant stop and the
//    rollback each put every answer back.
//
// Made-up church, made-up people.
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_money_holders_db.mjs
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
const [owner, admin, accountant, manager, member, viewer, stranger, barber, shopHand] = [1, 2, 3, 4, 5, 6, 7, 8, 9].map(u);
const PEOPLE = { owner, admin, accountant, manager, member, viewer, stranger, barber, shopHand };
// The nine tables ministry_financial_privacy stands on (2026-09-29), split
// as the 2026-07-31 team policies split them: a working seat writes the
// first five through the browser, and only reads the last four.
const TEAM_WRITES = ['invoices', 'bills', 'business_expenses', 'customer_ledger', 'plaid_transactions'];
const TEAM_READS = ['journal_entries', 'ledger_entries', 'plaid_accounts', 'chief_bookkeeping_proposals'];
const MONEY = [...TEAM_WRITES, ...TEAM_READS];
const BANK = ['plaid_transactions', 'plaid_accounts'];
let checks = 0;

// What Supabase already has: the roles, auth.uid() from the JWT, the
// business tables, and each money table with its own permissive policies
// (the owner's, tenant_member_read, tenant_writer_write, the accountant's).
await db.exec(`
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid, type text);
CREATE TABLE public.business_users(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL
  REFERENCES public.businesses(id) ON DELETE CASCADE, user_id uuid, role text, status text, joined_at timestamptz DEFAULT now());
CREATE TABLE public.business_collaborators(business_id uuid, user_id uuid, role text, status text);
CREATE TABLE public.events(id text PRIMARY KEY, business_id uuid, event_type text);
CREATE TABLE public.chief_notifications(id text PRIMARY KEY, business_id uuid, data jsonb);
CREATE FUNCTION public.is_business_owner(b uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM businesses WHERE id = b AND owner_id = auth.uid()) $$;
CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM business_users WHERE business_id = b AND user_id = auth.uid() AND status = 'active') $$;
CREATE FUNCTION public.is_business_collaborator(b uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM business_collaborators WHERE business_id = b AND user_id = auth.uid() AND status = 'active') $$;
`);
// is_business_writer and tenant_writer_write, as their own file writes them.
const seats = await sql('APPLY-2026-07-31-seat-access-data-plane.sql');
{
  const a = seats.indexOf('create or replace function public.is_business_writer'), b = seats.indexOf('\ndo $$', a);
  assert.ok(a >= 0 && b > a, 'the 2026-07-31 file still has is_business_writer');
  await db.exec(seats.slice(a, b));
  for (const t of TEAM_WRITES) assert.match(seats, new RegExp(`'${t}'`), `${t} is still a table the team writes`);
}
for (const t of MONEY) {
  await db.exec(`CREATE TABLE public.${t}(id text PRIMARY KEY, business_id uuid, note text${t === 'invoices'
    ? ', is_gift boolean NOT NULL DEFAULT false, total numeric' : ''})`);
}
for (const t of [...MONEY, 'events', 'chief_notifications']) {
  await db.exec(`ALTER TABLE public.${t} ENABLE ROW LEVEL SECURITY;
    CREATE POLICY owner_all ON public.${t} FOR ALL TO authenticated USING (public.is_business_owner(business_id)) WITH CHECK (public.is_business_owner(business_id));
    CREATE POLICY tenant_member_read ON public.${t} FOR SELECT TO authenticated USING (public.is_business_member(business_id));
    CREATE POLICY collaborator_read ON public.${t} FOR SELECT TO authenticated USING (public.is_business_collaborator(business_id));
    GRANT SELECT, INSERT, UPDATE, DELETE ON public.${t} TO authenticated;`);
}
for (const t of [...TEAM_WRITES, 'events', 'chief_notifications']) {
  await db.exec(`CREATE POLICY tenant_writer_write ON public.${t} FOR ALL TO authenticated
    USING (public.is_business_writer(business_id)) WITH CHECK (public.is_business_writer(business_id))`);
}
await db.exec('GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role');

// The wall as production has it: 2026-09-29 (its functions, its nine
// policies, the gift row, the relabel trigger, the events and alerts), the
// keys tables, then 2026-10-27 (the Giving keeper).
const readiness = await sql('APPLY-2026-09-29-ministry-readiness.sql');
const cut = (from, to) => {
  const a = readiness.indexOf(from), b = readiness.indexOf(to, a);
  assert.ok(a >= 0 && b > a, `the 2026-09-29 file still has ${from}`);
  return readiness.slice(a, b);
};
await db.exec(cut('create or replace function public.ministry_finance_access', '\ncreate table if not exists public.ministry_care_requests'));
await db.exec(cut('-- Keep financial notifications/events', '\n-- Every roster write'));
await db.exec(await sql('APPLY-2026-10-27-church-keys.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-keys-gift-rows.sql'));

await db.query('INSERT INTO businesses VALUES ($1, $2, $3), ($4, $5, $6)', [church, owner, 'church', shop, barber, 'barber']);
for (const [biz, who, role] of [[church, admin, 'admin'], [church, manager, 'manager'], [church, member, 'member'],
  [church, viewer, 'viewer'], [shop, shopHand, 'member']]) {
  await db.query(`INSERT INTO business_users(business_id, user_id, role, status) VALUES ($1, $2, $3, 'active')`, [biz, who, role]);
}
await db.query(`INSERT INTO business_collaborators VALUES ($1, $2, 'accountant', 'active')`, [church, accountant]);
for (const t of MONEY) {
  await db.exec(`INSERT INTO ${t}(id, business_id) VALUES ('${t}-church', '${church}'), ('${t}-shop', '${shop}')`);
}
await db.exec(`
INSERT INTO invoices(id, business_id, is_gift, total) VALUES ('gift', '${church}', true, 50);
INSERT INTO events VALUES ('given', '${church}', 'giving_received'), ('paid', '${church}', 'invoice_paid'), ('visit', '${church}', 'contact_created');
INSERT INTO chief_notifications VALUES ('gift alert', '${church}', '{"kind":"gift_received"}'),
  ('paid alert', '${church}', '{"kind":"invoice_paid"}'), ('other alert', '${church}', '{"kind":"task_due"}');
`);

// One question, asked as one person, inside a transaction that is always
// rolled back: nothing a probe writes stays.
async function ask(uid, text) {
  await db.exec('BEGIN');
  try {
    await db.exec('SET LOCAL ROLE authenticated');
    await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [uid]);
    const r = await db.query(text);
    return r.rows.length ? r.rows.map(x => x.id).sort() : (r.affectedRows ?? 0);
  } catch (e) {
    if (/row-level security|finance access|permission denied/.test(e.message)) return 'refused';
    throw e;
  } finally { await db.exec('ROLLBACK'); }
}
const sees = async (uid, table) => {
  const got = await ask(uid, `SELECT id FROM ${table} ORDER BY id`);
  return Array.isArray(got) ? got : [];
};
const writes = async (uid, table, biz) => ({
  insert: await ask(uid, `INSERT INTO ${table}(id, business_id) VALUES ('probe', '${biz === 'church' ? church : shop}')`),
  update: await ask(uid, `UPDATE ${table} SET note = 'probe' WHERE id = '${table}-${biz}'`),
  delete: await ask(uid, `DELETE FROM ${table} WHERE id = '${table}-${biz}'`),
});
// Everything one person can do with the money, as the database answers it.
async function everything(uid) {
  const out = {};
  for (const t of MONEY) {
    out[t] = { sees: await sees(uid, t), church: await writes(uid, t, 'church'), shop: await writes(uid, t, 'shop') };
  }
  out.gift = {
    insert: await ask(uid, `INSERT INTO invoices(id, business_id, is_gift) VALUES ('probe gift', '${church}', true)`),
    update: await ask(uid, `UPDATE invoices SET total = 1 WHERE id = 'gift'`),
    relabel: await ask(uid, `UPDATE invoices SET is_gift = true WHERE id = 'invoices-church'`),
    delete: await ask(uid, `DELETE FROM invoices WHERE id = 'gift'`),
  };
  out.events = await sees(uid, 'events');
  out.alerts = await sees(uid, 'chief_notifications');
  return out;
}
const everyone = async () => {
  const all = {};
  for (const [name, uid] of Object.entries(PEOPLE)) all[name] = await everything(uid);
  return all;
};
const service = async (text, params = []) => {
  await db.exec('SET ROLE service_role');
  try { return await db.query(text, params); } finally { await db.exec('RESET ROLE'); }
};
const serviceRefuses = async (text, message) => {
  await assert.rejects(service(text), e => { assert.match(e.message, message); return true; }); checks++;
};
const grant = (who, level, whoGave = false, bank = false, by = owner, biz = church) => service(
  `SELECT public.church_money_grant($1, $2, $3, $4, $5, $6) AS out`, [biz, who, level, whoGave, bank, by]);

// ─── 1. No holder: the file changes nobody's answer ───────────────────
const before = await everyone();
// The wall it starts from is the one we think it is.
assert.deepEqual(before.manager.bills.sees, [], 'a Manager reads no church money today'); checks++;
assert.ok(before.admin.bills.sees.includes('bills-church') && before.admin.invoices.sees.includes('gift')); checks++;
assert.equal(before.admin.bills.church.update, 1, 'an Admin seat writes a bill through the browser today'); checks++;
assert.equal(before.shopHand.bills.shop.update, 1, 'a shop is not walled'); checks++;
assert.ok(before.accountant.journal_entries.sees.includes('journal_entries-church')); checks++;

const apply = await sql('APPLY-2026-11-18-church-money-holders.sql');
await db.exec(apply);
assert.deepEqual(await everyone(), before, 'applied once, with no holder: every answer is the answer it was'); checks++;
await db.exec(apply);   // safe to run twice
assert.deepEqual(await everyone(), before, 'applied twice: the same'); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders`)).rows[0].n, 0); checks++;

// The two new guards stand in front of exactly the businesses the old one
// does, however the type is spelled: for someone with no standing, all three
// say the same thing about every kind of business.
{
  const spellings = ['Church', 'churches', 'Non-Profit', 'non profit', 'Faith Based', ' ministry ', 'NOT_FOR_PROFIT',
    'religious-org', 'barber', 'coach', 'churchy', 'nonprofits', '', null];
  let n = 500;
  for (const type of spellings) {
    const id = u(n++);
    await db.query('INSERT INTO businesses VALUES ($1, $2, $3)', [id, u(n++), type]);
    await db.exec('BEGIN');
    try {
      await db.exec('SET LOCAL ROLE authenticated');
      await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [stranger]);
      const r = (await db.query(`SELECT public.ministry_finance_guard($1) AS old, public.ministry_finance_write_guard($1) AS w,
        public.ministry_finance_bank_guard($1) AS b`, [id])).rows[0];
      assert.deepEqual([r.w, r.b], [r.old, r.old], `type ${JSON.stringify(type)}`); checks++;
    } finally { await db.exec('ROLLBACK'); }
  }
  // A business that is not there: no, from all three.
  await db.exec('BEGIN');
  try {
    await db.exec('SET LOCAL ROLE authenticated');
    await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [owner]);
    const r = (await db.query(`SELECT public.ministry_finance_guard($1) AS old, public.ministry_finance_write_guard($1) AS w,
      public.ministry_finance_bank_guard($1) AS b`, [u(999)])).rows[0];
    assert.deepEqual(r, { old: false, w: false, b: false }); checks++;
  } finally { await db.exec('ROLLBACK'); }
}

// What it added, and that it replaced no policy.
const policies = (await db.query(`SELECT policyname, cmd, permissive, count(*)::int AS n FROM pg_policies
  WHERE schemaname = 'public' AND (policyname LIKE 'ministry_financial_%' OR policyname IN
    ('church_money_bank', 'church_giving_bank', 'gift_row_privacy')) GROUP BY 1, 2, 3 ORDER BY 1`)).rows;
assert.deepEqual(policies.map(p => `${p.policyname} ${p.cmd} ${p.permissive} ${p.n}`), [
  'church_giving_bank ALL RESTRICTIVE 2', 'church_money_bank ALL RESTRICTIVE 2', 'gift_row_privacy ALL RESTRICTIVE 1',
  'ministry_financial_events SELECT RESTRICTIVE 1', 'ministry_financial_notifications SELECT RESTRICTIVE 1',
  'ministry_financial_privacy ALL RESTRICTIVE 9', 'ministry_financial_write_delete DELETE RESTRICTIVE 9',
  'ministry_financial_write_insert INSERT RESTRICTIVE 9', 'ministry_financial_write_update UPDATE RESTRICTIVE 9']); checks++;
for (const t of ['church_money_holders', 'church_money_asks']) {
  const r = (await db.query(`SELECT c.relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS n,
    has_table_privilege('authenticated', c.oid, 'select') AS a, has_table_privilege('anon', c.oid, 'select') AS b
    FROM pg_class c WHERE c.oid = 'public.${t}'::regclass`)).rows[0];
  assert.deepEqual(r, { rls: true, n: 0, a: false, b: false }, `${t} is the server's alone`); checks++;
}

// ─── 2. Holders ───────────────────────────────────────────────────────
// A See tick on a Viewer: the books, read only. Not who gave, not the bank.
await grant(viewer, 'see');
let v = await everything(viewer);
for (const t of MONEY.filter(x => !BANK.includes(x))) {
  assert.ok(v[t].sees.includes(`${t}-church`), `a See holder reads ${t}`); checks++;
  assert.ok(!v[t].sees.includes(`${t}-shop`), 'and never another business'); checks++;
}
for (const t of BANK) { assert.deepEqual(v[t].sees, [], `not the bank (${t}) without its tick`); checks++; }
assert.ok(!v.invoices.sees.includes('gift'), 'not who gave without its tick'); checks++;
assert.deepEqual(v.events, ['paid', 'visit']); checks++;
assert.deepEqual(v.alerts, ['other alert', 'paid alert']); checks++;
for (const t of MONEY) {
  assert.deepEqual(v[t].church, before.viewer[t].church, `a Viewer writes nothing in ${t}, tick or not`); checks++;
}
assert.deepEqual(v.gift, before.viewer.gift); checks++;
// Nobody else moved.
for (const name of ['owner', 'admin', 'accountant', 'manager', 'member', 'stranger', 'barber', 'shopHand']) {
  assert.deepEqual(await everything(PEOPLE[name]), before[name], `${name} is as they were`); checks++;
}

// A See tick with the bank on a Manager seat. The team policy lets a Manager
// write these tables; the tick opened reading, and the write guard keeps
// the writing shut. This is the hole the write policies exist for.
await grant(manager, 'see', false, true);
let m = await everything(manager);
for (const t of MONEY) { assert.ok(m[t].sees.includes(`${t}-church`), `See + bank reads ${t}`); checks++; }
for (const t of MONEY) {
  assert.deepEqual(m[t].church, { insert: 'refused', update: 0, delete: 0 }, `a See holder cannot write ${t}`); checks++;
}
assert.ok(!m.invoices.sees.includes('gift')); checks++;
// Without the three write policies that same Manager would have written.
await db.exec('BEGIN');
for (const c of ['insert', 'update', 'delete']) await db.exec(`DROP POLICY ministry_financial_write_${c} ON public.bills`);
await db.exec('SAVEPOINT s; SET LOCAL ROLE authenticated');
await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [manager]);
assert.equal((await db.query(`UPDATE bills SET note = 'x' WHERE id = 'bills-church'`)).affectedRows, 1,
  'the widened read guard alone would have let a See holder write'); checks++;
await db.exec('ROLLBACK');

// Work with who gave on a Member seat: writes the books and the gift rows,
// still not the bank.
await grant(member, 'work', true, false);
let w = await everything(member);
assert.ok(w.invoices.sees.includes('gift')); checks++;
assert.deepEqual(w.events, ['given', 'paid', 'visit']); checks++;
assert.deepEqual(w.alerts, ['gift alert', 'other alert', 'paid alert']); checks++;
for (const t of TEAM_WRITES.filter(x => !BANK.includes(x))) {
  assert.deepEqual(w[t].church, { insert: 1, update: 1, delete: 1 }, `a Work holder writes ${t}`); checks++;
  assert.deepEqual(w[t].shop, before.member[t].shop, 'and nothing of another business'); checks++;
}
for (const t of TEAM_READS.filter(x => !BANK.includes(x))) {
  assert.deepEqual(w[t].church, before.member[t].church, `${t} was never the team's to write`); checks++;
}
assert.deepEqual(w.gift, { insert: 1, update: 1, relabel: 1, delete: 1 }); checks++;
for (const t of BANK) {
  assert.deepEqual(w[t].sees, [], 'Work is not the bank'); checks++;
  assert.deepEqual(w[t].church, { insert: 'refused', update: 0, delete: 0 }); checks++;
}
// Lead writes as Work does; Work without who gave cannot touch a gift row.
await grant(member, 'lead', false, true);
w = await everything(member);
assert.equal(w.bills.church.update, 1); checks++;
assert.equal(w.plaid_transactions.church.update, 1, 'Lead + bank writes the bank feed'); checks++;
assert.deepEqual(w.gift, { insert: 'refused', update: 0, relabel: 'refused', delete: 0 }, 'no who gave, no gift rows'); checks++;
await grant(member, 'work', true, false);

// The Giving keeper still locks who gave, for a holder as for the owner.
await service(`INSERT INTO church_keepers(business_id, area, user_id) VALUES ('${church}', 'giving_money', '${admin}')`);
w = await everything(member);
assert.ok(!w.invoices.sees.includes('gift') && w.bills.sees.includes('bills-church'), 'the keeper locks the gifts, not the books'); checks++;
assert.deepEqual(w.gift, { insert: 'refused', update: 0, relabel: 'refused', delete: 0 }); checks++;
await service(`DELETE FROM church_keepers`);

// Moved down to a Viewer: still reads, no longer writes.
await service(`UPDATE business_users SET role = 'viewer' WHERE business_id = '${church}' AND user_id = '${member}'`);
w = await everything(member);
assert.ok(w.bills.sees.includes('bills-church')); checks++;
assert.deepEqual(w.bills.church, { insert: 'refused', update: 0, delete: 0 }, 'a Viewer seat never writes, whatever the tick says'); checks++;
// And that is the tick's own answer, not only the team policy's: the write
// guard itself says no to a Work row on a Viewer seat.
const guard = async (uid, fn) => {
  await db.exec('BEGIN');
  try {
    await db.exec('SET LOCAL ROLE authenticated');
    await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [uid]);
    return (await db.query(`SELECT public.${fn}($1) AS v`, [church])).rows[0].v;
  } finally { await db.exec('ROLLBACK'); }
};
assert.equal(await guard(member, 'ministry_finance_write_guard'), false); checks++;
assert.equal(await guard(member, 'ministry_finance_access'), true); checks++;
assert.equal(await guard(member, 'ministry_giving_access'), true); checks++;
assert.equal(await guard(member, 'ministry_finance_bank_guard'), false); checks++;
await service(`UPDATE business_users SET role = 'member' WHERE business_id = '${church}' AND user_id = '${member}'`);
assert.equal(await guard(member, 'ministry_finance_write_guard'), true); checks++;
assert.equal(await guard(owner, 'ministry_finance_write_guard'), true); checks++;
assert.equal(await guard(stranger, 'ministry_finance_write_guard'), false); checks++;
assert.equal(await guard(viewer, 'ministry_finance_access'), true, 'the Viewer holds See'); checks++;
assert.equal(await guard(viewer, 'ministry_finance_write_guard'), false); checks++;

// The seat ends: everything shuts at once. Invited again (a new seat row):
// the old tick does not come back with them.
await service(`UPDATE business_users SET status = 'revoked' WHERE business_id = '${church}' AND user_id = '${member}'`);
assert.deepEqual(await everything(member), before.stranger, 'a revoked seat holds nothing'); checks++;
await service(`INSERT INTO business_users(business_id, user_id, role, status) VALUES ('${church}', '${member}', 'member', 'active')`);
assert.deepEqual(await everything(member), before.member, 'invited again: the old tick is not theirs'); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders WHERE user_id = '${member}'`)).rows[0].n, 1); checks++;
// The owner says yes again, and it rides the new seat.
await grant(member, 'work', true, false);
assert.equal((await everything(member)).bills.church.update, 1); checks++;
// A seat row that is deleted takes its tick with it.
await service(`DELETE FROM business_users WHERE business_id = '${church}' AND user_id = '${member}' AND status = 'active'`);
assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders WHERE user_id = '${member}'`)).rows[0].n, 0); checks++;
await service(`UPDATE business_users SET status = 'active' WHERE business_id = '${church}' AND user_id = '${member}'`);
assert.deepEqual(await everything(member), before.member); checks++;

// ─── 3. Only the owner's word ─────────────────────────────────────────
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, '${admin}')`, /only the owner/);
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, null)`, /only the owner/);
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, '${barber}')`, /only the owner/);
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${viewer}', 'work', false, false, '${owner}')`, /Viewer login can only see/);
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${stranger}', 'see', false, false, '${owner}')`, /no active login/);
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${owner}', 'see', false, false, '${owner}')`, /holds giving already/);
await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'all', false, false, '${owner}')`, /see, work or lead/);
await serviceRefuses(`SELECT public.church_money_grant('${shop}', '${shopHand}', 'see', false, false, '${barber}')`, /not a church or nonprofit/);
await serviceRefuses(`SELECT public.church_money_grant('${u(99)}', '${member}', 'see', false, false, '${owner}')`, /only the owner/);
await serviceRefuses(`INSERT INTO church_money_holders(business_id, user_id, seat_id, level, granted_by)
  SELECT '${church}', user_id, id, 'everything', '${owner}' FROM business_users WHERE user_id = '${admin}'`, /church_money_holders_level/);
// A null level takes the tick away.
const gone = (await grant(viewer, null)).rows[0].out;
assert.deepEqual(gone, { ok: true, holder: null }); checks++;
assert.deepEqual(await everything(viewer), before.viewer); checks++;

// An ask: one open a login, never for yourself, answered by the owner alone.
const askFor = async (who, by, wants, extra = '') => (await service(
  `INSERT INTO church_money_asks(business_id, user_id, asked_by, wants${extra ? ', expires_at' : ''})
   VALUES ($1, $2, $3, $4${extra}) RETURNING id`, [church, who, by, JSON.stringify(wants)])).rows[0].id;
const first = await askFor(member, admin, { level: 'work', who_gave: true });
await serviceRefuses(`INSERT INTO church_money_asks(business_id, user_id, asked_by, wants)
  VALUES ('${church}', '${member}', '${manager}', '{"level":"see"}')`, /church_money_asks_one_open/);
await serviceRefuses(`INSERT INTO church_money_asks(business_id, user_id, asked_by, wants)
  VALUES ('${church}', '${admin}', '${admin}', '{"level":"see"}')`, /church_money_asks_not_for_self/);
for (const bad of ['{"level":"owner"}', '{}', '[]', '{"level":"see","bank":"yes"}']) {
  await serviceRefuses(`INSERT INTO church_money_asks(business_id, user_id, asked_by, wants)
    VALUES ('${church}', '${viewer}', '${admin}', '${bad}')`, /church_money_asks_wants/);
}
assert.deepEqual(await everything(member), before.member, 'an ask opens nothing'); checks++;
await serviceRefuses(`SELECT public.church_money_answer('${first}', true, '${admin}')`, /only the owner answers/);
await serviceRefuses(`SELECT public.church_money_answer('${first}', true, '${member}')`, /only the owner answers/);
await serviceRefuses(`SELECT public.church_money_answer('${u(98)}', true, '${owner}')`, /no such ask/);
const yes = (await service(`SELECT public.church_money_answer($1, true, $2) AS out`, [first, owner])).rows[0].out;
assert.equal(yes.status, 'approved'); checks++;
assert.equal(yes.holder.ask_id, first); checks++;
assert.deepEqual([yes.holder.level, yes.holder.who_gave, yes.holder.bank, yes.holder.granted_by], ['work', true, false, owner]); checks++;
assert.equal((await everything(member)).gift.update, 1); checks++;
await serviceRefuses(`SELECT public.church_money_answer('${first}', true, '${owner}')`, /already approved/);
const row = (await db.query(`SELECT status, answered_by FROM church_money_asks WHERE id = $1`, [first])).rows[0];
assert.deepEqual(row, { status: 'approved', answered_by: owner }); checks++;
// A no, an ask that ran out, and a yes the grant itself refuses.
const second = await askFor(viewer, admin, { level: 'see', bank: true });
assert.equal((await service(`SELECT public.church_money_answer($1, false, $2) AS out`, [second, owner])).rows[0].out.status, 'declined'); checks++;
assert.deepEqual(await everything(viewer), before.viewer, 'a no opens nothing'); checks++;
const late = await askFor(viewer, admin, { level: 'see' }, `, now() - interval '1 minute'`);
await serviceRefuses(`SELECT public.church_money_answer('${late}', true, '${owner}')`, /ran out/);
await service(`UPDATE church_money_asks SET status = 'expired' WHERE id = $1`, [late]);
const tooMuch = await askFor(viewer, admin, { level: 'work' });
await serviceRefuses(`SELECT public.church_money_answer('${tooMuch}', true, '${owner}')`, /Viewer login can only see/);
assert.equal((await db.query(`SELECT status FROM church_money_asks WHERE id = $1`, [tooMuch])).rows[0].status, 'asked',
  'a yes that could not be given leaves the ask open'); checks++;
await service(`UPDATE church_money_asks SET status = 'withdrawn' WHERE id = $1`, [tooMuch]);

// The browser's roles read none of it and run none of it.
const denied = async (role, uid, text) => {
  await db.exec('BEGIN');
  try {
    await db.exec(`SET LOCAL ROLE ${role}`);
    await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [uid]);
    await assert.rejects(db.query(text), /permission denied/); checks++;
  } finally { await db.exec('ROLLBACK'); }
};
for (const role of ['authenticated', 'anon']) {
  await denied(role, member, `SELECT * FROM church_money_holders`);
  await denied(role, member, `SELECT * FROM church_money_asks`);
  await denied(role, member, `INSERT INTO church_money_holders(business_id, user_id, seat_id, granted_by)
    SELECT '${church}', '${member}', id, '${member}' FROM business_users LIMIT 1`);
  await denied(role, member, `SELECT public.church_money_grant('${church}', '${member}', 'lead', true, true, '${owner}')`);
  await denied(role, member, `SELECT public.church_money_answer('${first}', true, '${owner}')`);
  await denied(role, member, `SELECT public.church_money_tick('${church}', 'any')`);
  await denied(role, member, `SELECT public.ministry_finance_base('${church}')`);
  await denied(role, member, `SELECT public.ministry_finance_walled('${church}')`);
}
await denied('anon', member, `SELECT public.ministry_finance_write_guard('${church}')`);
await denied('anon', member, `SELECT public.ministry_finance_bank_guard('${church}')`);
// A tick is the caller's own: someone else's opens nothing for a stranger.
assert.deepEqual(await everything(stranger), before.stranger); checks++;
assert.deepEqual(await everything(manager), m, 'the Manager still holds See + bank, and only that'); checks++;

// Every function the policies read is SECURITY DEFINER with a fixed
// search_path; the two the server calls are not, and carry one too.
const fns = (await db.query(`SELECT p.proname, p.prosecdef AS definer, p.proconfig AS config FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname IN
  ('ministry_finance_base', 'ministry_finance_walled', 'church_money_tick', 'ministry_finance_access',
   'ministry_giving_access', 'ministry_finance_write_guard', 'ministry_finance_bank_guard',
   'church_money_grant', 'church_money_answer') ORDER BY 1`)).rows;
assert.equal(fns.length, 9); checks++;
for (const f of fns) {
  assert.deepEqual(f.config, ['search_path=public'], f.proname); checks++;
  assert.equal(f.definer, !['church_money_grant', 'church_money_answer'].includes(f.proname), f.proname); checks++;
}

// ─── The instant stop, the rollback, and applying again ───────────────
const held = (await db.query(`SELECT business_id, user_id, seat_id, level, who_gave, bank, granted_by, ask_id FROM church_money_holders ORDER BY user_id`)).rows;
assert.equal(held.length, 2, 'the Manager and the Member hold a tick going into the stop'); checks++;
await db.exec('DELETE FROM church_money_holders');
assert.deepEqual(await everyone(), before, 'the instant stop: no rows, every answer back'); checks++;
for (const h of held) {
  await db.query(`INSERT INTO church_money_holders(business_id, user_id, seat_id, level, who_gave, bank, granted_by, ask_id)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`, [h.business_id, h.user_id, h.seat_id, h.level, h.who_gave, h.bank, h.granted_by, h.ask_id]);
}
assert.equal((await everything(member)).bills.church.update, 1, 'the ticks are back'); checks++;

const rollback = await sql('ROLLBACK-2026-11-18-church-money-holders.sql');
await db.exec(rollback);
await db.exec(rollback);   // safe to run twice
assert.deepEqual(await everyone(), before, 'rolled back with holders still in the table: every answer back'); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders`)).rows[0].n, 2, 'the rollback keeps the rows'); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_proc WHERE proname IN ('ministry_finance_base', 'ministry_finance_walled',
  'church_money_tick', 'ministry_finance_write_guard', 'ministry_finance_bank_guard', 'church_money_grant', 'church_money_answer')`)).rows[0].n, 0); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_policies WHERE policyname LIKE 'ministry_financial_write_%'
  OR policyname = 'church_money_bank'`)).rows[0].n, 0); checks++;
// The two restored bodies are the files' own.
const body = async name => (await db.query(`SELECT prosrc FROM pg_proc WHERE proname = $1`, [name])).rows[0].prosrc.replace(/\s+/g, ' ').trim();
const fileBody = (text, name) => {
  const a = text.indexOf(`create or replace function public.${name}(`), b = text.indexOf('as $$', a), c = text.indexOf('$$;', b + 5);
  assert.ok(a >= 0 && b > a && c > b, `${name} is still in its file`);
  return text.slice(b + 5, c).replace(/\s+/g, ' ').trim();
};
assert.equal(await body('ministry_finance_access'), fileBody(readiness, 'ministry_finance_access')); checks++;
assert.equal(await body('ministry_giving_access'), fileBody(await sql('APPLY-2026-10-27-church-keys-gift-rows.sql'), 'ministry_giving_access')); checks++;

await db.exec(apply);
assert.equal((await everything(member)).bills.church.update, 1, 'applied again: the kept ticks count again'); checks++;
assert.deepEqual(await everything(manager), m); checks++;
// And its base is the 2026-09-29 body, word for word.
assert.equal(await body('ministry_finance_base'), fileBody(readiness, 'ministry_finance_access')); checks++;

// The server (service role) reads everything, as before.
assert.equal((await service(`SELECT count(*)::int AS n FROM invoices WHERE is_gift`)).rows[0].n, 1); checks++;

console.log(`church money holders: ${checks} checks passed`);
