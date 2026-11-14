---
title: Each person edits their own church email signature
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: "when i went in to write an email, i noted a bug where the add my signature sits . you can't see it fully. check that out for me. also add where the signature can be edited. just incase they want to change up how it looks."
status: shipped
prs: ["kmj-intake-server#1838"]
migrations: [supabase/APPLY-2026-11-14-church-mail-signature.sql (applied 2026-11-14)]
left_undone: []
decisions:
  - "A church email's signature was fixed: the sender's name, the church, the address it goes from. Each login can now write their own (church_mail_people.signature); empty goes back to the standard one."
  - "Per person, not one for the church: church mail goes out as the person (or a box they share), so the sign-off is theirs. Chief's mail keeps the business signature from Email Templates."
  - "Kept to 8 lines of 120 characters and 600 in all, whole lines only, no control characters, no blank lines at the ends or two in a row (clean_signature)."
  - "A signature that can't be read (the column not applied yet, a blip) is the standard one: a send never fails over a signature. Saving before the migration answers 503."
  - "The frontend half (the cut-off fix and the Edit link in New email) is solutionist-studio, merged after this is live."
related: [2026-11-13-church-mail-room.md]
---
Kevin found the signature cut off in New email and asked for a way to change
it. The server now keeps each person's own signature and signs their church
mail with it.
