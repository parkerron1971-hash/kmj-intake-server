---
title: Connecting a Gmail inbox is retired; church email replaces it
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: "yes retire the gmail for now (after: I thought we was deleting this because the cost to do the connection because we would have to pay for a security)"
status: shipped
prs: []
left_undone: ["Google's OAuth verification request for gmail.readonly (project solutionist-mail) is still on file; withdrawing it or removing the scope from the consent screen is Kevin's call in the Google Cloud console."]
decisions:
  - "Reading a Gmail inbox (gmail.readonly) needs Google's yearly CASA review (about $540 a year and up) to lose the unverified-app warning and the 100-person cap. Church email does the job without it. Production had ONE google_mailboxes row ever: KMJ Creative Solutions (the platform owner's own test), revoked, last sync 2026-10-29."
  - "Off unless GMAIL_CONNECT=on: /connect/google/start and /connect/google answer 410 with the plain reason, the callback shows it, gmail_sync.sync_tick skips. The code stays so it can come back. Reading already-synced messages still works."
  - "Chief's email_setup_status never offers Gmail while retired, and a verified domain counts as ready without an inbox."
  - "Sign in with Google is a separate client (Supabase) and is untouched."
related: [2026-11-14-church-mail-signature.md]
---
Kevin asked to retire the Gmail inbox connection because of the yearly Google
security review it would need. Nothing new can connect, the sync job stops, and
Chief stops suggesting it; church email brings mail in instead.
