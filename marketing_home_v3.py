"""The home page of mysolutionist.app, third edition (2026-10-14).

Kevin approved this page pass by pass as a design (the artifact
"Solutionist Homepage", six versions on 10/14: the S at the center of the
hero, the practitioner photos in Who it's for, the moving scenes, thirty
things sorted to three, the seven-tools calculator, the film and the plan
table) and then said "ship to live". The design's HTML is
marketing_home_v3.html; this module renders it with everything that has to
be live:

  * the price cards, the plan table and every price in the page's prose and
    scripts read the same dials the app's Billing cards do
    (marketing_pages._tier_dials, pricing_config), so the page cannot quote a
    price the product does not charge;
  * the plan table is built from marketing_pages._COMPARE_GROUPS and
    feature_gates.FEATURE_MIN_PLAN, the same source /compare reads, so it can
    never promise a tier difference the product does not enforce; each card's
    "plus" list is filtered through the same gate map;
  * the founding seat (the section, the strip under the cards and the flyer)
    reads the live seat count and price, and disappears when there is no seat
    to sell;
  * the trial length, the no-card promise and the contact address are the
    shell's sentinels; the pixel, the analytics and the structured data are the
    second edition's, so search and attribution see no change;
  * the film is /assets/film.mp4 and the photos are /assets/home/*.jpg.

Every business, person and number inside the page (Fade & Co., Andre,
$6,910) is sample data, labeled so on the page, and never reads a real
business. The second edition stays importable: HOME_EDITION=v2 puts it back
without a deploy (marketing_pages.render_home).
"""
from __future__ import annotations

import datetime
import html as _html
import pathlib

TEMPLATE_PATH = pathlib.Path(__file__).resolve().parent / "marketing_home_v3.html"
DESCRIPTION = ("One system for the whole business, and Chief, an AI chief of staff who runs it beside you: "
               "bookings, clients, invoices, your website and the books, in the words your trade uses. "
               "Every problem has a solution.")

_TEMPLATE_CACHE: dict = {"mtime": None, "text": ""}

_PLANS = (("starter", "Starter"), ("professional", "Professional"), ("practice", "Solutionist"))
_CHECK = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
_ARROW = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
_CHEV = '<svg class="i chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>'

# What each card adds over the plan below it. Every line names the gate it
# depends on and only prints while that gate's minimum plan IS this card's
# plan, so a gate that moves takes the claim with it.
_PLUS = {
    "starter": (
        (None, "Contacts, booking, invoices, your website and Chief"),
        ("bookkeeping_basic", "Bookkeeping and bank reconciliation"),
        ("marketing_suggestion", "A suggested post for you every week"),
        ("agent_connector", "Connect your own AI, read-only"),
    ),
    "professional": (
        ("period_close", "Closing, 1099s and the year-end package"),
        ("chief_bookkeeping", "Chief explains your books"),
        ("site_concierge", "Chief answers your website’s visitors"),
        ("marketing_week", "Chief plans your marketing week"),
        ("agent_connector_write", "Your own AI can keep records here"),
    ),
    "practice": (
        ("dedicated_sms_number", "A texting number of your own"),
        ("ai_clips", "Find my best clips: ten hours of recordings a month"),
        ("accountant_collaborator", "An accountant seat, compliance reports and an audit trail"),
        ("marketing_autopilot", "Chief runs your marketing week"),
    ),
}
_BLURB = {
    "starter": "The full workspace. Contacts, invoicing, scheduling, content, goals, your site, and Chief.",
    "professional": ("Everything in Starter, plus the full accounting layer: closing, 1099s, year-end. "
                     "And Chief on your books, your site and your sourcing."),
    "practice": ("For the operator running everything through the system: Professional, plus room for a "
                 "team and more than one business."),
}
_INCLUDES = {"starter": "Included", "professional": "Everything in Starter, plus",
             "practice": "Everything in Professional, plus"}
_DEPTH = {"Standard": 1, "Advanced": 2, "Maximum": 3}


def _template() -> str:
    st = TEMPLATE_PATH.stat()
    if _TEMPLATE_CACHE["mtime"] != st.st_mtime:
        _TEMPLATE_CACHE["text"] = TEMPLATE_PATH.read_text(encoding="utf-8")
        _TEMPLATE_CACHE["mtime"] = st.st_mtime
    return _TEMPLATE_CACHE["text"]


