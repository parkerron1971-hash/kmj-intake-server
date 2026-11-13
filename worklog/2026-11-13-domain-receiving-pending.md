---
title: Turning on receiving no longer takes a church's sending down
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'i sent the test email, check it'
status: in progress
prs: []
migrations: []
left_undone: []
decisions: ["Sending health is read from the sending records (email_domain_dns.sending_status): Resend's own status covers receiving too, and a pending receiving record reads partially_verified", "Every sending record verified is verified, whatever the receiving record says; a sending record not verified is still pending, and Resend's failed with no records is still failed", "The monitor and Email Setup's status, verify and health reads all use it, so a church switching its mail over keeps its own sending identity and gets no 'stopped verifying' email"]
related: [2026-11-13-church-mail.md, 2026-11-13-church-mail-switch.md]
---
Kevin's test to test@lovecityc.com arrived at 12:09 and was sorted to Love
City. The copy went to his login's inbox, and Resend shows it delivered.

While checking, I found two monitor emails, "lovecityc.com stopped verifying"
and then "sending again". Turning on receiving left the domain
partially_verified until the MX moved, and the monitor flipped the church's
sending to failed for about 20 minutes. Its mail would have gone out from the
platform address in that time. Every church switching over would have hit
the same thing.
