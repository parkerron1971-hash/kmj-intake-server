// Giving as its own tick, in the database, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-18-church-money-holders.sql over the 2026-09-29
// money wall, the 2026-07-31 team policies and the 2026-10-27 Giving keeper.
//
// 1. WITH NO HOLDER, EXACTLY ONE THING CHANGES. For an owner, an Admin, the
//    outside accountant, a Manager, a Member, a Viewer, a stranger, a shop's
//    own people, the signed-out role and a login with no id: every select,
//    insert, update, delete, upsert, RETURNING, FOR UPDATE and move on every
//    money table, the gift row, the events and the alerts answers the same
//    before the file and after it (run twice), EXCEPT an unfiltered write on
//    events or chief_notifications, which no longer reaches the money rows
//    the login cannot see. The list of differences is held to that, by name.
// 2. WITH A HOLDER the right parts open and no others: a See tick reads the
//    books and writes nothing (not a bill, not a money event, not a money
//    alert), even on a Manager seat that the team policy lets write; who
//    gave and the bank each take their own tick; Work writes; a Viewer never
//    writes. The seat ending ends it, and being invited again does not bring
//    it back.
// 3. Only the owner's word makes a holder (the server functions), the
//    browser's roles can read or run none of it, the instant stop and the
//    rollback each put the reading answers back.
// 4. AN OLDER FILE RUN AGAIN ONLY NARROWS: after the 2026-09-29 block, the
//    2026-10-27 file or its rollback, every holder has less or the same,
//    never more, and this file and its rollback still run.
// 5. The same on tables owned by a role that is not a superuser, with and
//    without BYPASSRLS, with Supabase's default privileges and RLS on the
//    three business tables.
//
// The fixture mirrors what production's catalog said on 2026-11-18: the
// permissive policies on bills and business_expenses by name (the allow-all
// TO public on business_expenses included, on purpose), tenant_member_read
// and tenant_writer_write where production has them, and the fourteen
// restrictive policies as the repo's own files make them. The third and
// fourth permissive policies on the two bank tables are a guess (a read for
// the accountant).
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
const church = '11111111-1111-4111-8111-111111111111';
const shop = '22222222-2222-4222-8222-222222222222';
const u = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const [owner, admin, accountant, manager, member, viewer, stranger, barber, shopHand] = [1, 2, 3, 4, 5, 6, 7, 8, 9].map(u);
// name -> [user id, role]. `anon` is the signed-out role; `nobody` is the
// signed-in role with no id in its token.
const PEOPLE = {
  owner: [owner], admin: [admin], accountant: [accountant], manager: [manager], member: [member], viewer: [viewer],
  stranger: [stranger], barber: [barber], shopHand: [shopHand], anon: ['', 'anon'], nobody: [''],
};
// The nine tables ministry_financial_privacy stands on (2026-09-29), split
// as the 2026-07-31 team policies split them: a working seat writes the
// first five through the browser, and only reads the last four.
const TEAM_WRITES = ['invoices', 'bills', 'business_expenses', 'customer_ledger', 'plaid_transactions'];
const TEAM_READS = ['journal_entries', 'ledger_entries', 'plaid_accounts', 'chief_bookkeeping_proposals'];
const MONEY = [...TEAM_WRITES, ...TEAM_READS];
const BANK = ['plaid_transactions', 'plaid_accounts'];
const BESIDE = ['events', 'chief_notifications'];
const NEW_FUNCTIONS = ['ministry_finance_walled', 'church_money_tick', 'ministry_finance_write_guard',
  'ministry_finance_bank_guard', 'church_money_giving_write', 'church_money_grant', 'church_money_answer',
  'church_money_ask'];
const APPLY = await sql('APPLY-2026-11-18-church-money-holders.sql');
const ROLLBACK = await sql('ROLLBACK-2026-11-18-church-money-holders.sql');
const READINESS = await sql('APPLY-2026-09-29-ministry-readiness.sql');
const GIFT_ROWS = await sql('APPLY-2026-10-27-church-keys-gift-rows.sql');
const GIFT_ROWS_BACK = await sql('ROLLBACK-2026-10-27-church-keys-gift-rows.sql');
const cut = (text, from, to) => {
  const a = text.indexOf(from), b = text.indexOf(to, a);
  assert.ok(a >= 0 && b > a, `the file still has ${from}`);
  return text.slice(a, b);
};
// The 2026-09-29 wall as that file writes it: its two functions, its nine
// policies, the gift row and the relabel trigger; then the events and alerts.
const READINESS_BLOCK = cut(READINESS, 'create or replace function public.ministry_finance_access',
  '\ncreate table if not exists public.ministry_care_requests')
  + cut(READINESS, '-- Keep financial notifications/events', '\n-- Every roster write');
let checks = 0;

