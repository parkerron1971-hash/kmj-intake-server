// A member's Bible highlights, notes and saved verses on a real Postgres
// (PGlite): supabase/APPLY-2026-10-19-bible-marks.sql. Rows go through every
// check the table has:
//   bible_marks  one row per member per verse; member_bible_marks.save's upsert
//                merges into it; a made-up book, chapter 0, verse 177, an unknown
//                colour or a note past 2,000 characters is refused; a member's
//                rows go with them; the browser's roles can't read any of it
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/bible_marks_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const jas = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', sam = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$2,$5)', [jas, b1, 'Jasmine', sam, 'Sam']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-19-bible-marks.sql'));
await db.exec(await sql('APPLY-2026-10-19-bible-marks.sql'));   // idempotent

// member_bible_marks.save: PostgREST's merge-duplicates upsert on the key.
const upsert = `INSERT INTO bible_marks(business_id, contact_id, book, chapter, verse, colour, note, bookmarked, updated_at)
  VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now())
  ON CONFLICT (business_id, contact_id, book, chapter, verse) DO UPDATE SET colour = excluded.colour,
    note = excluded.note, bookmarked = excluded.bookmarked, updated_at = excluded.updated_at RETURNING *`;
let row = (await db.query(upsert, [b1, jas, 'PRO', 4, 23, 'gold', null, false])).rows[0];
assert.equal(row.colour, 'gold'); checks++;
row = (await db.query(upsert, [b1, jas, 'PRO', 4, 23, 'gold', 'Guard what I let in first', false])).rows[0];
assert.equal(row.note, 'Guard what I let in first'); checks++;
await db.query(upsert, [b1, jas, '1CO', 13, 4, null, null, true]);               // a bookmark alone, a numbered book
// PGlite's now() ticks in whole milliseconds: two quick saves can tie, and a tie
// sorts either way, so the newest-first check below needs a later millisecond.
await new Promise((r) => setTimeout(r, 5));
await db.query(upsert, [b1, jas, 'PSA', 119, 176, 'teal', null, false]);         // the Bible's last-numbered verse
await db.query(upsert, [b1, sam, 'PRO', 4, 23, 'pink', null, false]);            // Sam's own mark on the same verse
const mine = (await db.query(`SELECT count(*)::int n FROM bible_marks WHERE contact_id = $1`, [jas])).rows[0].n;
assert.equal(mine, 3); checks += 4;
const theirs = (await db.query(`SELECT colour FROM bible_marks WHERE contact_id = $1`, [sam])).rows[0].colour;
assert.equal(theirs, 'pink'); checks++;

// Nothing that isn't a verse, a colour on the list, or a note of sensible size.
await refuses(upsert, [b1, jas, 'Proverbs', 4, 1, 'gold', null, false], /check constraint/);
await refuses(upsert, [b1, jas, 'PRO', 0, 1, 'gold', null, false], /check constraint/);
await refuses(upsert, [b1, jas, 'PRO', 4, 177, 'gold', null, false], /check constraint/);
await refuses(upsert, [b1, jas, 'PRO', 4, 1, 'neon', null, false], /check constraint/);
await refuses(upsert, [b1, jas, 'PRO', 4, 1, null, 'x'.repeat(2001), false], /check constraint/);
await refuses(`INSERT INTO bible_marks(business_id, contact_id, book, chapter, verse) VALUES ($1,$2,'PRO',4,1)`,
  [b1, '99999999-9999-4999-8999-999999999999'], /foreign key/);

// The newest-first list the Highlights & notes page reads.
const newest = (await db.query(`SELECT book FROM bible_marks WHERE business_id = $1 AND contact_id = $2
  ORDER BY updated_at DESC LIMIT 1`, [b1, jas])).rows[0].book;
assert.equal(newest, 'PSA'); checks++;

// A member's marks go when they do; another member's stay.
await db.query(`DELETE FROM contacts WHERE id = $1`, [sam]);
const left = (await db.query(`SELECT count(*)::int n FROM bible_marks`)).rows[0].n;
assert.equal(left, 3); checks++;

// Server-only: RLS on, no grant for the browser's roles.
const locked = (await db.query(`SELECT relrowsecurity r FROM pg_class WHERE relname = 'bible_marks'`)).rows[0].r;
assert.equal(locked, true); checks++;
const grants = (await db.query(`SELECT has_table_privilege('anon','public.bible_marks','select') a,
  has_table_privilege('authenticated','public.bible_marks','select') b,
  has_table_privilege('service_role','public.bible_marks','insert') c`)).rows[0];
assert.deepEqual(grants, { a: false, b: false, c: true }); checks++;

console.log(`bible_marks_db: ${checks} checks passed`);
