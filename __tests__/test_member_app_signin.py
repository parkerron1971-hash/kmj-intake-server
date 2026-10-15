"""The member app's front door (Kevin 2026-10-15: "it's plain... upgrade
this design. be creative with it"): sign in, the code, and the pages a
member can land on before they're in."""
import re
from html import unescape

import member_app_signin as sg
import member_portal as mp

BIZ = {"id": "b1", "name": "First Light", "type": "ministry",
       "settings": {"brand_kit": {"colors": {"primary": "#0B2146"}, "accent": "#F4AE3D"}}}


def _on(monkeypatch, messages=False, giving=False):
    import giving_router
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "turned_on", lambda b: messages)
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: giving)


def test_sign_in_is_the_church_photo_and_still_a_plain_form(monkeypatch):
    _on(monkeypatch)
    page = mp.render_signin(BIZ, None)
    assert '<body class="si">' in page and 'class="si-photo"' in page and 'class="mb-top"' not in page
    # one accessible headline; the styled one is hidden from readers
    assert '<span class="mp-sr">Welcome home.</span>' in page and 'Welcome<br><em>home.</em>' in page
    # the form posts what it always posted, and reads right without script:
    # the email/mobile switch starts hidden and the label covers both
    form = page[page.index('<form class="mp-form si-form"'):]
    assert 'method="post" action="/my/code"' in form and 'name="email"' in form and 'type="text"' in form
    assert 'class="si-seg" role="group" aria-label="Sign in with" hidden' in page
    assert '<label for="mp-email">Email or mobile number</label>' in page
    assert sg.SIGNIN_JS in page and "Send my code" in page
    assert page.count('class="mp-foot') == 0 and "Powered by Solutionist" in page




def test_a_church_with_no_photos_gets_leaded_glass_in_its_colours(monkeypatch):
    import member_app_photos as photos
    _on(monkeypatch)
    page = mp.render_signin(BIZ, None)
    top = page.split('class="si-photo"')[1].split("</div>")[0]
    assert 'class="si-glass"' in top and "<img" not in top
    monkeypatch.setattr(photos, "photos", lambda b, s: ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"])
    page = mp.render_signin(BIZ, None)
    assert 'class="si-glass"' not in page
    src = re.search(r'class="si-photo"[^>]*>.*?src="([^"]+)"', page, re.S).group(1)
    assert src.startswith("https://cdn.example/")


def test_an_error_keeps_what_was_typed(monkeypatch):
    _on(monkeypatch)
    page = mp.render_signin(BIZ, None, error="Enter the email <b>or</b> number.", email='a"b')
    assert 'role="alert">Enter the email &lt;b&gt;or&lt;/b&gt; number.</p>' in page and 'value="a&quot;b"' in page


def test_the_code_is_one_real_input_under_six_cells():
    page = mp.render_code(BIZ, None, email="+15550102030")
    assert "Check your texts" in page and "(555) 010-2030" in page
    form = page[page.index('action="/my/verify"'):]
    assert 'name="code"' in form and 'autocomplete="one-time-code"' in form and 'inputmode="numeric"' in form
    assert form.count("<i></i>") == 6 and 'class="si-otp" aria-hidden="true" hidden' in form
    assert sg.CODE_JS in page and "requestSubmit" in sg.CODE_JS
    # a fresh code: its ten minutes and the minute before another can be sent
    assert 'class="si-timer" hidden' in page and 'data-wait="60"' in page
    assert 'action="/my/code"' in page and 'value="+15550102030"' in page


def test_after_an_error_nothing_counts_down():
    page = mp.render_code(BIZ, None, email="ana@example.com", error=mp.GENERIC_CODE_ERROR)
    body = page.split('<body class="si">')[1].split("<script>")[0]
    assert "Check your email" in body and "si-timer" not in body and "data-wait" not in body
    assert mp._e(mp.GENERIC_CODE_ERROR) in body


def test_the_resend_wait_matches_the_server():
    import rate_limit
    assert rate_limit._LIMITS["member_code_email_minute"] == (1, 60)


def test_the_pages_before_sign_in_share_the_look():
    for page, words in ((mp.render_unavailable(BIZ, None), "This page isn't open yet"),
                        (mp.render_signin_paused(BIZ, None), "Sign-in is paused"),
                        (mp.render_try_again(BIZ, None), "We couldn't open your page just now"),
                        (mp.render_shared_address(BIZ, None), "more than one person's record")):
        assert '<body class="si">' in page and 'class="si-status"' in page and words in unescape(page)
        assert 'action="/my/code"' not in page and 'class="mb-top"' not in page


def test_who_is_signing_in_offers_each_person():
    page = mp.render_choose(BIZ, None, [{"id": "c1", "name": "Ana <Rivers>"}, {"id": "c2", "name": ""}])
    assert page.count('action="/my/person"') == 2 and 'value="c1"' in page and 'value="c2"' in page
    assert "Ana &lt;Rivers&gt;" in page and "Someone in your household" in page


def test_every_colour_in_the_stylesheet_is_filled_in():
    css = sg.css(BIZ, {"accent": "#F4AE3D"})
    assert "$" not in css and "rgba(" in css
    import member_app_ui as ui
    assert ui._Tokens({"accent": "#102030"})["accent_20"] == "rgba(16,32,48,0.2)"


def test_the_door_holds_still_for_reduced_motion():
    css = sg.css(BIZ, {"accent": "#F4AE3D"})
    still = css[:css.index("@media (prefers-reduced-motion:no-preference)")]
    # nothing outside the motion block starts hidden or moving, but the busy spinner
    assert "animation:" not in still.replace("animation:si-spin", "")
    assert "opacity:0" not in still
