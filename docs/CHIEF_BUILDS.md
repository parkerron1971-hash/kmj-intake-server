# Chief Split implementation

Implemented 2026-09-18. This branch adds the durable executor and its migration. The companion frontend adds Chief build cards.

## Behavior

Chief queues typed, durable builds for workshops, forms with links, flyers and Events pages. Known plans use no planning model call. Existing site refinement and image generation keep their own paid execution paths. Chief receives plain receipts, not handler diagnostics.

Each order has a stable identity, durable checkpoints before effects, read-back verification and a resumable approval/question state. Verified completed steps replay. Unknown send outcomes are never automatically sent again. HTTPS pages are fetched with the existing DNS-pinned public fetcher; redirects and failed verification never produce a clickable success receipt.

Leases serialize builds per business across replicas. A process runs at most eight workers. Heartbeats fence stale workers; scheduler recovery resumes interrupted work. Child image/site jobs are checked on later ticks instead of long polling loops. Cards poll every five seconds while active, thirty otherwise, and pause in hidden tabs. They reject stale approval revisions, refresh after responses, and clear old results on business changes. Voice stream fallback reuses one request ID.

## Plans: several pieces of work from one message (2026-09-26)

Kevin, from the Dev Desk: can someone "give a project such as schedule events, make flyer, etc... in one message and it all get worked on ... and conversation still go on?" He chose one brain with many hands over many agents, on the condition that Chief redirects when a worker stops.

A **plan** is a work order of kind `plan` (`chief_plans.py`). Its facts are a title, a goal and up to 12 steps. Each step is an ordinary Chief action (`{"title", "action": {"type", ...}, "for_each"?, "approval"?}`). It runs on this same worker, with the same leases, checkpoints, card, chat message and push, so the chat is free while it works.

- **Same steps as a mission.** `chief_missions.validate_steps` decides what a step may be. A later step can use an earlier result (`"@create_contact.contact_id"`) or repeat over a list (`for_each`). Not allowed as plan steps: work orders, form builds (`create_client_form`), event setup and permission verbs. A plan makes at most one image.
- **Same door.** Every step runs through `chief_of_staff._execute_actions` inside `Adapter.handler_scope`, as the owner who asked. The policy, taint, class-C gate and spend guard are the chat's own.
- **Sends, notifying bookings, charges and deletes (class C)** run on the owner's own ask on the desktop, as in chat. A spoken or tainted plan holds them for a yes. No order runs more than three of them without a go-ahead. A step marked `approval: true` always waits.
- **Order.** Each step waits for the one before it, so a stop is never stepped over. The exception is an image, which only holds up a step that references it. A step waiting on a running image says so and is picked up on the next tick.
- **Retries.** A write that may have happened (the handler raised or timed out) is `uncertain` and never repeated blind. A clean refusal can be retried.

**Chief's first look at a stop.** When a step fails or is uncertain, the worker runs one model turn before the owner is bothered. That turn has read-only tools (`reset_turn(writes_allowed=False)`, `read_tool_definitions()`) and sees the plan, what each step did and why it stopped. Chief answers with one `plan_decision` tag:
- `continue` rewrites the steps still to run and adds a plain note on what changed and why.
- `ask` puts one question and a suggestion on the card (`needs_answer`, field `plan_answer`). The owner's answer, from the card or from chat through `respond_work_order`, is the input to the next look.

The guard rails live in `apply()`/`_revise()`, not in the prompt:
- A rewritten plan passes the same step rules.
- Any class-C step in it that is not exactly one the owner already asked for (same action) waits for their go-ahead, and so does any class-C step when the look read third-party text.
- Chief looks at most twice on its own per plan (and four times after answers).
- Every look is recorded in `result.looks`. The latest change leads the summary, and `public_job` exposes the notes.

A look costs one model turn, only when something stopped. It is skipped over the daily spend cap.

**The closing check (2026-09-26, after the live test).** Asked for nine changes, Chief made three in its reply, planned two, and "call Plan Test D" was in neither. A stop only catches a step that ran, so a finished plan now gets one closing look, once per plan. It compares the owner's words with what the reply already did and with the plan's receipts. The reply's changes are recorded by the server in `facts.done_in_turn` (`note_done_in_turn`, called from `_execute_actions` just before `submit_work_order`); the model cannot write it. Anything missing goes through the same `continue` path and guards, and a send, charge or delete it adds waits for the owner. Nothing missing adds no note. The check runs only on a plan that finished `done`, never on one that is held, waiting or asking.

**Overflow.** A reply can make three direct changes (`MAX_WRITE_CALLS`). Once those are spent (budget, not a hold), `submit_work_order` stays open for the turn's one order, and the refusal tells the model to put the rest into one plan instead of promising "the next pass".

A plan's image is found by its stable id on every run, so a redirect cannot pay for a second image; an image that fails still needs the owner.

## Several jobs from one message, side by side (step 2, 2026-09-26)

- **Up to four work orders per turn** (`MAX_ORDERS_PER_TURN`), one per piece: for example a workshop (`event_setup`), a flyer, and one plan for everything else. Each order has its own identity, `stable_id(business, turn, slot)`. The first keeps the original `build` slot, so a replayed turn still matches its order; later ones are `build:2`, `build:3` and so on. Answering a job (`respond_work_order`) and starting one stay in separate turns. The overflow after the three direct changes stays open until the turn's last order.
- **Lanes** (`supabase/APPLY-2026-09-26-chief-build-lanes.sql`): one running build per business and lane, instead of per business. The lanes are `site` (workshops, forms with links, events pages, which share the Events collection, forms and the website), `image` (flyers) and `plan` (plans). A workshop, a flyer and a plan from one message run at once, and two workshops still take turns. Only `chief_build_claim` changes (same signature), so the server code runs before and after the migration; before it, jobs simply queue per business as they did. `scripts/chief-build-lanes-db-check.mjs` checks it in CI.
- **No five-minute wait.** When a job finishes, the worker starts whatever was queued for that business (`_launch_waiting`), instead of waiting for the recovery tick.
- **Starting a plan names its pieces**: "Working on these in the background: A, B and C. You can leave this chat..." Before, the reply and its receipts never said what went to the background.

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
