---
title: Leaders map fixes - Serve teams hang by name, saves say what they did, an answered ask has Undo, the map opens for Love City's office
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: fix what was found live on 11-03/11-04 (Chief refused to hang Love City''s Serve teams on its departments; Jessica got a 404 on the leaders map) and in the F8 frontend review (no made flag, no Undo for an answered ask, asks/mine says only a status)'
status: shipped
prs: [kmj-intake-server#1761]
migrations: []
left_undone:
  - "Frontend (solutionist-studio): show GET /church/map/asks `answered` (happened, put_back) with an Undo that posts /church/map/asks/{id}/undo (both parts, so an answer that moved a duty gets Undo too); use the apply answer's can_undo for the inline Undo; show `cant_apply` on an ask where Apply isn't offered; show asks/mine `happened` on My week; read a save's made/can_undo/note (DepartmentEditor, useMap.ts): solutionist-studio#1489"
  - "No What's New: the map is still CHURCH_MAP=owner (Love City only)"
  - "Picked up in 2026-11-06-church-map-open-items.md: the duties' login-only switch (Love City's admin couldn't move a duty through an ask), the two Undos for an ask's change, and the ten-a-day cap's same-instant race"
decisions:
  - "church_map.office_open(user, biz) = open_to(user) or church_open(biz): the map routes, the asks' map gate, Chief's map verbs (chief_map._map_open) and the role page's change log all follow it; seats unchanged (Manager reads, owner/admin writes, money the owner)"
  - "A unit's kind is taken in Chief's words (serve team, team, Serve teams, group, budget line, ...) or left out; a Serve team is the Serve card's team (the editor's Teams), else a Sunday team, which is a group; a name with no kind must fit exactly one kind; a kind that is none is a 400 in words"
  - "list_map says each held thing's kind and what is on no department yet (the editor's pickers); the prompt teaches units as the department's whole list"
  - "Logged saves (departments, archive, answers-to, settings) answer change, made, can_undo and note; before step 2's file made is None (not told)"
  - "POST /church/map/asks/{id}/undo runs undo_ask's own checks (_undo_checks, shared with Chief's undo_ask), duty first then the map change; Apply keeps duty_move.duty_change_id on the ask when it moved the duty; without it (applied before this, or finished by a second Apply) the duty's newest move to them by whoever said yes; the map part is the ask's change when whoever said yes applied it"
  - "GET /church/map/asks keeps asks/count as they were and adds answered (last 30 days, 20 at most: who, said, status, resolved_at, happened, put_back, can_undo); each open ask adds cant_apply"
  - "A new department's line lists leader, overseer, office helper, area and what it holds, set or not (nobody / none / nothing yet), on the sheet and in every receipt"
related: [2026-11-05-church-is-this-right.md, 2026-11-05-church-step2-chief.md, solutionist-studio 2026-11-05-church-is-this-right-fe.md, solutionist-studio 2026-11-05-church-department-editor.md]
---
Seven fixes to the leaders map and Is this right?, in church_map.py, church_map_router.py, church_map_asks.py,
chief_map.py, church_map_batch.py and one chief_prompt line. The response shapes the frontend needs are in the PR
body and in docs/CHURCH_LEADERS_STEP2.md §10 ("Fixed 2026-11-06"). The duties' switch was still the login's when
this merged; 2026-11-06-church-map-open-items.md opens it by the church too.
