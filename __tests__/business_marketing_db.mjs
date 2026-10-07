// The marketing suite's storage (supabase/APPLY-2026-10-07-marketing-suite.sql)
// on a real Postgres (PGlite): replay, approval, claims, pause, expiry, links,
// and who can read what.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/business_marketing_db.mjs
// (CI installs PGlite into $RUNNER_TEMP and sets PGLITE_MODULE; locally the
// fallback is output/marketing-qa, like the other marketing checks.)
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const db = new PGlite();

// What Supabase already has: the roles, auth.uid() from the JWT, businesses
// with its owner + member policies, and the SECURITY DEFINER member helper
// (copied from __migrations__/2026_06_10_hotfix_rls_recursion.sql).
await db.exec(`
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
CREATE TABLE public.businesses (id uuid PRIMARY KEY, owner_id uuid, name text);
CREATE TABLE public.business_users (business_id uuid REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id uuid, status text, role text);
CREATE OR REPLACE FUNCTION public.is_business_member(b_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.business_users bu
                 WHERE bu.business_id = b_id AND bu.user_id = auth.uid() AND bu.status = 'active');
$$;
REVOKE ALL ON FUNCTION public.is_business_member(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_business_member(uuid) TO authenticated;
ALTER TABLE public.businesses ENABLE ROW LEVEL SECURITY;
CREATE POLICY businesses_owner_all ON public.businesses FOR ALL USING (owner_id = auth.uid());
CREATE POLICY businesses_member_read ON public.businesses FOR SELECT USING (public.is_business_member(businesses.id));
GRANT SELECT ON public.businesses TO authenticated;
GRANT ALL ON public.businesses, public.business_users TO service_role;
ALTER TABLE public.business_users ENABLE ROW LEVEL SECURITY;
CREATE POLICY business_users_self ON public.business_users FOR SELECT USING (user_id = auth.uid());
`);

const sql = await readFile(new URL('../supabase/APPLY-2026-10-07-marketing-suite.sql', import.meta.url), 'utf8');
assert.match(sql.trimEnd(), /NOTIFY pgrst, 'reload schema';$/, 'the migration ends by reloading the API schema');
assert.doesNotMatch(sql.replace(/--.*$/gm, ''), /using\s*\(\s*true\s*\)/i, 'no USING (true) anywhere');
await db.exec(sql);
await db.exec(sql); // replay-safe

