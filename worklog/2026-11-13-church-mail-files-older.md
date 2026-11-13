---
title: The Email room sends files and shows older mail
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'build these (attaching files when you send from the room; lists show the newest 100 per box, with no paging)'
status: in progress
prs: []
migrations: []
left_undone:
  - "A sent file's contents aren't kept: Sent shows its name and size, and the person who got it has the file."
decisions:
  - "POST /church-mail/send takes files as base64 (a data: URL is fine): 10 at most, 10 MB in all, never a program file (.exe, .js, .bat and the like, which mail services block anyway), and a file that isn't whole base64 is refused before anything goes."
  - "The files go to the mail service with the message; the Sent row keeps each file's name, size and type."
  - "GET /church-mail/list takes before= (the last shown message's time) and answers the next 100 older; `more` counts the rows read, before any are filtered out."
related: [2026-11-13-church-mail-room.md]
---
The last two gaps Kevin listed in the Email room, on the server side.
