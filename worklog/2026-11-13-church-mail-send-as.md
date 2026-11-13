---
title: Chief sends a person's email from their own church address
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'we need to setup the email room for everyone so when they go there, they can fill out what is needed for email to work unless there is a simple process. I want everyone to send out emails today...'
status: in progress
prs: []
migrations: []
left_undone: ["The Email room (read, write, a Sent list, in the app) waits on a mock and Kevin's yes; this is the simple process meanwhile", "A draft approved later on Approvals goes as the church's address: drafts don't record who wrote them"]
decisions: ["One-to-one emails Chief sends for the login talking to it go out FROM that login's own church address (church_mail.sender_box) with the reply coming back to that address, so it reaches them as a copy and their answer goes out as the church address again (the relay, #1811)", "Only while the domain's mail comes here (mail_comes_here), so the replies have somewhere to land; a login off the team never sends as the church; a read that fails sends as the church, as before, never a held send", "Bulk mail (batch_email) and unattended sends stay the church's address and its routed reply"]
related: [2026-11-13-church-mail.md, 2026-11-13-church-mail-relay.md]
---
Kevin wants everyone to send email today. The simple process needs no new
screen. A person gets an address from Chief (the pastor, Naiya or Jessica can
give one). They ask Chief to write to someone, and the email goes out from
their own address. Replies come back to their inbox, and when they answer,
the reply goes out as the church address too.
