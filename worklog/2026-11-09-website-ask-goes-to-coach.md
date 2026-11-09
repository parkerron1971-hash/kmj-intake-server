---
title: A website ask gets the website, not the booking page
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "make sure chief can interpret what everyone is asking like you can"
status: shipped
prs: []
migrations: []
left_undone:
  - "Only proven by talking to Chief from the front end again, after this and the Coach PR are live."
decisions:
  - "Chief no longer asks for facts before the Coach. Its address question went nowhere, and the Coach now knows what is on file and asks for what is missing."
  - "Booking can be offered in one line, but it waits for their yes."
related: [2026-11-09-coach-reads-the-ask.md]
---
Talking to Chief as a test shop: "I need a website, nothing fancy, I just want people
to find me and book" got the booking page published and an address question that went
nowhere. It took a second push ("a real website") to reach the Coach. An owner who
didn't know to push would have thought that was the website.

Small words now describe the site's job instead of shrinking the ask. A website ask
goes to the Coach in that same turn and outranks the setup list, and Chief passes
everything they said about the site, word for word.
