---
title: "The website contact form's texts box in the business's own name"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "on the form for text, does it say provider or just the business name and does say anything about carrier?? (Kevin, 2026-10-12)"
status: waiting on review
prs: [kmj-intake-server#1402]
migrations: []
left_undone: ["the /public/site/{slug} studio preview (get_site_html) still shows the box as built; visitors' addresses (subdomain, custom domain) all pass _augment_html", "the 'Carriers are not liable for delayed or undelivered messages' line on each business's /texting-terms page stays: the standard line texting terms carry, for clients, naming no provider"]
decisions: ["the booking page's boxes switch to the business's own name once its registration is sent (#1377); the composed site's contact form said 'from {business} via The Solutionist System' forever. It now switches on the same rule (texting_registration.is_sent, shared with the booking page)", "switched when the page is served (public_site._augment_html, which every stored page passes) because the box is baked into the stored page at build time; only a page with the box reads the registration, remembered five minutes per business; a failed read leaves the box as built", "the switched box keeps the rest of the disclosure word for word (not a condition of purchase, frequency, rates, STOP, HELP) and links the business's own /texting-terms and /texting-privacy"]
related: [2026-10-11-booking-box-own-name.md, 2026-10-12-texting-words-not-twilio.md]
---
Kevin asked whether the texting forms name the provider or just the
business. The owner's registration form and, once the business registers,
the booking page's boxes name only the business. The composed site's
contact form kept "via The Solutionist System" after registering, which
would be opt-in proof naming another company under the business's own
campaign. It now switches with the booking page. KMJ's hand-built site has
no texts box on its contact form, so the pilot isn't affected either way.
