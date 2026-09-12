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
    """The whole product on every plan, from the same source the /compare
    page reads (_COMPARE_GROUPS + FEATURE_MIN_PLAN + the dials): every row,
    a tick where every plan has it, the dial where plans differ. Kevin,
    9/12: a differences-only table made Starter read as a column of
    dashes; the old site showed what each plan includes, so this does."""
    import feature_gates
    import marketing_pages as mp
    d = mp._tier_dials()
    plans = ("starter", "professional", "practice")
    names = ("Starter", "Professional", "Solutionist")
    rank = feature_gates._PLAN_RANK
    ok = '<span class="mx-cell"><i class="ok"></i></span>'
    no = '<span class="mx-cell"><i class="no"></i></span>'
    groups = []
    for group, entries in mp._COMPARE_GROUPS:
        rows = []
        for label, source, _note in entries:
            if callable(source):
                values = [str(source(d[p])) for p in plans]
                if not all(v.strip() for v in values):
                    continue
                cells = "".join(f'<span class="mx-cell"><b>{v}</b></span>' for v in values)
            elif source == mp._ALL:
                cells = ok * 3
            else:
                min_plan = feature_gates.FEATURE_MIN_PLAN.get(source)
                if not min_plan:
                    continue
                cells = "".join(ok if rank.get(p, 0) >= rank.get(min_plan, 99) else no for p in plans)
            sub = f"<small>{_note}</small>" if _note else ""
            rows.append(f'            <div class="mx-row"><div class="mx-what"><b>{label}</b>{sub}</div>{cells}</div>')
        if rows:
            groups.append(f'          <div class="mx-group"><h4>{group}</h4>\n' + "\n".join(rows) + "\n          </div>")
    return chr(10).join(groups)


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
    dials = mp._tier_dials()
    starter = dials["starter"]["price_num"]
    html = (_template()
            .replace("{{PRICING}}", _pricing_html())
            .replace("{{COMPARE_TIERS}}", _compare_tiers_html())
            .replace("{{STARTER_PRICE}}", str(starter))
            .replace("{{PRO_PRICE}}", str(dials["professional"]["price_num"]))
            .replace("{{SOL_PRICE}}", str(dials["practice"]["price_num"]))
            .replace("{{FOUNDER_AD_CSS}}", ad_css)
            .replace("{{FOUNDER_AD_MARKUP}}", ad_markup)
            .replace("{{PIXEL}}", mp._pixel_script())
            .replace("{{ANALYTICS}}", _analytics_scripts())
            .replace("{{APP_URL}}", mp.APP_URL)
            .replace("{{DESCRIPTION}}", _html.escape(DESCRIPTION))
            .replace("{{YEAR}}", str(datetime.date.today().year)))
    return mp._fill_trial(mp._fill_contact(html))