def _gate_on(key, plan: str) -> bool:
    import feature_gates
    return key is None or feature_gates.FEATURE_MIN_PLAN.get(key) == plan


def _seats_line(t: dict) -> str:
    seats = "1 seat" if t["seats"] == 1 else f"{t['seats']} team seats"
    biz = "1 business" if t["businesses"] == 1 else f"{t['businesses']} businesses"
    return f"{seats} · {biz}"


def _banks_line(t: dict) -> str:
    return "Unlimited bank connections" if t["banks"] == "Unlimited" else f"{t['banks']} bank connections"


def _price_cards_html() -> str:
    """The three plan cards. Prices, annual twins, credits, the words under
    them, the analysis ladder, seats and bank connections come from the dials;
    the "plus" lines from the gate map. Professional is the lit card."""
    import marketing_pages as mp
    import pricing_config
    d = mp._tier_dials()
    credits_n = pricing_config.tier_credits()
    top = max(credits_n.values()) or 1
    cards, prev = [], None
    for plan, name in _PLANS:
        t = d[plan]
        mid = plan == "professional"
        monthly = t["price_num"]
        annual_total = monthly * mp.ANNUAL_MONTHS
        words = mp._credits_in_words(credits_n[plan], chief_works=(plan != "starter"),
                                     builds=(3 if plan == "practice" else 1))
        if plan == "practice":
            words = words.replace(", and Chief works between them", "")
        feats = [label for key, label in _PLUS[plan] if _gate_on(key, plan)]
        if prev is None or _seats_line(t) != _seats_line(prev):
            feats.append(_seats_line(t))
        if prev is None or t["banks"] != prev["banks"]:
            feats.append(_banks_line(t))
        depth = ""
        if t["analysis"]:
            level = _DEPTH.get(t["analysis"], 0)
            dots = "".join('<i class="on"></i>' if k <= level else "<i></i>" for k in (1, 2, 3))
            depth = (f'\n        <div class="depth"><span>{t["analysis"]} deep analysis</span>'
                     f'<span class="dots" aria-hidden="true">{dots}</span></div>')
        ribbon = '<span class="pc-ribbon">Most people land here</span>' if mid else ""
        lis = "".join(f"<li>{_CHECK}<span>{f}</span></li>" for f in feats)
        cards.append(f"""
      <div class="price-card{' is-mid' if mid else ''}">
        <div class="plan-top">{ribbon}<div class="price-name">{name}</div></div>
        <div class="pz"><b class="pc-num" data-monthly="{monthly}" data-annual="{annual_total // 12}" data-to="{monthly}" data-prefix="$">${monthly}</b><span>/month</span></div>
        <div class="bl price-billed" data-monthly="Billed monthly" data-annual="${annual_total:,} a year, billed once">Billed monthly</div>
        <p class="ds">{_BLURB[plan]}</p>
        <div class="meter" role="img" aria-label="{t['credits']} AI actions a month"><div class="row"><b>{t['credits']}</b><span>AI actions a month</span></div><div class="bar"><i style="--w:{credits_n[plan] / top * 100:.1f}%"></i></div><small>{words}</small></div>{depth}
        <p class="inc">{_INCLUDES[plan]}</p>
        <ul>{lis}</ul>
        <a class="btn {'btn-white' if mid else 'btn-ink'}" href="/start?plan={plan}">Start with {name} {_ARROW}</a>
      </div>""")
        prev = t
    return "".join(cards)


