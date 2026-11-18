---
title: The church's guest card (which card the bulletin's New here code opens), chosen by the first-time guests' login
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17, "build that": a printed connect card / guest QR that Tiara (People & Care, the first-time guests) can make herself'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the frontend PR, guest-print-cards)]
migrations: []
left_undone:
  - "Merge this backend first: Print for guests' Make it our guest card calls PUT /church/guest-card. Until then the print sheet still prints, from intake_forms, with nothing to choose"
  - "If chief-office-howto merges first and church_findway.json conflicts: merge main and re-run node scripts/export-church-map.mjs from the frontend; never hand-merge it"
  - "Love City has New here off (settings.new_here.on unset), so its print sheet offers its cards (Plan your visit, Baptism, Serve with us) and not the text"
decisions:
  - "The choice lives in settings.new_here.guest_form, inside New here's own server key (business_settings.SERVER_KEYS), written with business_settings.merge(under=['new_here']): no new server key, so no change to the unapplied settings-server-keys SQL list, and the app's logins can never write it once that migration is applied"
  - "new_here.put_new_here keeps settings.new_here.guest_form (new_here.KEPT): its PUT builds the key from clean(body) and would otherwise drop the choice"
  - "Who chooses: church_duties.holds(biz, user, 'first_guests') (the owner and admins always; Tiara by default; whoever it is moved to). A failed duty read is a 503 on the PUT and can_choose false on the GET. Every login of the church reads it (viewer)"
  - "A private card (settings.private_care, or 'prayer' in its name) is never offered or accepted: it goes only to Prayer & care and never starts a follow-up, which is the first-time guests' job. A switched-off card is refused (400), another church's is a 404"
  - "Card addresses: the church's own address (custom domain, else its subdomain), else the API host (chief_form_actions.public_form_url's rule)"
  - "church_duties first_guests opens now names the guest card; church_findway.json re-exported from the frontend (two Forms answers: Print guest cards with a QR code, Choose the card guests scan on the bulletin; it also picked up one Reach answer the frontend had changed since the last export)"
related: [2026-11-17-guest-lane-new-here.md, 2026-11-17-settings-server-keys.md, "solutionist-studio worklog/2026-11-17-guest-print-cards.md"]
---
Before building I read both repos' worklogs: the guest lane (New here opened
to Tiara the same day, which left "the printed connect card and the
bulletin's QR code" with their lanes), the settings server keys (unapplied;
why the choice sits inside new_here rather than a key of its own) and the
church bulletin (Media's Bulletins & print).

`guest_card.py` (`GET`/`PUT /church/guest-card/{business_id}`), mounted
after New here in `kmj_intake_automation.py`. `new_here.py`: `KEPT`.
`church_duties.py`: first_guests `opens`. `docs/CHURCH_DUTIES.md`: "The guest
card". Tests: `__tests__/test_guest_card.py` (19: the cards a guest can be
sent to and their addresses, the text only when New here is on with a number,
who reads and who chooses, the duty moving, a 503 on an unread duty, the cards
refused, a failed write, a chosen card switched off later, New here's PUT
keeping it).
