// scripts/db_checks.mjs — the database checks (PGlite), in parts, for CI's test-db jobs.
//
//   node scripts/db_checks.mjs --list              # every check this finds
//   node scripts/db_checks.mjs --check 4           # each check in exactly one of 4 parts
//   node scripts/db_checks.mjs --part 2 4          # the checks in part 2 of 4
//   node scripts/db_checks.mjs --run 2 4 [--jobs N] # run part 2 of 4, N at a time
//   node scripts/db_checks.mjs --run all           # run every check (locally)
//
// Kevin, 2026-11-28: "this process takes too long". The checks used to be a
// hand-kept list in ci.yml, run one after another (~19 minutes). Now:
//
// - The checks are FOUND, not listed: every scripts/*-db-check.mjs and every
//   __tests__/*_db.mjs. A new check runs in CI the moment its file exists;
//   nobody has to remember to add a line. (Five checks had been written and
//   never added to the old list.) A check that must not run in CI goes in
//   "skip" in scripts/db_checks.json, with the reason.
// - Each check runs in its own node process through scripts/db_check_child.mjs,
//   which removes the ~10 s PGlite exit wait (see that file).
// - The checks are split into parts by measured seconds ("seconds" in
//   scripts/db_checks.json; a check not in there counts DEFAULT_SECONDS), the
//   longest first to the lightest part. The split depends only on the files
//   and that json, so every CI job agrees on it.
// - Inside a part, checks run side by side (one per core by default). Each
//   check's output is printed whole when it finishes, with its time.
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { availableParallelism } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG = path.join(ROOT, 'scripts', 'db_checks.json');
const DEFAULT_SECONDS = 4;
const TIMEOUT_MS = 10 * 60 * 1000;

export function config() {
  const c = existsSync(CONFIG) ? JSON.parse(readFileSync(CONFIG, 'utf8')) : {};
  return { seconds: c.seconds || {}, skip: c.skip || {} };
}

export function found() {
  const out = [];
  for (const [dir, test] of [['scripts', n => n.endsWith('-db-check.mjs')], ['__tests__', n => n.endsWith('_db.mjs')]]) {
    for (const name of readdirSync(path.join(ROOT, dir))) if (test(name)) out.push(`${dir}/${name}`);
  }
  return out.sort();
}

export function checks() {
  const { skip } = config();
  return found().filter(f => !(f in skip));
}

export function parts(n) {
  const { seconds } = config();
  const files = checks().map(f => [seconds[f] ?? DEFAULT_SECONDS, f]);
  files.sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? -1 : 1));
  const bins = Array.from({ length: n }, () => ({ load: 0, files: [] }));
  for (const [s, f] of files) {
    let i = 0;
    for (let k = 1; k < n; k++) if (bins[k].load < bins[i].load) i = k;
    bins[i].files.push(f);
    bins[i].load += s;
  }
  return bins.map(b => ({ load: Math.round(b.load), files: b.files.sort() }));
}

export function check(n) {
  const problems = [];
  const { seconds, skip } = config();
  const every = checks();
  const assigned = parts(n).flatMap(p => p.files);
  const count = new Map();
  for (const f of assigned) count.set(f, (count.get(f) || 0) + 1);
  for (const f of every) if (count.get(f) !== 1) problems.push(`${f} is in ${count.get(f) || 0} parts, not exactly one`);
  for (const f of assigned) if (!every.includes(f)) problems.push(`${f} is in a part but isn't a check`);
  if (parts(n).some(p => p.files.length === 0)) problems.push(`a part of ${n} has no checks`);
  const all = new Set(found());
  for (const f of Object.keys(seconds)) if (!all.has(f)) problems.push(`db_checks.json "seconds" names ${f}, which doesn't exist`);
  for (const [f, why] of Object.entries(skip)) {
    if (!all.has(f)) problems.push(`db_checks.json "skip" names ${f}, which doesn't exist`);
    if (!String(why).trim()) problems.push(`db_checks.json "skip" gives no reason for ${f}`);
  }
  return { checks: every.length, skipped: Object.keys(skip).length, parts: n, problems };
}

function runOne(file) {
  return new Promise(resolve => {
    const started = Date.now();
    const child = spawn(process.execPath, [path.join(ROOT, 'scripts', 'db_check_child.mjs'), file], {
      cwd: ROOT, env: process.env, stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '';
    child.stdout.on('data', d => { out += d; });
    child.stderr.on('data', d => { out += d; });
    const timer = setTimeout(() => { out += `\n(stopped after ${TIMEOUT_MS / 60000} minutes)\n`; child.kill('SIGKILL'); }, TIMEOUT_MS);
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      resolve({ file, ok: code === 0, code: code ?? signal, seconds: (Date.now() - started) / 1000, out: out.replace(/\r/g, '') });
    });
  });
}

async function run(files, jobs) {
  const gh = !!process.env.GITHUB_ACTIONS;
  const results = [];
  let next = 0;
  const started = Date.now();
  console.log(`${files.length} database checks, ${jobs} at a time`);
  const worker = async () => {
    while (next < files.length) {
      const r = await runOne(files[next++]);
      results.push(r);
      const head = `${r.ok ? 'ok  ' : 'FAIL'} ${r.file} (${r.seconds.toFixed(1)}s)`;
      if (gh && r.ok) console.log(`::group::${head}\n${r.out.trimEnd()}\n::endgroup::`);
      else console.log(`${head}\n${r.out.trimEnd().replace(/^/gm, '    ')}`);
      if (gh && !r.ok) console.log(`::error title=database check failed::${r.file} exited with ${r.code}`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(jobs, files.length) }, worker));
  const failed = results.filter(r => !r.ok);
  const times = Object.fromEntries(results.sort((a, b) => (a.file < b.file ? -1 : 1)).map(r => [r.file, Math.round(r.seconds * 10) / 10]));
  console.log(`\nseconds per check (to refresh scripts/db_checks.json): ${JSON.stringify(times)}`);
  console.log(`${results.length - failed.length} of ${results.length} database checks passed in ${((Date.now() - started) / 1000).toFixed(0)}s`);
  for (const r of failed) console.log(`FAILED: ${r.file}`);
  return failed.length ? 1 : 0;
}

function part(argv) {
  const k = Number(argv[0]), n = Number(argv[1]);
  if (!Number.isInteger(k) || !Number.isInteger(n) || k < 1 || k > n) throw new Error(`part ${argv[0]} of ${argv[1]} isn't one of 1..n`);
  return parts(n)[k - 1].files;
}

async function main(argv) {
  const jobsAt = argv.indexOf('--jobs');
  const jobs = jobsAt >= 0 ? Number(argv.splice(jobsAt, 2)[1]) : availableParallelism();
  const [cmd, ...rest] = argv;
  if (cmd === '--list') { console.log(checks().join('\n')); return 0; }
  if (cmd === '--check') {
    const r = check(Number(rest[0] || 4));
    console.log(JSON.stringify({ checks: r.checks, skipped: r.skipped, parts: r.parts }));
    for (const p of r.problems) console.error(`db_checks --check: ${p}`);
    return r.problems.length ? 1 : 0;
  }
  if (cmd === '--part') { console.log(part(rest).join('\n')); return 0; }
  if (cmd === '--run') {
    const files = rest[0] === 'all' ? checks() : rest.length === 2 ? part(rest) : rest;
    return run(files, Math.max(1, jobs));
  }
  console.error('usage: node scripts/db_checks.mjs --list | --check N | --part K N | --run K N [--jobs J] | --run all | --run <files>');
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2));
}