def _compare_table_html() -> str:
    """Every row of the plan table, grouped, with how many rows each plan
    includes per group and whether a row differs between plans (the "only
    what changes" switch reads that). Same rules as /compare: a gate decides a
    tick, a dial fills a number, a row with an empty dial is dropped."""
    import feature_gates
    import marketing_pages as mp
    d = mp._tier_dials()
    rank = feature_gates._PLAN_RANK
    head = "".join(
        f'<div class="pl{" hi" if p == "professional" else ""}"><b>{n}</b>'
        f'<span class="pp" data-monthly="{d[p]["price_num"]}" data-annual="{d[p]["price_num"] * mp.ANNUAL_MONTHS // 12}">'
        f'${d[p]["price_num"]}/mo</span>{"<em>Most chosen</em>" if p == "professional" else ""}</div>'
        for p, n in _PLANS)
    out = [f'<div class="cx-grid cx-head"><div class="lbl">What you get</div>{head}</div>']
    for gi, (group, entries) in enumerate(mp._COMPARE_GROUPS):
        rows, has, diffs = [], [0, 0, 0], 0
        for label, source, note in entries:
            if callable(source):
                values = [str(source(d[p])) for p, _ in _PLANS]
                if not all(v.strip() for v in values):
                    continue
            elif source == mp._ALL:
                values = ["Y", "Y", "Y"]
            else:
                min_plan = feature_gates.FEATURE_MIN_PLAN.get(source)
                if not min_plan:
                    continue
                values = ["Y" if rank.get(p, 0) >= rank.get(min_plan, 99) else "-" for p, _ in _PLANS]
            same = len(set(values)) == 1
            diffs += 0 if same else 1
            cells = []
            for k, v in enumerate(values):
                hi = " hi" if k == 1 else ""
                if v == "Y":
                    has[k] += 1
                    inner = f'<i class="yes" aria-label="Included">{_CHECK}</i>'
                elif v == "-":
                    inner = '<i class="no" aria-label="Not included"></i>'
                else:
                    has[k] += 1
                    inner = f"<b>{v}</b>"
                cells.append(f'<span class="c{hi}">{inner}</span>')
            sub = f"<small>{note}</small>" if note else ""
            rows.append(f'<div class="cx-grid cx-r" data-same="{1 if same else 0}"><span class="w"><b>{label}</b>{sub}</span>{"".join(cells)}</div>')
        if not rows:
            continue
        n = len(rows)
        counts = "".join(f'<span class="c{" hi" if k == 1 else ""}">{has[k]} of {n}</span>' for k in range(3))
        out.append(
            f'<div class="cx-g" data-g="{gi}" data-open="true" data-diffs="{diffs}">'
            f'<button type="button" class="cx-grid cx-gh" aria-expanded="true"><span class="t">{_CHEV}{group}<small>{n} rows</small></span>{counts}</button>'
            f'<div class="cx-rows"><div>{"".join(rows)}</div></div></div>')
    return "\n".join(out)


def _founder_state():
    """The live founding offer, or None when there is no seat to sell (no
    founder price on the server, or anything failing on the way: the page
    never breaks over it)."""
    import marketing_pages as mp
    import pricing_config
    import stripe_billing
    try:
        if not stripe_billing._founder_price_ids():
            return None
        limit = stripe_billing._founder_seat_limit()
        taken = mp._founder_seats_taken_sync()
        prices = pricing_config.tier_price_cents()
        price = prices.get("founder", 0) // 100
        state = {"limit": limit, "taken": taken, "left": max(0, limit - taken), "next": min(limit, taken + 1),
                 "price": price, "list_price": prices.get("professional", 0) // 100,
                 "credits": pricing_config.founder_credits()}
    except Exception:
        return None
    return state if price and limit > 0 else None


_NUM_WORDS = {10: "ten", 20: "twenty", 25: "twenty-five", 30: "thirty", 40: "forty", 50: "fifty", 100: "a hundred"}


def _founder_strip_html(f) -> str:
    """One line under the cards: the seat, the price, the live count. At zero
    it stays as one quiet line saying the seats went, because that tells the
    next visitor the offer was real."""
    if not f:
        return ""
    if f["left"] <= 0:
        return (f'<div class="seatstrip founder is-gone" id="founderStrip" data-left="0"><span class="sq" aria-hidden="true"></span>'
                f'<span><b>The {f["limit"]} founding seats are gone.</b> The price on this page is the price. '
                f'0 of {f["limit"]} seats left.</span></div>')
    nn = f"{f['next']:02d}"
    return (f'<a class="seatstrip" id="founderStrip" data-left="{f["left"]}" href="/start?plan=founder">'
            f'<span class="sq" aria-hidden="true"></span><b>Founding seat</b>'
            f'<span>Professional for ${f["price"]} a month, locked while you hold it. '
            f'<b>{f["left"]}</b> of {f["limit"]} seats left, {f["credits"]:,} AI actions a month.</span>'
            f'<span class="go">Claim seat {nn} {_ARROW}</span></a>')


