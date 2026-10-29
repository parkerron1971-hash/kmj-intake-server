---
title: The office's Groups page, server side — how each group is doing, a word to every group, a nudge to a leader
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "you can continue to work on things." Next from the approved canvas "Church Groups, Together" (board Office: "Every group, alive. … see how each one is doing, help its leaders, and speak to every group at once. You never see their private chat.")'
status: shipped
prs: [kmj-intake-server#1536, solutionist-studio#1313]
migrations: [supabase/APPLY-2026-10-20-group-word.sql (applied)]
left_undone: ["Chief drafting a note to a quiet group's leaders (the canvas's second Chief move); the page names the group and opens it instead", "the canvas's 'pinned for a week': the word sits on top of each member's group Home until they press Got it"]
decisions: ["health is counts only: messages in each group's chat this week (delivered), Board posts and wall prayers this month, never a word of a chat; the safety picture: held this week, open reports, officers of 2, prayers that went straight to a pastor this week; a failed read is a 503, never a quiet group", "a word to every group is a group_posts row with no group and no author ('Your pastors' on the card), Got it asked; audience every group or the group leaders only (group_posts.audience; leaders-only shows only to a group's leaders); one 'groups' note to everyone in an active group (or its leaders), and an email to adults with no phone set up; any seat that can edit sends, any seat reads", "Remind <leader>: a 'groups' note to the group's leaders that people are waiting, once a day per group (ref_id); it says when group news is off so the office knows to call"]
related: [2026-10-20-church-group-space.md, 2026-10-20-group-news-by-email.md, 2026-10-20-chat-evening.md]
---
`church_groups_office.py` (new): GET /church/groups/health, POST /church/groups/word, POST /church/groups/remind (mounted in kmj_intake_automation). `member_portal_groups`: a leaders-only word shows only to leaders; the office's word reads "Your pastors · to every group (leader)". Migration: group_posts.audience.

Checks: 13 tests in `test_church_groups_office.py` (19 sabotages, 18 caught; the other, counting the office's own word as a group's post, can't happen: posts with no group are never counted); `group_word_db.mjs` 4 checks on PGlite, in CI (2 sabotages caught). Rollback probe on the live database before applying.
