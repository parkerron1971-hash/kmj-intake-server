---
title: Durable church website connect cards and private prayer requests
date: 2026-10-13
agent: Codex (GPT-6)
asked: "KAI brief: make Love City Church forms land properly in Solutionist"
status: waiting on review
prs: [kmj-intake-server#1409]
migrations: []
left_undone: ["Claude Code review and merge; do not merge in this session"]
decisions: ["Reuse contacts shown as Members and owner-only ministry_care_requests; no schema change", "A confirmed database write determines success; notification_sent reports email outcome", "Prayer requests never enter contacts, scoring, events, SMS consent or automated outreach", "Keep full submissions in immutable event/care rows; cap metadata at ten summaries; strict church limits only", "Church notifications use only the verified sending address"]
---
Added structured connect_card and prayer_request payloads to the existing public
contact-submit route, including compatibility with the initial hyphenated church
form labels. Contact history uses conditional updates. Review revisions below replace the
initial unbounded metadata with bounded summaries and durable full-text rows. Prayer requests reuse the existing Prayer & care owner view. Legacy
contact callers keep their payload and notification routing.

Read backend worklogs before building; the related contact-box SMS disclosure
work is unaffected. The nested solutionist-studio checkout and current frontend were later located
and inspected: connect answers need contact_note events for the Members Notes
tab; private care already has an owner-only viewer. Rebased this branch onto origin/main before changes.

Final local validation: 276 tests passed across test_site_love_city,
test_website_forms,
test_outbound_integrity, test_lead_identity, test_lead_scoring and
test_site_manual_source, test_ministry_readiness, test_member_portal_church,
test_lead_door_defects and test_site_audit_fixes_0801. New tests cover durability, database and notification
failures, full limits, legacy payloads, server recipients, privacy and concurrent
updates. No live submissions or database changes were made.

After KAI confirmed #1408 merged, rebased onto origin/main at 61248292 before
editing forms.js. Both forms now send structured fields (including interests,
heard_from, notes and a boolean follow_up) alongside the readable message.
connect.html needed no change. Each connect card also writes a full contact_note
visible in Members → select the person → Notes; that write must succeed before
acknowledging the card. Prayer requests stay in the owner-only "Private prayer
and care requests" view under intake forms, with no contact or event writes.

Regression tests cover missing site email, footer email, verified sender and
fallback email: stored submissions return ok:true, notification_sent:false, and
the real browser shows success and clears the form. Failures keep the visitor's
input. The owner-only private-care read route returns the saved prayer request
and rejects a different owner. No live submissions or recipient settings changed.

The final local run included real Chromium tests (none skipped). JavaScript
syntax validation and git diff --check passed. PR #1409 is to leave draft only
after its final required test check passes; Claude Code reviews before merge.

Review revisions (2026-10-14): addressed Claude Code's two must-fix items, five
should-fix items and six nits. Plain forms accept up to 100,000 characters per
text field, store the full text in their event and still attempt email on storage
failure while returning 503. KMJ's message box now has maxlength=10000. Contact
metadata keeps ten summaries. Tenant/payload-scoped receipt IDs make contact
history, full notes, prayer records and alerts retry-safe; the church browser
reuses its key on failure. Synchronous database work runs off the event loop.

Church storage generates generic in-app alerts. Prayer email defaults to a
content-free app link (no person in subject or Reply-To); an explicit server
constant makes Kevin's later policy decision easy. Notes and emails no longer
duplicate structured answers. Failure exceptions reach Railway via print.
Unknown-field errors are bounded, empty interests rejected, the source identifier
and 200-character subject cap retained, church attribution omission documented,
replica-local rate limits documented, and browser 400 errors shown as safe text.

Read the available frontend worktree logs; no overlapping church-form work was
found there. Verified contacts.updated_at and its trigger in the frontend base
schema, and chief_notifications columns in its notification migration. No live
submissions, database writes, or recipient configuration changes were made.

Review validation: 748 tests passed across all site suites (including real
Chromium with no skips), form endpoints, lead identity/scoring, outbound
integrity, ministry/member-portal, event-spine and notification tests. JavaScript
syntax and git diff --check passed. Full CI is required before handing back.

Final targeted rerun after preserving the plain-contact lead wakeup on the event
loop: 138 passed. Church forms still never wake the lead agent.

Rebase/re-review (2026-10-14): rebased #1409 cleanly onto origin/main 72a75323,
including W10's photo PR #1411 (b2a2ae02) and the Subsplash exit plan #1412.
Read the photo worklog; no site/form conflicts needed manual resolution.
Range-diff confirms all four implementation commits retained their patches.
All site suites and form/lead/ministry/event/notification regressions passed:
749 tests, including real Chromium, no skips. JavaScript syntax and diff checks
passed. A temporary merge with #1410 at ac56fee4 is conflict-free.

Read-only re-review of #1410: the API-interception layer is removed, visitor
queries are preserved with map values authoritative, and multi-site fixtures
check host selection. 870 site/redirect/API-related tests plus eight additional
Authorization/spoofed-host and query-duplicate probes passed. No changes were
made to #1410's branch. Neither PR is to be merged in this session.


Follow-up review fixes (2026-10-14): plain forms now cut name/email to 200,
phone to 40 and message to 100,000 characters. Only message gets the larger
limit; church validation remains strict. Accepted fallback email after a plain
storage failure returns 200 with ok:true, stored:false, notification_sent:true;
503 remains when neither copy succeeds. Added a browser retry-key fallback for
missing crypto/randomUUID and tested both cases in Chromium.

Church form kinds require the canonical ministry vertical. Content-free alerts
now use notification_engine.create_urgent_alert, honoring urgent_alerts opt-out.
An optional stable notification ID preserves atomic insert-only retry behavior
without resetting read alerts; existing notification callers retain their path.
Legacy callers without a submission key get a fresh receipt per request so a
later identical message updates interaction and creates its own event. Keyed
retries still deduplicate contact history, notes, care rows and alerts.

Before rebasing, 538 site tests and 487 endpoint/dependency tests passed; the
subsequent notification transport regression brought the standalone form suite
to 95 passing tests. No browser tests skipped. JavaScript syntax and diff checks
passed. #1410 is merged. Open #1414 is KAI's approved overlap exception; waiting
for it to merge before rebasing, reading its migration on main, and running care
inbox tests with these tests. No private_care.py or care SQL edits, live database
writes, or push during this wait. The current overlap check found no other
conflict (including new #1416); repeat the full check immediately before push.


Coordination stop: the subsequent full diff-content check (beyond filenames)
found new PR #1416 at ff9cc4ce adds ministry_care_requests reads in church_reads.py
(selecting status, created_at and prayed_at) and related fixture tests. It has no
direct file overlap with #1409 and no SQL/schema writes, but is another care-table
dependency outside KAI's explicit #1414 exception. Stopped and reported before
rebase/push. #1414 remains open. Fixes are committed locally; final rebase,
main-migration compatibility check, combined care-inbox tests and CI remain
pending coordination. No private_care.py or care-inbox SQL changes.


Coordination cleared and latest-main verification (2026-10-14): KAI explicitly
cleared #1416's read-only care-table access and authorized pushing the committed
fixes before rebasing. Pushed a29b025f, then found #1414 (130ae5d4) and #1416
(080153ef) both merged. Rebased cleanly onto origin/main c5eebe30, which also
includes #1417's assignment flow and subsequent member work. No conflicts.
No new overlapping backend/frontend worklog entries were present; read current
care code and migrations directly.

Read APPLY-2026-10-14-care-inbox-actions.sql from main, plus the base care,
member contact-link, and care-assignment migrations. Our insert remains valid:
UUID id/business, null form_id, JSON submission and status new; created_at has
its existing now() default. The added timestamps and assignment columns, along
with contact_id, are nullable. No schema or care-inbox production files changed.

Replaced the old owner-reader fixture test with an integration regression using
an actual website prayer insert and both merged readers, with SQL defaults and
scoped/projected reads modeled in memory. The owner sees the full private request;
a teammate sees nothing until the owner assigns it, then sees that request.
The row can be marked reviewed; church_reads returns the correct new/reviewed
counts and age, without any prayer text or identity. No live requests or writes.
Combined care-inbox, church-read, form, endpoint, Love City, manual-site and
ministry/member tests: 310 passed, no skips. The broader combined run passed
1,187 tests across all site suites and the affected care/form/notification/lead
backends, with no skips. JavaScript syntax and diff checks passed. Final open-PR
file and care-table diff checks found no uncleared overlap. Required CI will
run on the pushed head; no merge is authorized in this session.


Merge lane (2026-10-15): KAI relayed Kevin's explicit approval to squash-merge
#1409 without --admin and retain the branch, after rebase/CI/overlap checks.
Verified every follow-up item in 869e9e50: plain limits/truncation at
website_forms.py:13,35 (must-fix and nit 4); accepted fallback-email success at
public_site.py:2573 (should-fix 1); randomUUID fallback at
sites/love-city-church/forms.js:109 (should-fix 2); canonical ministry gate at
public_site.py:2526 (nit 1); create_urgent_alert at website_forms.py:150 and its
urgent_alerts preference gate at notification_engine.py:649 (nit 2); fresh
unkeyed receipts at website_forms.py:96 (nit 3).

Main advanced by #1439 to 9be2b4f1. Rebased cleanly; range-diff confirms all eight
prior patches are unchanged. The requested form, endpoint, care-inbox,
church-reads, Love City, manual-site and ministry/member regressions passed
310 tests, no skips. JavaScript syntax and diff checks passed. Every open PR's
files and care-table diff was checked; #1440 and #1441 also have no overlap.
CI, squash merge and source-only production verification follow this commit;
report their exact hashes/results in the PR description and final handoff.
Do not submit live forms: Kevin will perform the test submissions himself.
