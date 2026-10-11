---
title: "Cross-business patterns strip each business's own client names first"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "awesome. continue (Kevin, 2026-10-11, after the Layer Two build)"
status: waiting on review
prs: [kmj-intake-server#1392]
migrations: []
left_undone: ["names typed that are not contacts (a client's child, a misspelling) still rely on the three-business floor", "Feed 2's on-by-default setting and the privacy-policy wording are Kevin's call (Layer Two legal flags)"]
decisions: ["deny-list per business from contacts.name and businesses.name only, read past the 1,000-row page cap", "full names match in any case; a single part matches only capitalised, all caps, or as the contact wrote it, so a client called Will does not strip 'will'", "if the names cannot be read the run writes nothing"]
related: [2026-10-11-business-brain.md]
---
The Layer Two audit flagged that Feed 2 (vertical_distill) did not scrub names:
_scrub strips numbers, emails, links and dates, and only the k-anonymity floor kept
a client name from travelling. Each run now replaces the business's own client and
business names with [name] before scrubbing. Side effect: "Remind Marcus..." and
"Remind Ana..." become one signal that can clear the floor with no name in it.
