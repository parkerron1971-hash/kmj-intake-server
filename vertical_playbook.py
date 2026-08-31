"""
vertical_playbook.py — Feed 1b. What an operator in this trade knows.

WHY THIS EXISTS
  Everything the system knew about a vertical was VOICE. `vertical_context`
  ships register, formality, a six-word vocabulary, three or four hallmarks,
  a couple of taboos and a list of typical offerings — roughly 600-1200
  characters — and that is the whole of it. The effect is that Chief SOUNDS
  like a lawyer's assistant without knowing anything about running a law
  practice. It can use the word "matter" and still have nothing to say about
  work-in-progress ageing into a fee dispute.

  This module is the other half: operating knowledge. What goes wrong in
  this trade, what the season does to it, what the customer pushes back on.

WHY IT IS RETRIEVED AND NOT ALWAYS-ON
  The static block promises under 600 chars for the median vertical and
  never over 1500, and a test enforces it. That budget is real — the block
  ships on EVERY Chief request. Depth cannot live there.

  So it lives where Feed 2's does: `vertical_knowledge` rows, embedded,
  pulled by relevance to what the practitioner actually asked, under the
  learned block's own 700-char budget. A question about collections
  retrieves the collections knowledge and nothing else. The pipe was
  already built and already wired into the Chief turn; it had nothing
  flowing through it, because Feed 2 cannot produce a row until three
  businesses in one vertical show the same pattern and the evidence tables
  are empty.

  Curation is how the shelf gets stocked before the learning loop can
  stock it. When Feed 2 does start producing, the two sit side by side —
  and they are labelled differently in the prompt on purpose, because
  "several businesses like yours do this" and "this is how the trade
  works" are not the same claim and Chief should not weigh them alike.

WHAT MAY LIVE HERE — AND THE ONE THING THAT MAY NOT
  Qualitative operating knowledge. Mechanisms, sequences, seasons,
  objections: things that are true about the trade and that a practitioner
  would recognise.

  NOT BENCHMARK NUMBERS. Not "typical no-show rate is 15%", not "the
  average ticket is $45". Nobody measured those here, and a fabricated
  number reads as authoritative precisely because it is specific — Chief
  would repeat it to a practitioner who would act on it. Where the useful
  thing IS a number, the entry says which number to look at and what it
  would mean, and leaves the value to the business's own data. A test
  asserts no entry carries a bare percentage or currency figure.

  Anything a practitioner should hear from their accountant or lawyer
  defers to them rather than answering, the same way the bookkeeping map
  does.

AUTHORING
  Python literals, in git. Deliberately not authored straight into the
  table: every row here is a claim the product makes about someone's
  trade, and it should be reviewable in a diff before it reaches a
  prompt. `curate_tick()` projects it into rows, diff-first, the way
  vertical_knowledge.seed_tick projects the profiles.
"""
from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger("vertical_playbook")

# Kinds. Free-form in the table by design; these are the ones used here.
KIND_PLAYBOOK = "playbook"      # what goes wrong, and the move
KIND_SEASON = "season"          # what the calendar does to this trade
KIND_OBJECTION = "objection"    # what the customer pushes back on
KIND_SIGNAL = "signal"          # which number to watch, and what it means


