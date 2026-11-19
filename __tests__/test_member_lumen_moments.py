# __tests__/test_member_lumen_moments.py
#
# The moments in the member app's new look (member_lumen_moments, behind
# MEMBER_LUMEN): Kevin on the Lumen Next mock, "build all the moments". Pins,
# for Prayer, Give and Messages:
#   - the sheet: every rule under body.lm; the moves only when the phone
#     allows motion (the loading spinner is the one exception);
#   - Prayer: the sent page lights the flame; a group's prayer wall carries
#     the script that lights the request just prayed for, its form unchanged;
#   - Give: the amount rolls (the Lumen give script draws the digits), the
#     thank-you draws its ring and check; the payment script is untouched;
#   - Messages: every conversation carries the script (a sent bubble's
#     flight, reactions in place), next to instant send, which is unchanged;
#   - off: none of it, anywhere;
#   - the same reads as before, on and off; both scripts parse.

import pathlib
import re
import shutil
import subprocess
import sys
from collections import Counter

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import member_lumen_give as mlg
import member_lumen_moments as mlm
import member_lumen_ui as lm
import test_church_threads as tct
import test_member_messaging as tmm
from test_church_threads import fake, screen  # noqa: F401  (fixtures)
from test_member_group_chat import _page as group_page, church as gchurch  # noqa: F401  (fixture)
from test_member_lumen_give import _get as give_get, church as give_church  # noqa: F401  (fixture)
from test_member_lumen_people import _fresh_caches, calendar, threads  # noqa: F401  (fixtures)
from test_member_messaging import env  # noqa: F401  (fixture)


# ─── the sheet ───────────────────────────────────────────────────────


def test_the_moments_are_in_the_lumen_file_under_body_lm():
    text = ui.sheet("lumen")[0]
    for cls in ("lm-flamewrap", "lm-fl", "lm-hl", "lm-od", "lm-os", "lm-okdraw", "lm-flew", "lm-lit", "lm-pop"):
        assert f".{cls}" in text, cls
    assert mlm.CSS in lm.templates()
    css = re.sub(r"/\*.*?\*/", "", mlm.CSS.template, flags=re.S)
    frames = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", css)
    flat = re.sub(r"@media[^{]*\{", "", frames)
    for sel in re.findall(r"(?:^|\})\s*([^{}]+)\{", flat):
        for one in sel.split(","):
            if one.strip():
                assert one.strip().startswith("body.lm"), one
    assert "!important" not in css and "$" not in css
    # Every move waits for the phone's yes to motion; outside it, only the
    # Give button's spinner turns (it says the payment form is loading).
    i = frames.index("@media (prefers-reduced-motion:no-preference){")
    outside = frames[:i]
    assert re.findall(r"animation:([a-zA-Z]+)", outside) == ["lmoSpin"]


# ─── Prayer ──────────────────────────────────────────────────────────


def test_a_sent_prayer_lights_the_flame(calendar, monkeypatch):  # noqa: F811
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/prayer?done=prayer&s=team").text
    sent = html[html.index('<section class="lm-sent'):]
    sent = sent[:sent.index("</section>")]
    assert sent.startswith('<section class="lm-sent is-lit"') and mlm.flame() in sent
    assert sent.count('<span class="lm-hl"></span>') == 3 and 'class="lm-fl"' in sent
    assert "Your pastors <em>have it.</em>" in sent and 'href="/my">Done</a>' in sent
    assert "lm-pring" not in html


