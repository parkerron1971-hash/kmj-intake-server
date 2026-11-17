// The server's columns of public.businesses, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-17-businesses-server-columns.sql over a table shaped
// like production's (all 30 columns, read 2026-11-17), its RLS (an owner may
// do anything to their row, an office admin may update it), the Supabase
// grants it had (ALL to anon and authenticated), and the triggers already on
// it: businesses_guard_sample, businesses_guard_server_settings, the type
// mirror to business_profiles, guard_financial_account_connection and the
// updated_at stamp.
//
// What it holds: before the migration the app's login can comp itself a plan
// and an admin can make itself the owner (the hole, so the test is about the
// real thing); after it, every write the app and the server's user-login
// writers make still lands, every server column is refused to the app's
// logins (the grants), the app can't insert a business, the server and the
// SQL editor are not held, and with the grants widened again the trigger
// refuses the same writes.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/businesses_server_columns_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const db = new PGlite();
const church = '11111111-1111-4111-8111-111111111111', shop = '22222222-2222-4222-8222-222222222222';
const pastor = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', office = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const stranger = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const group = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
let checks = 0;

const OWNER_COLUMNS = ['brand_kit_draft', 'brand_kit_draft_at', 'brand_kit_history', 'cdi_vocabulary', 'name',
  'settings', 'type', 'updated_at', 'voice_profile'];
