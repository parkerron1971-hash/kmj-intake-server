---
title: Hermes logs a standing finding once a day
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'finish everything. nothing is being sent out for text so make sure everything is good.'
status: shipped
prs: [kmj-intake-server#1191]
migrations: []
left_undone: []
decisions: ['same title within 24h is not re-logged; titles carry counts, so a changed number logs again']
related: [2026-10-02-sms-delivery-reports.md]
---
Hermes wrote 121 operator-log entries in a day and a half, mostly the same
"1 inbound text unanswered" finding every hourly tick. It now skips a title
it already logged in the last 24 hours. Texting itself checked healthy the
same day: Twilio active, A2P campaign VERIFIED, both numbers in the pool; no
texts since Sep 29 because nothing asked for one (no sessions since Aug 5).
