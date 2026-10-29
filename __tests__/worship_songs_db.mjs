// The church song library on a real Postgres (PGlite):
// supabase/APPLY-2026-10-19-worship-songs.sql. Rows go through every check:
//   worship_songs   a song with its parts and orders; a blank title, a key
//                   that isn't one, a CCLI number that isn't digits, 7 lines
//                   to a slide, 41 parts or a source nobody set up are
//                   refused; a Proclaim import that runs twice can't add the
//                   same song twice, but two churches can each have it
// and the browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/worship_songs_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '99999999-9999-4999-8999-999999999999';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-19-worship-songs.sql'));
await db.exec(await sql('APPLY-2026-10-19-worship-songs.sql'));   // idempotent

const sections = JSON.stringify([
  { id: 'v1', kind: 'verse', number: 1, label: 'Verse 1', lines: ['When peace like a river attendeth my way,', 'When sorrows like sea billows roll;'] },
  { id: 'r', kind: 'refrain', number: null, label: 'Refrain', lines: ['It is well with my soul,', 'It is well, it is well with my soul.'] },
]);
const arrangements = JSON.stringify([{ id: 'main', name: 'Main', order: ['v1', 'r', 'r'] }]);

// What worship_router.create_song writes.
const song = (await db.query(`INSERT INTO worship_songs(business_id, title, sections, arrangements, has_words, song_key,
    public_domain, source) VALUES ($1, 'It Is Well With My Soul', $2::jsonb, $3::jsonb, true, 'D', true, 'pasted') RETURNING *`,
  [b1, sections, arrangements])).rows[0];
assert.equal(song.lines_per_slide, 2); assert.deepEqual(song.times_sung, {}); assert.equal(song.archived_at, null); checks += 3;

// What the Proclaim import writes, twice: the second one can't land.
const proclaim = `INSERT INTO worship_songs(business_id, title, source, source_ref, times_sung, last_sung, song_key)
  VALUES ($1, 'Wall Come Down', 'proclaim', 'proclaim:wall come down', '{"2026": 15}'::jsonb, '2026-05-10', 'A') RETURNING id`;
await db.query(proclaim, [b1]);
await refuses(proclaim, [b1], /duplicate key|unique/);
await db.query(proclaim, [b2]); checks++;   // another church has the same song
// Typed songs have no source_ref, so any number of them can share a title.
await db.query(`INSERT INTO worship_songs(business_id, title) VALUES ($1, 'Untitled song'), ($1, 'Untitled song')`, [b1]); checks++;

// What a song can't be.
await refuses(`INSERT INTO worship_songs(business_id, title) VALUES ($1, '   ')`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title, song_key) VALUES ($1, 'x', 'H')`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title, ccli_number) VALUES ($1, 'x', '12ab')`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title, lines_per_slide) VALUES ($1, 'x', 7)`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title, source) VALUES ($1, 'x', 'lyrics-site')`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title, tempo) VALUES ($1, 'x', 5)`, [b1], /check constraint/);
const many = JSON.stringify(Array.from({ length: 41 }, (_, i) => ({ id: `v${i}`, kind: 'verse', label: `Verse ${i}`, lines: ['a'] })));
await refuses(`INSERT INTO worship_songs(business_id, title, sections) VALUES ($1, 'x', $2::jsonb)`, [b1, many], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title, sections) VALUES ($1, 'x', '{"a":1}'::jsonb)`, [b1], /check constraint|non-array/);
await refuses(`INSERT INTO worship_songs(business_id, title, times_sung) VALUES ($1, 'x', '[]'::jsonb)`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_songs(business_id, title) VALUES ($1, 'x')`, ['33333333-3333-4333-8333-333333333333'], /foreign key/);

// Taking a song out keeps the row (the import still knows it came over).
await db.query(`UPDATE worship_songs SET archived_at = now() WHERE id = $1`, [song.id]);
const left = (await db.query(`SELECT count(*)::int AS n FROM worship_songs WHERE business_id = $1 AND archived_at IS NULL`, [b1])).rows[0].n;
assert.equal(left, 3); checks++;

// A church that leaves takes its songs with it.
await db.query('DELETE FROM businesses WHERE id = $1', [b2]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM worship_songs WHERE business_id = $1', [b2])).rows[0].n, 0); checks++;

// Server-only: the browser's roles see nothing and change nothing.
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM worship_songs', [], /permission denied/);
  await refuses(`INSERT INTO worship_songs(business_id, title) VALUES ('${b1}', 'x')`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`worship_songs: ${checks} checks passed`);