// A forged value for every column the app's logins may not write.
const FORGED = {
  id: '99999999-9999-4999-8999-999999999999', owner_id: office, created_at: '2020-01-01T00:00:00Z',
  attribution: { utm_source: 'forged' }, comp_tier: 'church_large', tier: 'church_large',
  subscription_status: 'trialing', subscription_plan: 'price_forged', trial_ends_at: '2099-01-01T00:00:00Z',
  current_period_end: '2099-01-01T00:00:00Z', cancel_at_period_end: true, stripe_customer_id: 'cus_forged',
  stripe_subscription_id: 'sub_forged', stripe_account_id: 'acct_forged', in_the_clear: true,
  in_the_clear_at: '2026-11-17T00:00:00Z', is_active: false, entity_group_id: group, use_composer: true,
  is_sample: true, sample_of: shop,
};

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ select nullif(current_setting('app.uid', true), '')::uuid $$;
  GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
  GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated, service_role;
  CREATE TABLE public.businesses(
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid, name text, type text,
    settings jsonb DEFAULT '{}'::jsonb, voice_profile jsonb DEFAULT '{}'::jsonb, cdi_vocabulary text,
    tier text DEFAULT 'starter', is_active boolean DEFAULT true,
    created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
    comp_tier text, stripe_account_id text, stripe_customer_id text, stripe_subscription_id text,
    subscription_status text CHECK (subscription_status IS NULL OR subscription_status IN
      ('trialing', 'active', 'past_due', 'canceled', 'incomplete', 'unpaid', 'paused')),
    subscription_plan text, trial_ends_at timestamptz, current_period_end timestamptz,
    cancel_at_period_end boolean DEFAULT false, entity_group_id uuid,
    in_the_clear boolean DEFAULT false, in_the_clear_at timestamptz,
    brand_kit_history jsonb DEFAULT '[]'::jsonb, brand_kit_draft jsonb, brand_kit_draft_at timestamptz,
    use_composer boolean NOT NULL DEFAULT false, attribution jsonb,
    is_sample boolean NOT NULL DEFAULT false, sample_of uuid);
  CREATE TABLE public.business_users(business_id uuid, user_id uuid, role text, status text DEFAULT 'active');
  CREATE TABLE public.business_profiles(business_id uuid PRIMARY KEY, business_type text, updated_at timestamptz);
  CREATE FUNCTION public.is_business_admin(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    select exists (select 1 from public.business_users bu where bu.business_id = b_id and bu.user_id = auth.uid()
                     and bu.status = 'active' and bu.role = 'admin') $$;
  CREATE FUNCTION public.is_business_member(b_id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    select exists (select 1 from public.business_users bu where bu.business_id = b_id and bu.user_id = auth.uid()
                     and bu.status = 'active') $$;
  ALTER TABLE public.businesses ENABLE ROW LEVEL SECURITY;
  CREATE POLICY owner_full_access ON public.businesses FOR ALL TO authenticated
    USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
  CREATE POLICY businesses_admin_update ON public.businesses FOR UPDATE
    USING (public.is_business_admin(businesses.id)) WITH CHECK (public.is_business_admin(businesses.id));
  CREATE POLICY businesses_member_read ON public.businesses FOR SELECT USING (public.is_business_member(businesses.id));
  ALTER TABLE public.business_profiles ENABLE ROW LEVEL SECURITY;
  CREATE POLICY business_profiles_owner ON public.business_profiles FOR ALL TO authenticated
    USING (business_id IN (select id from public.businesses where owner_id = auth.uid()))
    WITH CHECK (business_id IN (select id from public.businesses where owner_id = auth.uid()));
  CREATE FUNCTION public.businesses_touch() RETURNS trigger LANGUAGE plpgsql AS $$
    begin new.updated_at := now(); return new; end $$;
  CREATE TRIGGER trg_businesses_updated_at BEFORE UPDATE ON public.businesses
    FOR EACH ROW EXECUTE FUNCTION public.businesses_touch();
  GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
  GRANT ALL ON public.businesses, public.business_profiles TO anon, authenticated, service_role;
  GRANT SELECT ON public.business_users TO authenticated, service_role;`);

// The triggers production already has on businesses, from their own files.
for (const file of ['../supabase/APPLY-2026-11-15-sample-church.sql',
                    '../supabase/APPLY-2026-11-17-settings-server-keys.sql',
                    '../supabase/APPLY-2026-09-07-financial-policy.sql',
                    '../__migrations__/2026_06_07_pathc_phase2_sync_triggers.sql']) {
  await db.exec(await readFile(new URL(file, import.meta.url), 'utf8'));
}

const founding = { n: 1, plan: 'church_growing', price_id: 'price_f' };
const ROW = {
  owner_id: pastor, name: 'Grace', type: 'ministry', tier: 'church_growing',
  settings: { theme: 'ledger', founding_church: founding }, voice_profile: { tone: 'warm' },
  subscription_status: 'active', subscription_plan: 'price_f', stripe_customer_id: 'cus_grace',
  stripe_subscription_id: 'sub_grace', current_period_end: '2026-12-16T00:00:00Z',
};
const seed = async () => {
  await db.query('DELETE FROM businesses');
  await db.query(`INSERT INTO businesses(id, owner_id, name, type, tier, settings, voice_profile, subscription_status,
      subscription_plan, stripe_customer_id, stripe_subscription_id, current_period_end)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12), ($13, $14, 'Shop', 'coach', 'starter', '{}', '{}',
      null, null, null, null, null)`,
    [church, ROW.owner_id, ROW.name, ROW.type, ROW.tier, ROW.settings, ROW.voice_profile, ROW.subscription_status,
     ROW.subscription_plan, ROW.stripe_customer_id, ROW.stripe_subscription_id, ROW.current_period_end,
     shop, stranger]);
  await db.query('DELETE FROM business_profiles');
  await db.query(`INSERT INTO business_profiles VALUES ($1, 'ministry', now())`, [church]);
};
await db.query(`INSERT INTO business_users VALUES ($1, $2, 'admin', 'active')`, [church, office]);
await seed();

const row = async id => (await db.query(`SELECT to_jsonb(b) - 'updated_at' AS r FROM businesses b WHERE id = $1`, [id])).rows[0]?.r;
const as = async (role, uid) => {
  await db.exec('RESET ROLE');
  await db.query("select set_config('app.uid', $1, false)", [uid || '']);
  if (role) await db.exec(`SET ROLE ${role}`);
};
// What PostgREST runs for PATCH /businesses?id=eq.<id> with this body: one
// UPDATE naming exactly the body's keys.
const patch = async (id, body) => {
  const keys = Object.keys(body);
  const set = keys.map((k, i) => `"${k}" = $${i + 2}`).join(', ');
  return (await db.query(`UPDATE businesses SET ${set} WHERE id = $1 RETURNING id`, [id, ...keys.map(k => body[k])])).rows;
};
const refuses = async (fn, re) => { await assert.rejects(fn, e => { assert.match(e.message, re); return true; }); checks++; };

// ─── 0. The hole, before the migration ───
await as('authenticated', pastor);
await patch(church, { comp_tier: 'church_large' });
await as('authenticated', office);
await patch(church, { owner_id: office });
await as(null);
let r = await row(church);
assert.equal(r.comp_tier, 'church_large'); checks++;            // the pastor comped the church
assert.equal(r.owner_id, office); checks++;                     // the office login owns it now
await seed();

// ─── 1. The migration, twice ───
const sql = await readFile(new URL('../supabase/APPLY-2026-11-17-businesses-server-columns.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);
checks++;

const privileges = async () => (await db.query(`select a.attname as col,
    has_column_privilege('authenticated', 'public.businesses'::regclass, a.attname, 'UPDATE') as app_update,
    has_column_privilege('authenticated', 'public.businesses'::regclass, a.attname, 'INSERT') as app_insert,
    has_column_privilege('anon', 'public.businesses'::regclass, a.attname, 'UPDATE')
      or has_column_privilege('anon', 'public.businesses'::regclass, a.attname, 'INSERT') as anon_write
  from pg_attribute a where a.attrelid = 'public.businesses'::regclass and a.attnum > 0 and not a.attisdropped
  order by 1`)).rows;
const assertNarrow = async () => {
  const p = await privileges();
  assert.equal(p.length, 30); checks++;
  assert.deepEqual(p.filter(x => x.app_update).map(x => x.col), OWNER_COLUMNS); checks++;
  assert.ok(p.every(x => !x.app_insert && !x.anon_write)); checks++;
};
await assertNarrow();
assert.deepEqual(Object.keys(FORGED).length + OWNER_COLUMNS.length, 30); checks++;
const t = (await db.query(`select has_table_privilege('authenticated', 'public.businesses', 'SELECT') s,
  has_table_privilege('authenticated', 'public.businesses', 'DELETE') d,
  has_table_privilege('service_role', 'public.businesses', 'INSERT') and has_table_privilege('service_role', 'public.businesses', 'UPDATE') w`)).rows[0];
assert.deepEqual(t, { s: true, d: true, w: true }); checks++;

// ─── 2. What the app and the server's user-login writers send still lands ───
await as('authenticated', pastor);
await patch(church, { name: 'Grace Church', type: 'coach' });                 // BusinessIdentityEditor
await patch(church, { voice_profile: { tone: 'plain' } });                    // VoiceToneEditor, AboutMeReview, Chief
await db.query('select public.merge_business_settings($1, $2)', [church, { rooms_visited: { home: 't' } }]);
await patch(church, { settings: { theme: 'glass', rooms_visited: { home: 't' } } });   // the fallback whole write
await patch(church, { settings: { theme: 'glass', rooms_visited: { home: 't' }, brand_kit: { a: 1 } },
  brand_kit_history: [{ kit: {} }], updated_at: new Date().toISOString() });  // brand_engine.save_brand_kit
await patch(church, { brand_kit_draft: { a: 2 }, brand_kit_draft_at: '2026-11-17T01:00:00Z' });
await patch(church, { cdi_vocabulary: 'universal-premium' });
await as(null);
r = await row(church);
assert.equal(r.name, 'Grace Church'); checks++;
assert.equal(r.type, 'coach'); checks++;
assert.deepEqual(r.voice_profile, { tone: 'plain' }); checks++;
assert.deepEqual(r.settings, { theme: 'glass', rooms_visited: { home: 't' }, brand_kit: { a: 1 }, founding_church: founding }); checks++;
assert.deepEqual(r.brand_kit_history, [{ kit: {} }]); checks++;
assert.deepEqual(r.brand_kit_draft, { a: 2 }); checks++;
assert.equal(r.cdi_vocabulary, 'universal-premium'); checks++;
// The type's mirror still runs as the user: the profile followed the business ...
assert.equal((await db.query('select business_type from business_profiles where business_id = $1', [church])).rows[0].business_type, 'coach'); checks++;
// ... and the business follows the profile (sync_profile_type_trigger updates type and updated_at as the user).
await as('authenticated', pastor);
await db.query(`UPDATE business_profiles SET business_type = 'ministry' WHERE business_id = $1`, [church]);
await as(null);
assert.equal((await row(church)).type, 'ministry'); checks++;
// An office admin may change what an admin changes.
await as('authenticated', office);
await patch(church, { name: 'Grace Street' });
await db.query('select public.merge_business_settings($1, $2)', [church, { theme: 'office' }]);
await as(null);
r = await row(church);
assert.equal(r.name, 'Grace Street'); checks++;
assert.equal(r.settings.theme, 'office'); checks++;
// The billing, the Stripe ids and the owner never moved.
for (const k of ['owner_id', 'tier', 'subscription_status', 'subscription_plan', 'stripe_customer_id', 'stripe_subscription_id']) {
  assert.equal(r[k], ROW[k], k); checks++;
}
await seed();

// ─── 3. Every server column is refused to the app's logins, out loud ───
const before = await row(church);
for (const [col, value] of Object.entries(FORGED)) {
  await as('authenticated', pastor);
  await refuses(() => patch(church, { [col]: value }), /permission denied for table businesses/);
  await as('authenticated', office);
  await refuses(() => patch(church, { [col]: value }), /permission denied for table businesses/);
}
await as(null);
assert.deepEqual(await row(church), before); checks++;
// A write that mixes an owner column with a server one lands nothing.
await as('authenticated', pastor);
await refuses(() => patch(church, { name: 'Comped', comp_tier: 'church_large', settings: {} }), /permission denied/);
await as(null);
assert.deepEqual(await row(church), before); checks++;
// The office admin can't take the church: the owner stays the owner.
await as('authenticated', office);
await refuses(() => patch(church, { owner_id: office }), /permission denied/);
await as(null);
assert.equal((await row(church)).owner_id, pastor); checks++;
// A stranger reaches no row with an owner column, and is refused a server one.
await as('authenticated', stranger);
assert.deepEqual(await patch(church, { name: 'Mine' }), []); checks++;
await refuses(() => patch(church, { comp_tier: 'church_large' }), /permission denied/);
// anon writes nothing at all.
await as('anon', '');
await refuses(() => patch(church, { name: 'anon' }), /permission denied/);
// No app login makes a business: not the signup's shape, not a forged one.
await as('authenticated', pastor);
await refuses(() => db.query(`INSERT INTO businesses(owner_id, name, type, settings) VALUES ($1, 'Second', 'therapist', '{}')`, [pastor]),
  /permission denied for table businesses/);
await refuses(() => db.query(`INSERT INTO businesses(owner_id, name, comp_tier) VALUES ($1, 'Comped', 'church_large')`, [pastor]),
  /permission denied/);
await as(null);
assert.equal((await db.query('select count(*)::int n from businesses')).rows[0].n, 2); checks++;
assert.deepEqual(await row(church), before); checks++;

// ─── 4. The server and the SQL editor are not held ───
await as('service_role', '');
// The Stripe webhook (stripe_billing._apply_subscription_state), a comp, Connect, a trial, the foundation badge.
await patch(church, { subscription_status: 'past_due', subscription_plan: 'price_g', tier: 'church_established',
  current_period_end: '2027-01-16T00:00:00Z', cancel_at_period_end: true, stripe_subscription_id: 'sub_new' });
await patch(church, { comp_tier: 'church_small', stripe_account_id: 'acct_grace', trial_ends_at: '2026-12-01T00:00:00Z' });
await patch(church, { in_the_clear: true, in_the_clear_at: '2026-11-17T02:00:00Z', entity_group_id: group,
  use_composer: true, is_active: true });
// POST /access/businesses/create's insert, as the service role.
const made = (await db.query(`INSERT INTO businesses(owner_id, name, type, voice_profile, cdi_vocabulary, settings, tier, attribution)
  VALUES ($1, 'New church', 'ministry', '{}', 'universal-premium', $2, 'starter', $3) RETURNING tier, comp_tier, subscription_status, is_active`,
  [pastor, { practitioner_name: 'P' }, { utm_source: 'x', via: 'app' }])).rows[0];
assert.deepEqual(made, { tier: 'starter', comp_tier: null, subscription_status: null, is_active: true }); checks++;
await as(null);
r = await row(church);
assert.equal(r.subscription_status, 'past_due'); checks++;
assert.equal(r.comp_tier, 'church_small'); checks++;
assert.equal(r.stripe_account_id, 'acct_grace'); checks++;
assert.equal(r.in_the_clear, true); checks++;
assert.equal((await db.query('select count(*)::int n from business_financial_account_locks where stripe_account_id = $1', ['acct_grace'])).rows[0].n, 1); checks++;
await db.query('UPDATE businesses SET owner_id = $2, comp_tier = null WHERE id = $1', [church, office]);   // the SQL editor
assert.equal((await row(church)).owner_id, office); checks++;
await seed();
await db.query(`DELETE FROM businesses WHERE name = 'New church'`);

// ─── 5. With the grants widened again, the trigger refuses the same writes ───
const widened = await row(church);
await db.exec('GRANT INSERT, UPDATE ON public.businesses TO anon, authenticated');
await as('authenticated', pastor);
await refuses(() => patch(church, { comp_tier: 'church_large' }), /Solutionist keeps comp_tier on a business/);
await refuses(() => patch(church, { subscription_status: 'trialing', trial_ends_at: '2099-01-01T00:00:00Z' }),
  /Solutionist keeps subscription_status, trial_ends_at/);
await refuses(() => patch(church, { name: 'Comped', stripe_account_id: 'acct_mine' }), /stripe_account_id/);
for (const [col, value] of Object.entries(FORGED)) {
  if (col === 'is_sample' || col === 'sample_of') continue;      // businesses_guard_sample's: it refuses first
  await refuses(() => patch(church, { [col]: value }), new RegExp(`Solutionist keeps ${col} on a business`));
}
await refuses(() => patch(church, { is_sample: true }), /sample church/i);
await refuses(() => db.query(`INSERT INTO businesses(owner_id, name) VALUES ($1, 'Second')`, [pastor]),
  /A business is made by Solutionist/);
// A server column sent back unchanged passes, and the owner's columns still land.
await patch(church, { name: 'Grace Again', tier: ROW.tier, subscription_status: ROW.subscription_status,
  stripe_customer_id: ROW.stripe_customer_id });
await as('authenticated', office);
await refuses(() => patch(church, { owner_id: office }), /Solutionist keeps owner_id on a business/);
await as('anon', '');
assert.deepEqual(await patch(church, { name: 'anon' }), []); checks++;    // RLS: anon reaches no row
await as(null);
r = await row(church);
assert.equal(r.name, 'Grace Again'); checks++;
assert.deepEqual({ ...r, name: widened.name }, widened); checks++;        // nothing else moved
await as('service_role', '');
await patch(church, { comp_tier: 'church_large' });
await as(null);
assert.equal((await row(church)).comp_tier, 'church_large'); checks++;
// Running the file again narrows the grants back.
await db.exec(sql);
await assertNarrow();

// ─── 6. The guard is the caller's, and fires second ───
const def = (await db.query(`select prosecdef from pg_proc where proname = 'businesses_guard_server_columns'`)).rows;
assert.deepEqual(def, [{ prosecdef: false }]); checks++;
const order = (await db.query(`select tgname from pg_trigger where tgrelid = 'public.businesses'::regclass
  and not tgisinternal and (tgtype & 2) = 2 order by tgname`)).rows.map(x => x.tgname);
assert.deepEqual(order, ['businesses_guard_sample', 'businesses_guard_server_columns',
  'businesses_guard_server_settings', 'trg_businesses_updated_at']); checks++;

console.log(`businesses server columns: ${checks} checks passed`);