def test_off_a_sent_prayer_is_todays(calendar, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/prayer?done=prayer&s=team").text
    assert "lm-flame" not in html and "lm-hl" not in html and "lm-moment" not in html


def _wall(env):
    for t in ("group_prayers", "group_prayer_marks"):
        env.t.setdefault(t, [])
    env.t["group_prayers"].append({
        "id": "00000000-0000-4000-8000-000000001501", "business_id": tmm.BIZ, "group_id": tmm.GRP,
        "contact_id": tmm.BEN, "removed_at": None, "body": "My mom's surgery Friday", "to_pastor": False,
        "answered_at": None, "praise": None, "created_at": tct.iso(tct.NOW)})


def test_a_groups_prayer_wall_carries_the_light(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    _wall(gchurch)
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/prayer").text
    assert mlm.JS in html
    # The tap is still the plain form post the old look sends.
    assert ('<form method="post" action="/my/groups/prayer/mark"><input type="hidden" name="id" '
            'value="00000000-0000-4000-8000-000000001501"><input type="hidden" name="kind" value="praying">') in html
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/prayer").text
    assert "lm-moment" not in html and "/my/groups/prayer/mark" in html


# ─── Give ────────────────────────────────────────────────────────────


def test_give_rolls_its_amount_and_draws_its_thanks(give_church, fake, monkeypatch):  # noqa: F811
    import giving_router as gr
    import public_site
    html = give_get(fake, monkeypatch, "/my/give?thanks=1")
    assert mlg.GIVE_JS in html
    assert "function roll(t)" in mlg.GIVE_JS and "'lm-od'" in mlg.GIVE_JS and "roll((c/100)" in mlg.GIVE_JS
    assert '<p class="lm-amt is-empty" aria-hidden="true"><sup>$</sup><span data-amt>0</span></p>' in html
    gave = html[html.index('<dialog class="lm-gave"'):html.index("</dialog>")]
    assert mlm.check() in gave and "Thank you, <em>Ana.</em>" in gave and 'id="gv-thanks"' in gave
    # The payment: the give page's own script, byte for byte.
    assert gr._give_script(api_origin=public_site._EMBED_ORIGIN, slug="", embed_json="null", app=True) in html


# ─── Messages ────────────────────────────────────────────────────────


def test_a_conversation_carries_the_moments_beside_instant_send(threads, monkeypatch):  # noqa: F811
    import member_instant_send as mis
    html = tct._app(threads, monkeypatch, tct.ANA).get("/my/inbox/church").text
    assert lm.SCROLL_JS + mlm.JS in html
    assert mis.script("ct-compose", "ct-chat", "ct-say", "ct-err", "ct") in html     # instant send, as it was
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = tct._app(threads, monkeypatch, tct.ANA).get("/my/inbox/church").text
    assert "lm-moment" not in html


def test_a_groups_chat_carries_the_moments(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._group_tid(gchurch, tmm.ANA, tmm.GRP)
    tmm._send(gchurch, tmm.BEN, tid, "Who's in?")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat").text
    assert mlm.JS in html
    # The picker the script answers: the same react forms the old look posts.
    assert f'<form method="post" action="/my/messages/{tid}/react">' in html
    assert re.search(r'<button class="gc-pk" type="submit" aria-pressed="false" aria-label="Love">', html)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert "lm-moment" not in group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat").text


def test_the_script_reads_the_answers_the_routes_give():
    # A reaction: {"ok": true, "on": bool} (test_member_group_chat pins the
    # route); a refusal falls back to the plain post; a lost answer reloads.
    assert "x.ok){react(li,kind,!!x.on)" in mlm.JS
    assert "HTMLFormElement.prototype.submit.call(f)" in mlm.JS and "location.reload()" in mlm.JS
    # I'm praying: remembered only when it turns on, lit only on ?done=praying.
    assert "k.value==='praying'" in mlm.JS and "done=praying(&|$)" in mlm.JS
    # A sent bubble replaced mid-flight finishes the same flight.
    assert "'mis-pending'" in mlm.JS and "lm-flew" in mlm.JS and "now-t<700" in mlm.JS


# ─── the same reads ──────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/my/prayer?done=prayer&s=team", "/my/inbox/church"])
def test_the_moments_read_nothing_more(threads, calendar, monkeypatch, path):  # noqa: F811
    c = tct._app(threads, monkeypatch, tct.ANA)
    got = {}
    for mode in ("on", "off"):
        monkeypatch.setenv("MEMBER_LUMEN", mode)
        c.get(path)
        threads.gets.clear()
        c.get(path)
        got[mode] = Counter(r.split("?")[0] for r in threads.gets)
    assert got["on"] == got["off"]


# ─── the scripts parse ───────────────────────────────────────────────


@pytest.mark.parametrize("script", [mlm.JS, mlg.GIVE_JS])
def test_the_scripts_parse(script):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = script[len("<script>"):-len("</script>")]
    res = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
