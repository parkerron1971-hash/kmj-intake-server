---
title: The kids pickup mock shows its names again
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-04, on the church product pages: "the mocks where it breakdown the giving, member app etc.. that needs an upgrade in quality". The audit found this one broken outright.'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The full upgrade of the product pages (lit rooms kit, Giving first) follows in its own PRs"
decisions:
  - "The pickup mock's white cards (.k-card) and the leader's yellow note set their own dark text; they were inheriting the dark section's white, so children's and adults' names and the note read as blank"
related: [2026-10-23-church-site.md]
---
On /churches/kids-and-youth, the Pickup section's two phones showed empty rows: the names (Maya B., Lisa Brooks, Tom Brooks…) and the "You see first names and allergies" note were white on white. Fixed by giving the card and the note their own ink, with a test that holds it.
