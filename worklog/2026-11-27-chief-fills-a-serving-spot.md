---
title: Chief fills an open serving spot through the serving page's own ask, offer, take back and fill (Love City first)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-26 (through KAI): "start the serving-spot skill as you proposed": give Chief the page''s own actions with the page''s checks; steps that suggest, get the person''s yes, ask, then report "asked, waiting"; Love City only first; scoped to who can schedule today. Core-sensitive: PR, green, not merged, Codex cross-review first'
status: open
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Not merged (Kevin's/KAI's call). No live Chief eval run: the with/without comparison bills production and waits on a cost estimate and Kevin's yes"
  - "A team's own leader (a member, not a login) still schedules from the member app's Lead tab; Chief serves office logins only"
  - "The church skills load a job's steps only on the turn whose words match: the log check (below) found the follow-up turn of a giving job had no steps. Carrying a job's steps to the next turn or two is a separate change"
decisions:
  - "Five verbs in chief_serving_spots.py: serving_spot (read, a mid-turn lookup), ask_to_serve, offer_serving_spot, take_back_serving_ask (one ask, or a fill's unsent asks with fill:true), fill_serving_spots. Every write IS sunday_planning's route (ask, offer, take_back, fill, unfill) called as the signed-in login, so the page's switch, who-schedules-which-team (_scheduler, _place_gate) and its checks (on the team, away, another spot that hour, Sundays a month, a yes never overwritten) are the only rules. Chief adds one that only narrows: it never takes back a yes (as sunday_leading.take_back)"
  - "The read runs the same gates as the ask (_scheduler, _place_gate) before naming anyone, so Chief only suggests where it could ask; with no place it lists only the teams this login schedules"
  - "Every receipt says asked and waiting for an answer, sent on the next sweep (every 15 minutes, outside quiet hours), never filled"
  - "Switch CHIEF_SERVING_SPOTS = off | owner (default: member_asks.platform_church, Love City) | on; under it SUNDAY_PLANNING. Signed in, never unattended; a church; a tainted turn's write held. Registry: chief_only, writes class C, fill bulk; excluded from plans (chief_missions); the read is in the church edition's loaded verbs; how-to in the turn's tail only where open"
  - "Lanes: the verbs are every office login's in chief_areas (as serving_week and event_volunteers), because who schedules a team is a duty (serve_schedule, production_schedule) that can sit in any lane; the page refuses a login that schedules nothing, before any team's name is said"
  - "Skill church_skills/fill-a-serving-spot.md (needs serving_spots = the switch open for the church): look, suggest from the list only, get their yes to that name and spot, ask, hand back 'asked, waiting'"
  - "Free log check of the three giving skills (Railway web logs since they went live 11-26, read-only, no message text): 6 Chief turns at Love City; the first ('work on the offering', 00:01 UTC 11-27) loaded sunday-giving-count; its follow-up did not (no trigger words); no action_guide lookups; the 4 turns after #2093 loaded none"
  - "Codex cross-review (gpt-6-luna, read-only, before the PR) found 2 medium, 0 high, both fixed with tests: '9am' could match a 9pm service on a day with two (now only a bare hour may mean the afternoon, and a bare hour that fits both asks which); and a yes given between Chief's look and the take-back could be deleted, because the route's own delete doesn't look at the status (now the page's own gates, then a delete kept to an ask or offer still unanswered; a row left means they just said yes: a 409)"
related: [2026-11-26-church-skills.md, 2026-11-27-answer-check-knows-what-chief-can-do.md]
---
Read both repos' work logs first; nothing open touches the serving page or the church skills.

`chief_serving_spots.py` (new); wired in `chief_of_staff.py` (handlers, progress, the turn's tail),
`chief_tool_loop.py` (the read tool and the mid-turn list), `chief_lean_brief.py` (church edition),
`chief_areas.py`, `chief_missions.py`, `action_registry.py`, `church_skills.py` (NEEDS).
Skill: `church_skills/fill-a-serving-spot.md`.
Tests: `__tests__/test_chief_serving_spots.py` (new, over test_sunday_planning's fake and the page's real
routes); pins updated in `test_church_skills.py` and `test_tool_loop.py`.