const ids = (prefix, n) => `${prefix}0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const A = ids('a', 1), B = ids('b', 1), C = ids('c', 1);            // businesses
const ownerA = ids('1', 1), ownerB = ids('1', 2), memberA = ids('1', 3), stranger = ids('1', 4), exMember = ids('1', 5);
const H = (c) => c.repeat(64);                                        // a valid content hash
const one = async (q, p = []) => (await db.query(q, p)).rows[0];
const count = async (q, p = []) => (await one(`SELECT count(*)::int AS n FROM (${q}) q`, p)).n;
const status = async (id) => (await one('SELECT status FROM marketing_posts WHERE id=$1', [id])).status;

await db.query(`INSERT INTO businesses(id, owner_id, name) VALUES ($1,$2,'A'),($3,$4,'B'),($5,$4,'C')`, [A, ownerA, B, ownerB, C]);
await db.query(`INSERT INTO business_users VALUES ($1,$2,'active','viewer'),($1,$3,'removed','viewer')`, [A, memberA, exMember]);

// Every table, every policy: RLS on, SELECT only, nothing permissive.
for (const t of ['marketing_desks', 'marketing_runs', 'marketing_posts', 'marketing_link_clicks', 'marketing_post_events']) {
  assert.equal((await one(`SELECT relrowsecurity FROM pg_class WHERE relname=$1`, [t])).relrowsecurity, true, t);
}
const policies = (await db.query(`SELECT tablename, policyname, cmd, qual FROM pg_policies
  WHERE tablename IN ('marketing_desks','marketing_runs','marketing_posts','marketing_link_clicks','marketing_post_events')`)).rows;
assert.equal(policies.length, 6, 'owner + member read on desks, runs and posts; nothing on clicks or events');
assert.ok(policies.every((p) => p.cmd === 'SELECT' && p.qual && p.qual.trim() !== 'true'), JSON.stringify(policies));

// The service role does all the writing from here on.
await db.exec('SET ROLE service_role');

// ── constraints ─────────────────────────────────────────────────────
await db.query(`INSERT INTO marketing_desks(business_id) VALUES ($1),($2)`, [A, B]);      // C has no desk
await assert.rejects(db.query(`UPDATE marketing_desks SET post_hour=5 WHERE business_id=$1`, [A]));
await assert.rejects(db.query(`UPDATE marketing_desks SET post_hour=22 WHERE business_id=$1`, [A]));
await db.query(`UPDATE marketing_desks SET post_hour=21 WHERE business_id=$1`, [A]);

let n = 0;
const post = async (biz, over = {}) => {
  const id = over.id || ids('d', ++n);
  const row = { business_id: biz, source: 'plan', content_hash: H('a'), run_offset: '1 hour', expires_offset: '7 hours', ...over };
  await db.query(`INSERT INTO marketing_posts(id, business_id, source, caption, publish_text, content_hash,
      run_at, expires_at, link_code, tracked_url, design_status, run_id, targets)
    VALUES ($1,$2,$3,'caption','caption https://x/go/c',$4, now()+$5::interval, now()+$6::interval,$7,$8,$9,$10,$11)`,
    [id, row.business_id, row.source, row.content_hash, row.run_offset, row.expires_offset, row.link_code || null,
     row.tracked_url || null, row.design_status || 'none', row.run_id || null, JSON.stringify(row.targets || [])]);
  return id;
};
await assert.rejects(post(A, { source: 'buffer' }), 'unknown source');
await assert.rejects(post(A, { content_hash: 'not-a-hash' }), 'content hash must be a digest');
await assert.rejects(post(A, { expires_offset: '1 hour' }), 'expires_at must be after run_at');
await assert.rejects(post(A, { design_status: 'thinking' }), 'unknown design status');
await assert.rejects(post(A, { targets: {} }), 'targets is a list');
const linked = await post(A, { link_code: 'abcdefgh' });
await assert.rejects(post(B, { link_code: 'abcdefgh' }), 'a link code names one post');
await assert.rejects(db.query(`UPDATE marketing_posts SET status='posted' WHERE id=$1`, [linked]), 'unknown status');
await db.query(`DELETE FROM marketing_posts WHERE id=$1`, [linked]);

// ── marketing_claim_run: keyed by business ──────────────────────────
const week = '2026-10-08', runA = ids('e', 1), runB = ids('e', 2);
const claimRun = (run, biz, source, replan = false, kind = 'week') =>
  one('SELECT marketing_claim_run($1,$2,$3,$4,$5,$6) AS ok', [run, biz, week, kind, source, replan]).then((r) => r.ok);
assert.equal(await claimRun(runA, A, 'scheduled'), true, 'first claim wins');
assert.equal(await claimRun(runA, A, 'scheduled'), false, 'not twice while running');
assert.equal(await claimRun(runB, B, 'scheduled'), true, 'another business plans the same week');
assert.equal(await claimRun(ids('e', 9), A, 'manual'), false, 'a different run id never takes the week');
await assert.rejects(claimRun(ids('e', 8), A, 'robot'), 'unknown source');
await assert.rejects(claimRun(ids('e', 8), A, 'manual', false, 'blast'), 'unknown kind');
await db.query(`UPDATE marketing_runs SET status='failed' WHERE id=$1`, [runA]);
assert.equal(await claimRun(runA, A, 'scheduled'), true);          // attempt 2
await db.query(`UPDATE marketing_runs SET status='failed' WHERE id=$1`, [runA]);
assert.equal(await claimRun(runA, A, 'scheduled'), true);          // attempt 3
await db.query(`UPDATE marketing_runs SET status='failed' WHERE id=$1`, [runA]);
assert.equal(await claimRun(runA, A, 'scheduled'), false, 'the scheduler stops after three attempts');
assert.equal(await claimRun(runA, A, 'manual'), true, 'the owner always may');
await db.query(`UPDATE marketing_runs SET created_at=now()-interval '20 minutes' WHERE id=$1`, [runA]);
assert.equal(await claimRun(runA, A, 'scheduled'), true, 'a run stuck running is reclaimable');
await db.query(`UPDATE marketing_runs SET status='succeeded' WHERE id=$1`, [runA]);
const weekDraft = await post(A, { run_id: runA });
assert.equal(await claimRun(runA, A, 'manual'), false, 'a succeeded week is closed');
assert.equal(await claimRun(runA, A, 'scheduled', true), false, 'only the owner replans');
assert.equal(await claimRun(runA, A, 'manual', true), true, 'the owner starts the week over');
assert.equal(await status(weekDraft), 'cancelled');
assert.equal((await one('SELECT revision FROM marketing_posts WHERE id=$1', [weekDraft])).revision, 2);
await assert.rejects(post(A, { run_id: runB }), "a post cannot sit under another business's run");

// ── marketing_approve: all or nothing, one business ─────────────────
const actor = ownerA;
const a1 = await post(A, { content_hash: H('1') }), a2 = await post(A, { content_hash: H('2') });
const b1 = await post(B, { content_hash: H('3') });
const item = (id, hash, revision = 1) => ({ id, revision, content_hash: hash });
const approve = (biz, items, via = 'owner', who = actor) =>
  one('SELECT marketing_approve($1,$2,$3,$4) AS n', [biz, JSON.stringify(items), who, via]).then((r) => r.n);
const drafts = async () => (await db.query(`SELECT status FROM marketing_posts WHERE id IN ($1,$2,$3)`, [a1, a2, b1])).rows.every((r) => r.status === 'draft');

await assert.rejects(approve(A, [item(a1, H('1')), item(a2, H('2'), 2)]), 'a stale revision refuses the batch');
await assert.rejects(approve(A, [item(a1, H('1')), item(a2, H('9'))]), 'a changed post refuses the batch');
await assert.rejects(approve(A, [item(a1, H('1')), { id: a2, content_hash: H('2') }]), 'a missing revision refuses the batch');
await assert.rejects(approve(A, [item(a1, H('1')), item(b1, H('3'))]), "another business's post refuses the batch");
await assert.rejects(approve(B, [item(a1, H('1'))]), "a business cannot approve another's post");
await assert.rejects(approve(A, []), 'at least one');
await assert.rejects(approve(A, Array.from({ length: 51 }, () => item(a1, H('1')))), 'at most fifty');
await assert.rejects(approve(A, [item(a1, H('1'))], 'chief'), 'Chief is not a kind of approval');
await assert.rejects(approve(A, [item(a1, H('1'))], 'owner', null), 'someone approved it');
assert.ok(await drafts(), 'nothing was approved by a refused batch');
await db.query(`UPDATE marketing_posts SET design_status='designing' WHERE id=$1`, [a2]);
await assert.rejects(approve(A, [item(a1, H('1')), item(a2, H('2'))]), /flyer is still being made/, 'not while its flyer is being made');
await db.query(`UPDATE marketing_posts SET design_status='ready' WHERE id=$1`, [a2]);   // revision stays 1 in this test
const past = await post(A, { content_hash: H('4'), run_offset: '-1 minute', expires_offset: '1 hour' });
await assert.rejects(approve(A, [item(a1, H('1')), item(past, H('4'))]), 'a time that has passed refuses the batch');
assert.ok(await drafts());
assert.equal(await approve(A, [item(a2, H('2')), item(a1, H('1'))]), 2);
const approvedRow = await one('SELECT * FROM marketing_posts WHERE id=$1', [a1]);
assert.equal(approvedRow.status, 'approved');
assert.equal(approvedRow.approved_hash, H('1'));
assert.equal(approvedRow.approved_by, actor);
assert.equal(approvedRow.approved_via, 'owner');
assert.ok(approvedRow.approved_at);
await assert.rejects(approve(A, [item(a1, H('1'))]), 'not twice');
assert.equal(await approve(B, [item(b1, H('3'))], 'standing', ownerB), 1);
assert.equal((await one('SELECT approved_via FROM marketing_posts WHERE id=$1', [b1])).approved_via, 'standing');

// ── marketing_claim_due: concurrent claims, edits, desks ────────────
await db.query(`UPDATE marketing_posts SET run_at=now()-interval '1 minute' WHERE id IN ($1,$2,$3)`, [a1, a2, b1]);
const edited = await post(A, { content_hash: H('5') });
await approve(A, [item(edited, H('5'))]);
await db.query(`UPDATE marketing_posts SET run_at=now()-interval '1 minute', content_hash=$2 WHERE id=$1`, [edited, H('6')]);
const deskless = await post(C, { content_hash: H('7') });
await approve(C, [item(deskless, H('7'))], 'owner', ownerB);
await db.query(`UPDATE marketing_posts SET run_at=now()-interval '1 minute' WHERE id=$1`, [deskless]);
await assert.rejects(db.query('SELECT * FROM marketing_claim_due(0)'));
await assert.rejects(db.query('SELECT * FROM marketing_claim_due(101)'));
const claims = await Promise.all([1, 2, 3].map(() => db.query('SELECT * FROM marketing_claim_due(1)')));
const claimed = claims.flatMap((r) => r.rows);
assert.equal(claimed.length, 3, 'three due posts, three claims');
assert.equal(new Set(claimed.map((r) => r.id)).size, 3, 'no post is claimed twice');
assert.deepEqual(new Set(claimed.map((r) => r.id)), new Set([a1, a2, b1]));
assert.ok(claimed.every((r) => r.status === 'dispatching' && r.claimed_at));
assert.equal((await db.query('SELECT * FROM marketing_claim_due(10)')).rows.length, 0, 'nothing left to claim');
assert.equal(await status(edited), 'approved', 'a post edited after approval is never claimed');
assert.equal(await status(deskless), 'approved', 'a post without a desk is never claimed');

// Stale dispatching -> uncertain (never resent automatically).
await db.query(`UPDATE marketing_posts SET claimed_at=now()-interval '15 minutes' WHERE id=$1`, [a1]);
await db.query(`UPDATE marketing_posts SET claimed_at=now()-interval '5 minutes' WHERE id=$1`, [a2]);
await db.query('SELECT * FROM marketing_claim_due(10)');
assert.equal(await status(a1), 'uncertain');
assert.match((await one('SELECT error FROM marketing_posts WHERE id=$1', [a1])).error, /interrupted/);
assert.equal(await status(a2), 'dispatching', 'a send still within its window is left alone');

// Expiry -> failed.
await db.query(`UPDATE marketing_posts SET run_at=now()-interval '2 hours', expires_at=now()-interval '1 minute' WHERE id=$1`, [edited]);
await db.query('SELECT * FROM marketing_claim_due(10)');
assert.equal(await status(edited), 'failed');

// Pause vs claim: a paused desk hands nothing over; the other desk still does;
// the sweeps still apply to the paused one; unpausing releases it.
const pa = await post(A, { content_hash: H('8') }), pb = await post(B, { content_hash: H('9') });
const pbExpired = await post(B, { content_hash: H('b') });
await approve(A, [item(pa, H('8'))]);
await approve(B, [item(pb, H('9')), item(pbExpired, H('b'))], 'owner', ownerB);
await db.query(`UPDATE marketing_posts SET run_at=now()-interval '1 minute' WHERE id IN ($1,$2)`, [pa, pb]);
await db.query(`UPDATE marketing_posts SET run_at=now()-interval '2 hours', expires_at=now()-interval '1 minute' WHERE id=$1`, [pbExpired]);
await db.query(`UPDATE marketing_desks SET paused=true WHERE business_id=$1`, [B]);
const whilePaused = (await db.query('SELECT * FROM marketing_claim_due(10)')).rows.map((r) => r.id);
assert.deepEqual(whilePaused, [pa], 'only the unpaused desk is claimed');
assert.equal(await status(pb), 'approved');
assert.equal(await status(pbExpired), 'failed', 'expiry still applies to a paused desk');
await db.query(`UPDATE marketing_desks SET paused=false WHERE business_id=$1`, [B]);
assert.deepEqual((await db.query('SELECT * FROM marketing_claim_due(10)')).rows.map((r) => r.id), [pb]);
// The claim share-locks the desk row and skips a locked one, so a pause that
// is mid-update makes the claim pass that desk by rather than race it.
const claimDef = (await one(`SELECT pg_get_functiondef('public.marketing_claim_due(integer)'::regprocedure) AS d`)).d;
assert.match(claimDef, /FOR UPDATE OF p SKIP LOCKED\s+FOR SHARE OF d SKIP LOCKED/);

// ── marketing_follow: counts only sent posts ────────────────────────
const follow = (code, countClick = true) => db.query('SELECT * FROM marketing_follow($1,$2)', [code, countClick]).then((r) => r.rows);
const linkPost = async (code, st) => {
  const id = await post(B, { content_hash: H('c'), link_code: code, tracked_url: `https://b.example/?utm_content=${code}` });
  await db.query(`UPDATE marketing_posts SET status=$2 WHERE id=$1`, [id, st]);
  return id;
};
const sent = { submitted: await linkPost('subm2tdd', 'submitted'), published: await linkPost('publ2shd', 'published'),
  partly_published: await linkPost('part2yyy', 'partly_published') };
