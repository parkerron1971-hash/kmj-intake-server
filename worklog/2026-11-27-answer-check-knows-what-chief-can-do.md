---
title: The answer check is told what Chief can do for the person in the chat, so an honest offer isn't held back
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-27, after asking Chief to work on the offering: "it knew what i was asking with confidence ... but when i said what said it said it could[n''t] verify it''s answer. that needs to be fixed in general"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Not re-measured live yet. Before: in the 14 days to 2026-11-27, 3 of 138 saved replies (2.2%) were replaced by 'I couldn't verify my proposed answer' and 4 (2.9%) carried an 'I couldn't confirm' line (read-only count of chief_conversations, no text read; office logins' turns were not saved before 11-26, so the true rate is unknown). Count again in a week"
  - "The second gap in the same turn is not closed: a reply that leans on what an EARLIER turn read (the 22nd's count was read in the turn before) has only the conversation as evidence for it, which the review rightly won't take as current fact. With the offer supported as a capability the reply should pass; a reply that states the earlier read as fact still won't"
  - "No live Chief eval was run"
decisions:
  - "Cause, from the live logs (00:02 UTC 11-27, Love City): 'claim without support: Whenever you have the gift amounts and names for the 22nd, just tell me and I'll ... (Nothing in the supplied sources shows ... that Chief can record offerings)'. The review's only capability sources were invoice delivery and Chief's computer, so an offer of any other action had nothing to stand on"
  - "chief_truth.actions_capability: the actions THIS login may use (chief_areas.refusal is None for its lane) whose name and description share words with the draft, each with what it does (action_registry), at most 10. A capability source: it supports 'I can' and offers of work to come, never that anything ran, is set up, or what a record holds; an action claim still needs a receipt (assess_review is unchanged)"
  - "One sentence added to the review's instructions: an offer of work to come is supported by a capability source naming that action, and need not show the records it would act on ready now (the action checks that when it runs). The review's cached system prompt is written once again after the deploy"
  - "About 1,500 characters more review input on a turn whose draft names an action; nothing on one that names none"
related: [2026-11-13-answer-check-cost.md, 2026-11-26-church-skills.md]
---
Read both repos' work logs first; nothing open touches the answer check.

`chief_truth.py`: `actions_capability` and the `system:chief_actions` source in
`finalize_reply`, beside the two capability sources it already had; one sentence
in `REVIEW_SYSTEM`. Tests: `__tests__/test_answer_check_knows_what_chief_can_do.py`.
