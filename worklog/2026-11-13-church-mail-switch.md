---
title: Chief switches a church's mail on
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'can we muild what is needed so this can go live right away?'
status: in progress
prs: []
migrations: []
left_undone: ["kmjcreate.com: receiving is on at Resend (its MX record is receive.forge.rmta.net, priority 10), but the MX isn't added yet; its @ is a CNAME, which must become an ALIAS (same target) before an MX can sit beside it, and that waits on Kevin's yes", "Love City's cut-over: the addresses people use today and who reads the office box come first"]
decisions: ["switch_on_church_mail is the owner's alone: it changes where the church's mail goes. It turns receiving on through Resend's update-domain API (capabilities.receiving) with the domain id Email Setup stored, so no one needs the Resend dashboard", "It names the one MX record and what it replaces, with Namecheap's steps when the zone is Namecheap's, and warns that every address people use today needs a box first; asked again once the record is in, it asks Resend to verify it (Resend drops mail until the receiving record is verified)", "Resend's receiving host for this account is receive.forge.rmta.net (Forge), which church_mail.RECEIVING_MX already matches", "A person's own automatic reply (Auto-Submitted: auto-replied from the address a copy went to) isn't copied back to them; anyone else's still is"]
related: [2026-11-13-church-mail.md]
---
The follow-up to #1809. Chrome wasn't signed in to Resend and the server
already holds the key, so the switch belongs in the system: every church
needs it, and Kevin can say it to Chief.
