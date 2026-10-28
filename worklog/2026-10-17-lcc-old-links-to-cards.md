---
title: Love City's old sign-up addresses (/baptism, /volunteer, /ministryworks, /city-serve) open the church's cards
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'After #1468 pointed the Ministries buttons at the cards: "point the old /baptism and /volunteer links at the cards too"'
status: shipped
prs: [kmj-intake-server#1470]
migrations: []
left_undone: []
decisions:
  - "/ministryworks and /city-serve go to Serve with us too: they are the old site's other serving sign-ups and went to the same place as /volunteer"
  - "A hand-built site's redirect may now target /public/widget/form/<uuid>, exactly: same host, no query, no extra path; the visitor's own query is still kept by with_visitor_query"
related: [2026-10-17-lcc-site-cards.md, 2026-10-13-love-city-church-site.md]
---
The old SnapPages addresses for baptism and serving sent a visitor to the
connect card with a box ticked, because clean_redirects allowed only the
site's own pages as targets. A target may now also be one of the site's
form pages, `/public/widget/form/<uuid>` and nothing more, which both
church addresses answer (the card, or its closed page when switched off).
Love City's map sends /baptism to the Baptism card and /volunteer,
/ministryworks and /city-serve to Serve with us, the same cards the
Ministries buttons open.

Rehearsed: matching the form path with search() instead of fullmatch()
fails 4 tests, including //evil.example/public/widget/form/<id>.
