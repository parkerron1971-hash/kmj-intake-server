---
title: "The booking page's texts boxes in the business's own name, once its registration is sent"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "building everything now so it's setup for people to get updates and everything through our system (Kevin, 2026-10-11; the ISV plan's step 3 switch of the booking box)"
status: waiting on review
prs: [kmj-intake-server#1377, solutionist-studio#1203]
migrations: []
left_undone: ["who may get texts from the business's OWN number once approved (step 4): consents given before the switch named Solutionist System; sms_consents.consented_at against the registration's twilio.sent_at tells the two apart without a schema change"]
decisions: ["the box words come from texting_registration.booking_box/offers_box, the same functions that write the campaign's message flow, so the page and the campaign can never drift apart", "the switch happens once the registration is with Twilio (submitted, brand_pending, campaign_pending, approved, or sent back after Twilio had it); a draft, or a registration that failed Twilio's own check before anything was submitted, keeps the old words", "an unreadable registration keeps the old words (never half-switched); the payload key is present only when switched, so every other business's payload is byte-identical"]
related: [2026-10-11-isv-step-3.md]
---
Once a business's texting registration is with Twilio, its reviewers read
the booking page's consent boxes, and those must name the business (error
30927) word for word as its campaign quotes them. The widget config now
carries `texting` (both boxes in the business's name and its own
/texting-terms and /texting-privacy) for those businesses only, and
static/embed.js is rebuilt from solutionist-studio#1203, which shows them.
