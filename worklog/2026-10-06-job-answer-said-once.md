---
title: Answering a job in progress says its sentence once, and a plan beside another job says you can leave once
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "Fix the remaining Chief repeats itself case: respond_work_order still uses its summary as label, result and reply; if cheap and safe, a plan and another job should say the background sentence once"
status: done
prs: [kmj-intake-server job-answer-said-once]
migrations: []
left_undone: ["A refused start or answer still prints its reason as the step line end, the reply and the receipt label (label equals result; the app hides the repeated result). Same as before for submit_work_order", "respond() still stores the summary_label Your build is queued to continue, which is the reply for an answered job; it says build, not the job name, and does not say they can leave", "An already existing job re-submitted beside a plan still leads with the generic I am on it sentence (rare)"]
decisions: ["respond_work_order label and result are one short line naming the job (Resumed your thumbnail, Cancelled your plan); the job's summary_label rides as say, said once in the reply", "job_sentence in chief_build_runtime merges every started or continued job into one sentence; plain jobs lead as Started your thumbnail and your form, a plan keeps its named pieces, and one You can leave this chat closes it", "One job, or several jobs saying the same sentence, reads exactly as before", "with_job_sentences and the receipts-only reply both go through job_sentence, so the order of the jobs no longer decides which one is heard", "Failures keep their reason as both label and result, unchanged", "The respond_work_order step line starts Continuing the work or Cancelling the work, never the verb"]
related: [2026-10-06-chief-design-noun-and-said-once.md]
---
The leftover from the said-once work. When the owner answered a job's
question, said go ahead, or cancelled it, `handle_respond_work_order`
returned the job's summary ("Your build is queued to continue.") as the
label, the result and, through the receipts-only path in
`chief_truth._finalize_reply`, the reply. The step line ended on the label
too, so one answer printed the same sentence three times. Now the receipt
says "Resumed your thumbnail" (or "Cancelled your thumbnail") and the
summary is `say`, said once.

A message that started a plan and a thumbnail printed two background
sentences, each saying they could leave. `job_sentence` now merges them:
"Started your thumbnail. Working on these in the background: Add Ada and
Call Ada. You can leave this chat; ..." once. Tests are in
`__tests__/test_job_answer_said_once.py`.
