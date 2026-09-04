# Launch Access Control — Runbook (Arc 19 Phase B)

How to run the invite-only launch, grandfather accounts, set up Stripe for
the LOCKED pricing (docs/pricing_model.md), and flip billing enforcement —
plus how to roll all of it back.

> **2026-08-24 — the doors are open.** `LAUNCH_INVITE_ONLY` now defaults
> **OFF**: anyone can create an account, create a business, and start a
> subscription on a 7-day free trial. Everything below still works — set
> `LAUNCH_INVITE_ONLY=on` in Railway and the invite-only launch described
> here is back, no deploy needed. Invites, referrals, team invites and
> grandfathering are unaffected either way.

**State after deploy + migration:**
- `LAUNCH_INVITE_ONLY` defaults **OFF** → anyone can create a business and
  subscribe. Set it to `on` to require an invite (or grandfather); sign-IN
  stays open either way, and uninvited sign-UPs then see the waitlist.
- `BILLING_ENFORCE` stays **off** → all features free, no caps, no charges.
  Usage counters + the usage UI are live regardless (honest from day one).
- **Every account existing at migration time is grandfathered automatically**
  (free forever, unlimited usage, all features) — you, the accountant
  collaborators, team invitees, all of them.

---

## 0. Deploy-day order

1. Push backend `main` (Railway auto-deploys) + frontend `module-system`
   (Vercel auto-deploys).
2. Apply **`__migrations__/2026_06_10_phaseb_launch_access.sql`** in Supabase
   Studio. This creates the access tables AND mass-grandfathers every
   existing user. *(Run it after any earlier pending migrations.)*
3. Verify: Bookkeeping → Admin shows the **LAUNCH CONSOLE** section (it only
   renders for you — your email must match `PLATFORM_OWNER_EMAIL` on
   Railway, default kmjcreativesolution@gmail.com). Grandfathered count
   should equal your current user count.

## 1. Sending invites

Bookkeeping → Admin → **Launch Console → Invite a practitioner**:
type the email → **Send invite**. That creates a 30-day single-use token and
emails the link (`https://system.mysolutionist.app/?invite=<token>`) via
Resend. If the email fails, the link is shown — copy and send it yourself.
The Waitlist list has a one-click **invite** button per entry.

What the invitee experiences: link → sign-up form (email prefilled) →
account created → email verification → first sign-in consumes the token →
they can create their business. Invited accounts are **NOT grandfathered** —
they meter and (once enforcement flips) pay.

**Revoking:** Launch Console → Invites → **revoke** (pending invites only;
an accepted invite is already a person — use the grandfather/billing tools
for them instead).

## 2. Grandfathering a specific user

Launch Console → **Grandfather a user** → paste their auth user id (Supabase
Dashboard → Authentication → Users → copy UUID) → **Grant**. Effect is
immediate and total: unlimited usage, every feature, all caps bypassed, on
every business they own. **Remove** undoes it (they fall back to whatever
plan they have). Each grant records when/why.

## 3. Stripe setup (do BEFORE flipping enforcement)

In the Stripe **platform** account (the LLC account — NOT a Connect account):

1. **Products** — create three: "Solutionist Starter", "Solutionist
   Professional", "Solutionist Practice".
2. **Subscription Prices** (recurring): monthly $79 / $149 / $299 (Founder $99) and annual
   $790 / $1,990 / $3,990 (~17% off).
3. **Overage Prices** (one per product): *recurring → usage-based
   (metered)*, monthly, aggregation **sum**, per-unit **$0.40 / $0.30 /
   $0.25**. These bill the per-interaction overage; Solutionist reports only
   billable overage quantity (allotments + the 2×-bill cap are enforced in
   our code, never in Stripe).
4. **Webhook**: endpoint `https://kmj-intake-server-production.up.railway.app/billing/webhook`,
   events: `checkout.session.completed`, `customer.subscription.*`,
   `invoice.payment_succeeded`, `invoice.payment_failed`. Copy the signing
   secret.
