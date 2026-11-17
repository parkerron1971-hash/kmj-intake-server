---
title: Chief knows a church's menu door by door, and answers "where is" and "how do I" from the Help Center's own answers
date: 2026-11-17
agent: Claude Code (Claude Fable 5.2)
asked: "creating a way for chief to be more proactive in helping those navigate... go with your picks"
status: shipped
prs: [kmj-intake-server#1883, kmj-intake-server#1884, solutionist-studio#1590]
migrations: []
left_undone: ["Chief does not speak first yet (the three quiet offers: looks lost, first time in a room, after an upgrade)", "room_orientation.ROOMS still lacks most church rooms", "searches that find nothing are not saved yet", "a duty can add a page to a login's menu beyond its areas; the menu block does not say so page by page"]
decisions: ["church_findway.json is the frontend's export and is never edited by hand", "the whole church's menu sits in the per-business cached part of the prompt, tagged with who sees each page; it is not cut per login, so it caches", "the turn's answers are cut to the login's areas, and money pages are never a lane's", "the matcher is the frontend's, line for line, with the same list of test questions on both sides", "CHIEF_FINDWAY=off turns both blocks off"]
related: [2026-11-16-chief-page-list.md]
---
Kevin loaded his first church and found people could not tell where things
were. Chief was part of it: its directions listed the business rooms, so a
pastor asking where to pay a deacon back was told about invoices. This is
Chief's half of the Find Your Way plan
(https://claude.ai/artifact/NkxZNfbZmNbcj6RPYrVjMp); the app's half is the
Help Center (solutionist-studio#1590).

- `church_findway.json`: the doors, each page's name, tab and sub, who sees
  it, its search words and its card (106 pages, 271 answers). Written by the
  frontend: `node scripts/export-church-map.mjs ../kmj-intake-server/church_findway.json`.
- `church_findway.py`: `menu_block(biz)` is the church's menu for the
  per-business part of the prompt (about 1,500 tokens, churches only);
  `turn_block(biz, message, scope)` adds the matching Help Center answers to
  a turn that asks where or how, and nothing to any other turn.
- `chief_prompt._build_system_prompt` places the menu after the vertical
  block; `chief_of_staff.chief_chat` adds the turn block to the per-message
  tail and records it as a source for the answer check.
- `system_destinations.json` has `operate/help-center`.

Before building more here: when a page is added to a church's menu, export
the map again in the same piece of work, or Chief will not know the page.
`__tests__/test_church_findway.py` fails if the map names a page the page
list does not have.

Tried on the live app the same day (Love City, the owner): "Where do I pay
Deacon Ray back for the paint he bought?" Chief said it was a check request
and opened Check requests, but called the place "Operate, in the Checks
section", because it repeats the open-page action's label. `handle_navigate`
now labels a church's page by its place on the menu
(`church_findway.place_of`: "Opened Office › Money out › Check requests").
