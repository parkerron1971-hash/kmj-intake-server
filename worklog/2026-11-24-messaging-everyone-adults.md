---
title: "One switch: every adult with a birthday on record can use member messaging"
date: 2026-11-24
agent: Claude Code (Claude Opus 5.5)
asked: 'can you creat a simple toggle that would work to turn on all member messaging. this would be for numbers that filled out date of birth. if you have a better option for turn on messages for everyone. that would be great.'
status: in progress
prs: ["kmj-intake-server (this PR)", "solutionist-studio (the switch on the Messaging page, next)"]
migrations: []
left_undone:
  - "The office switch on Messaging → People (solutionist-studio), PATCH /messaging/settings {adults_with_birthday}."
decisions:
  - "Kevin's answers: automatic (now and as birthdays are added), adults only (teens stay one by one so the office links parents first), only the birthday on their record (contacts.birthdate; a birthday typed in the app never opens messaging)."
  - "settings.messaging.adults_with_birthday. The per-person switch (msg_members.enabled) stays the one thing every reader checks; messaging_everyone writes it: on gives every adult with a record birthday and no row an enabled row (enabled_by BY_SWITCH); a row that exists is never touched, so someone the office switched off or Safety paused stays off. Off turns off only what it turned on (BY_SWITCH, now BY_SWITCH_OFF); on again brings those back."
  - "A sweep every 15 minutes (messaging_everyone.sweep_tick) opens adults added since, and a teen on their 18th birthday."
  - "Who changes it: the chat rules' keeper (messaging_router._chat_rules_keeper). The server's writes skip the database's grant guard, as every server write does; messaging still opens only once the church turns it on with two safety officers."
related: []
---
The office used to turn member messaging on one person at a time. Now one switch turns it on for every adult with a
birthday on their record, and keeps doing so as birthdays are added.
