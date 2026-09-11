"""The home page of mysolutionist.app, second edition (2026-09-11).

Kevin approved this page cut by cut as a design concept (the artifact
"Solutionist Hero, Bridgemind Cut", thirteen versions on 9/10 and 9/11)
and then said "let's push the site". The concept's HTML is turned into
marketing_home_v2.html by scripts/build_home_v2_template.py; this module
renders it with everything that has to be live:

  * the founding-seat strip and the three price cards are the SAME
    functions the previous home used (_founder_strip_html,
    _price_cards_html in marketing_pages), so the numbers come from the
    dials and every pricing test keeps its contract;
  * the plan-difference table on the page is built from _COMPARE_GROUPS
    and feature_gates.FEATURE_MIN_PLAN, so it can never promise a tier
    difference the product does not enforce;
  * the founding-seat flyer is marketing_founder_ad's, with its rules;
  * the film is /assets/film.mp4, the pixel and the first-party
    analytics are the shell's own;
  * the trial length and the contact address are the shell's sentinels.

Everything inside the room (Fade & Co., Andre, $6,910) is sample data,
labeled so on the page, and never reads a real business.
"""
from __future__ import annotations

import datetime
import html as _html
import pathlib

TEMPLATE_PATH = pathlib.Path(__file__).resolve().parent / "marketing_home_v2.html"
DESCRIPTION = ("One system runs the whole business: clients, calendar, invoices, books, your site and your "
               "marketing, with Chief, a chief of staff who reads your real day and does the work. "
               "Say what you do and the room takes shape.")

_TEMPLATE_CACHE: dict = {"mtime": None, "text": ""}


def _template() -> str:
    st = TEMPLATE_PATH.stat()
    if _TEMPLATE_CACHE["mtime"] != st.st_mtime:
        _TEMPLATE_CACHE["text"] = TEMPLATE_PATH.read_text(encoding="utf-8")
        _TEMPLATE_CACHE["mtime"] = st.st_mtime
    return _TEMPLATE_CACHE["text"]


def _pricing_html() -> str:
    import marketing_pages as mp
    return f"""    <section class="pricing chapter" id="pricing">
      <div class="hd reveal">
        <span class="eyebrow">What it costs</span>
        <h2 style="margin-top:12px">Chief works while you work: every plan, from day one.</h2>
        <p>One price. The whole business. A chief of staff who never clocks out.</p>
        <div class="billing" role="group" aria-label="Billing period"><button type="button" data-period="monthly" aria-pressed="true">Monthly</button><button type="button" data-period="annual" aria-pressed="false">Annual <span class="save">2 months free</span></button></div>
      </div>
{mp._founder_strip_html()}
      <div class="price-grid is-lit-grid">{mp._price_cards_html()}
      </div>
      <p class="askline reveal">__TRIAL_FREE__ on every plan. Every action logged and reversible. <button type="button" id="askCost">Or ask Chief what it costs.</button></p>
    </section>
"""


def _compare_tiers_html() -> str:
    """Only the rows that differ between plans, from the same source the
    /compare table reads. A row with the same answer on every plan is
    the product, not a difference, and stays off this table."""
    import feature_gates
    import marketing_pages as mp
    d = mp._tier_dials()
    plans = ("starter", "professional", "practice")
    names = ("Starter", "Professional", "Solutionist")
    rank = feature_gates._PLAN_RANK
    ok, no = '<span class="ok">✓</span>', '<span class="no">—</span>'
    groups = []
    for group, entries in mp._COMPARE_GROUPS:
        rows = []
        for label, source, _note in entries:
            if callable(source):
                values = [str(source(d[p])) for p in plans]
                if not all(v.strip() for v in values) or len(set(values)) == 1:
                    continue
                cells = "".join(f"<td>{v}</td>" for v in values)
            elif source == mp._ALL:
                continue
            else:
                min_plan = feature_gates.FEATURE_MIN_PLAN.get(source)
                if not min_plan:
                    continue
                marks = [rank.get(p, 0) >= rank.get(min_plan, 99) for p in plans]
                if all(marks):
                    continue
                cells = "".join(f"<td>{ok if m else no}</td>" for m in marks)
            rows.append(f"          <tr><td>{label}</td>{cells}</tr>")
        if rows:
            groups.append(f'          <tr class="grp"><td colspan="4">{group}</td></tr>\n' + "\n".join(rows))
    header = "".join(f"<th>{n} {d[p]['price']}</th>" for p, n in zip(plans, names))
    return f"""      <h3 class="reveal">What changes between plans</h3>
      <p class="sub reveal">Contacts, invoices, booking, documents, your site, Chief on every screen, the overnight run: on every plan. These are the rows that differ.</p>
      <div class="tbl reveal">
      <table>
        <thead><tr><th>What you get</th>{header}</tr></thead>
        <tbody>
{chr(10).join(groups)}
        </tbody>
      </table>
      </div>
      <p class="more reveal">The full table, every row on every plan: <a href="/compare">mysolutionist.app/compare</a></p>
"""


def _analytics_scripts() -> str:
    """The shell's attribution + first-party traffic scripts, as they are."""
    import marketing_pages as mp
    t = mp.SHELL_TEMPLATE
    i = t.index("<script>\n/* Campaign attribution")
    j = t.index("{extra_scripts}")
    return t[i:j].replace("{{", "{").replace("}}", "}")


def render_home_v2() -> str:
    import marketing_founder_ad
    import marketing_pages as mp
    ad_css, ad_markup = marketing_founder_ad.founder_ad_bundle("/")
    starter = mp._tier_dials()["starter"]["price_num"]
    html = (_template()
            .replace("{{PRICING}}", _pricing_html())
            .replace("{{COMPARE_TIERS}}", _compare_tiers_html())
            .replace("{{STARTER_PRICE}}", str(starter))
            .replace("{{FOUNDER_AD_CSS}}", ad_css)
            .replace("{{FOUNDER_AD_MARKUP}}", ad_markup)
            .replace("{{PIXEL}}", mp._pixel_script())
            .replace("{{ANALYTICS}}", _analytics_scripts())
            .replace("{{APP_URL}}", mp.APP_URL)
            .replace("{{DESCRIPTION}}", _html.escape(DESCRIPTION))
            .replace("{{YEAR}}", str(datetime.date.today().year)))
    return mp._fill_trial(mp._fill_contact(html))
