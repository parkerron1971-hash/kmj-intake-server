"""Home's date and the "Today"/"Tomorrow" kickers wear the highlight (Kevin's
approved Member page mock: the office preview colours them, so the app does).
It is the gold token (--lm-gold: the readable ink, a deeper shade on white,
the lit shade at night), so a church's own highlight reaches them too."""
from datetime import date, datetime

import member_app_ui as ui
import member_lumen_home as lh


def test_today_tonight_and_tomorrow_wear_the_highlight_other_days_stay_quiet():
    assert 'class="lm-wkk is-soon"' in lh._kicker("Today · 10:30 AM")
    assert 'class="lm-wkk is-soon"' in lh._kicker("Tonight · 7:00 PM")
    assert 'class="lm-wkk is-soon"' in lh._kicker("Tomorrow")
    for quiet in ("This Thursday · 7:00 PM", "Saturday, November 28", "Your first Sunday · 10:30 AM", "Todayish"):
        assert 'class="lm-wkk">' in lh._kicker(quiet), quiet
    card = lh.week_card("", href="/my/events", day=date(2026, 11, 22), kicker="Today · 10:30 AM", title="Sunday Worship")
    assert '<p class="lm-wkk is-soon">Today · 10:30 AM</p>' in card
    card = lh.pass_card("", href="/my/events", day=date(2026, 11, 23), chip="Tomorrow", kicker="Tomorrow · 10:30 AM",
                        title="Sunday Worship")
    assert 'lm-wkk is-soon' in card


def test_the_sheet_colours_the_date_and_the_soon_kickers_with_the_gold_token():
    import member_lumen_home
    css = member_lumen_home.CSS.template
    assert ".lm-ey4{margin:0;display:flex;align-items:center;gap:6px;font:700 11px/1.2 var(--mb-ui);letter-spacing:.14em;" \
           "text-transform:uppercase;color:var(--lm-gold);}" in css
    assert ".lm-wkk.is-soon{color:var(--lm-gold);}" in css
    # the date line keeps its words and its markup
    head = lh.greeting("Ana", datetime(2026, 11, 22, 9, 0), [], new=False)
    assert '<p class="lm-ey4">' in head and "Sunday · November 22" in head


def test_a_saved_highlight_reaches_the_gold_token(monkeypatch):
    import member_lumen
    monkeypatch.setattr(member_lumen, "page", lambda: True)
    biz = {"id": "b", "settings": {"member_portal": {"app_highlight": "#2fb6a6"}}}
    pal = ui.palette(biz, {})
    assert pal["gold"] == "#2fb6a6" and ui.contrast(pal["gold_ink"], pal["bg"]) >= 4.5
