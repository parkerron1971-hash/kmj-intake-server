---
title: A reply to a church mail copy goes out from the church address
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'do what is needed to make sure that the system is equip to send and receieve emails with no problems … I want to make sure that this becomes setup for every church so that it works for everyone'
status: in progress
prs: ["kmj-intake-server#1811"]
migrations: []
left_undone: ["Writing a NEW email as tia@lovecityc.com (not a reply) still needs the Email room or a Chief verb; replies are covered", "Email Setup has no 'Receive mail here' screen yet (mock first); Chief's switch_on_church_mail covers every church meanwhile"]
decisions: ["A copy's Reply-To is a one-message relay address at the church's domain: r + the church_mail row id (32 hex) + a 16-char HMAC over the id and the person the copy went to (CHURCH_MAIL_SECRET, else the service-role key; no secret means the old Reply-To, the sender)", "A reply to it goes to that message's sender only, from the address the mail came to, threaded with In-Reply-To/References; only when it comes from the person the copy went to and DMARC passes, so a spoofed From or a leaked address sends nothing", "A refused reply is held; the person hears why and who to write directly, unless the From wasn't theirs (a stranger's try tells no one)", "An automatic reply answering a copy is never sent on as the church (two responders would answer each other)", "switch_on_church_mail checks for a CNAME at the domain's root (a website connected with 'CNAME @', as kmjcreate.com was) and says to make it an ALIAS first, with Namecheap's steps"]
related: [2026-11-13-church-mail.md, 2026-11-13-church-mail-switch.md]
---
Kevin asked that the system send and receive church email with no problems,
for every church. Copies already reached each person's own inbox, but a reply
went out from their personal address. Now it goes out from the church address
it came to, without any new screen.

The CNAME check comes from kmjcreate.com on 11-13: its root was a CNAME to the
website, so no MX record could take effect. I swapped it to an ALIAS with the
same value on Kevin's yes, the site still answered 200, and Resend verified
the receiving record.
