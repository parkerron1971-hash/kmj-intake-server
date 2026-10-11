---
title: "Refer a friend: your own thank-you words, and how long a code is good for"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "continue to build the next steps that you just shared (Kevin, 2026-10-11, after editable thank-you words, an end date for thank-you codes and a Chief action were offered)"
status: waiting on review
prs: [kmj-intake-server#1371, solutionist-studio#1197]
migrations: [supabase/APPLY-2026-10-11-thank-you-words.sql]
left_undone: ["Chief can't change refer-a-friend or make an offer yet (the next PR)", "changing how long codes are good for applies to new thank-yous only; ones already made keep their day"]
decisions: ["the owner may rewrite the subject, email and text, but {{code}} must stay in the email and the text, so the regular always gets their code", "a line whose link or end day this thank-you doesn't have is left out whole, and a part that still comes out without the code is sent in the suggested words instead", "no end stays the default; an end day is 7 to 365 days from the day the thank-you is made, on the business's clock, and its last day still works", "settings (amounts, the P.S., the thank-you) save while the program is off: it is made paused; before, choosing an amount before turning it on saved nothing"]
related: [2026-10-11-refer-a-friend.md]
---
Refer a friend's thank-you was fixed words with no end. Now the owner can
rewrite it in Grow, Offers (with {{first_name}}, {{friend}}, {{amount}},
{{code}}, {{book_link}}, {{own_link}}, {{ends}} and {{business}}) and choose
how long a new thank-you code is good for: no end, 30, 60 or 90 days. The
booking page says when one has ended.

Also fixed: choosing an amount (or the P.S.) before ever turning the program
on didn't save, because the server returned before making anything; the
preview harness faked the save, so the browser check missed it.
