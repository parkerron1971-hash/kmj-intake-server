---
title: "Member app new look (Look 5.1): a pastor or a leader posts their own moment"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin on the mock "Next: a pastor or leader posts their own moment": "i like it lets do it"'
status: in progress
prs: ["kmj-intake-server (the tables: APPLY-2026-11-21-church-moments.sql)"]
migrations: [supabase/APPLY-2026-11-21-church-moments.sql (NOT applied)]
left_undone:
  - "The moments themselves (posting, Home's row, the poster's sheet, the held list): the next PR."
decisions:
  - "Two server-only tables (RLS on, no policies, browser roles revoked): church_moments and church_moment_marks (one row a person a moment: seen, loved)."
  - "ends_at may run seven days and two hours, not three: 'Until Sunday' posted on a Monday runs almost seven days."
  - "media_kind is 'photo' only; the column is ready for 'video', which is not built."
related: [2026-11-20-lumen-home-look-5-1.md, 2026-11-20-lumen-member-posts.md]
---
The tables for leaders' moments ship first, on their own, so Kevin can apply
the file early. Nothing reads them until the next PR, and that PR treats a
missing table as "not applied yet".
