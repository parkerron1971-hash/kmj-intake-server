---
title: Guest Welcome Path (visitor flow upgrade)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "we need to upgrade the visitor flow experience ... chief should be sending a follow up call to the admin of people and care or a church should be able to assign who should be over this", then "by default the calls goes to people and care until we get a welcome team ... allow this to be selected by any church", then "build"
status: in progress
prs: []
migrations: []
left_undone: ["every door joins the texts", "who calls our guests", "guests room + scorecard", "call brief", "replies reach the caller", "weeks two to six"]
decisions: ["calls go to People & Care (first_guests) until the church has a Welcome Team; each church can pick its own way", "call due within 2 days", "Monday note signed by the senior pastor", "each church picks its own newcomers' event", "GUEST_PATH unset = owner; off is the rollback"]
related: [2026-11-14-new-here-guest-texts.md, 2026-11-17-guest-lane-new-here.md, 2026-11-17-guest-print-cards.md, 2026-10-26-checkin-welcome-handoff.md]
---
Mock: https://claude.ai/artifact/WmRiSK8seJky8pJUK5nztE (8 boards). The
first PR is the shared core, `guest_path.py`: the GUEST_PATH switch, the
doors, the guest's keys in contacts.metadata.new_here, and which follow-ups
are a guest's welcome call. The pieces build on it in this order: every door
joins the texts, who calls our guests, the Guests room and scorecard, the
call brief, replies reach the caller, weeks two to six.

Built on Kevin's direct "build" (11-20) after the mock; check Mission Control
→ Build → Plan before adding more in this area.
