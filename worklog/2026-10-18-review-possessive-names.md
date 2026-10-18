---
title: The answer check reads "Monica's" as Monica
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "fix and retest" (after a Haiku 5.5 vs Sonnet replay of the answer check, to see whether the check can move to the cheaper model)'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "The review lane stays on Sonnet. Moving it (CHIEF_MODEL_REVIEW=claude-haiku-5-5, CHIEF_REVIEW_THINKING=low) is Kevin's call; how fast Sonnet is on the same 25 answers was not measured"
  - "The replay ran once per setting; Haiku's verdicts vary from run to run"
decisions:
  - "Strip the possessive only where a name is matched against a record (claim corroboration and the free sentence prover); which words count as names is unchanged"
  - "A contraction left after stripping (Let's, Here's) is not a name"
related: []
---
`chief_truth.py`: `_record_names` turns "Monica's" / "Monica’s" / "James'"
into the name a record holds, and drops a leftover contraction. The claim
corroboration (`_SentenceProver._corroborates`) and the free sentence prover
(`prove`, behind `fast_lane`) use it. Before, "Monica's $1,200 invoice is
overdue" looked for the word "monica's", which no record holds: the paid
check held it as "claim number 1200 is not in the quote" whenever the
reviewer quoted her invoice's status instead of its total, and the free
prover always sent it on to the paid check. "Monica owes $1,200" passed both.
A wrong figure, or someone else's figure, is still held
(`__tests__/test_chief_possessive_names.py`; 5 of its 7 tests fail without
the fix).

How it was found: 25 advice answers were recorded from
`scripts/chief_advice_eval.py` (fixture businesses), each with the Sonnet
check's verdict, and the check was then replayed with the review on Haiku 5.5.
The bench and corpus are in `C:\Users\kmccl\Projects\review-bench\`, not
committed.

| review | good answers held back | false answers stopped |
|---|---|---|
| Sonnet 5.5 (recorded) | 5 of 25 | n/a |
| Haiku 5.5, thinking off, before the fix | 8 of 18 (Sonnet 4) | 59 of 59 planted |
| Haiku 5.5, thinking low, before the fix | 5 of 19 (Sonnet 4) | 63 of 63 planted |
| Haiku 5.5, thinking low, with the fix | 5 of 25 (Sonnet 5) | 14 of 14 factual-eval bad drafts; 14 of 14 good drafts right |

With the fix, each model held back one answer the other passed. Haiku's
check took a median 9.6 s on these long advice answers. The replays cost
about $1, $1 and $0.23; whenever the review holds something back, the repair
runs on Sonnet, and that is most of the cost.
