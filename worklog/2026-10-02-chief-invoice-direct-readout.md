---
title: Chief reads invoice displays without a contradictory rewrite
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Invoice answer lists records and then tells me to disregard them"
status: in progress
prs: []
migrations: []
left_undone: ["Parent integration and deployment", "Production voice retest"]
decisions: ["Only whole-message invoice display requests qualify", "One actual validated invoice card is the authority", "Mixed advice and operations keep normal composition and review"]
related: [2026-10-02-chief-conversation-recovery.md]
---
The inspected turn released its answer after final review, not as an early
unchecked prefix. A generated retraction survived claim trimming. The existing
composer already received a row digest, so missing invoice data was not proven
to cause that turn's failure.

Pure invoice-display requests now read the returned card deterministically,
including bounded invoice IDs, clients, amounts, statuses and due dates. The
scope, form, remaining displayed rows and existing 25-row cap stay explicit.
The composer and final reviewer are skipped only for one successful validated
invoice display with matching requested scope/form. Earlier generated sentences
are held on these turns so they cannot precede the actual card readout.

Mixed requests retain model composition and factual review, with validated typed
invoice cells added to the existing digest. Labels, model summaries and speak
prose cannot invent the direct answer. Instruction-shaped stored cells are
rejected from the shortcut using existing speech/injection detectors.

Validation: 247 invoice, recovery, composer, receipt and speech tests passed.
Call-count tests prove both unnecessary model calls are skipped; no production
latency improvement is claimed before a new voice test. Regression fixtures use
fictional invoices and no private conversation content.
