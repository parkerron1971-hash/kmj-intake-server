---
title: A church's planning course, on the page that was the Solutionist Academy
date: 2026-11-17
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-17, on the Academy being a business strategy course on a church''s Help door: "i would say keep for business and build a church planning course!"'
status: in review
prs: [kmj-intake-server#1892]
migrations: []
left_undone:
  - "No real model-written session has been read: the coach's prompt is tested with fakes (live evals bill production)."
  - "The coach is told nothing of the church's own numbers (attendance, follow-up, giving): it asks. church_weekly_briefing.week already reads most of them and could be handed to it later."
  - "A church that began the business course before today keeps that row: its business pages stay in it unread, and the church course starts at the first part not written."
decisions:
  - "Eight parts: Calling, Community, The path, Ministries, Leaders, Stewardship, An honest look, The next 90 days."
  - "Kept in the row a business's course uses (strategy_tracks): parts 1 to 7 under their own ids in `phases`, the 90 days in `launch_plan` in the launch plan's shape. No migration."
  - "Finishing a church's course marks the plan written and builds nothing: no site, no products page, no intake form, no settings write (a business's finish does all four)."
  - "The business-only save verbs (save_pricing, save_packages, save_business_model, save_projections, save_swot) refuse for a church, so a slip never writes a business page into a church's row."
  - "The coach is told to assume no denomination, style of worship or theology, never to invent a figure or a name, never to ask what a person gives, and not to preach."
  - "A step of the 90 days keeps its link only when it is a page on a church's menu (church_findway.pages)."
  - "The everyday Chief is told the plan (mission, vision, values, who to reach, how far the 90 days are) and never the Academy."
related: [2026-11-17-chief-church-menu.md]
---
The Solutionist Academy is a business strategy course (market research,
pricing, service packages, a launch plan). It was on every church's Help
door, and a pastor who opened it was asked what he would charge.

- `church_plan_course.py` (new): `PARTS`, `clean` and `clean_weeks` (what is
  kept of what the coach saves), `page` / `done` / `current`, `coach_prompt`,
  `chief_block`.
- `chief_strategy_actions.py`: `save_phase`, `advance_phase`,
  `save_launch_plan`, `session_summary` and `complete_strategy_track` take a
  church's parts; a church's finish is `_finish_church_plan`.
- `chief_prompt.py`: a church in `strategy_coach` mode gets
  `_build_church_coach_prompt`; `_format_strategy_block` gives a church
  `chief_block`.
- `__tests__/test_church_plan_course.py`: 19 tests, one holding a business's
  coach word for word, one holding the parts to the app's list.

The page is the frontend's (solutionist-studio, `church/plan/`).
