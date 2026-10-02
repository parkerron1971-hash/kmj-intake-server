# AGENTS.md — for Codex and any other coding agent

**Read `CLAUDE.md` first. Every rule in it applies to you**: trunk `main`
auto-deploys to Railway; migrations are applied by hand as
`supabase/APPLY-*.sql`; server code uses the service-role helpers, never the
anon key; every write endpoint needs auth plus an owner check; webhooks fail
closed; Chief handlers return `{result, label}`; one PR per change, never
stacked.

## The work log (required)

- **Before building**, read `worklog/` here and in solutionist-studio for the
  same or overlapping work.
- **At the end of every session that changes code**, add or update one
  `worklog/YYYY-MM-DD-slug.md` in the same PR (format: `worklog/README.md`):
  what Kevin asked, what you built (PRs, migrations), status, decisions and
  what you left undone. Put your own model in `agent:` (e.g. `Codex (GPT-6)`).
- **If you stop before shipping**, open a draft PR with your log entry anyway,
  saying what is unfinished and where. Never leave work only on disk.

## Commits

End commit messages with a trailer naming the model that actually wrote the
commit, e.g. `Co-authored-by: Codex GPT-6 <noreply@openai.com>`.