const unsent = { draft: await linkPost('draft222', 'draft'), approved: await linkPost('appr2ved', 'approved'),
  failed: await linkPost('fail2ddd', 'failed'), cancelled: await linkPost('canc2lld', 'cancelled'), pulled: await linkPost('pull2ddd', 'pulled') };
const codes = { submitted: 'subm2tdd', published: 'publ2shd', partly_published: 'part2yyy', draft: 'draft222',
  approved: 'appr2ved', failed: 'fail2ddd', cancelled: 'canc2lld', pulled: 'pull2ddd' };
for (const st of Object.keys(codes)) {
  const rows = await follow(codes[st]);
  assert.deepEqual(rows, [{ business_id: B, tracked_url: `https://b.example/?utm_content=${codes[st]}` }], st);
}
await follow(codes.published); await follow(codes.published, false);
assert.deepEqual(await follow('nosuch22'), [], 'an unknown code resolves to nothing');
const clicks = Object.fromEntries((await db.query('SELECT post_id, business_id, clicks FROM marketing_link_clicks')).rows.map((r) => [r.post_id, r]));
assert.equal(clicks[sent.submitted].clicks, 1);
assert.equal(clicks[sent.published].clicks, 2, 'count_click=false is not a click');
assert.equal(clicks[sent.partly_published].clicks, 1);
for (const id of Object.values(unsent)) assert.equal(clicks[id], undefined, 'a post that never went out has no clicks');
assert.ok(Object.values(clicks).every((c) => c.business_id === B));

