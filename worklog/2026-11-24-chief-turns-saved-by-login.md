---
title: Chief's turns are saved under the login that asked, and each login recalls its own
date: 2026-11-24
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-23: "check out a conversation Jessica was having with Chief and the response chief was given"; her words could not be read. Then "yes" to saving staff conversations, each person recalling their own and the owner able to read all'
status: waiting on Kevin
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-24-chief-conversations-by-login.sql (NOT APPLIED)]
left_undone:
  - "NOT APPLIED: supabase/APPLY-2026-11-24-chief-conversations-by-login.sql. Until Kevin runs it, only the owner's turns are saved, exactly as before"
  - "The owner reading the team's conversations: not built. The rows are kept apart on purpose (they never show unnamed in the owner's own history or recall); the read for the owner, with each conversation named, is the next change"
  - "The app's own four-hour sweep (ChiefOfStaff.tsx archiveToServer) still saves as the person: the owner's lands with no login (it reads as the owner's), an office login's is still refused. The server's save covers every turn, so nothing is lost"
  - "Platform quality (chief_quality) reads every saved reply, the team's too from now on: more replies in the 'couldn't verify' counts, which is what it is for"
  - "No live Chief eval was run"
decisions:
  - "Why nothing was saved: chief_conversations had one rule (owner only, APPLY-2026-09-08) and no login column, and a turn is archived as the person who asked. An office login's save was refused without a word: Love City, the week to 2026-11-23, 72 turns and 18 saved"
  - "user_id (who asked) on the row, written by the server from the verified session, for the owner's turns too. A row with none was saved before today or by the owner's own app: the owner's"
  - "Row rules: the owner reads and writes the owner's own and the ones with no login; any other login reads its own while it is still on the team (is_business_member, the existing SECURITY DEFINER helper: no new cross-table rule, no 42P17 cycle). Nobody reads another login's rows through the app"
  - "The code is safe before or after the file: user_id is written, and the recall filtered, only once the column answers (schema_probe)"
  - "recall_conversation is every login's (it was the owner's and the admins'): the read keeps to whoever is asking, said by the server (_recall_whose) and by the row rules. A surface with no login in it (the connector) acts for the owner, never for the team"
  - "The nightly brain pass learns from the owner's conversations only (chief_brain_pass._owners_own): what it learns becomes how Chief works for the business, and an office login's words are not the owner's"
related: [2026-11-23-chief-held-says-it-again.md, 2026-10-02-chief-conversation-gaps.md]
---
Before building I read both repos' work logs: the conversation recovery and gaps
logs (10-02), and the confirm-loop fix this came out of (11-23). No open PR
touches the conversation archive.

`chief_of_staff._archive_turn` saves through the service role with the turn's
login once `chief_conversations.user_id` exists; `handle_recall_conversation`
adds `_recall_whose`; `chief_areas` places `recall_conversation` for every
login; `chief_brain_pass.gather` reads the owner's rows. Tests:
`__tests__/test_chief_turns_by_login.py` (the save both ways, the recall filter
per kind of asker, the lane placement, the nightly filter, and the SQL's rules
read as text).

Kevin applies the SQL by hand: its check-before and check-after queries and a
rollback are in the file.