# Keyed canonically — vertical_knowledge._key() resolves aliases on the way
# in, so a business typed 'church' reaches the ministry shelf.
#
# 'custom' is absent on purpose. vertical_registry marks it "intentionally
# GENERIC — triggers Chief interactive discovery": the premise is that the
# system does not yet know what the business does, so writing it a playbook
# would mean inventing the trade.
PLAYBOOK: Dict[str, List[Dict[str, str]]] = {
    "lawyer": [
        {"kind": KIND_PLAYBOOK,
         "content": "Unbilled work in progress ages badly. The longer the gap between doing "
                    "the work and billing it, the harder it collects and the more likely the "
                    "client disputes it — a matter that goes quiet is the one that becomes a "
                    "fee dispute."},
        {"kind": KIND_PLAYBOOK,
         "content": "Scope creep is how a profitable flat-fee matter turns unprofitable. Work "
                    "beyond the engagement letter needs a written amendment before it happens, "
                    "not a favour that surfaces at billing."},
        {"kind": KIND_PLAYBOOK,
         "content": "A conflict check run after the intake call has already cost the firm the "
                    "call. It belongs before substantive discussion, not merely before "
                    "engagement."},
        {"kind": KIND_SIGNAL,
         "content": "The number that predicts trouble is the age of unbilled time, not the "
                    "size of the receivable. Receivables are visible; WIP is not."},
        {"kind": KIND_OBJECTION,
         "content": "Prospects compare hourly rates across firms and almost never compare what "
                    "each rate includes. Answering a rate question with a rate competes on "
                    "price; answering with scope changes the axis."},
        {"kind": KIND_SEASON,
         "content": "Estate and tax-adjacent work concentrates before year-end. Court calendars "
                    "go quiet from late December and reopen hard in January."},
    ],
    "therapist": [
        # Money, scheduling and admin only. Clinical records are out of scope
        # (vertical_scope.py) and nothing here reaches toward session content.
        {"kind": KIND_PLAYBOOK,
         "content": "A cancelled hour that isn't refilled is revenue that cannot be recovered — "
                    "the slot does not carry forward. A short waitlist that can be texted "
                    "same-day is worth more to a practice than a longer roster."},
        {"kind": KIND_PLAYBOOK,
         "content": "Claims denied on eligibility usually fail on stale coverage data rather "
                    "than anything about the care. Re-verifying at intake and again at the "
                    "start of each plan year prevents most of them."},
        {"kind": KIND_SIGNAL,
         "content": "Watch the gap between date of service and date of payment for insurance "
                    "work. A widening gap is a claims problem showing up before the revenue "
                    "does."},
        {"kind": KIND_OBJECTION,
         "content": "Prospective clients ask about cost before they ask about fit. A "
                    "private-pay practice that leads with its rate ends up competing on rate."},
        {"kind": KIND_SEASON,
         "content": "Late December and much of August are the reliable soft weeks; January is "
                    "the reliable surge."},
    ],
    "contractor": [
        {"kind": KIND_PLAYBOOK,
         "content": "The bid is not the sale. An estimate that isn't followed up within a few "
                    "days loses to whoever did follow up, and the follow-up is where most of "
                    "this work is actually won."},
        {"kind": KIND_PLAYBOOK,
         "content": "Ordering materials before the deposit clears is how a trade business ends "
                    "up financing its customer. The deposit exists to cover the point of no "
                    "return, so it has to land before that point."},
        {"kind": KIND_PLAYBOOK,
         "content": "A change order agreed verbally on site is the one that doesn't get paid. "
                    "Price it and put it in writing before the work happens — at invoicing it "
                    "reads as a surprise bill."},
        {"kind": KIND_SIGNAL,
         "content": "Track the share of bids that turn into jobs, and separately how long a bid "
                    "sits before it is accepted. A healthy close rate with a lengthening delay "
                    "means the follow-up slipped, not the pricing."},
        {"kind": KIND_OBJECTION,
         "content": "Customers compare bid totals, not scope. A bid that names what the cheaper "
                    "bid leaves out wins more often than one that simply lowers the number."},
        {"kind": KIND_SEASON,
         "content": "Exterior trades compress into the warm months. The winter gap is the "
                    "window to sell interior work, not the season to go quiet."},
    ],
    "personal_services": [
        {"kind": KIND_PLAYBOOK,
         "content": "Rebooking happens in the chair or it doesn't happen. The moment to book "
                    "the next appointment is before the client stands up — afterwards it "
                    "becomes an outbound task that mostly doesn't get done."},
        {"kind": KIND_PLAYBOOK,
         "content": "A no-show costs the chair, not just the ticket, because the slot cannot be "
                    "resold after the fact. A card on file changes the behaviour far more than "
                    "a stated policy does."},
        {"kind": KIND_PLAYBOOK,
         "content": "Retail attaches to the service that just happened. Recommending the "
                    "product actually used during the appointment converts; a shelf on its own "
                    "does not."},
        {"kind": KIND_SIGNAL,
         "content": "The number that describes the health of this business is the share of "
                    "clients who come back within their usual interval — not the number of new "
                    "clients. A full book of first-timers is a leak, not growth."},
        {"kind": KIND_OBJECTION,
         "content": "Price pushback here is usually about the unknown rather than the amount. "
                    "Naming what the service includes and how long it takes defuses more of it "
                    "than discounting."},
        {"kind": KIND_SEASON,
         "content": "December and the run-up to school terms and major holidays are the peaks; "
                    "January is the reliable trough."},
    ],
    "coach": [
        {"kind": KIND_PLAYBOOK,
         "content": "The client who goes quiet between sessions is the one who doesn't renew. A "
                    "check-in between sessions is retention work, not admin."},
        {"kind": KIND_PLAYBOOK,
         "content": "Discovery calls convert on fit, not on persuasion. Disqualifying early "
                    "protects both the roster and the results the practice can point to later."},
        {"kind": KIND_PLAYBOOK,
         "content": "A package sold as a number of sessions gets compared on price per session. "
                    "The same package sold as an outcome over a period does not."},
        {"kind": KIND_SIGNAL,
         "content": "Renewal rate at the end of a package says more about the practice than "
                    "lead volume does. Falling renewals with steady leads is a delivery "
                    "problem wearing a marketing disguise."},
        {"kind": KIND_SEASON,
         "content": "January and September are the two reliable surges — the moments people "
                    "restart. Summer is the reliable trough."},
    ],
    "consultant": [
        {"kind": KIND_PLAYBOOK,
         "content": "An engagement that ends without a next step defined is the one that "
                    "doesn't renew. The final deliverable is the best moment to scope what "
                    "follows it, and the worst moment to leave silent."},
        {"kind": KIND_PLAYBOOK,
         "content": "Scope written as activities gets billed as activities. Scope written as "
                    "deliverables with acceptance criteria is what makes a fixed fee safe to "
                    "quote."},
        {"kind": KIND_PLAYBOOK,
         "content": "Hourly pricing caps revenue at the practitioner's capacity. Moving off it "
                    "needs the client's business case captured at intake — by proposal time "
                    "the anchor is already the rate."},
        {"kind": KIND_SIGNAL,
         "content": "Watch revenue concentration by client. A practice where one client is most "
                    "of the year is a practice one email away from a bad quarter."},
        {"kind": KIND_SEASON,
         "content": "Budget cycles drive this work: Q4 planning and Q1 budget release are the "
                    "two windows where decisions actually get made."},
    ],
    "creative": [
        {"kind": KIND_PLAYBOOK,
         "content": "Uncapped revision rounds are the main way a profitable project loses "
                    "money. The number of rounds belongs in the scope, together with the price "
                    "of one more."},
        {"kind": KIND_PLAYBOOK,
         "content": "Pass-through costs — ad spend, licensing, print — run through the "
                    "business's account without being its revenue. Mixed into the same bucket "
                    "they make margin unreadable."},
        {"kind": KIND_PLAYBOOK,
         "content": "Retainers survive on visible output. The month a client cannot see what "
                    "was done is the month before the cancellation email."},
        {"kind": KIND_SIGNAL,
         "content": "Compare fee revenue against pass-through separately from the total. A "
                    "growing total with flat fees means the business is getting busier without "
                    "getting bigger."},
        {"kind": KIND_OBJECTION,
         "content": "Clients compare deliverable counts across proposals. A proposal that shows "
                    "the thinking behind the deliverable competes somewhere the count can't "
                    "reach."},
    ],
    "course_creator": [
        {"kind": KIND_PLAYBOOK,
         "content": "Completion predicts refunds and testimonials better than sales volume "
                    "does. A cohort that finishes is the marketing for the next one."},
        {"kind": KIND_PLAYBOOK,
         "content": "Launches concentrate revenue and then leave a gap. An evergreen path off "
                    "the same asset is what turns a launch into a business."},
        {"kind": KIND_PLAYBOOK,
         "content": "Revenue is earned when the refund window closes, not on launch day. "
                    "Counting a launch as booked immediately overstates the month and "
                    "understates the next one."},
        {"kind": KIND_SIGNAL,
         "content": "Watch how far into the material students get before they stop. Where they "
                    "stop is where the course needs work, and it is usually earlier than the "
                    "creator expects."},
        {"kind": KIND_SEASON,
         "content": "January and September carry the intent to start something. The back half "
                    "of December is dead for anything that asks effort of the buyer."},
    ],
    "fitness_wellness": [
        {"kind": KIND_PLAYBOOK,
         "content": "Attrition is quiet. A member stops showing up weeks before they cancel, so "
                    "missed-visit patterns spot churn long before the cancellation does."},
        {"kind": KIND_PLAYBOOK,
         "content": "The first weeks decide whether a new member becomes a long-term one. "
                    "Attention spent on onboarding returns more than the same spend on "
                    "acquisition."},
        {"kind": KIND_PLAYBOOK,
         "content": "Unused class-pack balances are a liability rather than a win — they turn "
                    "into refund requests and bad reviews about as often as they expire "
                    "quietly."},
        {"kind": KIND_SIGNAL,
         "content": "Visit frequency per member is the leading indicator; cancellations are the "
                    "lagging one. By the time cancellations move, the cause is months old."},
        {"kind": KIND_SEASON,
         "content": "January is the surge and early spring the drop-off. Summer is soft for "
                    "indoor work and strong for outdoor."},
    ],
    "ministry": [
        {"kind": KIND_PLAYBOOK,
         "content": "Giving follows attendance with a lag — a drop in attendance shows up in "
                    "the offering weeks later. Watching only giving means noticing late."},
        {"kind": KIND_PLAYBOOK,
         "content": "A first-time visitor decides about returning within about a week. "
                    "Follow-up inside a few days is the highest-leverage thing a small "
                    "congregation does, and it is almost entirely a scheduling problem."},
        {"kind": KIND_PLAYBOOK,
         "content": "A designated giving campaign raises money that cannot pay the electric "
                    "bill. General fund health has to be tracked on its own or the books look "
                    "healthier than the church is."},
        {"kind": KIND_SIGNAL,
         "content": "The number worth watching is how many households give at all, not the "
                    "total. A stable total carried by fewer households is a fragile total."},
        {"kind": KIND_SEASON,
         "content": "December and Easter are the giving peaks. Summer is the reliable trough in "
                    "both attendance and giving."},
    ],
    "nonprofit": [
        {"kind": KIND_PLAYBOOK,
         "content": "Most individual giving arrives in the final weeks of December. An "
                    "organisation that begins its year-end appeal in December has already "
                    "missed the window where the appeal is planned."},
        {"kind": KIND_PLAYBOOK,
         "content": "Grants fund programs and rarely fund the people who run them. An "
                    "organisation funded entirely by restricted grants can be busy and "
                    "insolvent at the same time."},
        {"kind": KIND_PLAYBOOK,
         "content": "A first-time donor thanked promptly gives again at a markedly higher rate "
                    "than one who isn't. The acknowledgment is fundraising, not admin, and the "
                    "window is days."},
        {"kind": KIND_SIGNAL,
         "content": "Watch the share of revenue that is unrestricted. It is the only part that "
                    "can keep the lights on, and a growing budget can hide it shrinking."},
        {"kind": KIND_SEASON,
         "content": "November and December dominate individual giving. Grant deadlines cluster "
                    "by each funder's fiscal year rather than the calendar."},
    ],
    "financial_educator": [
        {"kind": KIND_PLAYBOOK,
         "content": "The line between education and personalised advice is where this "
                    "business's regulatory exposure sits. Teaching a framework stays on one "
                    "side; addressing a specific person's situation crosses to the other."},
        {"kind": KIND_PLAYBOOK,
         "content": "Affiliate and sponsorship income carries disclosure obligations that "
                    "course revenue does not. Booked into one bucket, the question of whether "
                    "a disclosure was needed becomes invisible."},
        {"kind": KIND_SIGNAL,
         "content": "Watch the mix between what the audience pays for and what sponsors pay "
                    "for. A business drifting toward sponsorship is changing who its customer "
                    "is."},
        {"kind": KIND_SEASON,
         "content": "Tax season and January are the two windows where demand for financial "
                    "education spikes."},
    ],
    "ecommerce": [
        {"kind": KIND_PLAYBOOK,
         "content": "Carts are abandoned at the shipping cost far more often than at the "
                    "product. The same number shown early reads as the price; shown at "
                    "checkout it reads as a surprise."},
        {"kind": KIND_PLAYBOOK,
         "content": "A stock-out costs more than the missed sale — the customer finds whoever "
                    "does have it and often stays there. Reorder against lead time, not "
                    "against zero."},
        {"kind": KIND_PLAYBOOK,
         "content": "Returns are a cost of selling online, not a failure. A return policy that "
                    "is hard to find raises support load and chargebacks more than it prevents "
                    "returns."},
        {"kind": KIND_SIGNAL,
         "content": "Watch the share of orders from returning customers, not order count alone. "
                    "A store growing only on first-time buyers is re-buying its revenue every "
                    "month."},
        {"kind": KIND_OBJECTION,
         "content": "Shoppers compare the delivered price, not the listed one. A listing that "
                    "is cheaper until checkout loses to the one that was honest up front."},
        {"kind": KIND_SEASON,
         "content": "Q4 dominates and the run-up starts well before it. January is returns and "
                    "support volume rather than sales."},
    ],
    "saas": [
        {"kind": KIND_PLAYBOOK,
         "content": "Churn is decided in the first weeks, not at renewal. An account that never "
                    "reached the thing it signed up to do has already gone; the cancellation is "
                    "the paperwork catching up."},
        {"kind": KIND_PLAYBOOK,
         "content": "Usage leads and billing lags. An account whose logins stopped is a renewal "
                    "that has already failed, and the invoice is the last place it shows."},
        {"kind": KIND_PLAYBOOK,
         "content": "Annual plans smooth cash and hide churn — a customer who stopped using it "
                    "in month two still reads as revenue until the renewal that never comes."},
        {"kind": KIND_SIGNAL,
         "content": "Net revenue retention — expansion from existing accounts minus what "
                    "churned — answers whether the business grows without new logos. A signup "
                    "count cannot answer that."},
        {"kind": KIND_OBJECTION,
         "content": "Prospects compare feature lists and buy on the one job they came to do. A "
                    "demo that tours the product loses to one that does that job."},
        {"kind": KIND_SEASON,
         "content": "Enterprise buying follows budget cycles and stalls over holidays. "
                    "Self-serve signups spike in January and September."},
    ],
    "service_provider": [
        {"kind": KIND_PLAYBOOK,
         "content": "A quote that isn't followed up loses to whoever did. Most of this work is "
                    "won in the gap between the estimate and the decision, not in the estimate."},
        {"kind": KIND_PLAYBOOK,
         "content": "Recurring work is worth more than its ticket suggests, because a client "
                    "already on a schedule costs nothing to re-acquire."},
        {"kind": KIND_PLAYBOOK,
         "content": "A deposit is what stops a cancellation from costing the whole day. Without "
                    "one, the calendar looks full right up until it isn't."},
        {"kind": KIND_SIGNAL,
         "content": "Track the share of revenue from repeat clients. Rising new-client counts "
                    "with flat repeat revenue means the work isn't sticking."},
    ],
}


