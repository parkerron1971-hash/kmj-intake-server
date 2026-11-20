// The old gift thank-you events move to the giving class, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-20-gift-thankyou-events.sql and its ROLLBACK.
//
//   - A row moves exactly when payment_agent.py's own test says it is a gift's
//     (trigger.startswith(("giving", "donation")), the trigger kept as
//     data->>'trigger_event'): case-sensitive, no trigger is not a gift. The
//     same list of triggers is run through that test here, in JavaScript, and
//     the rows the file moved are exactly the ones it picks.
//   - Every row is kept: same id, business, contact, amount, source and time.
//     Nothing else in events changes, and no other event type moves.
//   - Twice is a no-op. The file's Check before and Check after blocks run as
//     written and count what they say.
//   - The rollback moves back exactly the rows the file marked, never a gift
//     thank-you the code wrote as giving itself, and the file applies again.
//
// People and amounts here are made up.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/gift_thankyou_events_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const read = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const FILE = await read('APPLY-2026-11-20-gift-thankyou-events.sql');
const BACK = await read('ROLLBACK-2026-11-20-gift-thankyou-events.sql');
const AGENT = await readFile(new URL('../payment_agent.py', import.meta.url), 'utf8');
const db = new PGlite();
let checks = 0;
const same = (got, want, why) => { assert.deepEqual(got, want, why); checks++; };

// The code's test, as it stands in payment_agent.py.
const PREFIXES = ['giving', 'donation'];
assert.ok(AGENT.includes('for_gift = trigger.startswith(("giving", "donation"))'), 'the agent still tests this way'); checks++;
assert.ok(AGENT.includes('"data": {"amount": amount, "trigger_event": ev.get("event_type")}'), 'and keeps the trigger here'); checks++;
const isGift = trigger => PREFIXES.some(p => String(trigger ?? '').startsWith(p));

await db.exec(`CREATE TABLE public.events(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, contact_id uuid, event_type text NOT NULL,
  data jsonb, source text, created_at timestamptz NOT NULL DEFAULT now());`);

const church = '11111111-1111-4111-8111-111111111111';
const shop = '22222222-2222-4222-8222-222222222222';
const giver = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
// Every trigger the agent answers (PAYMENT_EVENT_TYPES), and the edges of the test.
const TRIGGERS = ['giving_received', 'donation_received', 'payment_received', 'deposit_paid', 'balance_paid',
  'Giving_received', 'DONATION_received', ' giving_received', 'givin', 'donations', 'giving', 'paymentgiving', '', null];
let n = 0;
for (const biz of [church, shop]) {
  for (const t of TRIGGERS) {
    n++;
    await db.query(`INSERT INTO events(business_id, contact_id, event_type, data, source, created_at)
      VALUES ($1, $2, 'payment_thankyou_created', $3, 'payment_agent', now() - ($4 || ' minutes')::interval)`,
      [biz, giver, JSON.stringify(t === null ? { amount: 25 + n } : { amount: 25 + n, trigger_event: t }), n]);
  }
}
// Rows no test should touch: no data at all, data that isn't an object, the
// prompting events themselves, and a gift thank-you the code wrote since #1940.
await db.query(`INSERT INTO events(business_id, contact_id, event_type, data, source) VALUES
  ($1, $2, 'payment_thankyou_created', NULL, 'payment_agent'),
  ($1, $2, 'payment_thankyou_created', '"giving_received"', 'payment_agent'),
  ($1, $2, 'giving_received', '{"amount": 50, "trigger_event": "giving_received"}', 'stripe'),
  ($1, $2, 'payment_received', '{"amount": 70}', 'stripe'),
  ($1, $2, 'giving_thankyou_created', '{"amount": 40, "trigger_event": "giving_received"}', 'payment_agent')`,
  [church, giver]);

const snap = async () => (await db.query(`SELECT id, business_id, contact_id, event_type, data, source, created_at
  FROM events ORDER BY created_at, id`)).rows;
const before = await snap();
const wanted = before.filter(r => r.event_type === 'payment_thankyou_created'
  && r.data && typeof r.data === 'object' && !Array.isArray(r.data) && isGift(r.data.trigger_event)).map(r => r.id).sort();
same(wanted.length, 8, 'giving_received, donation_received, donations and a bare giving, in each business');

// The file's commented blocks, as written.
const block = (text, from, to) => {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const a = lines.findIndex(l => l.startsWith(from));
  const z = to ? lines.findIndex((l, i) => i > a && l.startsWith(to)) : lines.length;
  assert.ok(a >= 0 && z > a, `${from} is in the file`);
  return lines.slice(a + 1, z).map(l => l.replace(/^-- {0,3}/, '')).filter(l => !l.startsWith('-- ') && l.trim() !== '--')
    .join('\n').split(';').map(s => s.trim()).filter(Boolean);
};
const asked = block(FILE, '-- Check before', 'begin;');
same(asked.length, 4, 'four questions before');
const count = async q => Number(Object.values((await db.query(q)).rows[0])[0]);
const q1 = await count(asked[0]);
same(q1, 8, 'Q1 counts the old gift rows');
const q2 = await count(asked[1]);
same(q2, before.filter(r => r.event_type === 'payment_thankyou_created').length - 8, 'Q2 counts the rest');
same(await count(asked[2]), 1, 'Q3: the one the code wrote since');
const byTrigger = (await db.query(asked[3])).rows;
assert.ok(byTrigger.some(r => r.prompted_by === 'giving_received')); checks++;

await db.exec(FILE);
const once = await snap();
await db.exec(FILE);                                            // twice is a no-op
same(await snap(), once, 'a second run changes nothing');

const moved = once.filter((r, i) => r.event_type !== before[i].event_type || JSON.stringify(r.data) !== JSON.stringify(before[i].data));
same(moved.map(r => r.id).sort(), wanted, 'exactly the rows the code calls a gift moved');
for (const r of moved) {
  const was = before.find(b => b.id === r.id);
  same(r.event_type, 'giving_thankyou_created');
  same(r.data, { ...was.data, retyped_from: 'payment_thankyou_created' }, 'the amount and trigger kept, one mark added');
  same([r.business_id, r.contact_id, r.source, String(r.created_at)],
    [was.business_id, was.contact_id, was.source, String(was.created_at)], 'the row kept');
}
same(once.length, before.length, 'no row added or removed');

const after = block(FILE, '-- Check after', '-- Rollback');
same(after.length, 3, 'three questions after');
same(await count(after[0]), 0, 'no old gift row left');
same(await count(after[1]), q1, 'as many moved as Q1 said');
same(await count(after[2]), q2, 'the payment thank-yous untouched');
same(await count(asked[2]), 1 + q1, 'Q3 + Q1 giving thank-yous now');

// The rollback: exactly the marked rows go back; the code's own giving row stays.
await db.exec(BACK);
same(await snap(), before, 'the rollback puts every row back as it was');
await db.exec(BACK);
same(await snap(), before, 'and twice changes nothing');
const back = block(BACK, '-- Check after');
same(await count(back[0]), 0);
await db.exec(FILE);
same(await snap(), once, 'and the file applies again the same way');

console.log(`gift_thankyou_events_db: ${checks} checks passed`);
