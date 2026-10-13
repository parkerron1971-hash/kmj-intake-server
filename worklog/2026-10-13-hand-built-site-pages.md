---
title: Hand-built sites install and serve their own page sets
date: 2026-10-13
agent: Codex (GPT-6)
asked: "Rebase site-sync-any-pages onto origin/main and address the review of ef88bb1a"
status: waiting on Kevin
prs: [kmj-intake-server#1407]
migrations: []
left_undone: ["Required GitHub test check and Kevin's separate approval to merge PR #1407"]
decisions: ["Initially local-only; KAI later authorized publishing PR #1407, with merge awaiting Kevin's separate approval", "Composed sites retain main's fixed secondary pages and configured World offer path", "Manual sites may own /sermons; hosted /sermons/<id> still serves details", "API routes, member portal, texting compliance, and data/news/academy namespaces are reserved", "Main also owns /live and /group-live as authenticated APIs; Love City's live page ID is watch", "Automatic deploy checks of manual sites inspect at most four pages including home; adoption input is capped at 24000 characters"]
related: [2026-10-03-no-card-trial.md, 2026-10-03-owner-only-preview.md, 2026-10-12-contact-box-own-name.md]
---
Fetched origin/main at fe8d5b19 and dropped inherited 6a02f95c because its patch is already on main. Resolved six public_site.py conflicts by retaining main's pv preview gate, _site_page_id/_preview_page_id, offer_page.path and hosted route precedence, then adding validated manual-page handling behind the manual-source check. Resolved site_check.py by keeping main's composed and offer URLs and enumerating arbitrary pages only for manual sites. No sites/ source files were edited.

The installer keeps home first, preserves build order, validates IDs and nonempty HTML, excludes reserved IDs, and caps installs at 20 pages. Every skip reaches stdout as well as logging. A route-table test detects new shadowing APIs, and a shipped-build contract test checks every build.py. KMJ regression coverage computes the legacy hash algorithm and simulates JSONB key ordering, with no fixed content hash.

Reviewed overlapping backend trial/texting logs and frontend no-card-trial/site-preview-only logs on solutionist-studio's module-system branch. Tests cover composed 404s, World offer routing, hosted giving precedence, preview tokens, the sermon index/detail split, validation, adoption ordering/budget, and deploy-check cost. All 44 site-related test files pass: 870 tests, including test_pages_that_match, test_nav_clean_routes, test_no_card_trial, and test_site_manual_source. The branch full suite passes 15265 tests, with 6 failures also present on untouched main, 16 skips, 1 expected failure, and 17 passing subtests (1829.14s). No branch-only failures.

Conflict resolutions, each reviewed against origin/main:

| Conflict | Resolution |
| --- | --- |
| public_site helpers/nav signature | Retained both World page helpers and the cfg parameter; added a manual-only preview branch. |
| public_site sitemap | Kept composed fixed pages and offer_page.path; enumerated stored IDs only for manual sites. |
| public_site secondary preview signature | Retained pv, preview_blocked, and pv propagation to the home fallback. |
| public_site secondary preview lookup | Retained _preview_page_id and composed lookup; validated stored pages only for manual sites. |
| public_site slug serving | Retained main composed lookup and hosted routes; manual pages return after the offline/trial gates. |
| public_site custom-domain serving | Same separation and gates, with the custom-domain canonical origin retained. |
| site_check page enumeration | Retained all composed URLs including the configured offer; manual pages use their own IDs. |

Untouched-main baseline: `python -B -m pytest -q --tb=short` against a git-archive snapshot of fe8d5b1975cf75f5e6417ea2d40c6bfa30c0cc1a, using the same Python environment: **15144 passed, 7 failed, 16 skipped, 1 xfailed, 17 subtests passed** (1881.42s). Baseline failures:

- `__tests__/test_business_marketing_standing.py::test_at_send_time_a_lapsed_plan_or_autonomy_off_is_not_sent_back_to_waiting_and_told[plan]`
- `__tests__/test_business_marketing_standing.py::test_at_send_time_a_lapsed_plan_or_autonomy_off_is_not_sent_back_to_waiting_and_told[autonomy]`
- `__tests__/test_business_marketing_standing.py::test_at_send_time_a_covered_post_goes_on_and_an_unreadable_business_holds_it`
- `__tests__/test_chief_keep_warm.py::test_a_ping_that_writes_stops_the_pings`
- `__tests__/test_chief_keep_warm.py::test_a_refused_ping_stops_the_pings`
- `__tests__/test_connected_ai.py::test_saved_device_credential_round_trip`
- `__tests__/test_gather_context_wave2.py::test_wave_two_does_not_wait_on_itself`

The marketing failures report an expired posting window instead of the expected draft/approved state. The keep-warm tests expected one ping but got none. The credential test raises `OSError: Could not protect the local connection credential.` The wave-two timing assertion measured 0.72s added latency against a 0.4s threshold. These failures are outside the site-sync changes.

Branch validation command: `python -B -m pytest -q --tb=short --disable-warnings`. Its six failure IDs and assertion/error text match the baseline above, excluding `test_wave_two_does_not_wait_on_itself`, which passes on the branch. The site selection contains all test files whose names include site/pages, plus navigation, no-card trial, findability, sermons, offer coaching, and owner-only preview. All 870 tests pass (130.55s). These full-suite results describe 80725173, before the follow-up below.

Initial local delivery scope checks: no diff from origin/main under sites/, chief_truth.py, or __tests__/test_review_evidence_order.py; git diff --check is clean. No push, merge, deploy, migration, or production database action was performed.

Follow-up requested by KAI after Claude Code reviewed 80725173 together with Love City: get_site_html now passes site_config to the preview rewrite only for manual sites. A handler-level regression pins the composed World home offer link to /saturday-shave-club, matching main, while the manual version still links to /public/site/acme/saturday-shave-club. The composed case failed before the fix; the manual case already passed. Love City examples in six test files and this log now use the actual page ID watch. Follow-up validation: all 44 site-related files pass, **872 tests passed**, 24 warnings (89.06s), including test_pages_that_match, test_nav_clean_routes, test_no_card_trial and test_site_manual_source. No full-suite rerun was requested for this narrow follow-up.

PR handoff: [#1407](https://github.com/parkerron1971-hash/kmj-intake-server/pull/1407) targets main. After the direct main push was rejected by repository protection, KAI authorized the pull-request route and explicitly withheld merge permission until Kevin gives the go. The seven required local suites pass (252 tests); the GitHub test check is required before handoff. Automated review found no blockers. Local main remains untouched in its other worktree.
