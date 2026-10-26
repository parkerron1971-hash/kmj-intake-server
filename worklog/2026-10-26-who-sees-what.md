---
title: Who sees what — each church login sees its areas, My week, one Serve tab, check-in hand-offs
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: "yes go with your picks and build it. make sure the design for frontend is top tier"
status: in progress
prs: [kmj-intake-server (this PR, login areas)]
migrations: [supabase/APPLY-2026-10-26-login-areas.sql]
left_undone: ["My week endpoint", "the Serve tab in the member app", "a first-time check-in starts a welcome follow-up (separate PR)", "the morning brief and Chief narrowed per person", "tasks handed to a person", "Areas & Keys steps 2-3 (the walls)"]
decisions: ["Kevin's picks: the tab is called Serve; a first-time check-in starts a welcome follow-up; volunteers get a part, not an office login; every login shares the church calendar", "the owner and admins see everything; a login nothing places sees everything, as before", "Giving is never offered as a login's area: money stays walled to owner, admin and accountant", "everything rides CHURCH_AREAS: off | owner | on; switches on on a Thursday (this is the quiet week)"]
related: [2026-10-23-church-areas-and-keys.md]
---
Kevin worried that once pastors, admins and teams sign in, the system gets overwhelming
(canvas "Who Sees What", https://claude.ai/artifact/99aFvCSRXU1x9pmqUcncoP). The fix is
the layer between who's allowed in and the screen: what each person is shown, and what's
theirs to do. It's part of the Build item "Church areas and keys".

This PR: each office login carries its areas. `church_areas.login_view` decides what one
login is shown: the church's own pick (`business_users.areas`), else Chief's guess from the
roles and teams its person holds (matched by email: a Lead tab role, ChurchSavvy's team,
kids check-in, leading a group, safety officer), else the whole church. `/team/my-role`
carries `areas` and `areas_by` for a church when CHURCH_AREAS is `on`; a failed read shows
what was shown before. The map (`GET /church/areas`) lists every login with its view;
`PUT /church/areas/login` lets an admin pick a login's areas or send it back to the guess.

Before building more here: this only shapes what the app shows. Every router still checks
its own role; the walls are Areas & Keys steps 2 and 3.
