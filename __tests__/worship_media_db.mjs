// The church's pictures and videos on a real Postgres (PGlite):
// supabase/APPLY-2026-10-19-worship-media.sql. Rows go through every check:
// a picture and a video under the church's own prefix go in; an object name
// outside the pattern (another folder, a path trick, an .html file), a type
// that isn't allowed, a file over 100 MB, a blank name or a status nobody
// set up are refused; one object can't be two rows; a church that leaves
// takes its rows with it; the browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/worship_media_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-19-worship-media.sql'));
await db.exec(await sql('APPLY-2026-10-19-worship-media.sql'));   // idempotent

const id = () => crypto.randomUUID();
const add = `INSERT INTO worship_media(business_id, kind, name, object_name, mime, bytes) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`;
const pic = (await db.query(add, [b1, 'image', 'Stage photo', `${b1}/worship-${id()}.png`, 'image/png', 1200])).rows[0];
assert.equal(pic.status, 'uploading'); assert.equal(pic.url, null); checks += 2;
await db.query(add, [b1, 'video', 'The Making promo', `${b1}/worship-${id()}.mp4`, 'video/mp4', 50 * 1024 * 1024]); checks++;

await refuses(add, [b1, 'image', 'x', `elsewhere/worship-${id()}.png`, 'image/png', 10], /check constraint/);
await refuses(add, [b1, 'image', 'x', `${b1}/../worship-${id()}.png`, 'image/png', 10], /check constraint/);
await refuses(add, [b1, 'image', 'x', `${b1}/worship-${id()}.html`, 'image/png', 10], /check constraint/);
await refuses(add, [b1, 'image', 'x', `${b1}/worship-${id()}.png`, 'text/html', 10], /check constraint/);
await refuses(add, [b1, 'video', 'x', `${b1}/worship-${id()}.mp4`, 'video/mp4', 101 * 1024 * 1024], /check constraint/);
await refuses(add, [b1, 'image', '  ', `${b1}/worship-${id()}.png`, 'image/png', 10], /check constraint/);
await refuses(add, [b1, 'image', 'twin', pic.object_name, 'image/png', 10], /duplicate key|unique/);
await refuses(`UPDATE worship_media SET status = 'published' WHERE id = $1`, [pic.id], /check constraint/);

await db.query(`UPDATE worship_media SET status = 'ready', url = 'https://x.supabase.co/storage/v1/object/public/business-assets/' || object_name WHERE id = $1`, [pic.id]);
checks++;

await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM worship_media')).rows[0].n, 0); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM worship_media', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`worship_media: ${checks} checks passed`);
