---
title: Is this right? Office logins check their work with Chief, and corrections go to the Pastor for a yes (B11)
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "yes to both, build it" (docs/CHURCH_LEADERS_STEP2.md §10): Chief introduces itself to an office login from the login, and their corrections arrive as one-tap edits'
status: in progress
prs: [kmj-intake-server#1731]
migrations: [supabase/APPLY-2026-11-05-church-map-asks.sql (NOT applied; Kevin applies it by hand)]
left_undone:
  - "F8 (solutionist-studio): Is this right? on My week (GET /church/map/asks/mine: checked_at, due) and From your team on the department sheet (GET /church/map/asks, POST …/{id}/apply|done|discard), checked at 1280px and 390px; show an ask's waiting change once, under From your team, by change.id"
  - "Apply supabase/APPLY-2026-11-05-church-map-asks.sql; until then every B11 verb says it isn't ready and its routes answer 503"
  - "No What's New entry until CHURCH_MAP switches on (F2's rule)"
decisions:
  - "church_map_asks.py: my_work and list_asks (sensitive reads, mid-turn too); confirm_my_work, suggest_work_change, note_gap (an office seat: Manager or Admin); answer_ask (the owner or an admin; a sixth verb so Chief answers through the routes' own code)"
  - "Open by the church (church_map.church_open), not the login, so Love City's office reaches it while CHURCH_MAP is owner"
  - "A check keeps what my_work showed (`work`, by key); the check comes back when today's differs, which also catches a lanes duty moving away"
  - "A suggestion's map part is a waiting change made by the speaker (church_map_batch.suggest); parts Chief can't make send nothing and say why; a duty move keeps who had it then and never moves over a later move"
  - "Who sees what (about: access, or a can_see_all part) goes as words only; money parts are the owner's; ten a day; the same gap inside 7 days joins the open one"
  - "Separate commits, B5's #1729 review leftovers: apply_pending lets go of what waited on drafts a finished undo took out; a change whose final mark didn't save never promises Undo"
related: [2026-11-05-church-step2-chief.md, 2026-11-02-chief-duties.md, 2026-10-28-chief-who-is-talking.md]
---
An office login (Tiara, People & Care) opens Chief. The THIS LOGIN block offers the check once, early. Chief
reads `my_work` (her lane, jobs with their days as My week walks them, the departments she helps, roles, who she
answers to) and asks if it's right. "Kids check-in is Laquesha's now" becomes a fix: her words plus a duty move.
It waits for Pastor Kevin or an admin. One tap on Apply moves the duty through church_duties' own move, and her
next turn tells her once. The owner and an admin hear "N things from your team wait for your yes". Details are in
docs/CHURCH_LEADERS_STEP2.md §10, "As built in B11".