def entries_for(vertical: str) -> List[Dict[str, str]]:
    """Curated knowledge for a vertical, alias-resolved. Empty for anything
    with no shelf — including 'custom', deliberately."""
    import vertical_registry
    return list(PLAYBOOK.get(vertical_registry.resolve(vertical)) or [])


def curate_tick(verticals: List[str] | None = None) -> Dict[str, int]:
    """Project this module into `vertical_knowledge` rows as source='curated'.

    Diff-first, exactly like `vertical_knowledge.seed_tick` and for the same
    reason: `upsert` embeds BEFORE it writes, so a blind re-run would pay for
    every embedding again to produce zero new rows. Checking first is what
    makes this cheap enough to schedule, and scheduling it is what stops the
    corpus depending on someone remembering to run it after an edit.

    Unlike the seed rows, these ARE read — `build_vertical_learned_block`
    retrieves source in ('learned','curated'). Editing this file and waiting
    for the tick genuinely changes what Chief knows.

    Idempotent. Safe to call as often as you like. Never raises."""
    import vertical_knowledge as vk

    if not vk._enabled():
        return {"written": 0, "skipped": 0, "verticals": 0, "failed": 0}

    keys = verticals or list(PLAYBOOK.keys())
    written = skipped = failed = 0
    for vertical in keys:
        # Per-vertical guard, same reasoning as seed_tick: one malformed
        # shelf should cost that shelf and nothing else. Without it the
        # remaining verticals never write and the scheduler wrapper
        # swallows the exception — silent AND partial.
        try:
            have = {r.get("content") for r in
                    vk.list_for_vertical(vertical, source=vk.SOURCE_CURATED)}
            for row in PLAYBOOK.get(vertical) or []:
                if row["content"] in have:
                    skipped += 1
                    continue
                # confidence 0.8: curated knowledge is deliberate and
                # reviewed, but it is a claim about a trade in general and
                # should lose to the business's own history, which is what
                # the block's framing tells Chief to do.
                if vk.upsert(vertical, row["kind"], row["content"],
                             source=vk.SOURCE_CURATED, confidence=0.8):
                    written += 1
        except Exception as e:
            failed += 1
            logger.warning(f"[playbook] curate_tick skipped '{vertical}': {e}")

    if written or failed:
        logger.info(f"[playbook] curate_tick wrote {written} new rows "
                    f"({skipped} already present, {failed} verticals failed) "
                    f"across {len(keys)} verticals")
    return {"written": written, "skipped": skipped,
            "verticals": len(keys), "failed": failed}
