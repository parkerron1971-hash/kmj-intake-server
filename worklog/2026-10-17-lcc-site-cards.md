---
title: Love City's "I want to be baptized" and "I want to serve" open the church's own cards; a switched-off card's link says so instead of "Form not found"
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'After the Forms & classes build made Love City''s Baptism and Serve with us cards: "yes point the website buttons at the new cards."'
status: shipped
prs: [kmj-intake-server#1468]
migrations: []
left_undone:
  - "The old SnapPages addresses /baptism and /volunteer (and /ministryworks, /city-serve) still land on the connect card with the box ticked: clean_redirects only allows the site's own pages as targets"
decisions:
  - "The card addresses live in build.py CARDS as build-time tokens ({{CARD_BAPTISM}}, {{CARD_SERVE}}), relative, so lovecityc.com and the subdomain both work"
  - "Next Step and Leaderschool keep their connect-card buttons: those are classes, not cards"
  - "A paused form's link answers 404 with an HTML page in the business's own style (render_closed_page), never JSON; a form that does not exist is unchanged"
related: [2026-10-16-church-cards.md]
---
Love City's Ministries page sent "I want to be baptized" and "I want to
serve" to the connect card with a box ticked. The church now has Baptism
and Serve with us cards in the app (Build → Forms & classes), whose
answers the Next steps road counts, so the two buttons open those cards
on the site's own address.

A card can be switched off in the app, and its link then answered with
the JSON `{"detail":"Form not found"}`, a dead end for a visitor who
pressed a website button. Both form-page routes (intake_endpoint on the
API host, which also answers the church's two addresses, and public_site
on a site host) now show a switched-off form as its own closed page: the
name, "This form isn't taking answers right now", and the way back to
the website when the page wears the website's style. The card page's
shared CSS moved into `_SHELL_CSS`; the open card renders pixel-identical
to main (Serve with us and an event registration, page and embedded, 1280
and 375).
