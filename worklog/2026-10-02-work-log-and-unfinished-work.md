---
title: The work log and the unfinished-work watcher
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'do we have an agent that watches these, like unfinished work? / leave a summary from that project with the PRs ... to match and determine if we should build or not'
status: in progress
prs: []
migrations: []
left_undone: ["Solution Space could report uncommitted work on Kevin's machine to the backend; not built"]
decisions: ["the log lives in each repo as worklog/*.md, written in the session's own PR", "the watcher never merges; it only brings green PRs up to date", "Codex reads AGENTS.md, so both repos now have one"]
---
Found while finishing merges: 54 open PRs across both repos, some six weeks
old and green, and a security audit left uncommitted. worklog.py reads both
logs; unfinished_work.py sorts open PRs every morning, updates green ones that
fell behind, lists pending migrations and open log entries, and keeps one
GitHub issue current. Platform Chief carries both in its snapshot.
