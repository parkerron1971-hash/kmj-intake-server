---
title: Chief names a design by what was asked for and says it is on it once
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin: whatever is missing, make the upgrades so it's better"
status: done
prs: [kmj-intake-server chief-design-noun-and-once, solutionist-studio chief-design-noun-and-once]
migrations: []
left_undone: ["respond_work_order still returns its summary as label and result and reply (rarer, same pattern)", "A message that starts a plan and another job still says two different background sentences"]
decisions: ["The started-job sentence is the receipt's say field, spoken once in the reply; label and result are one short line (Started your thumbnail)", "design_noun(goal, size, owner_request) in chief_code: the design's own brief first, then the owner's words, first noun named wins, else portrait is a flyer and other shapes a graphic", "No machine key changed: design_flyer, kind flyer and the flyer step name stay; only words people read", "public_job carries noun for flyer jobs so the app's done message and card title can use it"]
related: [2026-10-06-covers-look-like-the-person.md]
---
Live in Church, "Make a YouTube thumbnail" came back as "Designing your flyer" and
"All done with your flyer", and one reply printed "I'm on it and working in the
background. You can leave this chat" up to four times: submit() returned the
sentence as both label and result, the stream's step line ends with the label,
chief_truth.finalize_reply put the label after what had streamed, and the action
card printed label and result. The sentence now rides as `say` (the reply's one
copy) and the step and receipt say "Started your thumbnail". Every flyer-shaped
word people read (Director receipts, build stages, holds, questions, notices,
step start lines) now goes through design_noun.
