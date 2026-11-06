---
title: The admin covenant goes out to sign from the app
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "can you align the covenant so when they open the app it would pop up? i want to use e-signature."'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio church-covenant-gate (the popup)]
migrations: []
left_undone:
  - "Nobody has been asked. It waits for Kevin to read the wording and press Send in the popup"
  - "One church's words live in church_covenant_text.py. A second church needs them as data"
  - "No treasurer page: their money promises differ, and the seat is empty"
decisions:
  - "CHURCH_COVENANT, owner when unset: the platform owner's church, until a Thursday flip"
  - "Each admin's covenant is one DocuSeal submission from HTML (/submissions/html), signed in order: Admin, Executive Pastor, Senior Pastor. Nobody is emailed by DocuSeal"
  - "Its record is an esign_documents row, source_ref covenant:<version>:<user id>, so a signature takes the road every other one does: webhook, ledger hash, a copy to both sides"
  - "Duties come from church_duties, so the page can't drift from the role"
  - "The owner sends it. Sending twice asks nobody twice, and someone who joins later is the only one asked"
related: [2026-11-06-esign-once.md]
---
The covenant is the Claude Doc (https://claude.ai/artifact/62V8Qy7qbPRt4Httvp7Mw3). GET /church/covenant says what a login owes right now, and it reads DocuSeal for whose turn it is, by the covenant's order rather than DocuSeal's list. A failed read shows nothing, because this never stands between someone and their app. A real form was built on the kept test church with fake people.