// What Supabase already has. `ownedBy`: null (everything is the
// superuser's), or a role that is NOT a superuser, with or without
// BYPASSRLS, that owns every table and function and runs the files.
async function build({ ownedBy = null } = {}) {
  const db = new PGlite();
  await db.exec(`
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
-- Supabase's default privileges: every new table and function in public is
-- handed to all three roles unless a file takes it back.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid, type text);
CREATE TABLE public.business_users(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL
  REFERENCES public.businesses(id) ON DELETE CASCADE, user_id uuid, role text, status text, joined_at timestamptz DEFAULT now());
CREATE TABLE public.business_collaborators(business_id uuid, user_id uuid, role text, status text);
CREATE TABLE public.events(id text PRIMARY KEY, business_id uuid, event_type text, note text);
CREATE TABLE public.chief_notifications(id text PRIMARY KEY, business_id uuid, data jsonb, note text, status text DEFAULT 'unread');
-- The test's own: run one statement as the caller and say whether the
-- database refused it (a policy, a missing privilege, the gift trigger).
CREATE FUNCTION public.zz_try(q text) RETURNS text LANGUAGE plpgsql AS $$
begin
  execute q;
  return 'ok';
exception
  when insufficient_privilege then return 'refused';
  when raise_exception then
    if sqlerrm ~ 'finance access' then return 'refused'; end if;
    return 'error: ' || sqlerrm;
  when others then return 'error: ' || sqlstate || ' ' || sqlerrm;
end $$;
CREATE FUNCTION public.is_business_owner(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM businesses WHERE id = b_id AND owner_id = auth.uid()) $$;
CREATE FUNCTION public.is_business_member(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM business_users WHERE business_id = b_id AND user_id = auth.uid() AND status = 'active') $$;
CREATE FUNCTION public.is_business_admin(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM business_users WHERE business_id = b_id AND user_id = auth.uid() AND status = 'active' AND role = 'admin') $$;
CREATE FUNCTION public.is_business_collaborator(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT exists(SELECT 1 FROM business_collaborators WHERE business_id = b_id AND user_id = auth.uid() AND status = 'active') $$;
-- The three business tables under RLS, with the June hotfix's policies
-- (__migrations__/2026_06_10_hotfix_rls_recursion.sql): a policy function
-- here that read them as the caller would recurse or see nothing.
ALTER TABLE public.businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_collaborators ENABLE ROW LEVEL SECURITY;
CREATE POLICY businesses_owner ON public.businesses FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
CREATE POLICY businesses_member_read ON public.businesses FOR SELECT USING (public.is_business_member(businesses.id));
CREATE POLICY businesses_admin_update ON public.businesses FOR UPDATE USING (public.is_business_admin(businesses.id)) WITH CHECK (public.is_business_admin(businesses.id));
CREATE POLICY businesses_accountant_read ON public.businesses FOR SELECT USING (public.is_business_collaborator(businesses.id));
CREATE POLICY business_users_owner_all ON public.business_users FOR ALL USING (public.is_business_owner(business_users.business_id)) WITH CHECK (public.is_business_owner(business_users.business_id));
CREATE POLICY business_users_self_read ON public.business_users FOR SELECT USING (user_id = auth.uid());
CREATE POLICY collaborators_owner_read ON public.business_collaborators FOR SELECT USING (public.is_business_owner(business_collaborators.business_id));
CREATE POLICY collaborators_self_read ON public.business_collaborators FOR SELECT USING (user_id = auth.uid());
`);
  // is_business_writer, as its own file writes it.
  const seats = await sql('APPLY-2026-07-31-seat-access-data-plane.sql');
  await db.exec(cut(seats, 'create or replace function public.is_business_writer', '\ndo $$'));
  for (const t of TEAM_WRITES) assert.match(seats, new RegExp(`'${t}'`), `${t} is still a table the team writes`);
  for (const t of MONEY) {
    await db.exec(`CREATE TABLE public.${t}(id text PRIMARY KEY, business_id uuid, note text${t === 'invoices'
      ? ', is_gift boolean NOT NULL DEFAULT false, total numeric' : ''})`);
  }
  const mine = `business_id IN (SELECT businesses.id FROM businesses WHERE businesses.owner_id = auth.uid())`;
  for (const t of [...MONEY, ...BESIDE]) {
    await db.exec(`ALTER TABLE public.${t} ENABLE ROW LEVEL SECURITY;
      CREATE POLICY tenant_member_read ON public.${t} FOR SELECT TO authenticated USING (public.is_business_member(business_id));`);
    if (t === 'bills') {
      // Production's four, TO public, one owner-scoped qual each.
      await db.exec(`CREATE POLICY bills_owner_select ON public.bills FOR SELECT USING (${mine});
        CREATE POLICY bills_owner_insert ON public.bills FOR INSERT WITH CHECK (${mine});
        CREATE POLICY bills_owner_update ON public.bills FOR UPDATE USING (${mine}) WITH CHECK (${mine});
        CREATE POLICY bills_owner_delete ON public.bills FOR DELETE USING (${mine});`);
    } else if (t === 'business_expenses') {
      // Production's allow-all TO public (a separate change drops it), and
      // the owner's.
      await db.exec(`CREATE POLICY business_expenses_all ON public.business_expenses FOR ALL USING (true) WITH CHECK (true);
        CREATE POLICY business_member_access ON public.business_expenses FOR ALL TO authenticated USING (${mine}) WITH CHECK (${mine});`);
    } else {
      await db.exec(`CREATE POLICY business_member_access ON public.${t} FOR ALL TO authenticated USING (${mine}) WITH CHECK (${mine});`);
    }
  }
  for (const t of [...TEAM_WRITES, ...BESIDE]) {
    await db.exec(`CREATE POLICY tenant_writer_write ON public.${t} FOR ALL TO authenticated
      USING (public.is_business_writer(business_id)) WITH CHECK (public.is_business_writer(business_id))`);
  }
  for (const t of BANK) {
    await db.exec(`CREATE POLICY collaborator_read ON public.${t} FOR SELECT TO authenticated USING (public.is_business_collaborator(business_id))`);
  }
  // The wall as production has it: 2026-09-29, the keys tables, 2026-10-27.
  await db.exec(READINESS_BLOCK);
  await db.exec(await sql('APPLY-2026-10-27-church-keys.sql'));
  await db.exec(GIFT_ROWS);

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
INSERT INTO events(id, business_id, event_type) VALUES ('given', '${church}', 'giving_received'), ('paid', '${church}', 'invoice_paid'),
  ('visit', '${church}', 'contact_created'), ('shop given', '${shop}', 'giving_received'), ('shop paid', '${shop}', 'payment_received'),
  ('shop visit', '${shop}', 'contact_created');
INSERT INTO chief_notifications(id, business_id, data) VALUES ('gift alert', '${church}', '{"kind":"gift_received"}'),
  ('paid alert', '${church}', '{"kind":"invoice_paid"}'), ('other alert', '${church}', '{"kind":"task_due"}'),
  ('shop gift alert', '${shop}', '{"kind":"recurring_gift_ended"}'), ('shop paid alert', '${shop}', '{"kind":"invoice_paid"}'),
  ('shop other alert', '${shop}', '{"kind":"task_due"}');
`);

  if (ownedBy) {
    await db.exec(`CREATE ROLE pgowner NOSUPERUSER ${ownedBy === 'bypass' ? 'BYPASSRLS' : 'NOBYPASSRLS'} CREATEROLE;
      GRANT ALL ON SCHEMA public TO pgowner; GRANT USAGE ON SCHEMA auth TO pgowner;
      GRANT anon, authenticated, service_role TO pgowner WITH ADMIN OPTION;
      ALTER DEFAULT PRIVILEGES FOR ROLE pgowner IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
      ALTER DEFAULT PRIVILEGES FOR ROLE pgowner IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;`);
    for (const r of (await db.query(`SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND relkind = 'r'`)).rows) await db.exec(`ALTER TABLE public.${r.relname} OWNER TO pgowner`);
    for (const r of (await db.query(`SELECT p.oid::regprocedure::text AS f FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public'`)).rows) await db.exec(`ALTER FUNCTION ${r.f} OWNER TO pgowner`);
  }
  // A file, run as whoever owns the tables.
  const run = async text => {
    if (ownedBy) await db.exec('SET ROLE pgowner');
    try { await db.exec(text); } catch (e) { await db.exec('ROLLBACK').catch(() => {}); throw e; } finally { await db.exec('RESET ROLE'); }
  };

  const SNAP = table => `SELECT coalesce(jsonb_object_agg(t.id, to_jsonb(t)), '{}'::jsonb) AS rows FROM ${table} t`;
  const rowsOf = result => Object.fromEntries(Object.entries(result.rows[0].rows).map(([k, v]) => [k, JSON.stringify(v)]));
  // One statement, as one person, inside a transaction that is always rolled
  // back. The answer is what it did to `table`, read back as the superuser:
  // '+id' a new row, '-id' a deleted one, '~id' a changed one; [] nothing;
  // 'refused' when the database said no. A select answers the ids it saw.
  // (uid and role are this file's own constants, never input.)
  async function ask(who, text, table = null) {
    const [uid, role = 'authenticated'] = Array.isArray(who) ? who : [who];
    const as = `SET LOCAL ROLE ${role}; SELECT set_config('request.jwt.claim.sub', '${uid}', true)`;
    try {
      if (!table) {
        await db.exec(`BEGIN; ${as}`);
        return (await db.query(text)).rows.map(x => x.id).sort();
      }
      const was = rowsOf((await db.exec(`BEGIN; ${SNAP(table)}; ${as}`))[1]);
      // A write goes through zz_try, which catches the database's "no"
      // inside Postgres. (PGlite loses a little stack on every error that
      // reaches the top, and this file asks for thousands of refusals.)
      const said = (await db.query(`SELECT public.zz_try($1) AS said`, [text])).rows[0].said;
      if (said === 'refused') return 'refused';
      assert.equal(said, 'ok', `as ${JSON.stringify(who)}: ${text}`);
      const is = rowsOf((await db.exec(`RESET ROLE; ${SNAP(table)}`))[1]);
      return [...Object.keys(is).filter(k => !(k in was)).map(k => `+${k}`),
        ...Object.keys(was).filter(k => !(k in is)).map(k => `-${k}`),
        ...Object.keys(was).filter(k => k in is && is[k] !== was[k]).map(k => `~${k}`)].sort();
    } finally { await db.exec('ROLLBACK'); }
  }
  const sees = async (who, table) => { const got = await ask(who, `SELECT id FROM ${table} ORDER BY id`); return got === 'refused' ? [] : got; };
  // Every way the browser can write one money table, for one business.
  const writes = async (who, t, biz) => {
    const b = biz === 'church' ? church : shop, other = biz === 'church' ? shop : church, row = `${t}-${biz}`;
    const go = text => ask(who, text, t);
    return {
      insert: await go(`INSERT INTO ${t}(id, business_id) VALUES ('probe', '${b}')`),
      insertReturning: await go(`INSERT INTO ${t}(id, business_id) VALUES ('probe', '${b}') RETURNING id`),
      upsertNew: await go(`INSERT INTO ${t}(id, business_id) VALUES ('probe', '${b}') ON CONFLICT (id) DO UPDATE SET note = 'u'`),
      upsertHit: await go(`INSERT INTO ${t}(id, business_id) VALUES ('${row}', '${b}') ON CONFLICT (id) DO UPDATE SET note = 'u'`),
      upsertNothing: await go(`INSERT INTO ${t}(id, business_id) VALUES ('${row}', '${b}') ON CONFLICT (id) DO NOTHING`),
      update: await go(`UPDATE ${t} SET note = 'probe' WHERE id = '${row}'`),
      updateReturning: await go(`UPDATE ${t} SET note = 'probe' WHERE id = '${row}' RETURNING id`),
      delete: await go(`DELETE FROM ${t} WHERE id = '${row}'`),
      deleteReturning: await go(`DELETE FROM ${t} WHERE id = '${row}' RETURNING id`),
      forUpdate: await ask(who, `SELECT id FROM ${t} WHERE business_id = '${b}' FOR UPDATE`),
      moveOut: await go(`UPDATE ${t} SET business_id = '${other}' WHERE id = '${row}'`),
    };
  };
  // Events and alerts: by id, by business, and with no WHERE at all.
  const beside = async (who, t) => {
    const go = text => ask(who, text, t);
    const out = { sees: await sees(who, t) };
    const rows = t === 'events' ? ['given', 'paid', 'visit', 'shop given', 'shop paid', 'shop visit']
      : ['gift alert', 'paid alert', 'other alert', 'shop gift alert', 'shop paid alert', 'shop other alert'];
    for (const id of rows) {
      out[`update ${id}`] = await go(`UPDATE ${t} SET note = 'probe' WHERE id = '${id}'`);
      out[`delete ${id}`] = await go(`DELETE FROM ${t} WHERE id = '${id}'`);
    }
    out.updateMine = await go(`UPDATE ${t} SET note = 'probe' WHERE business_id = '${church}'`);
    out.deleteMine = await go(`DELETE FROM ${t} WHERE business_id = '${church}' RETURNING id`);
    out.updateNoWhere = await go(`UPDATE ${t} SET note = 'probe'`);
    out.deleteNoWhere = await go(`DELETE FROM ${t}`);
    if (t === 'events') {
      out.insertGiving = await go(`INSERT INTO events(id, business_id, event_type) VALUES ('probe', '${church}', 'giving_received')`);
      out.insertGivingReturning = await go(`INSERT INTO events(id, business_id, event_type) VALUES ('probe', '${church}', 'giving_received') RETURNING id`);
      out.insertInvoice = await go(`INSERT INTO events(id, business_id, event_type) VALUES ('probe', '${church}', 'invoice_sent')`);
      out.insertOther = await go(`INSERT INTO events(id, business_id, event_type) VALUES ('probe', '${church}', 'contact_created')`);
      out.retypeIntoGiving = await go(`UPDATE events SET event_type = 'giving_received' WHERE id = 'visit'`);
      out.retypeOutOfGiving = await go(`UPDATE events SET event_type = 'contact_created' WHERE id = 'given'`);
      out.retypeNoWhere = await go(`UPDATE events SET event_type = 'giving_received'`);
    } else {
      out.insertGift = await go(`INSERT INTO chief_notifications(id, business_id, data) VALUES ('probe', '${church}', '{"kind":"gift_received"}')`);
      out.insertOther = await go(`INSERT INTO chief_notifications(id, business_id, data) VALUES ('probe', '${church}', '{"kind":"task_due"}')`);
      out.markAllRead = await go(`UPDATE chief_notifications SET status = 'read' WHERE business_id = '${church}' AND status = 'unread'`);
      out.retypeIntoGift = await go(`UPDATE chief_notifications SET data = '{"kind":"gift_received"}' WHERE id = 'other alert'`);
      out.retypeNoWhere = await go(`UPDATE chief_notifications SET data = '{"kind":"gift_received"}'`);
    }
    return out;
  };
  // Everything one person can do with the money, as the database answers it.
  async function everything(who) {
    const out = {};
    for (const t of MONEY) {
      out[t] = { sees: await sees(who, t), church: await writes(who, t, 'church'), shop: await writes(who, t, 'shop'),
        updateNoWhere: await ask(who, `UPDATE ${t} SET note = 'probe'`, t), deleteNoWhere: await ask(who, `DELETE FROM ${t}`, t) };
    }
    out.gift = {
      insert: await ask(who, `INSERT INTO invoices(id, business_id, is_gift) VALUES ('probe gift', '${church}', true)`, 'invoices'),
      update: await ask(who, `UPDATE invoices SET total = 1 WHERE id = 'gift'`, 'invoices'),
      relabel: await ask(who, `UPDATE invoices SET is_gift = true WHERE id = 'invoices-church'`, 'invoices'),
      delete: await ask(who, `DELETE FROM invoices WHERE id = 'gift'`, 'invoices'),
    };
    for (const t of BESIDE) out[t] = await beside(who, t);
    return out;
  }
  const everyone = async (names = Object.keys(PEOPLE)) => {
    const all = {};
    for (const name of names) all[name] = await everything(PEOPLE[name]);
    return all;
  };
  const service = async (text, params = []) => {
    await db.exec('SET ROLE service_role');
    try { return await db.query(text, params); } finally { await db.exec('RESET ROLE'); }
  };
  const grant = (who, level, whoGave = false, bank = false, by = owner, biz = church) => service(
    `SELECT public.church_money_grant($1, $2, $3, $4, $5, $6) AS out`, [biz, who, level, whoGave, bank, by]);
  return { db, run, ask, sees, everything, everyone, service, grant };
}

