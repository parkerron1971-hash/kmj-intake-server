---
title: A church's setup list names what it has to switch on
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06, on the settings a new church has to turn on: "yes I agree because they might not know to turn them on."'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio church-turn-on-steps (What's New)]
migrations: []
left_undone: []
decisions:
  - "Four new church steps: Turn on your member app, Choose your phone alerts, Set up Sunday check-in, Set up member messaging. The website concierge step gets a church's words, its own section in Settings, and a place after the site"
  - "Each step ticks off from the setting the feature reads (settings.member_portal, member_push.church_kinds, church_checkin_settings, settings.messaging), so it can't say done while the feature is off"
  - "Alerts, check-in and messaging wait for the member app. Messaging says it needs two safety officers"
  - "ALWAYS_SHOWN: a coach's plan can't hide these, because nobody knows to ask for them"
  - "VERTICAL_WORDS can set a step's weight for one vertical; member-app joined system_destinations.json, which the frontend already had"
related: [2026-11-06-church-setup-words.md]
---
All of these start off on purpose, because a church decides what reaches a phone. That left a new church with a site that says "news with phone alerts" and an app where none ring, unless someone knew which switch to find. Read from the kept test church on the real database: the member app and import showed done, and the rest were waiting with the right screens.
