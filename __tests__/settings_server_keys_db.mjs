// The server's keys in businesses.settings, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-17-settings-server-keys.sql over RLS shaped like
// production's businesses policies (owner, and an admin through
// is_business_admin, may UPDATE their row).
//
// What it holds: the app's login writing the whole settings object back from
// a copy read before the founding place was written (the 2026-11-16 loss)
// keeps the place; the app's login can't forge, change or drop a server key,
// and its own keys still land; the server and the SQL editor are not held;
// merge_business_settings writes only the keys it names, for the server and
// (its own keys only) for the app, and refuses a server key out loud.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/settings_server_keys_db.mjs
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
let checks = 0;

await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ select nullif(current_setting('app.uid', true), '')::uuid $$;
  GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
  GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated, service_role;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid, name text,
    settings jsonb DEFAULT '{}'::jsonb, updated_at timestamptz DEFAULT now());
  CREATE TABLE public.business_users(business_id uuid, user_id uuid, role text);
  CREATE FUNCTION public.is_business_admin(b uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    select exists (select 1 from public.businesses x where x.id = b and x.owner_id = auth.uid())
        or exists (select 1 from public.business_users u where u.business_id = b and u.user_id = auth.uid() and u.role = 'admin') $$;
  ALTER TABLE public.businesses ENABLE ROW LEVEL SECURITY;
  CREATE POLICY businesses_owner_read ON public.businesses FOR SELECT USING (owner_id = auth.uid());
  CREATE POLICY businesses_admin_read ON public.businesses FOR SELECT USING (public.is_business_admin(id));
  CREATE POLICY businesses_owner_insert ON public.businesses FOR INSERT WITH CHECK (owner_id = auth.uid());
  CREATE POLICY businesses_admin_update ON public.businesses FOR UPDATE
    USING (public.is_business_admin(id)) WITH CHECK (public.is_business_admin(id));
  GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
  GRANT ALL ON public.businesses TO anon, authenticated, service_role;
  GRANT SELECT ON public.business_users TO authenticated, service_role;`);

const sql = await readFile(new URL('../supabase/APPLY-2026-11-17-settings-server-keys.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);   // safe twice
checks++;

const keys = (await db.query('select public.business_settings_server_keys() as k')).rows[0].k;
assert.equal(keys.length, 44); checks++;
assert.ok(keys.includes('payroll'), 'payroll is the server\'s (PUT /payroll/settings)'); checks++;
for (const k of ['founding_church', 'no_card_trial', 'extra_logins', 'church_move', 'lifecycle_emails',
                 'sample_church', 'churchsavvy_only', 'computer', 'autonomy']) {
  assert.ok(keys.includes(k), k); checks++;
}
for (const k of ['rooms_visited', 'theme', 'brand_kit', 'chief_preferences', 'goals', 'store', 'track']) {
  assert.ok(!keys.includes(k), `${k} is the app's own`); checks++;
}

const founding = { n: 1, at: '2026-11-16T21:40:00Z', plan: 'church_growing', price_id: 'price_f' };
// The first church as it was two hours after its payment, and what the app had loaded before it.
const before = { giving: { enabled: true }, rooms_visited: { 'home': 't0' }, churchsavvy_only: false, track: 'purpose' };
const now = { ...before, founding_church: founding, lifecycle_emails: { welcome_at: 't1' }, extra_logins: 1 };
await db.query('INSERT INTO businesses(id, owner_id, name, settings) VALUES ($1, $2, $3, $4), ($5, $6, $7, $8)',
  [church, pastor, 'Grace', now, shop, stranger, 'Shop', { theme: 'x' }]);
await db.query(`INSERT INTO business_users VALUES ($1, $2, 'admin')`, [church, office]);

const settings = async id => (await db.query('SELECT settings FROM businesses WHERE id = $1', [id])).rows[0].settings;
const as = async (role, uid) => {
  await db.exec('RESET ROLE');
  await db.query("select set_config('app.uid', $1, false)", [uid || '']);
  if (role) await db.exec(`SET ROLE ${role}`);
};
const patch = async (id, s) => (await db.query('UPDATE businesses SET settings = $2 WHERE id = $1 RETURNING settings', [id, s])).rows;
const merge = async (id, set, drop = [], under = []) =>
  (await db.query('select public.merge_business_settings($1, $2, $3, $4) as s', [id, set, drop, under])).rows[0].s;
const refuses = async (fn, re) => { await assert.rejects(fn, e => { assert.match(e.message, re); return true; }); checks++; };