// Every leaf where two answers differ, as "who / table / what".
function differences(a, b, path = []) {
  if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b)) {
    return [...new Set([...Object.keys(a), ...Object.keys(b)])].flatMap(k => differences(a[k], b[k], [...path, k]));
  }
  return JSON.stringify(a) === JSON.stringify(b) ? [] : [path.join(' / ')];
}
// `now` gives a person less than `was`, or the same, at every leaf: it sees
// no row it did not see and changes no row it did not change.
function lessOrSame(now, was, path = []) {
  if (now && was && typeof now === 'object' && typeof was === 'object' && !Array.isArray(now) && !Array.isArray(was)) {
    for (const k of new Set([...Object.keys(now), ...Object.keys(was)])) lessOrSame(now[k], was[k], [...path, k]);
    return;
  }
  const did = v => (Array.isArray(v) ? v : []);
  const extra = did(now).filter(x => !did(was).includes(x));
  assert.deepEqual(extra, [], `${path.join(' / ')} got wider: ${JSON.stringify(was)} -> ${JSON.stringify(now)}`);
}
const md5s = async db => Object.fromEntries((await db.query(`SELECT p.proname, md5(btrim(regexp_replace(p.prosrc, '[[:space:]]+', ' ', 'g'))) AS h
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname IN
  ('ministry_finance_access', 'ministry_finance_guard', 'ministry_giving_access', 'church_giving_open',
   'protect_gift_classification', 'is_business_writer')`)).rows.map(r => [r.proname, r.h]));

// The one narrowing at zero holders, by name. A Manager or a Member of the
// church cannot see its money events and alerts; the shop's hand cannot see
// the shop's giving ones (gifts are private in any business). An unfiltered
// write of theirs used to reach those rows.
const HIDDEN = {
  manager: { events: ['given', 'paid'], chief_notifications: ['gift alert', 'paid alert'] },
  member: { events: ['given', 'paid'], chief_notifications: ['gift alert', 'paid alert'] },
  shopHand: { events: ['shop given'], chief_notifications: ['shop gift alert'] },
};
const NARROWED = Object.keys(HIDDEN).flatMap(who => BESIDE.flatMap(t =>
  ['updateNoWhere', 'deleteNoWhere', 'retypeNoWhere'].map(op => `${who} / ${t} / ${op}`))).sort();
function onlyTheNarrowing(before, after, label) {
  assert.deepEqual(differences(before, after).sort(), NARROWED, `${label}: the differences are exactly the unfiltered writes`);
  checks++;
  for (const [who, tables] of Object.entries(HIDDEN)) {
    for (const [t, hidden] of Object.entries(tables)) {
      const was = before[who][t], is = after[who][t];
      // Before: the unfiltered write reached every row of theirs, the hidden
      // money rows too. After: the same rows less the hidden ones.
      for (const [op, mark] of [['updateNoWhere', '~'], ['deleteNoWhere', '-']]) {
        for (const id of hidden) assert.ok(was[op].includes(mark + id), `${label}: ${who} reached ${id} before`);
        assert.deepEqual(is[op], was[op].filter(x => !hidden.includes(x.slice(1))), `${label}: ${who} / ${t} / ${op}`);
        assert.ok(is[op].length > 0, `${label}: ${who} still writes the rows they can see`); checks += 2;
      }
      // An unfiltered update that would make a money row of a row they may
      // not write is refused; it went through before.
      assert.ok(Array.isArray(was.retypeNoWhere) && was.retypeNoWhere.length > 0); checks++;
      assert.equal(is.retypeNoWhere, 'refused', `${label}: ${who} / ${t} / retypeNoWhere`); checks++;
    }
  }
}

