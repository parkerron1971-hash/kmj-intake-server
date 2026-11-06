---
title: A signature fires its emails and events once
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "i want to use e-signature. can you see if it''s working right?"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions:
  - "The status write is the claim: the patch matches only a row not already in that status, so one delivery gets a row back and the rest stop"
  - "A failed write fires nothing; refresh and the next delivery still can"
related: []
---
A real three-signer test on the kept test church went through: signed in order at DocuSeal, audit log, signed PDF, and the webhook reached the server on its own. But the last signature sent three identical confirmation emails, because form.completed and submission.completed land together on several replicas and each read the row as still "sent". contract_signed fired three times too, and that event drives what follows a signed agreement.
