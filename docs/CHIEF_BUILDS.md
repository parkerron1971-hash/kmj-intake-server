# Chief Split implementation

Implemented 2026-09-18. This branch adds the durable executor and its migration. The companion frontend adds Chief build cards.

## Behavior

Chief queues typed, durable builds for workshops, forms with links, flyers and Events pages. Known plans use no planning model call. Existing site refinement and image generation keep their own paid execution paths. Chief receives plain receipts, not handler diagnostics.

Each order has a stable identity, durable checkpoints before effects, read-back verification and a resumable approval/question state. Verified completed steps replay. Unknown send outcomes are never automatically sent again. HTTPS pages are fetched with the existing DNS-pinned public fetcher; redirects and failed verification never produce a clickable success receipt.

Leases serialize builds per business across replicas. A process runs at most eight workers. Heartbeats fence stale workers; scheduler recovery resumes interrupted work. Child image/site jobs are checked on later ticks instead of long polling loops. Cards poll every five seconds while active, thirty otherwise, and pause in hidden tabs. They reject stale approval revisions, refresh after responses, and clear old results on business changes. Voice stream fallback reuses one request ID.

## Important contract decisions

- Owner-only first rollout; underlying action scope, policy, taint, spend and voice gates still run per step. No user JWT is stored in a job.
- Approval is for a specific held action and parameter digest. The card uses an authenticated, revision-bound response endpoint. Bare yes stays insufficient.
- Workshop registration is the real RSVP flow, including capacity and duplicate registration handling. Generic forms remain the form_and_link plan.
- An image must have ready bytes to be verified; queued/working is waiting.
- Manual websites return a needs_hand receipt for navigation changes. Paid event booking and arbitrary custom coding are outside this first release. Custom is explicitly delayed by spec section 9 until the deterministic paths have run live for a week.
- The dedicated executor uses chief_jobs storage and recovery, but does not pass through the legacy _run path that assumes every returned result is final.

## Activation

1. Review and merge the backend changes; apply supabase/APPLY-2026-09-18-chief-builds.sql after merge. Prerequisites are the existing chief_jobs table and the September 8 image studio reservation function. The migration is replayable and tested against the original jobs schema and active-job index.
2. Deploy the frontend and backend. Keep CHIEF_BUILDS=off until the migration is verified.
3. Set CHIEF_BUILDS=on on the backend. Create a test order from the signed-in owner conversation, confirm the card updates and restart the worker during a test build to verify production recovery.
4. Rehearse the real workshop: Embrace the Shift Workshop, 2026-10-13 19:00 America/Detroit, 1084 Allen Avenue, Muskegon MI, free. Verify the live events and registration URLs return 200 and show the correct event. Review any existing matching event before creating it. Generate a flyer only with the explicit go-ahead.
5. The approved synthetic live prompt evaluations passed (83/83 module checks and 5/5 routing scenarios). Complete the production rehearsal above; only after a week of live deterministic builds should custom planning be considered.

The repository's backend CLAUDE.md says: “Migrations are applied by Kevin, by hand.” This session prepared and locally exercised the SQL; it did not apply it to production, deploy or claim the live rehearsal passed. Rollback is CHIEF_BUILDS=off followed by allowing active workers to stop/redeploy. Keep durable job history; do not drop lease columns while a worker is active.

## Verification

- Frontend production build passed. App TypeScript diagnostics match the baseline exactly; no new diagnostics. Existing large-bundle warnings remain.
- Chromium interaction checks passed at 320, 375, 768 and 1280px, including approval, typed answer, retry, cancellation, stale responses, polling revisions, business switching and hiding unverified URLs.
- PostgreSQL checks passed: original schema upgrade, migration replay, exclusive claims, lease fencing, completed-order replay, approval revision, duplicate identity, image owner checks and RPC privileges. The check is wired into backend CI.
- Offline Chief turn replay: 102/102. Live model evaluation, initially blocked by automatic approval review, completed after explicit user approval: 83/83 module checks and 5/5 routing scenarios.
- Local design and browser verification completed. Automatic approval review blocked the 12ui external comparison command because its repo argument could export private content. No bypass was attempted.