// ═══ 1 to 3: the main run, everything the superuser's ══════════════════
{
  const { db, run, ask, sees, everything, everyone, service, grant } = await build();
  const serviceRefuses = async (text, message) => {
    await assert.rejects(service(text), e => { assert.match(e.message, message); return true; }); checks++;
  };
  const can = async (who, text, table) => { const got = await ask(who, text, table); assert.ok(Array.isArray(got) && got.length > 0, `${text} -> ${JSON.stringify(got)}`); checks++; };
  const cannot = async (who, text, table) => { const got = await ask(who, text, table); assert.ok(got === 'refused' || got.length === 0, `${text} -> ${JSON.stringify(got)}`); checks++; };

  // The functions this file builds on are the repo's own, and the hashes the
  // file tells Kevin to expect are theirs.
  const hashes = await md5s(db);
  for (const [name, h] of Object.entries(hashes)) {
    assert.match(APPLY, new RegExp(`--\\s+${name}\\((uuid)?\\)\\s+${h}\\n`), `the file's expected md5 for ${name}`); checks++;
  }
  assert.equal(Object.keys(hashes).length, 6); checks++;

  // ─── 1. No holder ───────────────────────────────────────────────────
  const before = await everyone();
  // The wall it starts from is the one we think it is.
  assert.deepEqual(before.manager.bills.sees, [], 'a Manager reads no church money today'); checks++;
  assert.ok(before.admin.bills.sees.includes('bills-church') && before.admin.invoices.sees.includes('gift')); checks++;
  assert.deepEqual(before.admin.bills.church.update, ['~bills-church'], 'an Admin seat writes a bill through the browser today'); checks++;
  assert.deepEqual(before.shopHand.bills.shop.update, ['~bills-shop'], 'a shop is not walled'); checks++;
  assert.ok(before.accountant.plaid_transactions.sees.includes('plaid_transactions-church')); checks++;
  assert.deepEqual(before.member.events.sees, ['visit'], 'a Member sees no money event today'); checks++;
  assert.deepEqual(before.member.events.deleteNoWhere, ['-given', '-paid', '-visit'],
    'and yet an unfiltered delete of theirs takes the money events with it'); checks++;
  // The signed-out role: nothing, except the table production leaves open.
  for (const t of MONEY.filter(x => x !== 'business_expenses')) {
    assert.deepEqual(before.anon[t].sees, [], `anon reads no ${t}`); checks++;
    assert.ok(Object.values(before.anon[t].church).every(v => v === 'refused' || v.length === 0), `anon writes no ${t}`); checks++;
  }
  for (const t of BESIDE) { assert.deepEqual(before.anon[t].sees, []); checks++; }
  assert.deepEqual(before.anon.business_expenses.sees, ['business_expenses-church', 'business_expenses-shop'],
    'business_expenses is open to the signed-out role today (business_expenses_all)'); checks++;
  assert.deepEqual(before.anon.business_expenses.church.delete, ['-business_expenses-church']); checks++;

  await run(APPLY);
  const after = await everyone();
  onlyTheNarrowing(before, after, 'applied once, no holder');
  await run(APPLY);   // safe to run twice
  assert.deepEqual(await everyone(), after, 'applied twice: the same'); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders`)).rows[0].n, 0); checks++;
  // The signed-out role is exactly where it was, the open table included:
  // the restrictive policies are TO authenticated and never consulted for it.
  assert.deepEqual(after.anon, before.anon, 'anon: no wider, no narrower'); checks++;
  assert.deepEqual(after.nobody, before.nobody); checks++;
  // ministry_finance_access is untouched; the six hashes moved only where
  // the file says (the guard and the giving function).
  const hashesAfter = await md5s(db);
  for (const name of ['ministry_finance_access', 'church_giving_open', 'protect_gift_classification', 'is_business_writer']) {
    assert.equal(hashesAfter[name], hashes[name], `${name} is not touched`); checks++;
  }
  for (const name of ['ministry_finance_guard', 'ministry_giving_access']) { assert.notEqual(hashesAfter[name], hashes[name]); checks++; }

  // The two new guards stand in front of exactly the businesses the old one
  // does, however the type is spelled.
  {
    const spellings = ['Church', 'churches', 'Non-Profit', 'non profit', 'Faith Based', ' ministry ', 'NOT_FOR_PROFIT',
      'religious-org', 'barber', 'coach', 'churchy', 'nonprofits', '', null];
    let n = 500;
    for (const type of [...spellings, 'missing']) {
      const id = u(n++);
      if (type !== 'missing') await db.query('INSERT INTO businesses VALUES ($1, $2, $3)', [id, u(n++), type]);
      await db.exec('BEGIN');
      try {
        await db.exec('SET LOCAL ROLE authenticated');
        await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [stranger]);
        const r = (await db.query(`SELECT public.ministry_finance_guard($1) AS old, public.ministry_finance_write_guard($1) AS w,
          public.ministry_finance_bank_guard($1) AS b`, [id])).rows[0];
        assert.deepEqual([r.w, r.b], [r.old, r.old], `type ${JSON.stringify(type)}`); checks++;
        if (type === 'missing') { assert.equal(r.old, false); checks++; }
      } finally { await db.exec('ROLLBACK'); }
    }
  }

  // What it added, and that it replaced no policy.
  const policies = (await db.query(`SELECT policyname, cmd, permissive, roles::text AS roles, count(*)::int AS n FROM pg_policies
    WHERE schemaname = 'public' AND (policyname LIKE 'ministry_financial_%' OR policyname LIKE 'church_money_%' OR policyname IN
      ('church_giving_bank', 'gift_row_privacy')) GROUP BY 1, 2, 3, 4 ORDER BY 1`)).rows;
  assert.deepEqual(policies.map(p => `${p.policyname} ${p.cmd} ${p.permissive} ${p.roles} ${p.n}`), [
    'church_giving_bank ALL RESTRICTIVE {authenticated} 2', 'church_money_alert_delete DELETE RESTRICTIVE {authenticated} 1',
    'church_money_alert_update UPDATE RESTRICTIVE {authenticated} 1', 'church_money_bank ALL RESTRICTIVE {authenticated} 2',
    'church_money_event_delete DELETE RESTRICTIVE {authenticated} 1', 'church_money_event_update UPDATE RESTRICTIVE {authenticated} 1',
    'gift_row_privacy ALL RESTRICTIVE {authenticated} 1', 'ministry_financial_events SELECT RESTRICTIVE {authenticated} 1',
    'ministry_financial_notifications SELECT RESTRICTIVE {authenticated} 1', 'ministry_financial_privacy ALL RESTRICTIVE {authenticated} 9',
    'ministry_financial_write_delete DELETE RESTRICTIVE {authenticated} 9', 'ministry_financial_write_insert INSERT RESTRICTIVE {authenticated} 9',
    'ministry_financial_write_update UPDATE RESTRICTIVE {authenticated} 9']); checks++;
  for (const t of ['church_money_holders', 'church_money_asks']) {
    const r = (await db.query(`SELECT c.relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS n,
      has_table_privilege('authenticated', c.oid, 'select,insert,update,delete,truncate,references,trigger') AS a,
      has_table_privilege('anon', c.oid, 'select,insert,update,delete,truncate,references,trigger') AS b
      FROM pg_class c WHERE c.oid = 'public.${t}'::regclass`)).rows[0];
    assert.deepEqual(r, { rls: true, n: 0, a: false, b: false }, `${t} is the server's alone, default privileges or not`); checks++;
  }

  // ─── 2. Holders ─────────────────────────────────────────────────────
  // A See tick on a Viewer: the books, read only. Not who gave, not the bank.
  await grant(viewer, 'see');
  let v = await everything(viewer);
  for (const t of MONEY.filter(x => !BANK.includes(x))) {
    assert.ok(v[t].sees.includes(`${t}-church`), `a See holder reads ${t}`); checks++;
    assert.ok(!v[t].sees.includes(`${t}-shop`) || t === 'business_expenses', 'and never another business'); checks++;
  }
  for (const t of BANK) { assert.deepEqual(v[t].sees, [], `not the bank (${t}) without its tick`); checks++; }
  assert.ok(!v.invoices.sees.includes('gift'), 'not who gave without its tick'); checks++;
  assert.deepEqual(v.events.sees, ['paid', 'visit']); checks++;
  assert.deepEqual(v.chief_notifications.sees, ['other alert', 'paid alert']); checks++;
  // Reading aside, a Viewer does nothing it could not do before: no write on
  // any table, the open one included (its allow-all hands a Viewer the
  // permissive half of a write, and the tick's Work rule is what holds).
  const reads = (o) => JSON.parse(JSON.stringify(o, (k, val) => (k === 'sees' || k === 'forUpdate' ? undefined : val)));
  assert.deepEqual(reads(v), reads(after.viewer), 'a Viewer writes nothing more, tick or not'); checks++;
  assert.deepEqual(v.business_expenses.church.update, []); checks++;
  // Nobody else moved.
  for (const name of Object.keys(PEOPLE).filter(n => n !== 'viewer')) {
    assert.deepEqual(await everything(PEOPLE[name]), after[name], `${name} is as they were`); checks++;
  }

  // A See tick with the bank on a Manager seat. The team policy lets a Manager
  // write these tables; the tick opened reading, and the write guard keeps
  // the writing shut. This is the hole the write policies exist for.
  await grant(manager, 'see', false, true);
  let m = await everything(manager);
  for (const t of MONEY) { assert.ok(m[t].sees.includes(`${t}-church`), `See + bank reads ${t}`); checks++; }
  for (const t of MONEY) {
    for (const [op, got] of Object.entries(m[t].church)) {
      if (op === 'forUpdate') continue;      // a row lock is a write: see below
      assert.ok(got === 'refused' || got.length === 0, `a See holder cannot ${op} ${t}: ${JSON.stringify(got)}`); checks++;
    }
    assert.deepEqual(m[t].church.forUpdate, [], `a See holder cannot lock a row of ${t}`); checks++;
    assert.ok(!m[t].updateNoWhere.includes(`~${t}-church`) && !m[t].deleteNoWhere.includes(`-${t}-church`)); checks++;
  }
  assert.ok(!m.invoices.sees.includes('gift')); checks++;
  // The same for the money rows beside them: a See holder sees the invoice
  // event and the invoice-paid alert, and can change or delete neither, by
  // id, by business or with no WHERE. (Before this was fixed: probe B1.)
  assert.deepEqual(m.events.sees, ['paid', 'visit']); checks++;
  assert.deepEqual(m.chief_notifications.sees, ['other alert', 'paid alert']); checks++;
  for (const [t, row] of [['events', 'paid'], ['chief_notifications', 'paid alert']]) {
    assert.deepEqual(m[t][`update ${row}`], [], `a See holder cannot change ${row}`); checks++;
    assert.deepEqual(m[t][`delete ${row}`], [], `a See holder cannot delete ${row}`); checks++;
    for (const op of ['updateMine', 'deleteMine', 'updateNoWhere', 'deleteNoWhere']) {
      assert.ok(Array.isArray(m[t][op]) && m[t][op].length > 0 && m[t][op].every(x => !x.endsWith(row) && !/given|gift alert/.test(x)),
        `${op} on ${t} works on the rest and skips the money rows: ${JSON.stringify(m[t][op])}`); checks++;
    }
  }
  // "Mark all read" by an office login is no error and marks the rest.
  assert.deepEqual(m.chief_notifications.markAllRead, ['~other alert']); checks++;
  // Without the three write policies that same Manager would have written.
  await db.exec('BEGIN');
  for (const c of ['insert', 'update', 'delete']) await db.exec(`DROP POLICY ministry_financial_write_${c} ON public.bills`);
  await db.exec('SET LOCAL ROLE authenticated');
  await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [manager]);
  assert.equal((await db.query(`UPDATE bills SET note = 'x' WHERE id = 'bills-church'`)).affectedRows, 1,
    'the widened read guard alone would have let a See holder write'); checks++;
  await db.exec('ROLLBACK');
  // And without the event policy that same Manager would have deleted the
  // invoice event the tick let them see.
  await db.exec('BEGIN');
  await db.exec(`DROP POLICY church_money_event_delete ON public.events`);
  await db.exec('SET LOCAL ROLE authenticated');
  await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [manager]);
  assert.equal((await db.query(`DELETE FROM events WHERE id = 'paid'`)).affectedRows, 1,
    'the widened read alone would have let a See holder delete a money event'); checks++;
  await db.exec('ROLLBACK');

  // See with who gave on a Member seat: sees the gift, the giving event and
  // the gift alert, and can change none of them.
  await grant(member, 'see', true, false);
  let w = await everything(member);
  assert.ok(w.invoices.sees.includes('gift')); checks++;
  assert.deepEqual(w.events.sees, ['given', 'paid', 'visit']); checks++;
  assert.deepEqual(w.chief_notifications.sees, ['gift alert', 'other alert', 'paid alert']); checks++;
  assert.deepEqual(w.gift, { insert: 'refused', update: [], relabel: [], delete: [] }); checks++;
  for (const [t, rows] of [['events', ['given', 'paid']], ['chief_notifications', ['gift alert', 'paid alert']]]) {
    for (const row of rows) {
      assert.deepEqual([w[t][`update ${row}`], w[t][`delete ${row}`]], [[], []], `See + who gave cannot touch ${row}`); checks++;
    }
    assert.ok(w[t].deleteNoWhere.every(x => !rows.includes(x.slice(1))) && w[t].deleteNoWhere.length > 0); checks++;
  }
  assert.deepEqual(w.events.retypeOutOfGiving, [], 'nor move a giving event out of its kind'); checks++;
  assert.deepEqual(w.chief_notifications.markAllRead, ['~other alert']); checks++;

  // Work with who gave on a Member seat: writes the books, the gift rows and
  // the money events and alerts; still not the bank.
  await grant(member, 'work', true, false);
  w = await everything(member);
  for (const t of TEAM_WRITES.filter(x => !BANK.includes(x))) {
    assert.deepEqual([w[t].church.insert, w[t].church.update, w[t].church.delete], [['+probe'], [`~${t}-church`], [`-${t}-church`]],
      `a Work holder writes ${t}`); checks++;
    if (t !== 'business_expenses') { assert.deepEqual(w[t].shop, after.member[t].shop, 'and nothing of another business'); checks++; }
  }
  for (const t of TEAM_READS.filter(x => !BANK.includes(x))) {
    assert.deepEqual(reads(w[t].church), reads(after.member[t].church), `${t} was never the team's to write`); checks++;
  }
  assert.deepEqual(w.gift, { insert: ['+probe gift'], update: ['~gift'], relabel: ['~invoices-church'], delete: ['-gift'] }); checks++;
  for (const [t, rows] of [['events', ['given', 'paid']], ['chief_notifications', ['gift alert', 'paid alert']]]) {
    for (const row of rows) {
      assert.deepEqual([w[t][`update ${row}`], w[t][`delete ${row}`]], [[`~${row}`], [`-${row}`]], `Work + who gave writes ${row}`); checks++;
    }
  }
  assert.deepEqual(w.chief_notifications.markAllRead, ['~gift alert', '~other alert', '~paid alert']); checks++;
  for (const t of BANK) {
    assert.deepEqual(w[t].sees, [], 'Work is not the bank'); checks++;
    assert.ok(Object.values(w[t].church).every(x => x === 'refused' || x.length === 0)); checks++;
  }
  // Lead writes as Work does; Work without who gave cannot touch a gift row,
  // a giving event or a gift alert, and still writes the invoice ones.
  await grant(member, 'lead', false, true);
  w = await everything(member);
  assert.deepEqual(w.bills.church.update, ['~bills-church']); checks++;
  assert.deepEqual(w.plaid_transactions.church.update, ['~plaid_transactions-church'], 'Lead + bank writes the bank feed'); checks++;
  assert.deepEqual(w.gift, { insert: 'refused', update: [], relabel: 'refused', delete: [] }, 'no who gave, no gift rows'); checks++;
  assert.deepEqual([w.events['delete given'], w.events['delete paid']], [[], ['-paid']]); checks++;
  assert.deepEqual([w.chief_notifications['update gift alert'], w.chief_notifications['update paid alert']], [[], ['~paid alert']]); checks++;
  await grant(member, 'work', true, false);

  // The Giving keeper still locks who gave, for a holder as for the owner,
  // in the gift rows and in the giving events and alerts.
  await service(`INSERT INTO church_keepers(business_id, area, user_id) VALUES ('${church}', 'giving_money', '${admin}')`);
  w = await everything(member);
  assert.ok(!w.invoices.sees.includes('gift') && w.bills.sees.includes('bills-church'), 'the keeper locks the gifts, not the books'); checks++;
  assert.deepEqual(w.gift, { insert: 'refused', update: [], relabel: 'refused', delete: [] }); checks++;
  assert.deepEqual([w.events.sees, w.events['delete given'], w.events['delete paid']], [['paid', 'visit'], [], ['-paid']]); checks++;
  assert.ok(!w.events.deleteNoWhere.includes('-given') && !w.chief_notifications.deleteNoWhere.includes('-gift alert')); checks++;
  // The owner is locked out too (2026-10-27), and now cannot blind-delete either.
  const locked = await everything(PEOPLE.owner);
  assert.ok(!locked.events.sees.includes('given') && !locked.events.deleteNoWhere.includes('-given')); checks++;
  await service(`DELETE FROM church_keepers`);

  // Moved down to a Viewer: still reads, no longer writes.
  const guard = async (uid, fn) => {
    await db.exec('BEGIN');
    try {
      await db.exec('SET LOCAL ROLE authenticated');
      await db.query(`SELECT set_config('request.jwt.claim.sub', $1, true)`, [uid]);
      return (await db.query(`SELECT public.${fn}($1) AS v`, [church])).rows[0].v;
    } finally { await db.exec('ROLLBACK'); }
  };
  await service(`UPDATE business_users SET role = 'viewer' WHERE business_id = '${church}' AND user_id = '${member}'`);
  w = await everything(member);
  assert.ok(w.bills.sees.includes('bills-church')); checks++;
  assert.ok(Object.entries(w.bills.church).every(([op, x]) => x === 'refused' || x.length === 0), 'a Viewer seat never writes, whatever the tick says'); checks++;
  assert.deepEqual(w.business_expenses.church.update, [], 'not even where a permissive policy would let a Viewer write'); checks++;
  assert.deepEqual([w.events['delete paid'], w.events['delete given']], [[], []]); checks++;
  // And that is the tick's own answer, not only the team policy's.
  assert.equal(await guard(member, 'ministry_finance_write_guard'), false); checks++;
  assert.equal(await guard(member, 'church_money_giving_write'), false); checks++;
  assert.equal(await guard(member, 'ministry_finance_guard'), true); checks++;
  assert.equal(await guard(member, 'ministry_giving_access'), true); checks++;
  assert.equal(await guard(member, 'ministry_finance_bank_guard'), false); checks++;
  assert.equal(await guard(member, 'ministry_finance_access'), false, 'the old name is never widened'); checks++;
  await service(`UPDATE business_users SET role = 'member' WHERE business_id = '${church}' AND user_id = '${member}'`);
  assert.equal(await guard(member, 'ministry_finance_write_guard'), true); checks++;
  assert.equal(await guard(member, 'church_money_giving_write'), true); checks++;
  assert.equal(await guard(owner, 'ministry_finance_write_guard'), true); checks++;
  assert.equal(await guard(stranger, 'ministry_finance_write_guard'), false); checks++;
  assert.equal(await guard(viewer, 'ministry_finance_guard'), true, 'the Viewer holds See'); checks++;
  assert.equal(await guard(viewer, 'ministry_finance_write_guard'), false); checks++;
  assert.equal(await guard(viewer, 'ministry_finance_access'), false); checks++;

  // The seat ends: everything shuts at once. Invited again (a new seat row):
  // the old tick does not come back with them.
  await service(`UPDATE business_users SET status = 'revoked' WHERE business_id = '${church}' AND user_id = '${member}'`);
  assert.deepEqual(await everything(member), after.stranger, 'a revoked seat holds nothing'); checks++;
  await service(`INSERT INTO business_users(business_id, user_id, role, status) VALUES ('${church}', '${member}', 'member', 'active')`);
  assert.deepEqual(await everything(member), after.member, 'invited again: the old tick is not theirs'); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders WHERE user_id = '${member}'`)).rows[0].n, 1); checks++;
  // The owner says yes again, and it rides the new seat.
  await grant(member, 'work', true, false);
  await can(member, `UPDATE bills SET note = 'x' WHERE id = 'bills-church'`, 'bills');
  // A seat row that is deleted takes its tick with it.
  await service(`DELETE FROM business_users WHERE business_id = '${church}' AND user_id = '${member}' AND status = 'active'`);
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders WHERE user_id = '${member}'`)).rows[0].n, 0); checks++;
  await service(`UPDATE business_users SET status = 'active' WHERE business_id = '${church}' AND user_id = '${member}'`);
  assert.deepEqual(await everything(member), after.member); checks++;
  // A hand-written row that names someone else's seat counts for nobody.
  await service(`INSERT INTO church_money_holders(business_id, user_id, seat_id, level, granted_by)
    SELECT '${church}', '${u(88)}', id, 'lead', '${owner}' FROM business_users WHERE user_id = '${admin}'`);
  assert.deepEqual(await sees(u(88), 'bills'), []); checks++;
  await service(`DELETE FROM church_money_holders WHERE user_id = '${u(88)}'`);
  // Two active seats for one login: the tick lands on the newest.
  {
    const two = u(77);
    await service(`INSERT INTO business_users(business_id, user_id, role, status, joined_at) VALUES
      ('${church}', '${two}', 'viewer', 'active', now() - interval '2 days'), ('${church}', '${two}', 'member', 'active', now())`);
    const g = (await grant(two, 'work')).rows[0].out;
    assert.equal((await db.query(`SELECT role FROM business_users WHERE id = $1`, [g.holder.seat_id])).rows[0].role, 'member'); checks++;
    await can(two, `UPDATE bills SET note = 'x' WHERE id = 'bills-church'`, 'bills');
    await service(`UPDATE business_users SET status = 'revoked' WHERE id = '${g.holder.seat_id}'`);
    assert.deepEqual(await sees(two, 'bills'), [], 'the ticked seat ended: the other seat carries nothing'); checks++;
    await service(`DELETE FROM business_users WHERE user_id = '${two}'`);
  }
  // The owner changes hands (no route does this today): the old owner loses
  // their standing and can give nothing; a tick they gave still reads.
  await db.exec('BEGIN');
  await db.exec(`UPDATE businesses SET owner_id = '${u(55)}' WHERE id = '${church}'`);
  await db.exec('SET LOCAL ROLE service_role');
  await assert.rejects(db.query(`SELECT public.church_money_grant('${church}', '${viewer}', 'see', true, true, '${owner}')`), /only the owner/); checks++;
  await db.exec('ROLLBACK');

  // ─── 3. Only the owner's word ───────────────────────────────────────
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, '${admin}')`, /only the owner/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, null)`, /only the owner/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, '${barber}')`, /only the owner/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${viewer}', 'work', false, false, '${owner}')`, /Viewer login can only see/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${stranger}', 'see', false, false, '${owner}')`, /no active login/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${owner}', 'see', false, false, '${owner}')`, /holds giving already/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'all', false, false, '${owner}')`, /see, work or lead/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'Work', false, false, '${owner}')`, /see, work or lead/);
  await serviceRefuses(`SELECT public.church_money_grant('${shop}', '${shopHand}', 'see', false, false, '${barber}')`, /not a church or nonprofit/);
  await serviceRefuses(`SELECT public.church_money_grant('${u(99)}', '${member}', 'see', false, false, '${owner}')`, /only the owner/);
  await serviceRefuses(`INSERT INTO church_money_holders(business_id, user_id, seat_id, level, granted_by)
    SELECT '${church}', user_id, id, 'everything', '${owner}' FROM business_users WHERE user_id = '${admin}'`, /church_money_holders_level/);
  // Nulls for the two ticks are "no".
  const plain = (await service(`SELECT public.church_money_grant($1, $2, 'see', null, null, $3) AS out`, [church, member, owner])).rows[0].out.holder;
  assert.deepEqual([plain.who_gave, plain.bank], [false, false]); checks++;
  // A null level takes the tick away.
  assert.deepEqual((await grant(member, null)).rows[0].out, { ok: true, holder: null }); checks++;
  assert.deepEqual((await grant(viewer, null)).rows[0].out, { ok: true, holder: null }); checks++;
  assert.deepEqual(await everything(viewer), after.viewer); checks++;

  // An ask: one open a login, never for yourself, answered by the owner alone.
  const open = (who, by, level, whoGave = false, bank = false, biz = church) => service(
    `SELECT public.church_money_ask($1, $2, $3, $4, $5, $6) AS out`, [biz, who, by, level, whoGave, bank]);
  const first = (await open(member, admin, 'work', true)).rows[0].out.ask;
  assert.deepEqual([first.status, first.wants, first.asked_by], ['asked', { level: 'work', who_gave: true, bank: false }, admin]); checks++;
  await serviceRefuses(`SELECT public.church_money_ask('${church}', '${member}', '${manager}', 'see', false, false)`, /church_money_asks_one_open/);
  await serviceRefuses(`SELECT public.church_money_ask('${church}', '${admin}', '${admin}', 'see', false, false)`, /their own access/);
  await serviceRefuses(`SELECT public.church_money_ask('${church}', '${owner}', '${admin}', 'see', false, false)`, /holds giving already/);
  await serviceRefuses(`SELECT public.church_money_ask('${church}', '${stranger}', '${admin}', 'see', false, false)`, /no active login/);
  await serviceRefuses(`SELECT public.church_money_ask('${church}', '${viewer}', '${admin}', 'work', false, false)`, /Viewer login can only see/);
  await serviceRefuses(`SELECT public.church_money_ask('${church}', '${viewer}', '${admin}', 'owner', false, false)`, /see, work or lead/);
  await serviceRefuses(`SELECT public.church_money_ask('${shop}', '${shopHand}', '${barber}', 'see', false, false)`, /not a church or nonprofit/);
  await serviceRefuses(`SELECT public.church_money_ask('${u(99)}', '${member}', '${admin}', 'see', false, false)`, /no such church/);
  await serviceRefuses(`INSERT INTO church_money_asks(business_id, user_id, asked_by, wants)
    VALUES ('${church}', '${admin}', '${admin}', '{"level":"see"}')`, /church_money_asks_not_for_self/);
  for (const bad of ['{"level":"owner"}', '{}', '[]', '{"level":"see","bank":"yes"}', '{"level":"see","who_gave":null}']) {
    await serviceRefuses(`INSERT INTO church_money_asks(business_id, user_id, asked_by, wants)
      VALUES ('${church}', '${viewer}', '${admin}', '${bad}')`, /church_money_asks_wants/);
  }
  assert.deepEqual(await everything(member), after.member, 'an ask opens nothing'); checks++;
  await serviceRefuses(`SELECT public.church_money_answer('${first.id}', true, '${admin}')`, /only the owner answers/);
  await serviceRefuses(`SELECT public.church_money_answer('${first.id}', true, '${member}')`, /only the owner answers/);
  await serviceRefuses(`SELECT public.church_money_answer('${u(98)}', true, '${owner}')`, /no such ask/);
  // A grant cannot be pinned on an ask that is another person's or another
  // church's; the owner of one church cannot answer another's ask.
  const other = '33333333-3333-4333-8333-333333333333';
  await db.query('INSERT INTO businesses VALUES ($1, $2, $3)', [other, u(60), 'church']);
  await db.query(`INSERT INTO business_users(business_id, user_id, role, status) VALUES ($1, $2, 'member', 'active')`, [other, u(61)]);
  const theirs = (await open(u(61), u(62), 'lead', true, true, other)).rows[0].out.ask.id;
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${member}', 'see', false, false, '${owner}', '${theirs}')`, /not for this person at this church/);
  await serviceRefuses(`SELECT public.church_money_grant('${church}', '${viewer}', 'see', false, false, '${owner}', '${first.id}')`, /not for this person at this church/);
  await serviceRefuses(`SELECT public.church_money_answer('${theirs}', true, '${owner}')`, /only the owner answers/);
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders`)).rows[0].n, 1, 'only the Manager holds a tick'); checks++;
  const yes = (await service(`SELECT public.church_money_answer($1, true, $2) AS out`, [first.id, owner])).rows[0].out;
  assert.deepEqual([yes.ok, yes.status, yes.holder.ask_id], [true, 'approved', first.id]); checks++;
  assert.deepEqual([yes.holder.level, yes.holder.who_gave, yes.holder.bank, yes.holder.granted_by], ['work', true, false, owner]); checks++;
  await can(member, `UPDATE invoices SET total = 1 WHERE id = 'gift'`, 'invoices');
  await serviceRefuses(`SELECT public.church_money_answer('${first.id}', true, '${owner}')`, /already approved/);
  assert.deepEqual((await db.query(`SELECT status, answered_by FROM church_money_asks WHERE id = $1`, [first.id])).rows[0],
    { status: 'approved', answered_by: owner }); checks++;
  // A no; an ask that ran out is marked, never answered, and does not hold
  // the place of a new one; a yes the grant itself refuses leaves it open.
  const second = (await open(viewer, admin, 'see', false, true)).rows[0].out.ask.id;
  assert.equal((await service(`SELECT public.church_money_answer($1, false, $2) AS out`, [second, owner])).rows[0].out.status, 'declined'); checks++;
  assert.deepEqual(await everything(viewer), after.viewer, 'a no opens nothing'); checks++;
  const late = (await open(viewer, admin, 'see')).rows[0].out.ask.id;
  await service(`UPDATE church_money_asks SET expires_at = now() - interval '1 minute' WHERE id = $1`, [late]);
  assert.deepEqual((await service(`SELECT public.church_money_answer($1, true, $2) AS out`, [late, owner])).rows[0].out,
    { ok: false, status: 'expired', holder: null }); checks++;
  assert.equal((await db.query(`SELECT status FROM church_money_asks WHERE id = $1`, [late])).rows[0].status, 'expired'); checks++;
  assert.deepEqual(await everything(viewer), after.viewer, 'an ask that ran out opens nothing, even on a yes'); checks++;
  const stale = (await open(viewer, admin, 'see')).rows[0].out.ask.id;
  await service(`UPDATE church_money_asks SET expires_at = now() - interval '1 minute' WHERE id = $1`, [stale]);
  const fresh = (await open(viewer, manager, 'see', true)).rows[0].out.ask.id;      // the stale one does not block it
  assert.equal((await db.query(`SELECT status FROM church_money_asks WHERE id = $1`, [stale])).rows[0].status, 'expired'); checks++;
  await service(`UPDATE church_money_asks SET status = 'withdrawn' WHERE id = $1`, [fresh]);
  const tooMuch = (await service(`INSERT INTO church_money_asks(business_id, user_id, asked_by, wants)
    VALUES ($1, $2, $3, '{"level":"work"}') RETURNING id`, [church, viewer, admin])).rows[0].id;
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
    await denied(role, member, `SELECT public.church_money_answer('${first.id}', true, '${owner}')`);
    await denied(role, member, `SELECT public.church_money_ask('${church}', '${viewer}', '${member}', 'see', true, true)`);
    await denied(role, member, `SELECT public.church_money_tick('${church}', 'any')`);
    await denied(role, member, `SELECT public.ministry_finance_walled('${church}')`);
  }
  for (const fn of ['ministry_finance_write_guard', 'ministry_finance_bank_guard', 'church_money_giving_write',
    'ministry_finance_guard', 'ministry_finance_access', 'ministry_giving_access']) {
    await denied('anon', member, `SELECT public.${fn}('${church}')`);
  }
  // A tick is the caller's own: someone else's opens nothing for a stranger.
  assert.deepEqual(await everything(stranger), after.stranger); checks++;
  assert.deepEqual(await everything(manager), m, 'the Manager still holds See + bank, and only that'); checks++;
  assert.deepEqual(await everything(PEOPLE.anon), after.anon, 'and the signed-out role is where it was'); checks++;

  // Every function a policy reads is SECURITY DEFINER with a fixed
  // search_path; the three the server calls are not, and carry one too.
  const fns = (await db.query(`SELECT p.proname, p.prosecdef AS definer, p.proconfig AS config FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname = ANY($1) ORDER BY 1`,
    [[...NEW_FUNCTIONS, 'ministry_finance_access', 'ministry_finance_guard', 'ministry_giving_access']])).rows;
  assert.equal(fns.length, 11); checks++;
  for (const f of fns) {
    assert.deepEqual(f.config, ['search_path=public'], f.proname); checks++;
    assert.equal(f.definer, !['church_money_grant', 'church_money_answer', 'church_money_ask'].includes(f.proname), f.proname); checks++;
  }

  // ─── The instant stop, the rollback, and applying again ─────────────
  const held = (await db.query(`SELECT business_id, user_id, seat_id, level, who_gave, bank, granted_by, ask_id FROM church_money_holders ORDER BY user_id`)).rows;
  assert.equal(held.length, 2, 'the Manager and the Member hold a tick going into the stop'); checks++;
  const withHolders = await everyone();
  await db.exec('DELETE FROM church_money_holders');
  assert.deepEqual(await everyone(), after, 'the instant stop: no rows, every answer back to the applied file with no holder'); checks++;
  for (const h of held) {
    await db.query(`INSERT INTO church_money_holders(business_id, user_id, seat_id, level, who_gave, bank, granted_by, ask_id)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`, [h.business_id, h.user_id, h.seat_id, h.level, h.who_gave, h.bank, h.granted_by, h.ask_id]);
  }
  assert.deepEqual(await everyone(['manager', 'member']), { manager: withHolders.manager, member: withHolders.member }, 'the ticks are back'); checks++;

  await run(ROLLBACK);
  await run(ROLLBACK);   // safe to run twice
  assert.deepEqual(await everyone(), before, 'rolled back with holders still in the table: every answer as before the file, the unfiltered write too'); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_money_holders`)).rows[0].n, 2, 'the rollback keeps the rows'); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_proc WHERE proname = ANY($1)`, [NEW_FUNCTIONS])).rows[0].n, 0); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_policies WHERE policyname LIKE 'ministry_financial_write_%'
    OR policyname LIKE 'church_money_%'`)).rows[0].n, 0); checks++;
  // Every function is byte for byte what the repo's files make.
  assert.deepEqual(await md5s(db), hashes, 'the rollback restores the two bodies from their own files'); checks++;

  await run(APPLY);
  assert.deepEqual(await everyone(), withHolders, 'applied again: the kept ticks count again'); checks++;
  // The server (service role) reads everything, as before.
  assert.equal((await service(`SELECT count(*)::int AS n FROM invoices WHERE is_gift`)).rows[0].n, 1); checks++;
}