// ── the audit trail ─────────────────────────────────────────────────
assert.ok(await count('SELECT 1 FROM marketing_post_events WHERE post_id=$1', [a1]) >= 4, 'insert, approve, claim, uncertain');
assert.equal(await count(`SELECT 1 FROM marketing_post_events e JOIN marketing_posts p ON p.id=e.post_id WHERE e.business_id <> p.business_id`), 0);
const before = (await one('SELECT updated_at FROM marketing_desks WHERE business_id=$1', [A])).updated_at;
await db.query(`UPDATE marketing_desks SET audience='parents nearby' WHERE business_id=$1`, [A]);
assert.ok((await one('SELECT updated_at FROM marketing_desks WHERE business_id=$1', [A])).updated_at >= before);

// ── who can read what ───────────────────────────────────────────────
await db.exec('RESET ROLE');
const as = async (role, uid, fn) => {
  await db.exec(`SET ROLE ${role}`);
  await db.query(`SELECT set_config('request.jwt.claim.sub', $1, false)`, [uid || '']);
  try { return await fn(); } finally { await db.exec('RESET ROLE'); }
};
const seen = (table) => db.query(`SELECT DISTINCT business_id FROM ${table} ORDER BY 1`).then((r) => r.rows.map((x) => x.business_id));
for (const table of ['marketing_desks', 'marketing_runs', 'marketing_posts']) {
  assert.deepEqual(await as('authenticated', ownerA, () => seen(table)), [A], `${table}: the owner of A sees A`);
  assert.deepEqual(await as('authenticated', memberA, () => seen(table)), [A], `${table}: a member of A sees A`);
  assert.deepEqual(await as('authenticated', exMember, () => seen(table)), [], `${table}: a removed member sees nothing`);
  assert.deepEqual(await as('authenticated', stranger, () => seen(table)), [], `${table}: a stranger sees nothing`);
  assert.deepEqual((await as('authenticated', ownerB, () => seen(table))).filter((b) => b === A), [], `${table}: B's owner never sees A`);
  await assert.rejects(as('anon', null, () => seen(table)), `${table}: anon cannot read`);
}
for (const table of ['marketing_link_clicks', 'marketing_post_events']) {
  await assert.rejects(as('authenticated', ownerB, () => seen(table)), `${table}: service role only`);
  await assert.rejects(as('anon', null, () => seen(table)), `${table}: service role only`);
}
await assert.rejects(as('authenticated', ownerA, () => db.query(`UPDATE marketing_posts SET status='approved' WHERE business_id=$1`, [A])), 'no browser writes');
await assert.rejects(as('authenticated', ownerA, () => db.query(`INSERT INTO marketing_desks(business_id) VALUES ($1)`, [C])), 'no browser writes');
await assert.rejects(as('authenticated', ownerA, () => db.query(`DELETE FROM marketing_posts WHERE business_id=$1`, [A])), 'no browser writes');
for (const call of ['SELECT * FROM marketing_claim_due(1)', `SELECT * FROM marketing_follow('subm2tdd', true)`,
  `SELECT marketing_approve('${A}', '[]'::jsonb, '${ownerA}', 'owner')`,
  `SELECT marketing_claim_run('${ids('e', 7)}', '${A}', '2026-10-15', 'week', 'manual', false)`]) {
  await assert.rejects(as('authenticated', ownerA, () => db.query(call)), `authenticated cannot run: ${call}`);
  await assert.rejects(as('anon', null, () => db.query(call)), `anon cannot run: ${call}`);
}

// ── deleting a business takes its marketing with it ────────────────
await db.exec('SET ROLE service_role');
await db.query('DELETE FROM businesses WHERE id=$1', [B]);
for (const t of ['marketing_desks', 'marketing_runs', 'marketing_posts', 'marketing_link_clicks', 'marketing_post_events']) {
  assert.equal(await count(`SELECT 1 FROM ${t} WHERE business_id=$1`, [B]), 0, t);
}
assert.ok(await count('SELECT 1 FROM marketing_posts WHERE business_id=$1', [A]) > 0, "A's posts are untouched");
await db.exec('RESET ROLE');

console.log('Marketing suite database checks passed: replay-safe migration, constraints, weekly claims by business, '
  + 'all-or-nothing approval, cross-business refusal, unique concurrent claims, stale and expired posts, pause, '
  + 'sent-only clicks, audit trail, owner/member reads, browser denial and business deletion.');
await db.close();
