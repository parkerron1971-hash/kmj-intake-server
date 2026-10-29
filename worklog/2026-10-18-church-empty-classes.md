---
title: A church's empty class list says "New classes are on the way", not courses
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Follow-up to the class list and class pages (#1491): the live check of Love City''s /academy, with nothing published yet, still said "New courses are on the way"'
status: shipped
prs: [kmj-intake-server (this PR)]
decisions:
  - "Same church test as the heading (vertical ministry): Classes, and a class with no title falls back to Class"
related: [2026-10-18-class-site-pages.md]
---
- `public_site.py`: the catalog's empty line and untitled-card fallback say
  class for a church.
- `__tests__/test_academy_site.py`: a church with nothing published says
  classes; a coach still says courses (fails with the old line).
