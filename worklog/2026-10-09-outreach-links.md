---
title: Outreach texts and emails carry a tracked link ({{link}})
date: 2026-10-09
agent: Claude Code (Claude Opus 5.5)
asked: "work on this in order (Kevin, 2026-10-09; step 1 of the approved plan: links on texts, emails and offers too)"
status: done
prs: [kmj-intake-server#1363, solutionist-studio#1189]
migrations: [supabase/APPLY-2026-10-09-marketing-links.sql]
left_undone: ["offers get their links with step 3 (marketing_links.kind allows only 'campaign' today)", "one-off texts (SMS broadcast) and nurture/Chief drafts send no tracked link yet; only Outreach campaign touches do", "email clicks are counted through the short link only; Resend click tracking stays off"]
decisions: ["a touch says {{link}} and gets its own short link on the business's site, made on its first send, one per touch (derived id and code), to the booking page when anything is bookable else the published site", "the link's tags are utm_source=email|sms, utm_medium=outreach, utm_campaign=<campaign id>, utm_content=<link id>, so visits, leads, bookings and payments join it as they join a post", "marketing_follow checks a post's code first, then a link's; a person's click on a link counts in marketing_link_hits", "a link that cannot be made holds the touch for a later tick; with nowhere to go, {{link}} is left out of the words; launching {{link}} with nowhere to go is a 409"]
related: [2026-10-09-booking-follows-the-link.md, 2026-10-09-desk-several-pictures.md]
---
The Reach plan's step 1, second part, after #1362 followed a post's link to
the booking and its payment. Outreach (campaigns_router) texts and emails
were plain words with no tracked link, so nothing they did could be counted.
Now a touch that says {{link}} (Chief places it when drafting; the app's
editor has "Add your link") sends that touch's own link, and the campaign
shows "Through your link: taps, visits, bookings, paid online" under it.
