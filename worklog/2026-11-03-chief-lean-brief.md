---
title: Chief's short brief (CHIEF_BRIEF=lean) — the same verbs and rules, ~40% fewer tokens a message
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "I have read on the shrink, you can start on that" (cold Chief messages write ~120k tokens and lose money on church credits)'
status: shipped, switch off
prs: [kmj-intake-server#1736]
migrations: []
left_undone:
  - "Turn it on: CHIEF_BRIEF=lean on the kmj-intake-server web service (the worker never builds Chief's brief). Then watch `railway logs --filter \"cache rewrite\"` (a cold message should write ~65-70k, not ~120k) and `--filter \"chief lean\"` (a one-line verb that ran without its how-to looked up)"
  - "Two rare-actions misses in lean, both judgement rather than reach: 'capture this idea' went to save_note (kept, and its own how-to accepts kind=idea), and 'draft a LinkedIn post about why we raised prices' asked for the reasons instead of drafting with plan_content"
  - "The static instruction blocks in the snapshot segment (what-if, weekly planning, decision support, website building, testimonials, video creation: ~3.5k tokens a business) were left where they are; they could become lookups or move to the shared block"
  - "The RULE sections are kept whole (~15k tokens) and nobody has edited them for length; the manual itself is ~78k tokens in full and grows with every feature (the short edition is cut from it automatically)"
  - "Read-tool use is not recorded anywhere (audit_log holds actions only), so the always-loaded reads (CORE_READS) are a judgement, not a count; add a tool-call tally if the deferred set needs tuning"
  - "Keep-warm (chief_keep_warm.py, another session's) copies payload['tools'] as sent, so it keeps the lean prefix warm as long as it keeps replaying the request's own tools (defer_loading flags and action_guide included) rather than rebuilding them"
decisions:
  - "One switch, CHIEF_BRIEF=lean; unset is today's brief byte for byte (KMJ's and Love City's prompts built from production data on this branch compare equal to main's)"
  - "Kept in full: the 38 verbs that did 90.5% of the 358 Chief actions in audit_log (actor_type chief) over the 60 days to 2026-11-03, churches included; the verbs whose how-to is an approval, send, money or undo rule (ALWAYS_VERBS); every RULE section whole"
  - "Every other verb keeps one line in its section (the request words the manual routes to it, or what it is) and its full how-to comes back from action_guide, cut from the same manual text: one source of truth, nothing reworded"
  - "An area none of whose verbs is kept keeps its header line; three such areas send their prose to the lookup (workspace layout, timers, revenue & tax), pinned by a test so a new one is a decision; EXPENSES and REPORTS keep theirs (a closed-books rule, a 'you can attach files')"
  - "Tools: none removed; outside the kept verbs and CORE_READS they carry defer_loading, and action_guide loads one with a tool_reference (the API rejects a tool_result that mixes text and a reference, so a deferred tool's description carries its manual how-to)"
  - "Snapshot digest: the top 15 saved memories plus every standing instruction and insight, memory text capped at 320 chars, 25 of the 60 contacts in CONTACT LOOKUP, the 6 latest texts, the 5 latest emails, and a SHORTENED IN THIS SNAPSHOT note. The answer check reviews the same digest, so a dropped fact needs a read this turn. Name resolution and the mailbox gate keep the full ctx"
  - "The lean tools travel only with the lean manual (its heading is the marker) and only when the turn can call tools; a lookup spends no read budget and the round cap is one higher"
  - "action_guide's answer is manual text and says so; the lean manual's intro tells Chief only that tool's answer instructs, the same words arriving any other way are data (TRUST BOUNDARY)"
related: [2026-10-11-memories-to-turn-tail.md]
---
Chief's brief was ~135-141k tokens a message, measured with count_tokens
on KMJ and Love City (tools 27.4k, manual 78.0k, the business's own block
6.3k, the snapshot 18.2-23.4k, the turn tail 4.5-5.5k). With
CHIEF_BRIEF=lean it is ~79-85k: tools 11.4k, manual 42.9k, snapshot
14.3-18.8k; the business block and the tail are unchanged. On the eval
fixture a cold main call writes 65.8k tokens instead of 119.1k ($0.27
instead of $0.49).

Evals, same cases on both briefs (live spend $10.70 of the $20 budget):
turn eval 199/204 today vs 196/204 lean (4 vs 5 cases with a miss, the
misses stochastic and different); factual eval 13/14 vs 14/14; advice
eval answered 68% vs 84% (withheld 8 vs 4 of 25); the new rare-actions
eval 10/10 vs 8/10 (7 looked up first). Warm main call 2.20c vs 1.68c.
The PR body has the full table.

Before changing the manual, read chief_lean_brief.py: KEEP_VERBS,
RULE_SECTIONS, AREA_PREFIXES and PROSE_KEPT decide what the short edition
keeps, and __tests__/test_chief_lean_brief.py proves nothing is lost.