The complete local results and initial broad-run failures are recorded below. CI has not been run on a remote PR.

## Reproduce

From backend worktree:

    python -m pytest __tests__/test_chief_builds.py __tests__/test_events_rsvp.py -q
    python scripts/chief_turn_eval.py --out ../chief-replay-eval.json
    node scripts/chief-builds-db-check.mjs

For the SQL check, install @electric-sql/pglite@0.5.8 in a temporary folder and set PGLITE_MODULE to its dist/index.js. CI already does this for the existing database checks.

From frontend:

    npm run build
    npx tsc -p tsconfig.app.json --noEmit
    npx vite --host 127.0.0.1 --port 5174 --strictPort
    python scripts/chief-builds-browser-check.py

The browser fixture only uses synthetic examples and intercepted API responses. Screenshots and run output live under output/chief-split.

## Final local results

- Initial full backend run: 8,146 passed, 16 skipped, 3 failures. The verb parity failure exposed missing JSON-tag documentation; it was fixed in the feature-gated context block without changing the parity reader. The other failures were a source-inspection mismatch while files were being edited and a timing threshold under load. A fresh run of all three affected test files passed: 25 tests. The entire 8,000+ suite was not rerun after the corrections; affected tests were rerun as reported below.
- Affected integration suite: 197 passed. Latest dedicated build suite after live-evaluation fixes: 35 passed. Affected prompt/tool/truth regression suite: 125 passed. Wiring checks: 66 passed. Additional agents suite: 85 passed. Offline browser safety sabotage checks: passed.
- Frontend final production build, new-file ESLint, What’s New validation and Chromium interaction checks: passed. TypeScript output is byte-for-byte equivalent after newline decoding: the same 14 pre-existing diagnostics, zero added.
- The PostgreSQL upgrade test runs in CI using its existing temporary PGlite installation. Remote CI itself has not been run in this session.


## Approved live evaluation — 2026-09-18

After Kevin approved external API evaluation, the current backend worktree passed the module-generation harness: **83/83 checks across eight cases**. The five-case Chief Split routing evaluation initially passed two cases, exposing legacy action routing and incomplete status evidence. The fixes place the feature-gated routing policy in the instruction portion of the prompt, offer background work orders instead of inline image generation when builds are enabled, and expose pending job state as evidence without claiming a completed write.

The corrected live run passed **5/5 scenarios**: workshop setup, form with link, flyer request, pending flyer status without another generation, and approval of the same held order. Three new regression tests cover the fixes; the dedicated build suite passes 35 tests and the affected prompt/tool/truth integration suite passes 125 tests.

These calls used synthetic business data with execution effects stubbed. The evaluation launcher removed database and delivery credentials before importing the app. No production business records were written. This validates live model routing and generated proposals; it does not replace deployment, remote CI, or the production workshop/restart rehearsal.

Artifacts: output/chief-split/module-build-live.json, chief-split-live-before.json, chief-split-live.json, and live-fix-regression.txt. The module harness was run from the implementation worktree (scripts/module_build_eval.py), so it exercised the changed source rather than the older eval-run checkout. Local reproduction with an approved model API environment uses output/chief-split/run-approved-eval.py; add --split for the routing harness.

## Delivery files

The implementation is present locally. Backend work is **uncommitted** in the isolated feat/chief-split worktree. The original backend checkout and unrelated frontend changes were preserved.

- output/chief-split/backend.patch — backend implementation, migration, tests and CI wiring.
- output/chief-split/frontend.patch — only this task’s frontend changes, relative to the workspace as it was before this task; it excludes unrelated edits. Do not reapply it to this already-updated workspace.
- output/chief-split/verification.json — machine-readable checks and live-check limits.
- output/chief-split/backend-full-suite.txt — initial broad-run results, including the three failures subsequently rechecked.

Both patches passed reverse-application checks against the completed working files. Approved external live evaluation passed. Production activation and workshop rehearsal remain pending; no production success is claimed.