// ─── 1. The 2026-11-16 write: the app sends back the copy it loaded before the payment ───
await as('authenticated', pastor);
await patch(church, { ...before, rooms_visited: { ...before.rooms_visited, 'grow/people': 't2' } });
await as(null);
let s = await settings(church);
assert.deepEqual(s.founding_church, founding); checks++;                  // the place stays
assert.deepEqual(s.lifecycle_emails, { welcome_at: 't1' }); checks++;
assert.equal(s.extra_logins, 1); checks++;
assert.deepEqual(s.rooms_visited, { home: 't0', 'grow/people': 't2' }); checks++;   // the app's own key lands

// ─── 2. The app's login can't forge, change or drop a server key ───
await as('authenticated', pastor);
await patch(church, { ...s, founding_church: { n: 1, plan: 'church_large' }, extra_logins: 40,
  no_card_trial: { started_at: 'x' }, computer: { spend_limit_cents: 999999 }, churchsavvy_only: true });
await as(null);
let t = await settings(church);
assert.deepEqual(t.founding_church, founding); checks++;
assert.equal(t.extra_logins, 1); checks++;
assert.ok(!('no_card_trial' in t) && !('computer' in t)); checks++;      // never set stays never set
assert.equal(t.churchsavvy_only, false); checks++;

await as('authenticated', pastor);
const dropped = { ...t };
for (const k of ['founding_church', 'churchsavvy_only', 'giving', 'extra_logins']) delete dropped[k];
await patch(church, { ...dropped, theme: 'ledger' });
await as(null);
t = await settings(church);
assert.deepEqual(t.founding_church, founding); checks++;
assert.equal(t.churchsavvy_only, false); checks++;                      // dropped, kept: nothing opens
assert.deepEqual(t.giving, { enabled: true }); checks++;
assert.equal(t.theme, 'ledger'); checks++;

// A null or a non-object from the app keeps the server's keys and nothing else.
await as('authenticated', pastor);
await patch(church, null);
await as(null);
t = await settings(church);
assert.deepEqual(Object.keys(t).sort(), ['churchsavvy_only', 'extra_logins', 'founding_church', 'giving', 'lifecycle_emails']); checks++;
await db.query('UPDATE businesses SET settings = $2 WHERE id = $1', [church, now]);

// An admin (an office login) is held the same way; a stranger reaches no row.
await as('authenticated', office);
await patch(church, { rooms_visited: { office: 't3' }, founding_church: null });
await as(null);
t = await settings(church);
assert.deepEqual(t.founding_church, founding); checks++;
assert.deepEqual(t.rooms_visited, { office: 't3' }); checks++;
await as('authenticated', stranger);
assert.deepEqual(await patch(church, { founding_church: founding }), []); checks++;
await as('anon', '');
assert.deepEqual(await patch(church, {}), []); checks++;
await as(null);
await db.query('UPDATE businesses SET settings = $2 WHERE id = $1', [church, now]);

// Another column alone never reaches the guard.
await as('authenticated', pastor);
await db.query('UPDATE businesses SET name = $2 WHERE id = $1', [church, 'Grace Church']);
await as(null);
assert.deepEqual(await settings(church), now); checks++;

// ─── 3. The server and the SQL editor are not held ───
await as('service_role', '');
await patch(church, { ...now, founding_church: { ...founding, n: 2 }, no_card_trial: { started_at: 's' } });
await as(null);
t = await settings(church);
assert.equal(t.founding_church.n, 2); checks++;
assert.deepEqual(t.no_card_trial, { started_at: 's' }); checks++;
await db.query('UPDATE businesses SET settings = $2 WHERE id = $1', [church, now]);   // the editor (postgres)
assert.deepEqual(await settings(church), now); checks++;

// ─── 4. A business the app makes is born without server keys, but for the birth keys ───
await as('authenticated', pastor);
const born = (await db.query(`INSERT INTO businesses(owner_id, name, settings) VALUES ($1, 'New', $2) RETURNING settings`,
  [pastor, { practitioner_name: 'P', churchsavvy_only: true, founding_church: founding, extra_logins: 9, autonomy: { client_facing_autonomy: 'enabled' } }])).rows[0].settings;
assert.deepEqual(born, { practitioner_name: 'P', churchsavvy_only: true }); checks++;
await as('service_role', '');
const made = (await db.query(`INSERT INTO businesses(owner_id, name, settings) VALUES ($1, 'Made', $2) RETURNING settings`,
  [pastor, { no_card_trial: { started_at: 's' } }])).rows[0].settings;
