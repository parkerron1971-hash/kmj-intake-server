---
title: A church job's steps are carried to its next turn or two, bounded by turns, time and a change of topic
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-27 (through KAI): "carry a skill''s steps through the next turn or two of the same job, so follow-ups like ''ok, now record it'' keep the giving or serving steps. Keep it bounded (an expiry by turns and time, cleared when the topic changes), so stale steps never leak into unrelated turns." Not merged: Kevin''s/KAI''s call'
status: open
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Not merged. No live Chief eval run (bills production)"
  - "Turns not saved by login (chief_turns_by_login off) carry nothing: the time check reads this login's saved turns"
decisions:
  - "Why: the free log check of 11-27 found only the first turn of a giving job loaded its steps; the follow-up ('the 22nd', no trigger words) had none and Chief never looked them up"
  - "church_skills.carried_block, called in chief_chat only when this message named no job and skills are on for the church. Stateless across replicas: the job is found in the history the app sends (a user message at most CARRY_TURNS=2 back that matches a job's triggers, the login's key and the church's features still checked); time and the same chat come from this login's last saved turns (chief_conversations, one read of at most 2 rows, only when the history names a job)"
  - "Bounds: the last turn under CARRY_MINUTES=30 ago and the job's message under CARRY_JOB_MINUTES=45; the saved turns must be the history's own messages (another chat carries nothing); this message and every one between must read as a continuation (no other job's words, no new-topic opening such as also / different question / by the way / never mind, at most 40 words); a turn since the job's message that ran any action outside the job's own (a screen move aside) is a new topic. A read that fails carries nothing"
  - "The carried steps say they are carried and to be followed only if this message continues the job; recorded as conversation for the answer check, like fresh steps"
related: [2026-11-26-church-skills.md, 2026-11-27-chief-fills-a-serving-spot.md]
---
Read both repos' work logs first; nothing open touches the church skills.

`church_skills.py`: `continues`, `carry_candidate`, `carried_block` and the bounds. `chief_of_staff.py`: one
call after `turn_block`, before the login block. Tests: `__tests__/test_church_skills_carry.py`.