// ═══ 4. An older file run again only narrows ═══════════════════════════
// Three holders: a Viewer with See and who gave, a Manager with See and the
// bank, a Member with Work, who gave and the bank.
async function withHolders() {
  const built = await build();
  await built.run(APPLY);
  await built.grant(viewer, 'see', true, false);
  await built.grant(manager, 'see', false, true);
  await built.grant(member, 'work', true, true);
  return { ...built, held: await built.everyone() };
}
const narrower = (now, was, label) => {
  for (const who of Object.keys(was)) lessOrSame(now[who], was[who], [label, who]);
  checks++;
};
{
  // The 2026-09-29 block: the guard goes back to its narrow body.
  const { db, run, everyone, held } = await withHolders();
  await run(READINESS_BLOCK);
  const now = await everyone();
  narrower(now, held, 'after the 2026-09-29 block');
  for (const who of ['viewer', 'manager', 'member']) {
    for (const t of MONEY.filter(x => x !== 'business_expenses')) { assert.deepEqual(now[who][t].sees, [], `${who} reads no ${t} until this file is run again`); checks++; }
    assert.ok(!now[who].events.sees.includes('given') && !now[who].events.sees.includes('paid')); checks++;
  }
  assert.ok(!(await db.query(`SELECT prosrc FROM pg_proc WHERE proname = 'ministry_finance_guard'`)).rows[0].prosrc.includes('church_money_tick')); checks++;
  // The 2026-10-27 file then puts the keeper's rule back, and this file the tick.
  await run(GIFT_ROWS);
  narrower(await everyone(), held, 'and then the 2026-10-27 file');
  await run(APPLY);
  assert.deepEqual(await everyone(), held, 'this file once more: every tick back, and nothing else'); checks++;
}
{
  // The 2026-10-27 file: who gave goes back to its narrow body. (This was
  // the hole: with ministry_finance_access widened, a See-only holder read
  // who gave after this re-run. probe B2.)
  const { run, everyone, held } = await withHolders();
  await run(GIFT_ROWS);
  const now = await everyone();
  narrower(now, held, 'after the 2026-10-27 file');
  for (const who of ['viewer', 'manager', 'member']) {
    assert.ok(!now[who].invoices.sees.includes('gift') && !now[who].events.sees.includes('given')
      && !now[who].chief_notifications.sees.includes('gift alert'), `${who} does not see who gave`); checks++;
    assert.deepEqual(now[who].bills.sees, held[who].bills.sees, 'the books are as they were'); checks++;
  }
  await run(APPLY);
  assert.deepEqual(await everyone(), held); checks++;
}
{
  // The 2026-10-27 rollback: the keeper and its functions are gone. Nobody
  // gains; this file and its rollback still run; who gave stays shut for a
  // holder (the gift rows read ministry_finance_access again).
  const { db, run, everyone, held } = await withHolders();
  await run(GIFT_ROWS_BACK);
  let now = await everyone();
  narrower(now, held, 'after the 2026-10-27 rollback');
  for (const who of ['viewer', 'manager', 'member']) {
    assert.ok(!now[who].invoices.sees.includes('gift') && !now[who].events.sees.includes('given')); checks++;
  }
  // No error from a write on a giving row, though ministry_giving_access is gone.
  assert.deepEqual(now.owner.events['delete given'], ['-given']); checks++;
  assert.deepEqual(now.admin.chief_notifications.markAllRead, ['~gift alert', '~other alert', '~paid alert']); checks++;
  assert.deepEqual([now.member.events['delete given'], now.member.events['delete paid']], [[], ['-paid']]); checks++;
  await run(APPLY);
  await run(APPLY);
  now = await everyone();
  narrower(now, held, 'this file run again after that rollback');
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_proc WHERE proname IN ('ministry_giving_access', 'church_giving_open')`)).rows[0].n, 0,
    'it does not bring the keeper functions back'); checks++;
  assert.deepEqual(now.member.bills.church.update, ['~bills-church'], 'the books tick still works'); checks++;
  await run(ROLLBACK);
  await run(ROLLBACK);
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_proc WHERE proname = ANY($1) OR proname = 'ministry_giving_access'`, [NEW_FUNCTIONS])).rows[0].n, 0); checks++;
  for (const who of ['viewer', 'manager', 'member']) {
    assert.deepEqual((await everyone([who]))[who].bills.sees, [], 'rolled back: no holder reads the books'); checks++;
  }
  // And back up again from there: the 2026-10-27 file, then this one.
  await run(GIFT_ROWS);
  await run(APPLY);
  assert.deepEqual(await everyone(), held, 'both files again: exactly the holders as they were'); checks++;
}
{
  // A table that is missing stops the file, and nothing of it stays.
  const { db, run } = await build();
  const guardBefore = (await md5s(db)).ministry_finance_guard;
  await db.exec('ALTER TABLE public.chief_bookkeeping_proposals RENAME TO somewhere_else');
  await assert.rejects(run(APPLY), /chief_bookkeeping_proposals is missing/); checks++;
  const left = (await db.query(`SELECT (SELECT count(*)::int FROM pg_class WHERE relname IN ('church_money_holders', 'church_money_asks')) AS t,
    (SELECT count(*)::int FROM pg_proc WHERE proname = ANY($1)) AS f,
    (SELECT count(*)::int FROM pg_policies WHERE policyname LIKE 'ministry_financial_write_%' OR policyname LIKE 'church_money_%') AS p`,
    [NEW_FUNCTIONS])).rows[0];
  assert.deepEqual(left, { t: 0, f: 0, p: 0 }, 'a stopped file leaves nothing'); checks++;
  assert.equal((await md5s(db)).ministry_finance_guard, guardBefore); checks++;
}