assert.deepEqual(made, { no_card_trial: { started_at: 's' } }); checks++;
await as(null);

// ─── 5. merge_business_settings ───
// The server: one key in, the rest as they are, even keys it never read.
await as('service_role', '');
s = await merge(church, { church_move: { state: 'requested' } });
assert.deepEqual(s, { ...now, church_move: { state: 'requested' } }); checks++;
s = await merge(church, {}, ['church_move', 'not_there']);
assert.deepEqual(s, now); checks++;
s = await merge(church, { sample_follow_up_at: 't9' }, [], ['lifecycle_emails']);
assert.deepEqual(s.lifecycle_emails, { welcome_at: 't1', sample_follow_up_at: 't9' }); checks++;
s = await merge(church, { phone_verified_at: 'p' }, [], ['no_card_trial']);     // made when missing
assert.deepEqual(s.no_card_trial, { phone_verified_at: 'p' }); checks++;
s = await merge(church, { a: 1 }, [], ['track']);                               // a non-object becomes one
assert.deepEqual(s.track, { a: 1 }); checks++;
assert.equal(await merge('99999999-9999-4999-8999-999999999999', { x: 1 }), null); checks++;
await refuses(() => merge(church, [1, 2]), /p_set must be a JSON object/);
await as(null);
await db.query('UPDATE businesses SET settings = $2 WHERE id = $1', [church, now]);

// Two writers a moment apart: the server's key and the app's key both stay,
// whichever order they land in, because neither sends the other's key.
await as('service_role', '');
await merge(church, { church_move: { state: 'paid' } });
await as('authenticated', pastor);
s = await merge(church, { rooms_visited: { ...now.rooms_visited, 'money/giving': 't4' } });
assert.deepEqual(s.church_move, { state: 'paid' }); checks++;
assert.deepEqual(s.founding_church, founding); checks++;
assert.equal(s.rooms_visited['money/giving'], 't4'); checks++;
s = await merge(church, {}, ['rooms_visited']);
assert.ok(!('rooms_visited' in s) && s.church_move.state === 'paid'); checks++;

// The app may not name a server key, in any of the three places.
await refuses(() => merge(church, { founding_church: founding }), /kept by Solutionist/);
await refuses(() => merge(church, {}, ['churchsavvy_only']), /kept by Solutionist/);
await refuses(() => merge(church, { n: 1 }, [], ['founding_church']), /kept by Solutionist/);
// Its own nested key is fine.
s = await merge(church, { presence: { look: 'a' } }, [], ['chief_preferences']);
assert.deepEqual(s.chief_preferences, { presence: { look: 'a' } }); checks++;
// RLS still decides whose row: an office admin may, a stranger reaches nothing.
await as('authenticated', office);
assert.equal((await merge(church, { theme: 'office' })).theme, 'office'); checks++;
await as('authenticated', stranger);
assert.equal(await merge(church, { theme: 'stranger' }), null); checks++;
await as(null);
assert.equal((await settings(church)).theme, 'office'); checks++;
// anon can't run it at all.
await as('anon', '');
await refuses(() => merge(church, { theme: 'anon' }), /permission denied/);
await as(null);

// ─── 6. The pure merge ───
const at = async (doc, under, set, drop) =>
  (await db.query('select public.business_settings_merge_at($1, $2, $3, $4) as d', [doc, under, set, drop])).rows[0].d;
assert.deepEqual(await at({ a: 1, b: { x: 1, y: 1 } }, ['b'], { z: 2 }, ['x']), { a: 1, b: { y: 1, z: 2 } }); checks++;
assert.deepEqual(await at(null, [], { a: 1 }, []), { a: 1 }); checks++;
assert.deepEqual(await at({ a: { b: 'no' } }, ['a', 'b'], { c: 1 }, []), { a: { b: { c: 1 } } }); checks++;
assert.deepEqual(await at({ a: 1, b: 2 }, [], {}, ['a']), { b: 2 }); checks++;

// None of the five functions is SECURITY DEFINER: current_user is the caller.
const defs = (await db.query(`select proname, prosecdef from pg_proc where proname in
  ('merge_business_settings', 'business_settings_merge_at', 'businesses_guard_server_settings',
   'business_settings_server_keys', 'business_settings_birth_keys') order by 1`)).rows;
assert.equal(defs.length, 5); checks++;
assert.ok(defs.every(r => r.prosecdef === false)); checks++;

console.log(`settings server keys: ${checks} checks passed`);
