---
title: B15b — With the suite on, Platform Chief, MC Today and the digest work the suite desk
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1343]
migrations: []
left_undone: ["Frontend: Mission Control's cards for the suite's marketing_post_now (frozen desk 'suite' payload: post_id, revision, caption, accounts, picture, or caption, platforms, image_id) and marketing_replan, which today render as generic review cards", "Frontend: Prepare post / Save to marketing hand the artwork to POST /platform/marketing/suite/ideas {artwork_id} while the suite is on (the hand-off is frontend-only; the backend makes no Buffer draft)", "F7: Mission Control's desk on /platform/marketing/suite", "GET /platform/chief/permissions still lists only 'Posting right away' as always reviewed (planning again on the suite is a card too)", "signups in the suite's results for the platform business"]
decisions: ["every decision keys on platform_suite's one predicate (switch on AND a validated platform business); switch off nothing here is reached: no verdict read, empty handler maps, a suite-only tag is 'not permitted' with no card written, and the Buffer card, Today, digest, prompt and snapshot are as before", "routing lives at the call sites (dispatch's handler map, decide's card handlers, propose's post-now review, platform_console, platform_today), so platform_chief_marketing's Buffer handlers and HANDLERS are unchanged", "Platform Chief's verbs call B10's own handlers (no second write path) for the validated platform business only, read as the service role and checked against the signed-in platform owner; a tag naming another business is refused before anything is read", "class C (post-now, replan) is a review card every time; the handler refuses unless it runs from a card the owner approved; B10's _unattended is set from that, never from the tag", "the suite post-now card freezes post_id, revision and content hash (or a new post's words, networks, picture, link); a post that moved on after the card is refused; a new flyer is not posted from a card", "replan keeps Mission Control's one-loop rule (a week the Buffer desk has live is not planned again)", "no approve verb anywhere; the standing OK (B13) is the only non-owner approval", "MC Today and the digest read the business desk's own Today/digest for the platform business plus the standing OK and pulled posts, and keep the Buffer desk's leftovers (failed, unconfirmed, paused with approved posts, missed, approved-but-window-closed) while it drains; Buffer waiting drafts are not asked about since nothing is approved there", "a failed read on either desk is an item saying it couldn't be read, never nothing", "the one B15 test that asserted the old suite-on refusal of a post-now card now asserts the same dispatch property on the unconfirmed state"]
related: [2026-10-08-marketing-platform-suite.md, 2026-10-08-chief-marketing-desk.md, 2026-10-08-marketing-standing.md]
---
Follow-up of kmj-intake-server#1342 (B15). With MC_MARKETING_SUITE on and a
validated PLATFORM_BUSINESS_ID, Platform Chief's marketing verbs
(marketing_desk, marketing_new_post, marketing_edit_post, marketing_skip_post,
marketing_replan, marketing_post_now) act on Solutionist's own suite desk
through B10's handlers, MC Today and the Mission Control Chief digest read the
suite desk (plus the standing OK, pulled posts and the Buffer drain's
leftovers), and the drawer gets a suite prompt and snapshot. New module
platform_chief_suite.py; small routing in platform_chief_authority (groups,
propose, decide), platform_chief_actions (dispatch), platform_console and
platform_today. No migration. Docs: docs/MARKETING_DESK.md, "With the suite
on, Platform Chief and MC Today". Tests: __tests__/test_platform_chief_suite.py.
