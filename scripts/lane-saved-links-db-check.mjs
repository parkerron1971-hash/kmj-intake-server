// Actual PostgreSQL semantics for saved Lane merchant links, synthetic identities; no remote database.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS; CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE TABLE businesses(id uuid PRIMARY KEY);');
const sql = readFileSync('supabase/APPLY-2026-09-25-lane-saved-links.sql', 'utf8');
await db.exec(sql); await db.exec(sql);
const id = n => '00000000-0000-4000-8000-' + String(n).padStart(12, '0');
const hash = n => n.toString(16).padStart(64, '0');
await db.query('INSERT INTO businesses VALUES($1),($2)', [id(1), id(2)]);
await db.query('INSERT INTO auth.users VALUES($1),($2)', [id(3), id(4)]);
const rpc = async (fn, args) => (await db.query('SELECT ' + fn + '(' + args.map((_, i) => '$' + (i + 1)).join(',') + ') AS v', args)).rows[0].v;
const list = async (b, u) => rpc('lane_link_list', [b, u]);

// Save, then the same page and account refreshes the same row.
assert.equal(await rpc('lane_link_save', [id(1), id(3), id(10), hash(1), 'sealed-1']), id(10));
assert.equal(await rpc('lane_link_save', [id(1), id(3), id(11), hash(1), 'sealed-1b']), id(10));
let rows = await list(id(1), id(3));
assert.equal(rows.length, 1);
assert.equal(rows[0].encrypted_state, 'sealed-1b');
assert.deepEqual(Object.keys(rows[0]).sort(), ['encrypted_state', 'id', 'link_hash', 'updated_at']);

// Another business or user sees nothing and cannot delete.
assert.deepEqual(await list(id(2), id(3)), []);
assert.deepEqual(await list(id(1), id(4)), []);
assert.equal(await rpc('lane_link_delete', [id(2), id(3), id(10)]), false);
assert.equal(await rpc('lane_link_delete', [id(1), id(4), id(10)]), false);

// Twenty per owner; a refresh at the cap still works; other owners are unaffected.
for (let n = 2; n <= 20; n++) assert.equal(await rpc('lane_link_save', [id(1), id(3), id(100 + n), hash(n), 'sealed']), id(100 + n));
assert.equal(await rpc('lane_link_save', [id(1), id(3), id(200), hash(21), 'one-too-many']), null);
assert.equal(await rpc('lane_link_save', [id(1), id(3), id(201), hash(1), 'refresh-at-cap']), id(10));
assert.equal(await rpc('lane_link_save', [id(1), id(4), id(202), hash(21), 'other-user']), id(202));
rows = await list(id(1), id(3));
assert.equal(rows.length, 20);
assert.equal(rows[0].id, id(10));  // Most recently updated first.

// Bad input is refused, not stored.
await assert.rejects(rpc('lane_link_save', [id(1), id(3), id(300), 'not-a-hash', 'x']));
await assert.rejects(rpc('lane_link_save', [id(1), id(3), id(300), hash(40), 'x'.repeat(16385)]));

// Delete, then the freed slot takes a new link.
assert.equal(await rpc('lane_link_delete', [id(1), id(3), id(10)]), true);
assert.equal(await rpc('lane_link_delete', [id(1), id(3), id(10)]), false);
assert.equal(await rpc('lane_link_save', [id(1), id(3), id(203), hash(21), 'fits-now']), id(203));

// Deleting the business or user removes their links.
await db.query('DELETE FROM businesses WHERE id=$1', [id(1)]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM lane_saved_links')).rows[0].n, 0);

for (const role of ['anon', 'authenticated']) {
  const p = (await db.query(`SELECT
    has_table_privilege($1,'public.lane_saved_links','SELECT') AS readable,
    has_table_privilege($1,'public.lane_saved_links','INSERT') AS writable,
    has_function_privilege($1,'public.lane_link_save(uuid,uuid,uuid,text,text)','EXECUTE') AS saves,
    has_function_privilege($1,'public.lane_link_list(uuid,uuid)','EXECUTE') AS lists,
    has_function_privilege($1,'public.lane_link_delete(uuid,uuid,uuid)','EXECUTE') AS deletes`, [role])).rows[0];
  assert.deepEqual(p, { readable: false, writable: false, saves: false, lists: false, deletes: false });
}
await db.exec('SET ROLE service_role');
assert.deepEqual(await list(id(2), id(3)), []);
await db.close();
console.log('Lane saved links: migration rerun, refresh-in-place, owner isolation, 20-link cap, input checks, cascade and service-only access passed.');
