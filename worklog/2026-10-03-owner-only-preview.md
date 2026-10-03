---
title: A no-card trial's site preview is only its own team's
date: 2026-10-03
agent: Claude Code (Claude Opus 5.5)
asked: 'build these (the reverse trial, owner-only previews, preview-only site cards)'
status: shipped
prs: [kmj-intake-server#1229, solutionist-studio#1115]
migrations: []
left_undone: []
decisions: ["the preview addresses (/public/site/{slug}[/page|/news], /sites/{id}/preview[-page]) show a no-card site only with ?pv=<token>; the token is HMAC over business and expiry (12h), minted by GET /billing/trial/preview-token for member+ seats", "merge the app side (which adds the token) BEFORE this, or owners see coming soon in their own preview"]
related: [2026-10-03-no-card-trial.md, 2026-10-03-reverse-trial.md]
---
The public address of a no-card trial's site already said "coming soon" until
a card, but the editor's preview addresses needed no sign-in, so the same
site could be shared from the API host. They now ask for a short-lived token
the app mints for the signed-in team; everyone else sees "coming soon".
Sites with a card, and every site outside a no-card trial, are unaffected.