5. **Railway env vars:**
   ```
   STRIPE_SECRET_KEY                    sk_live_…
   STRIPE_WEBHOOK_SECRET                whsec_…
   STRIPE_PRICE_ID_STARTER              price_…   (monthly)
   STRIPE_PRICE_ID_PROFESSIONAL         price_…
   STRIPE_PRICE_ID_PRACTICE             price_…
   STRIPE_PRICE_ID_STARTER_ANNUAL       price_…   (optional until annual UX ships)
   STRIPE_PRICE_ID_PROFESSIONAL_ANNUAL  price_…
   STRIPE_PRICE_ID_PRACTICE_ANNUAL      price_…
   STRIPE_PRICE_ID_STARTER_OVERAGE      price_…   (metered)
   STRIPE_PRICE_ID_PROFESSIONAL_OVERAGE price_…
   STRIPE_PRICE_ID_PRACTICE_OVERAGE     price_…
   ```
   *(Verify current Anthropic pricing at anthropic.com/pricing first — June
   2026 check: Opus $5/$25, Sonnet $3/$15, Haiku $1/$5 — margins are even
   better than the spec's table; rates above are the locked ones.)*

> **Note for the checkout flow:** subscriptions should be created with BOTH
> items (the tier price + its overage price) so the metered item exists for
> usage reporting. The existing `/billing/checkout` creates tier-only
> subscriptions today — adding the overage line item is a one-line
> `subscription_data.items` extension flagged for the enforcement-flip PR
> (it's deliberately not needed while everyone is grandfathered/dormant).

## 4. Pre-flight checklist (before `BILLING_ENFORCE=on`)

Open Launch Console → readiness panel. **Flip only when it shows
"Pre-flight clean."** It checks, live:
- ✅ all 3 subscription price ids set
- ✅ all 3 overage price ids set
- ✅ `STRIPE_WEBHOOK_SECRET` set
- ✅ zero active businesses whose owner is neither grandfathered nor
  subscribed (each listed issue names the gap)

Plus, manually:
- [ ] Stripe webhook shows successful test deliveries
- [ ] One end-to-end test subscription on a non-grandfathered test account
      (checkout → tier shows in Settings → Billing → usage meters against
      the right allotment)
- [ ] You're comfortable with the grandfathered count (that list is free
      forever)

Then: Railway → service → Variables → `BILLING_ENFORCE=on` → redeploy.
**The code never flips this itself.**

## 5. What enforcement changes, concretely

| Surface | Off (today) | On |
|---|---|---|
| Features (GL, exports, collaborator…) | all free | tier-gated (grandfather bypass) |
| Chief interactions | counted, never blocked | allotment → overage billed → blocked at 2× cap or hard cap |
| Business creation | invite-gate only | + tier cap (1/1/3) |
| Team seats | counted | capped 1/1/5 |
| Plaid connections | counted | capped 2/5/unlimited |
| Stripe usage reporting | dormant | daily job reports overage |

## 6. Rollback

- **Too aggressive / something's wrong:** `BILLING_ENFORCE=off` in Railway →
  everything is instantly free again. No data is touched; usage history and
  subscriptions persist. This is always safe.
- **Stop charging overage only:** remove the `*_OVERAGE` env vars — the
  daily reporter skips businesses with no overage price configured.
- **Close the doors again (re-gate to invite-only):** `LAUNCH_INVITE_ONLY=on`
  → business creation needs an invite or a grandfather flag again. This is
  the reverse of the 2026-08-24 flip; the open state is the default, and
  the free-trial pattern from Phase E is what carries billing.
- **Un-grandfather someone:** Launch Console → Grandfather → Remove.
- **Nuclear:** the migration's rollback block drops the five access tables
  (grandfather flags included — re-running the migration re-grandfathers
  whoever exists at that moment, so don't run it after launch unless you
  mean it).

## 6.5 Regulated-vertical autonomy defaults (Arc 20B)

Businesses created with a lawyer / therapist / counseling type carry
`settings.autonomy.client_facing_autonomy = "disabled"` from birth. When
autonomous Chief capabilities ship (Phase C), these businesses CANNOT enable
client-facing autonomy without an explicit acknowledgment screen
(professional-ethics ruling). No action needed now — the flag simply exists
so the default predates the feature. Grandfathering does NOT bypass this.

## 7. Support cheatsheet

| Practitioner says | Likely cause | Fix |
|---|---|---|
| "It says invite-only but I have an account" | Pre-launch account missing profile row | Grandfather them (or check migration ran) |
| "My invite link doesn't work" | Used / >30 days / revoked | Send a fresh invite |
| "Chief stopped responding" | 2× cap or their own hard cap | Settings → Billing shows which; upgrade or wait for the 1st |
| "Why did my bill go up?" | Overage | Settings → Billing shows the meter + per-unit rate; bill ≤ 2× plan, always |