def _seat_section_html(f) -> str:
    """The founding-seat chapter: the live count drawn as seats, the next
    seat's number on the card. Absent when there is no open seat."""
    if not f or f["left"] <= 0:
        return ""
    limit, taken = f["limit"], f["taken"]
    nn = f"{f['next']:02d}"
    words = _NUM_WORDS.get(limit, str(limit))
    seats = "".join('<i class="t"></i>' if i < taken else ('<i class="n"></i>' if i == taken else "<i></i>")
                    for i in range(limit))
    return f"""<!-- ============ NIGHT 4: founding seat ============ -->
<section class="ch night seat" id="seat" data-tone="night" aria-labelledby="seatH">
  <div class="seat-glow" aria-hidden="true"></div>
  <div class="wrap seat-grid">
    <div>
      <p class="eyebrow">Founding seats · {words} of them</p>
      <h2 class="h2" id="seatH">Get in at the beginning. <span class="grad">Keep the price.</span></h2>
      <p class="lede">{words[0].upper() + words[1:]} businesses get the full Professional plan, every part of the system and Chief, for ${f['price']} a month instead of ${f['list_price']}. The price is locked for as long as you hold the seat, and the seat comes with a Founding Charter in your name.</p>
      <div class="seats50" style="--cols:{min(25, limit)}" aria-hidden="true">{seats}</div>
      <p class="seat-meta mono"><span><b>{f['left']}</b> of {limit} seats left</span><span>Seat {nn} is next</span></p>
      <a class="btn btn-white" href="/start?plan=founder">Claim seat {nn} {_ARROW}</a>
    </div>
    <div class="cardstage" id="cardStage">
      <div class="floaty">
        <div class="fcard" id="fcard" role="img" aria-label="Founding seat card, number {nn} of {limit}">
          <span class="foil"></span><span class="dark"></span><span class="guil"></span><span class="sheen"></span>
          <div class="in">
            <div class="fc-top"><svg class="mk"><use href="#markW"/></svg><b>Solutionist</b><span class="no">Nº {nn} / {limit}</span></div>
            <div class="fc-mid"><span class="chipm"></span><span class="fm">Founding seat</span></div>
            <div class="fc-bot"><div><div class="rf">Reserved for</div><div class="bz" id="seatBiz">Fade &amp; Co.</div></div><div class="pl">Professional · ${f['price']}/mo<br>Locked while held</div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>
"""


def render_home_v3() -> str:
    import marketing_founder_ad
    import marketing_home_v2 as v2
    import marketing_pages as mp
    ad_css, ad_markup = marketing_founder_ad.founder_ad_bundle("/")
    dials = mp._tier_dials()
    founder = _founder_state()
    html = (_template()
            .replace("{{PRICE_CARDS}}", _price_cards_html())
            .replace("{{COMPARE_TABLE}}", _compare_table_html())
            .replace("{{FOUNDER_STRIP}}", _founder_strip_html(founder))
            .replace("{{SEAT_SECTION}}", _seat_section_html(founder))
            .replace("{{STARTER_PRICE}}", str(dials["starter"]["price_num"]))
            .replace("{{PRO_PRICE}}", str(dials["professional"]["price_num"]))
            .replace("{{SOL_PRICE}}", str(dials["practice"]["price_num"]))
            .replace("{{FOUNDER_SENTENCE}}", v2._founder_sentence())
            .replace("{{FOUNDER_AD_CSS}}", ad_css)
            .replace("{{FOUNDER_AD_MARKUP}}", ad_markup)
            .replace("{{PIXEL}}", mp._pixel_script())
            .replace("{{ANALYTICS}}", v2._analytics_scripts())
            .replace("{{APP_URL}}", mp.APP_URL)
            .replace("{{DESCRIPTION}}", _html.escape(DESCRIPTION))
            .replace("{{YEAR}}", str(datetime.date.today().year)))
    html = mp._fill_trial(mp._fill_contact(html))
    # after the sentinels are filled, so the FAQ answers carry the real trial length
    return html.replace("</head>", v2._jsonld(html, dials) + "</head>", 1)
