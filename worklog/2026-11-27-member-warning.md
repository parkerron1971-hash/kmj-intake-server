---
title: "The member warning: a church's own \"the pastor will never ask you for gift cards\" note, a Give-page line, offered by Chief (backend)"
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-27 (through KAI, M-5 step 3): yes to the member warning, per church and offered by Chief; build it with the Needs a look front end: "each church chooses, offered by Chief, sendable in one tap (News plus app note, optional text), pre-filled with the pastor''s name, plus a Give-page line toggle. Off by default."'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (the Needs a look front end, which has the page)]
migrations: []
left_undone:
  - "Not merged: the account-2 review first"
  - "The privacy page and Help don't mention it yet (nothing is collected)"
decisions:
  - "member_warning.py keeps the church's choice in businesses.settings.member_warning {on, pastor, give_line, sent_at, sent_by, sent} through business_settings.merge (no migration). Off by default for every church"
  - "Sending is the office's own tap through the routes that already exist, each with its own gate: a News post (POST /church/news), an app note (POST /member-portal/{id}/announce) and, if chosen, a text to everyone who said yes (POST /sms/broadcast). The page records what went with PUT {sent: [...]}. Nothing here sends"
  - "The words: the pastor's name from the church's own choice, else the senior role (member_pastor + guest_path_weeks.pastor_signature: 'Pastor James'), else 'Our pastor'; the app note fits member_push's 60/180"
  - "The Give-page line shows only when on AND give_line, escaped, on the hosted /give, a hand-built site's give form and the member app's Give (one helper, give_line_html)"
  - "Chief offers it (turn_line in the turn's tail): only at a church that hasn't sent one, only on a turn whose words are about scams, fake messages, impersonation or gift cards; it opens Members with navigate and never says it was sent"
  - "Routes GET/PUT /church/member-warning?business_id=, a Manager seat and up (business_access), churches only"
related: [2026-11-27-needs-a-look-backend.md]
---
The member warning (inbound-safety proposal L7). The most common church scam
is a text to members using the pastor's name, from a number the church can't
see; members who already know are the defence. Tests:
`__tests__/test_member_warning.py` (off by default, the words, escaping, every
Give page, the routes and their seat, Chief's offer).
