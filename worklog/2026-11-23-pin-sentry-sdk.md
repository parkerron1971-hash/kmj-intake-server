---
title: sentry-sdk kept below 3 (3.0.0 would have switched error tracking off on the next deploy)
date: 2026-11-23
agent: Claude Code (Claude Fable 5.2)
asked: "Found while merging the confirm-loop fix (#2075): its tests failed on a file it never touched"
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Moving to sentry-sdk 3: its init no longer takes before_send_transaction, which is what keeps live audit links out of the events sent to Sentry (access_log_redaction.scrub_sentry_event). Needs its own look before the pin is lifted"
  - "Other requirements are also open-ended (>=): the same kind of break can come from any of them on a release day"
decisions:
  - "requirements.txt: sentry-sdk[fastapi]>=2.0.0,<3. No code changed"
related: []
---
`requirements.txt` asked for `sentry-sdk[fastapi]>=2.0.0` with no upper bound.
sentry-sdk 3.0.0 came out on 2026-11-23 and refuses the `before_send_transaction`
option ("Unknown option"), which `kmj_intake_automation.py` passes at boot.

Two effects from the next install on: CI fails
(`test_chief_computer_wiring.py::test_sentry_transport_never_receives_secure_entry_event`),
and in production `sentry_sdk.init` raises, the boot guard prints a warning and
carries on, and error tracking is off without anyone being told. The last
deploy (01:40 UTC) still installed 2.x.
