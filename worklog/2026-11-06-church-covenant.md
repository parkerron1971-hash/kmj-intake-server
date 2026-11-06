---
title: The admin covenant goes out to sign from the app
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "can you align the covenant so when they open the app it would pop up? i want to use e-signature."'
status: shipped
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
  - "DocuSeal opens a later signer's link before their turn, so the order holds because the server hands out a link only on that person's turn"
related: [2026-11-06-esign-once.md]
---
The covenant is the Claude Doc (https://claude.ai/artifact/62V8Qy7qbPRt4Httvp7Mw3). GET /church/covenant says what a login owes right now, and it reads DocuSeal for whose turn it is, by the covenant's order rather than DocuSeal's list. A failed read shows nothing, because this never stands between someone and their app. A real form was built on the kept test church with fake people.

Proved on the test church, 2026-11-06, submission 13225000: three fake people signed the real page in order, the webhook moved our row to completed, and exactly one Signed email went out (three before #1753). Chromium at Letter with 0.4in margins matches DocuSeal's PDF exactly, page by page, so page breaks can be tuned locally without spending a document. That is how the stranded "Keeping it" page went away: the covenant is four pages.