// ═══ 5. Owned by a role that is not a superuser ════════════════════════
for (const ownedBy of ['bypass', 'nobypass']) {
  const { db, run, everything, everyone, grant } = await build({ ownedBy });
  const before = await everyone();
  await run(APPLY);
  await run(APPLY);
  const after = await everyone();
  onlyTheNarrowing(before, after, `owner ${ownedBy}`);
  assert.deepEqual((await db.query(`SELECT DISTINCT pg_get_userbyid(proowner) AS o FROM pg_proc WHERE proname = ANY($1)`, [NEW_FUNCTIONS])).rows,
    [{ o: 'pgowner' }]); checks++;
  await grant(viewer, 'see', true, false);
  await grant(manager, 'see', false, true);
  await grant(member, 'work', true, true);
  const v = await everything(viewer), m = await everything(manager), w = await everything(member);
  assert.ok(v.bills.sees.includes('bills-church') && v.invoices.sees.includes('gift') && v.plaid_accounts.sees.length === 0); checks++;
  assert.ok(m.plaid_accounts.sees.includes('plaid_accounts-church') && !m.invoices.sees.includes('gift')); checks++;
  assert.deepEqual([m.bills.church.update, m.events['delete paid']], [[], []]); checks++;
  assert.deepEqual([w.bills.church.update, w.events['delete given'], w.plaid_transactions.church.update],
    [['~bills-church'], ['-given'], ['~plaid_transactions-church']]); checks++;
  // The three business tables are under RLS and still answer as before.
  assert.deepEqual(await everyone(['owner', 'admin', 'accountant', 'stranger', 'barber', 'shopHand', 'anon', 'nobody']),
    Object.fromEntries(['owner', 'admin', 'accountant', 'stranger', 'barber', 'shopHand', 'anon', 'nobody'].map(k => [k, after[k]]))); checks++;
  // The holders table forced under RLS: the tick reads nothing for an owner
  // that does not bypass it, and everything stays shut rather than erroring.
  await db.exec(`ALTER TABLE public.church_money_holders FORCE ROW LEVEL SECURITY`);
  const forced = await everything(member);
  if (ownedBy === 'nobypass') { assert.deepEqual(forced, after.member, 'forced RLS, no bypass: closed, not an error'); checks++; }
  else { assert.deepEqual(forced, w); checks++; }
  await db.exec(`ALTER TABLE public.church_money_holders NO FORCE ROW LEVEL SECURITY`);
  await run(ROLLBACK);
  await run(ROLLBACK);
  assert.deepEqual(await everyone(), before, `owner ${ownedBy}: rolled back to where it started`); checks++;
}

console.log(`church money holders: ${checks} checks passed`);
