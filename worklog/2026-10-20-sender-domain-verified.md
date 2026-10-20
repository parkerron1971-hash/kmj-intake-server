---
title: Team invites, accountant invites, contractor payment notes and reports send from the verified mysolutionist.app
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"ok let''s fix email when you can ... mysolutionist.app is good" (Kevin, 2026-10-20), after Love City''s team invite to its executive pastor could not be emailed'
status: shipped
prs: [kmj-intake-server#1520]
migrations: []
left_undone: []
decisions: ["send from invites@/payments@/reports@mysolutionist.app (the domain Resend has verified, which member codes and class reminders already use) rather than verifying solutionist.studio (Kevin)"]
related: [2026-10-20-church-group-space.md]
---
Resend refused every email from @solutionist.studio ("The solutionist.studio domain is not verified", 403 in the live log at 12:03 UTC): team invites (the page fell back to "share this link"), accountant/collaborator invites, contractor payment notes and both report emails. All five senders now use mysolutionist.app, and `test_sender_domain_verified.py` fails if any source file sends from @solutionist.studio again. Love City's pending invite (Jessica McCloud, Admin) was created before the fix; Kevin shares its link by hand.
