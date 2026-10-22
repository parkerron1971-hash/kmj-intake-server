---
title: One brand, three front pages, in one voice (/churches, /coaches, and a word list the site is held to)
date: 2026-10-22
agent: Claude Code (Claude Opus 5.5)
asked: "I want to make sure we build the voice system to function properly as suggested. the changes to website one brand three front pages. can we leave barbers and lawyers on the site?"
status: waiting on Kevin
prs: [kmj-intake-server#1546]
migrations: []
left_undone:
  - "The app (solutionist-studio) still says 'trade' in a few places (DocTemplatesDialog, ReferralsPanel, whatsNew, flyerTemplates); the voice test covers the public marketing pages only"
  - "Chief's own written voice (the Monday note in the brand page) arrives with the daily brief build; Chief's prompt is unchanged here"
  - "Signup does not carry the edition yet: /start links stay bare and onboarding starts empty (see the 2026-10-15 trade editions plan)"
  - "The size guide on the /churches pricing (about 150 people Starter, about 600 Professional, larger Solutionist) is Kevin's call to keep or drop"
  - "An edition's Who it's for list has two kinds of business, which leaves space beside the photo on a wide screen"
  - "Lanes: two new pages are a new feature, so this needs a Build slot on Mission Control → Build → Plan, which only Kevin can set; features switch on on Thursdays (2026-10-22 is one)"
decisions:
  - "An edition is the home page with its own first screen (headline, lede, three plain promises, the Who it's for line) and only its own kinds of business; it holds still on its own kind (no auto-cycle) and drops the moving list of all seven"
  - "The church page hides the dollar calculator and its nav link: 'what the quiet chairs cost you' is the wrong question to ask a pastor about giving"
  - "/consultants is the coaches page with consultants first; its canonical is /coaches and it is not in the sitemap"
  - "The home keeps all seven kinds of business (Kevin: keep barbers and lawyers), ordered ministry, coach, consultant, barber, law, contractor, nonprofit"
  - "brand_voice.AVOID is checked against what a visitor reads or hears: text, aria labels, alt and placeholder text, meta descriptions, structured data and the prose inside the page's scripts, never class names, ids or URL parameters"
  - "No new switch: HOME_EDITION=v2 still rolls the home back without a deploy, and the edition pages are plain routes"
related: [2026-10-14-home-third-edition.md, 2026-10-12-site-without-therapists.md]
---
Kevin read the brand page (https://claude.ai/artifact/Y6DSyYpqVP7FJ9KhTXD2HU)
and asked for its voice and its "one brand, three front pages" on the site,
keeping barbers and lawyers.

The voice: `brand_voice.py` holds the word list (no "trade", no "software",
Chief is never an "AI agent", "AI assistant" or "AI chief of staff", no hype
words) and a reader that finds them in what a visitor actually reads.
`__tests__/test_brand_voice.py` holds every public marketing page to it:
home, /churches, /coaches, /consultants, /features, /compare, /faq, /about
and /get-started. The pages were rewritten to pass. The hero now reads "One
system for the whole business. Chief keeps it moving, so you keep doing the
work you're known for." "Built for the trade you're in" became "Built for the
work you do." The compare table's "Chief, your AI Chief of Staff" became
"Chief, your chief of staff". The About page's "enterprise software" became
"enterprise tools".

The front pages: `marketing_home_v3.EDITIONS` and `render_edition()` serve
the same page as the home at /churches ("Your church office, handled."; month
to month, your own Stripe with no cut of giving, texts from your own number)
and /coaches ("One front door for your clients."). The server sets `ED` in
the page script, which filters and orders the kinds of business. The home
links to both from Who it's for and the footer. Checked at 1440 and 390 wide
in a local preview: no script errors, no sideways scroll.
