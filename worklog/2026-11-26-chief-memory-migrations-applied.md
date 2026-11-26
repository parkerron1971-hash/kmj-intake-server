---
title: The two Chief memory migrations are marked applied in the ledger
date: 2026-11-26
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-26: "run supabase again", then "i just ran both"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-24-chief-conversations-by-login.sql (APPLIED 2026-11-26), supabase/APPLY-2026-11-25-chief-thread-summaries.sql (APPLIED 2026-11-26)]
left_undone:
  - "Neither file's check-after was read back: Kevin stopped the browser before the read ran, and said he had run both. The first file's own run answered 'Success. No rows returned'; nothing was seen of the second"
  - "No live Chief turn was watched after: whether a team login's turn is now saved, a long chat is folded, or 'last time' shows has not been seen in production"
decisions:
  - "Check-before on production (read-only, 2026-11-26): chief_conversations had no user_id, exactly one policy (chief_conversations_business_owner ALL), both helpers present, no chief_thread_summaries table, 955 rows. That is what the first file expects"
  - "The first file was run from the editor with its hash checked against main's copy; Kevin then ran both himself. Both are safe to run twice"
  - "With both applied, three things switch on by themselves: every login's Chief turns are saved under that login (CHIEF_TURNS_BY_LOGIN), a long chat's oldest messages are folded into a summary (CHIEF_THREAD_SUMMARY), and a team login's new chat starts with where it left off (CHIEF_LAST_TIME). Each has its off switch"
related: [2026-11-24-chief-turns-saved-by-login.md, 2026-11-25-chief-long-chat-summary.md, 2026-11-25-chief-last-time-per-login.md]
---
`docs/MIGRATIONS.md` rows for the two files now say APPLIED with what was and
was not checked. The two tests that pinned "NOT APPLIED" in those rows pin that
the row says where it stands.
