---
title: A new office login gets its church email address when it accepts
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'build these (… Chief doesn''t yet offer an address automatically when you invite a new login …)'
status: in progress
prs: ["kmj-intake-server#1826"]
migrations: []
left_undone:
  - "Chief has no verb that invites a login (invites come from the Team page), so the address rides the invite itself rather than a Chief offer."
decisions:
  - "Only a church whose own domain's mail comes here (church_mail._live_church). Anyone else's invite is unchanged."
  - "The invite plans the address from the name the church knows the person by (their record) and names it in the invite email and the Team page's notice. With no name yet, the email says an address comes with accepting."
  - "Accepting gives it: church_mail.give_new_login makes the login's own box (never a second one, nor one beside a box for the person it already is), then the welcome note goes once. The name they signed up with is used when the church had none."
  - "Best effort both ways: an invite and an accept never fail over the address; a failure is logged and the login is in."
related: [2026-11-13-church-mail-room.md]
---
Kevin asked for new logins to get their church address without anyone
having to ask Chief for it.
