---
title: First-time guests include card and first check-in guests
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'yes. go ahead with all 4'
status: shipped
prs: [kmj-intake-server#1759]
migrations: []
---

church_reads.first_time_guests read only attendance.first_time, which only the
office's First time box writes. Someone who filled out a card, or a family's
first check-in at the kids desk or kiosk, was missing from Chief's answer, from
the Roll's New guests and from Home's guest list, while their follow-up sat
waiting. So "who came for the first time?" could answer nobody. The list now
also reads open welcome follow-ups still on Reach out. A first check-in counts;
a card counts if its answers say they're new, or if it never asked and the card
itself made their record. "A few times" and "I'm a regular" don't count, and
neither does a long-standing member sending in a card. The same reach-out rule
takes them off, and an unreadable follow-up table reads as unknown, never as
nobody.
