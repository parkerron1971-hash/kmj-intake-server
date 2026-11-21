---
title: Guest calls go to People & Care before the Executive Pastor
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'where is the new flow? (Love City showed the Executive Pastor as the guest caller, not People & Care)'
status: shipped
prs: []
migrations: []
left_undone: []
decisions: ["among logins that hold First-time guests: People & Care's own lane first, then anyone it was given to, then an Executive Pastor or office overseer, then the owner"]
related: [2026-11-20-who-calls-our-guests.md, 2026-11-20-guest-welcome-path.md]
---
Love City's Guests room named Jessica (Executive Pastor) as the caller. She
holds every non-money duty through her seven areas, and the tie-break was
fewest open calls, then name, so she sorted ahead of People & Care.
guest_calls.first_guests_logins now ranks People & Care's own login first.
A test models Love City's seats and fails on the old ranking.
