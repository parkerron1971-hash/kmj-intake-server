// scripts/db_check_child.mjs — runs ONE database check, then lets node exit at once.
//
//   PGLITE_MODULE=<.../pglite/dist/index.js> node scripts/db_check_child.mjs __tests__/x_db.mjs
//
// Why this exists (measured 2026-11-28): a PGlite that has written anything
// keeps node alive for about 10 seconds after the check's last line, unless
// the check calls `await db.close()`. About 80 of the checks don't, so CI
// spent ~13 of its ~19 database minutes waiting on nothing.
//
// This runs the check exactly as `node <file>` would (same file, same
// process.argv[1], same top-level awaits, its own process), and after the
// check's module has finished it closes every PGlite the check opened and
// still left open. Node then exits normally: any work the check left running
// still runs (and fails loudly if it touches a closed database), so nothing
// the check would have caught is skipped.
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const file = process.argv[2];
if (!file) {
  console.error('usage: node scripts/db_check_child.mjs <check file>');
  process.exit(2);
}
const full = path.resolve(file);
const opened = new Set();

const spec = process.env.PGLITE_MODULE;
if (spec) {
  // The same URL the checks import, so they get this (patched) class.
  const url = /^file:/i.test(spec) ? spec : pathToFileURL(spec).href;
  const { PGlite } = await import(url);
  for (const name of ['query', 'exec', 'transaction', 'execProtocol']) {
    const orig = PGlite.prototype[name];
    if (typeof orig !== 'function') continue;
    PGlite.prototype[name] = function (...args) {
      opened.add(this);
      return orig.apply(this, args);
    };
  }
}

// As if node had been started on the check itself.
process.argv.splice(1, 2, full);
await import(pathToFileURL(full).href);

for (const db of opened) {
  if (!db.closed) await db.close();
}
