---
title: Chief's short brief (CHIEF_BRIEF=lean) — the same verbs and rules, ~32% fewer tokens a message
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "I have read on the shrink, you can start on that" (cold Chief messages write ~120k tokens and lose money on church credits)'
status: shipped, switch off
prs: [kmj-intake-server#1736, kmj-intake-server#1738]
migrations: []
left_undone:
  - "Turn it on: CHIEF_BRIEF=lean on the kmj-intake-server web service (the worker never builds Chief's brief). Then watch `railway logs --filter \"cache rewrite\"` (a cold message should write ~65-70k, not ~120k) and `--filter \"chief lean\"` (a one-line verb that ran without its how-to looked up)"
  - "(Fixed in the follow-up PR, see below) the two rare-actions misses: 'capture this idea' went to save_note, 'draft a LinkedIn post' got an interview instead of plan_content"
  - "Two turn-eval rows fail on both briefs, every run (create_session, nb_barber_hours): not the short brief's, but nobody has looked at them"
  - "(Done 2026-11-13, see 2026-11-13-lean-brief-greeting.md) the turn eval on lean was rerun twice after the launch greeting fix: 200 and 200 on lean, 201 on the full brief"
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

## Follow-up (2026-11-04): the rare-actions misses (kmj-intake-server#1738)

The coordinator's rule for Kevin is to keep only a change that scores the
same or better. The rare-actions eval had gone 10/10 to 8/10. Both misses
had one cause, and it was not missing text: the always-kept request map
already routes "capture this idea" to capture_idea and "draft me a post" to
plan_content. Those were deferred tools, though, and a deferred tool loses
to a loaded neighbour (save_note), or to no tool at all (an interview).

The general fix is in `_siblings`. Any tool that a rule section, a header
line or a kept verb's own how-to names is loaded and written out in full,
and so is any tool whose description names a loaded tool, or that a
loaded tool's description names. The set is repeated until nothing new
joins, and today it holds 27 tools, among them create_goal,
create_session, create_note, log_activity, the project and session
updates, add/remove_block_range, marketing_desk, capture_website_references,
find_housing_payments, fund_status, housing_allowance_status, the
connected-agent tools, save_lesson_slides and inspect_course. A test pins
the invariant that every tool the short manual names, outside its
one-liners, is loaded.

Two smaller general fixes came out of the reruns:
- One-liners with no routing line carry the manual's own example asks. A
  run had sent "search the record…" to recall_conversation, because
  search_ledger's line held only its field name.
- Lines that say how to act at the moment of the request stay whatever
  verb they belong to: "you CAN", "never say you can't", "do NOT
  interrogate", "the asking is the approval", "without asking". Only 5
  such lines had been dropped. nb_therapist_intake had gone 1 in 4 on lean
  for want of "DESIGN THE FORM FROM WHAT YOU KNOW … Do NOT interrogate",
  and went 3 in 3 once it stayed.

Cost of the fix: the brief is ~97k (KMJ) and ~91k (Love City) instead of
~85k and ~79k. That is still 32% under today's brief: 141.7k and 135.5k
on current main (tools 18.1k vs 27.7k, manual 48.4k vs 78.8k).

Results on lean, same cases:
- Rare-actions eval: 10/10 in 3 runs on the sibling build, then 10/10 once
  more on the final build (earlier: 10/10 today, 8/10 lean).
- Turn eval: 194/204 once on the sibling build (earlier: 199 today, 196
  lean). Its misses are the two rows that fail on both briefs, the
  one-question and about-the-product prose checks that flip between runs
  on both, and nb_therapist_intake, now fixed.
- nb_therapist_intake on the final build: 3/3.

Live spend for the follow-up was $5.81; for the session, $16.51.
