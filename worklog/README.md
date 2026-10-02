# The work log

One short file per piece of work, written by the session that did it, Claude
Code or Codex. It answers the question Kevin asks before building anything:
**have we already built this, or started it?** The backend reads both repos'
logs (`worklog.py`); Platform Chief checks them before recommending a build;
the unfinished-work watcher lists anything not shipped or left undone.

## When to write one

- At the end of every session that changes code, in the same PR.
- If a session stops before it can ship, it still opens a **draft PR** with
  its log entry saying what is unfinished and where. Uncommitted work on one
  machine is invisible to everyone else.
- Before building, read this folder in **both** repos for overlapping work.

## Format

File name: `YYYY-MM-DD-short-slug.md`. Front matter, then a few plain
sentences.

```markdown
---
title: Support desk drafts replies          # what someone would search for
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)        # or: Codex (GPT-6)
asked: "start wave 3"                       # Kevin's words, briefly
status: shipped                             # shipped | in progress | stopped | waiting on Kevin
prs: [kmj-intake-server#1177, solutionist-studio#1087]
migrations: [supabase/APPLY-2026-10-02-support-drafts.sql (applied)]
left_undone: []                             # what a later session must pick up
decisions: ["drafts never send; a person presses Send"]
related: [2026-09-30-agent-operations-plan.md]
---
What was built and why, in a few sentences. What to check before building
more in this area.
```

Keep it short: the PRs hold the detail. Update the same file if the work
continues later; add a new file for new work.
