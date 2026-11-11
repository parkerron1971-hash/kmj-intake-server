---
title: Email Setup walks Namecheap domains through Mail Settings and guards the church's own mail
date: 2026-11-11
agent: Claude Code (Claude Opus 5.5)
asked: '"I want to make sure the instructions in the system are good for anyone" ... "yes make the change" (Kevin, 2026-11-11), after the MX record from Email Setup could not be found in Namecheap while setting up Love City email'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (Email Setup Namecheap panel)]
migrations: []
left_undone: ["Namecheap's own docs never confirm that Email Forwarding keeps working under Custom MX with eforward1-5 re-added; one third-party Resend+Namecheap guide does it that way. The steps end with a test message and a way back (switch to Email Forwarding) for that reason. Love City's first run will settle it.", "lovecityc.com's apex SPF TXT (include:spf.efwd.registrar-servers.com) was gone by the time the snapshot code first read it (11-11), so Love City's snapshot has no SPF to offer back."]
decisions: ["the steps are written by the backend (email_domain_dns.namecheap_note) so the screen and the 'email these to my web person' message say the same thing", "mail_before is stored once from dns-check (first sight, before the operator touches DNS) and replaced only when the live MX gains a new host (a deliberate move); never on empty or shrunk answers, which are what we warn about", "a failed apex MX lookup is 'unknown', never 'your mail is gone'"]
related: [2026-10-20-sender-domain-verified.md]
---
Namecheap keeps MX records behind its Mail Settings switch. While that says Email Forwarding, Private Email or Gmail, MX isn't in the Host Records list, so Resend's bounce MX on `send` can't be added. Changing it to Custom MX deletes the apex mail records Namecheap was managing, and the church's own email stops. The setup screen only linked Namecheap's TXT article.

Now `GET /email-domain/{id}/dns-check` also returns `mail` (the zone apex's MX now vs. `settings.email_domain.mail_before`, plus `missing`/`lost`) and, on Namecheap, `mail_note` (numbered steps plus the exact records to keep). Share-records appends the same steps as text. The frontend shows the steps until our MX is found, a red warning if the apex mail vanished (any provider), amber if some records went, and a green "still in place" line once our MX is found. Love City (lovecityc.com, Namecheap Email Forwarding) was the case; checked against its live DNS on 11-11.
