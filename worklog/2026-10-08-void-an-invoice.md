---
title: Void an invoice from the invoice drawer, and Chief's void no longer stalls on a shared pay link
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: 'Dev Desk: "Can you develope an ability to void out invoices. Chief and I. I don''t see a void ability"'
status: shipped
prs: [kmj-intake-server#1352, solutionist-studio#1176]
migrations: []
left_undone: ["an invoice carrying a pay link that can't be verified (KMJ's legacy platform-account links, a link from a Stripe account the business has since changed) is still refused, and the refusal has no 'I switched it off myself' way through", "Chief's void does not pass through the closed-period soft-lock; the drawer's Void button does", "drafts keep Delete in the drawer, not Void"]
decisions: ["the drawer never PATCHes the row: POST /invoices/{id}/void runs Chief's own _change('void_invoice') as the signed-in person (RLS), member+ like invoice-checkout", "the business's pasted pay link (settings.payments.stripe_link) is shared by design: a void leaves it on for other invoices and only detaches it from this row, and the result says so", "refusals come back as 409 with Chief's reason, shown as the toast"]
related: []
---
Chief has had `void_invoice` since 2026-09-09 (docs/CHIEF_INVOICE_LIFECYCLE.md),
but the app had no Void button, and both paths refused any invoice carrying
the business's own pasted pay link as "shared or cannot be verified". Every
invoice made without a per-invoice Connect link carries that link, so the
refusal covered most of them, including deleting such a draft.

`invoice_payment_links.is_business_pay_link` recognises that link and
`disable_invoice_payment_link` returns 'shared' without touching Stripe. A
per-invoice link is still verified, deactivated and its open checkouts
expired, as before. The new route lives in `chief_invoice_actions.router`,
registered after `stripe_payments_router` and well before the public-site
catch-all. The GL engine already drops voided invoices (cancelled is not an
issue status), and the webhook's amount fallback skips them.
