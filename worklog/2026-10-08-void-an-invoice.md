---
title: Void an invoice from the invoice drawer, and Chief's void no longer stalls on a shared pay link
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: 'Dev Desk: "Can you develope an ability to void out invoices. Chief and I. I don''t see a void ability"'
status: shipped
prs: [kmj-intake-server#1352, solutionist-studio#1176, kmj-intake-server (branch void-invoice-dead-ends), solutionist-studio (branch void-invoice-dead-ends)]
migrations: []
left_undone: ["a Stripe-side reason for KMJ's INV-2026-010 refusal was never seen (no Stripe access from here); the void now logs 'void refused' / 'pay link unverified' with the reason, so read Railway logs if it recurs", "Chief's void does not pass through the closed-period soft-lock; the drawer's Void button does", "drafts keep Delete in the drawer, not Void"]
decisions: ["the drawer never PATCHes the row: POST /invoices/{id}/void runs Chief's own _change('void_invoice') as the signed-in person (RLS), member+ like invoice-checkout", "the business's pasted pay link (settings.payments.stripe_link) is shared by design: a void leaves it on for other invoices and only detaches it from this row, and the result says so", "refusals come back as 409 {detail, code}; the drawer shows the reason above its buttons (toasts sat at z 800 under the 2900 drawer, so Kevin's first four refusals were invisible; toasts now 3000)", "a link is this invoice's own when source_type=invoice and source_id is its UUID; business_id may be missing (pre-2026-06-06 links) but never different; the connected account is searched, then the platform account", "a link nobody can verify needs the owner's word (link_off_confirmed, a second confirm in the drawer, an explicit yes to Chief); then it is detached, never switched off"]
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

Follow-up the same day: Kevin pressed Void on KMJ's INV-2026-010 (June 6,
$5) four times and saw nothing. The server refused each time in the pay-link
check, and the reason was drawn under the drawer. Branch
void-invoice-dead-ends: older links without a business tag count, the
platform account is searched too, a Stripe lookup error falls through to
the next account, a link that still can't be verified gets a "void anyway"
choice instead of a dead end, and every refusal is logged.
