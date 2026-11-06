---
title: The covenant's Send popup names the Executive Pastor
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "i want to use e-signature. can you see if it's working right?"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio covenant-names-pastor (the popup)]
migrations: []
left_undone: []
decisions:
  - "/church/covenant adds `pastor` beside `send`, owner only: the second signer's name, or None"
  - "It doesn't stop Send: a church may have no Executive Pastor. It says so before anything goes out"
related: [2026-11-06-church-covenant.md]
---
Found while checking the covenant. If the Executive Pastor isn't found, the form skips that signature and says "the Senior Pastor" in her place, and the owner's popup listed only the admins, so that couldn't be seen until after Send, which can't be repeated for the same admin.
