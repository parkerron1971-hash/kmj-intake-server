"""
member_app_signin.py — the member app's front door: sign in, the code,
and the pages a member can land on before they're in.

"Member App, Top Tier" (Kevin approved 2026-10-15: "this is it. layout is
better and it flows"; the first pass had been "plain"). The church's own
photo runs across the top of the screen and fades into the base the
church picked (black, gray or white). Under it, set to the left edge like
every screen of the app: the church's name, "Welcome home." with "home."
in Newsreader italic in the church's colour, one line on what's inside,
then the form: an Email | Mobile number switch that picks the keyboard,
the field, and Send my code. The verse of the day sits below. A church
with no photos gets leaded glass in its own colour at the top.

The code page: a large title ("Check your texts"), where it went, six
cells over one real input (autofill, paste and screen readers work as
before), and the page sends itself once the sixth digit is in. The pages
before sign-in (not open yet, paused, try again, ask the office, who's
signing in) share the look.

Everything works without script and holds still for reduced motion. The
script only picks the keyboard, mirrors the code into its cells, and
counts down the code's ten minutes and the minute before a new one can be
sent (rate_limit's member_code_email_minute).

Pure functions, no I/O beyond member_app_photos' look at the site folder.
"""
from __future__ import annotations

from html import escape
from string import Template
from typing import Any, Dict, List

import member_app_ui as ui


def _e(v: Any) -> str:
    return escape(str(v if v is not None else ""), quote=True)


_CSS = Template("""
.si .mp-shell{display:flex;flex-direction:column;min-height:100vh;min-height:100svh;padding-bottom:0;}
.si-first{position:relative;display:flex;flex-direction:column;justify-content:flex-end;min-height:100vh;min-height:100svh;
  padding:0 0 calc(28px + env(safe-area-inset-bottom,0px));}

/* the church's photo across the top, fading into the base */
.si-photo{position:absolute;z-index:0;top:0;left:calc(var(--g) * -1);right:calc(var(--g) * -1);height:62vh;height:62svh;max-height:620px;
  overflow:hidden;background:var(--s2);}
.si-photo>.mb-ph{position:absolute;inset:0;}
.si-photo>.mb-ph img{object-position:center 30%;}
.si-photo::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.5) 0%,rgba(0,0,0,0) 24%,rgba(0,0,0,0) 40%,
  $bg_55 66%,$bg_92 86%,var(--bg) 100%);}
.si-top{position:absolute;z-index:2;top:calc(16px + env(safe-area-inset-top,0px));left:0;right:0;display:flex;align-items:center;gap:10px;color:#fff;}
.si-logo{height:34px;width:auto;max-width:60vw;object-fit:contain;filter:drop-shadow(0 2px 12px rgba(0,0,0,.4));}
.si-name{font-size:15px;font-weight:700;letter-spacing:-.02em;margin:0;color:#fff;text-shadow:0 1px 10px rgba(0,0,0,.5);}
.si-top .mb-mark{width:32px;height:32px;border-radius:9px;}

/* leaded glass, for a church with no photos yet */
.si-glass{position:absolute;inset:0;display:block;background:
  linear-gradient(90deg,transparent calc(50% - 1.5px),$bg_70 calc(50% - 1.5px) calc(50% + 1.5px),transparent calc(50% + 1.5px)),
  repeating-linear-gradient(60deg,transparent 0 40px,$bg_55 40px 42px),
  repeating-linear-gradient(-60deg,transparent 0 40px,$bg_55 40px 42px),
  radial-gradient(55% 45% at 25% 22%,$fill_85,transparent 70%),
  radial-gradient(55% 55% at 82% 40%,$glow,transparent 72%),
  linear-gradient(180deg,$fill_60,var(--s2));}

/* the welcome and the form, set to the left edge */
.si-in{position:relative;z-index:2;}
.si-eyebrow{font-size:12.5px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;color:var(--acc);margin:0;}
.si-h{font-size:clamp(42px,12.4vw,52px);font-weight:740;letter-spacing:-.045em;line-height:.98;margin:8px 0 10px;}
.si-h em{font-family:var(--mb-serif);font-style:italic;font-weight:500;letter-spacing:-.03em;color:var(--acc);}
.si-sub{margin:0 0 22px;font-size:15.5px;color:var(--fg2);max-width:330px;}
.si-form{gap:10px;}
.si-js label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}
.si-seg{display:grid;grid-template-columns:1fr 1fr;padding:3px;border-radius:12px;background:var(--s1);}
.si-seg button{min-height:38px;border:0;border-radius:9px;background:none;font:inherit;font-size:14px;font-weight:600;color:var(--fg2);cursor:pointer;
  display:flex;align-items:center;justify-content:center;gap:7px;}
.si-seg button[aria-pressed="true"]{background:var(--s3);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.12);}
.si-seg button:focus-visible{outline:2px solid var(--focus);outline-offset:2px;}
.si-field{position:relative;}
.si-i{position:absolute;left:16px;top:50%;margin-top:-10px;display:flex;color:var(--fg2);pointer-events:none;}
.si-i-mail,.si-i-tel,.si-field[data-m] .si-i-at{display:none;}
.si-field[data-m="email"] .si-i-mail,.si-field[data-m="tel"] .si-i-tel{display:flex;}
.si-field:focus-within .si-i{color:var(--acc);}
.si-field .mp-input{padding-left:46px;min-height:56px;font-size:16.5px;border-radius:16px;}
.si-go{min-height:56px;font-size:16.5px;}
.si-go[aria-busy="true"]{opacity:.85;cursor:progress;}
.si-go[aria-busy="true"] .mb-ic{display:none;}
.si-go[aria-busy="true"]::before{content:"";width:18px;height:18px;border-radius:50%;border:2.5px solid currentColor;border-right-color:transparent;
  animation:si-spin .8s linear infinite;}
.si-note{margin:14px 0 0;font-size:13px;color:var(--fg3);text-align:center;}
.si-note .mb-ic{vertical-align:-3px;margin-right:5px;}
.si-verse{margin:8px 0 0;padding:22px;border-radius:var(--r-lg);background:var(--s1);}
.si-verse .mb-kick{color:var(--acc);}
.si-verse blockquote{margin:10px 0 10px;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:21px;line-height:1.3;text-wrap:pretty;}
.si-verse blockquote i{font-style:normal;}
.si-verse cite{font-style:normal;font-size:13px;color:var(--fg2);}
.si-foot{margin:28px 0 calc(24px + env(safe-area-inset-bottom,0px));text-align:center;font-size:12px;color:var(--fg3);}

/* the code */
.si-code,.si-status{position:relative;z-index:1;flex:1;display:flex;flex-direction:column;padding-top:calc(8px + env(safe-area-inset-top,0px));}
.si-code .mb-back{align-self:flex-start;}
.si-code h1{margin:10px 0 8px;}
.si-to{color:var(--fg2);font-size:15.5px;margin:0 0 22px;}
.si-to strong{color:var(--fg);white-space:nowrap;}
.si-change{color:var(--acc);font-weight:600;text-decoration:none;white-space:nowrap;}
.si-otp-wrap{position:relative;}
.si-otp{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) 12px repeat(3,minmax(0,1fr));gap:8px;}
.si-otp i{height:64px;border-radius:14px;display:grid;place-items:center;font-style:normal;font-size:30px;font-weight:700;letter-spacing:-.03em;
  background:var(--s1);transition:box-shadow .15s ease;font-variant-numeric:tabular-nums;}
.si-otp b{align-self:center;height:3px;border-radius:2px;background:var(--fg3);opacity:.5;}
.si-otp-wrap:focus-within .si-otp i.cur{box-shadow:inset 0 0 0 2px var(--acc);}
.si-otp-wrap:focus-within .si-otp i.cur:empty::after{content:"";width:2px;height:28px;border-radius:1px;background:var(--acc);}
.si-otp-on .mp-code{position:absolute;inset:0;z-index:2;width:100%;height:100%;min-height:0;padding:0;border:0;background:transparent;box-shadow:none;
  color:transparent;-webkit-text-fill-color:transparent;caret-color:transparent;outline:none;}
.si-otp-on .mp-code::selection{background:transparent;}
.si-otp-on label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}
.si-timer{display:flex;justify-content:center;gap:6px;margin:4px 0 0;font-size:13px;color:var(--fg3);font-variant-numeric:tabular-nums;}
.si-timer b{color:var(--fg2);}
.si-timer.si-out{color:var(--error);font-weight:600;}
.si-resend{margin:22px 0 0;text-align:center;display:flex;flex-direction:column;align-items:center;gap:6px;}
.si-resend p{font-size:14px;color:var(--fg2);margin:0;}
.si-resend p+button+p{font-size:13px;color:var(--fg3);}
.si-again{display:inline-flex;align-items:center;gap:7px;min-height:44px;padding:0 16px;border-radius:999px;border:0;background:var(--s1);color:var(--acc);
  font:inherit;font-size:14.5px;font-weight:600;cursor:pointer;font-variant-numeric:tabular-nums;}
.si-again:disabled{color:var(--fg3);cursor:default;}
.si-again:focus-visible{outline:2px solid var(--focus);outline-offset:3px;}

/* before they're in */
.si-status{align-items:flex-start;padding-top:calc(16px + env(safe-area-inset-top,0px));}
.si-status .si-top{position:static;color:var(--fg);}
.si-status .si-name{color:var(--fg);text-shadow:none;}
.si-status-in{margin:12vh 0 0;width:100%;}
.si-medal{width:64px;height:64px;border-radius:20px;display:grid;place-items:center;background:var(--acc-fill);color:var(--on-acc);margin-bottom:18px;}
.si-status h1{margin:0 0 10px;}
.si-status-b{font-size:15.5px;color:var(--fg2);max-width:400px;}
.si-status-b p{margin:0 0 10px;}
.si-acts{width:100%;max-width:400px;margin:14px 0 0;display:flex;flex-direction:column;gap:10px;}
.si-people{display:flex;flex-direction:column;gap:10px;}
.si-people form{margin:0;}
.si-person{display:flex;align-items:center;gap:14px;min-height:68px;padding:12px 14px;font-weight:650;}
.si-person .mb-avatar{width:44px;height:44px;background:var(--s3);}
.si-person>.mb-ic{margin-left:auto;color:var(--fg3);}
.si-status .si-foot{margin-top:auto;padding-top:40px;align-self:stretch;}

@keyframes si-spin{to{transform:rotate(360deg);}}
@media (prefers-reduced-motion:no-preference){
  .si-photo>.mb-ph img{animation:si-zoom 2.4s cubic-bezier(.2,.8,.2,1) both;}
  .si-in>*{animation:si-up .8s cubic-bezier(.2,.8,.2,1) both;}
  .si-in>:nth-child(2){animation-delay:.06s;} .si-in>:nth-child(3){animation-delay:.12s;} .si-in>:nth-child(4){animation-delay:.18s;}
  .si-in>:nth-child(5){animation-delay:.24s;}
  .si-otp i.on{animation:si-pop .2s ease-out;}
  .si-otp-wrap:focus-within .si-otp i.cur:empty::after{animation:si-blink 1s steps(1) infinite;}
  .si .mp-err{animation:si-shake .45s ease-in-out;}
}
@keyframes si-zoom{from{transform:scale(1.12);opacity:.4;}}
@keyframes si-up{from{opacity:0;transform:translateY(14px);}}
@keyframes si-pop{from{transform:scale(.88);}}
@keyframes si-blink{50%{opacity:0;}}
@keyframes si-shake{20%,60%{transform:translateX(-5px);}40%,80%{transform:translateX(5px);}}
""")


def css(biz: Dict[str, Any], theme: Dict[str, Any]) -> str:
    p = ui.palette(biz, theme)
    return _CSS.substitute(ui._Tokens({k: v for k, v in p.items() if isinstance(v, str)}))


# ─── pieces ──────────────────────────────────────────────────────────


def _pic(biz: Dict[str, Any], site) -> str:
    import member_app_photos as photos
    return photos.welcome(photos.photos(biz, site))


def _top_art(pic: str) -> str:
    inside = ui.photo(pic, eager=True) if pic else '<span class="si-glass"></span>'
    return f'<div class="si-photo" aria-hidden="true">{inside}</div>'


def _brand(biz: Dict[str, Any], site, theme: Dict[str, Any], *, on_photo: bool = True) -> str:
    """The church's logo (light over the photo; the base's own on a page
    without one), or its name."""
    import member_app_photos as photos
    name = (biz.get("name") or "").strip() or "Your church"
    light = True if on_photo else ui.palette(biz, theme)["dark"]
    word = photos.wordmark(site, light=light)
    if word:
        return f'<div class="si-top"><img class="si-logo" src="{_e(word)}" alt="{_e(name)}"></div>'
    logo = theme.get("logo_url") or ""
    mark = f'<span class="mb-mark" aria-hidden="true"><img src="{_e(logo)}" alt=""></span>' if logo else ""
    return f'<div class="si-top">{mark}<p class="si-name">{_e(name)}</p></div>'


def _verse() -> str:
    import bible_text as bt
    import member_portal_bible as mpb
    v = mpb.verse_of_day(bt.translation(""))
    if not v:
        return ""
    return (f'<figure class="si-verse"><span class="mb-kick">Verse of the day</span><blockquote>{v["html"]}</blockquote>'
            f'<figcaption><cite>{_e(v["label"])}</cite></figcaption></figure>')


def _foot(biz: Dict[str, Any]) -> str:
    return f'<p class="si-foot">Your page at {_e(biz.get("name") or "the church")} · Powered by Solutionist</p>'


SIGNIN_JS = """<script>(function(){
var f=document.querySelector('.si-form');if(!f)return;
var seg=f.querySelector('.si-seg'),inp=f.querySelector('#mp-email'),lab=f.querySelector('label[for="mp-email"]'),
fld=f.querySelector('.si-field'),go=f.querySelector('.si-go'),word=go.querySelector('span');
var M={email:['Your email','you@example.com','email','email'],tel:['Your mobile number','(555) 123-4567','tel','tel']};
function set(m){seg.setAttribute('data-m',m);fld.setAttribute('data-m',m);
[].forEach.call(seg.querySelectorAll('button'),function(b){b.setAttribute('aria-pressed',b.getAttribute('data-m')===m?'true':'false');});
lab.textContent=M[m][0];inp.placeholder=M[m][1];inp.inputMode=M[m][2];inp.setAttribute('autocomplete',M[m][3]);
try{localStorage.setItem('mb-si-mode',m);}catch(e){}}
var m='email';try{m=localStorage.getItem('mb-si-mode')||m;}catch(e){}
if(inp.value){m=/^[\\s+(\\d]/.test(inp.value)?'tel':'email';}
if(!M[m]){m='email';}
f.classList.add('si-js');seg.hidden=false;set(m);
seg.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;set(b.getAttribute('data-m'));inp.focus();});
f.addEventListener('submit',function(){go.setAttribute('aria-busy','true');word.textContent='Sending your code';
setTimeout(function(){go.disabled=true;},0);});
window.addEventListener('pageshow',function(e){if(e.persisted){go.removeAttribute('aria-busy');go.disabled=false;word.textContent='Send my code';}});
})();</script>"""


CODE_JS = """<script>(function(){
var inp=document.getElementById('mp-code');if(!inp)return;
var w=inp.closest('.si-otp-wrap'),box=w.querySelector('.si-otp'),c=box.querySelectorAll('i'),f=inp.form,
go=f.querySelector('.si-go'),word=go.querySelector('span'),sent=false;
box.hidden=false;f.classList.add('si-otp-on');
function paint(){var d=inp.value.replace(/\\D/g,'').slice(0,6);
for(var i=0;i<6;i++){c[i].textContent=d.charAt(i);c[i].className=(d.charAt(i)?'on':'')+(i===Math.min(d.length,5)?' cur':'');}
if(d.length<6){sent=false;}
else if(!sent){sent=true;setTimeout(function(){if(f.requestSubmit){f.requestSubmit();}else{f.submit();}},200);}}
inp.addEventListener('input',paint);paint();
f.addEventListener('submit',function(){go.setAttribute('aria-busy','true');word.textContent='Signing you in';});
window.addEventListener('pageshow',function(e){if(e.persisted){go.removeAttribute('aria-busy');word.textContent='Sign in';}});
var t=document.querySelector('.si-timer');
if(t){var end=Date.now()+600000,b=t.querySelector('b');t.hidden=false;
(function tick(){var s=Math.max(0,Math.round((end-Date.now())/1000));b.textContent=Math.floor(s/60)+':'+('0'+s%60).slice(-2);
if(s){setTimeout(tick,1000);}else{t.textContent='This code has run out. Send a new one below.';t.classList.add('si-out');}})();}
var r=document.querySelector('.si-resend [data-wait]');
if(r){var left=+r.getAttribute('data-wait'),rs=r.querySelector('span'),txt=rs.textContent;r.disabled=true;
(function step(){if(left<=0){r.disabled=false;rs.textContent=txt;return;}
rs.textContent=txt+' in '+Math.floor(left/60)+':'+('0'+left%60).slice(-2);left--;setTimeout(step,1000);})();}
})();</script>"""


# ─── pages (bodies for member_portal._shell) ─────────────────────────


def signin_body(biz: Dict[str, Any], site, theme: Dict[str, Any], *, error: str = "", email: str = "") -> str:
    name = (biz.get("name") or "").strip() or "the church"
    err = f'<p class="mp-err" role="alert">{_e(error)}</p>' if error else ""
    return f"""<div class="si-first">
{_top_art(_pic(biz, site))}
{_brand(biz, site, theme)}
<section class="si-in" aria-label="Sign in">
  <p class="si-eyebrow">{_e(name)}</p>
  <h1 class="si-h"><span class="mp-sr">Welcome home.</span><span aria-hidden="true">Welcome<br><em>home.</em></span></h1>
  <p class="si-sub">Your church, all week: messages, groups, giving and what's coming up.</p>
  <form class="mp-form si-form" method="post" action="/my/code">
    <div class="si-seg" role="group" aria-label="Sign in with" hidden>
      <button type="button" data-m="email" aria-pressed="true">{ui.icon('mail', 16)}Email</button>
      <button type="button" data-m="tel" aria-pressed="false">{ui.icon('phone', 16)}Mobile number</button>
    </div>
    <label for="mp-email">Email or mobile number</label>
    <div class="si-field"><span class="si-i si-i-at">{ui.icon('at')}</span><span class="si-i si-i-mail">{ui.icon('mail')}</span><span class="si-i si-i-tel">{ui.icon('phone')}</span>
      <input class="mp-input" id="mp-email" name="email" type="text" autocomplete="username" autocapitalize="off" spellcheck="false" required value="{_e(email)}"></div>
    {err}
    <button class="mp-go si-go" type="submit"><span>Send my code</span>{ui.icon('arrow', 19)}</button>
  </form>
  <p class="si-note">{ui.icon('lock', 15)}No password. We'll send you a 6-digit code.</p>
</section>
</div>
{_verse()}
{_foot(biz)}"""


def code_body(biz: Dict[str, Any], site, *, email: str, shown: str, texted: bool, error: str = "") -> str:
    """`shown` is the address or number as the member reads it back."""
    name = (biz.get("name") or "").strip() or "the church"
    err = f'<p class="mp-err" role="alert">{_e(error)}</p>' if error else ""
    # A fresh code (no error) gets its ten minutes counted down and the
    # minute before another can be sent.
    timer = '' if error else '<p class="si-timer" hidden>Works for <b>10:00</b></p>'
    wait = '' if error else ' data-wait="60"'
    return f"""<div class="si-code">
  <a class="mb-back" href="/my">{ui.icon('back', 24)}Back</a>
  <h1>Check your {'texts' if texted else 'email'}</h1>
  <p class="si-to">If <strong>{_e(shown)}</strong> is on {_e(name)}'s list, a 6-digit code is on its way{' by text' if texted else ''}. It works for 10 minutes.
    <a class="si-change" href="/my">Change</a></p>
  <form class="mp-form" method="post" action="/my/verify">
    <input type="hidden" name="email" value="{_e(email)}">
    <label for="mp-code">6-digit code</label>
    <div class="si-otp-wrap">
      <input class="mp-input mp-code" id="mp-code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]*" maxlength="7" required autofocus>
      <div class="si-otp" aria-hidden="true" hidden><i></i><i></i><i></i><b></b><i></i><i></i><i></i></div>
    </div>
    {err}
    {timer}
    <button class="mp-go si-go" type="submit" style="margin-top:8px"><span>Sign in</span>{ui.icon('arrow', 19)}</button>
  </form>
  <form method="post" action="/my/code" class="si-resend mp-noprint">
    <input type="hidden" name="email" value="{_e(email)}">
    <p>Nothing arrived? {'Give it a minute.' if texted else 'Check spam.'}</p>
    <button class="si-again" type="submit"{wait}>{ui.icon('refresh', 16)}<span>Send a new code</span></button>
    <p>Still nothing? Ask the church office which {'number' if texted else 'email'} they have for you.</p>
  </form>
  {_foot(biz)}
</div>"""


def status_body(biz: Dict[str, Any], site, theme: Dict[str, Any], *, icon: str, title: str, body: str,
                actions: str = "") -> str:
    """A page before sign-in that has one thing to say. `body` and
    `actions` are trusted markup from member_portal."""
    acts = f'<div class="si-acts">{actions}</div>' if actions else ""
    return f"""<section class="si-status">
  {_brand(biz, site, theme, on_photo=False)}
  <div class="si-status-in">
  <span class="si-medal" aria-hidden="true">{ui.icon(icon, 28)}</span>
  <h1>{_e(title)}</h1>
  <div class="si-status-b">{body}</div>
  {acts}
  </div>
  {_foot(biz)}
</section>"""


def people_list(people: List[Dict[str, Any]]) -> str:
    """Who's signing in: one card per person on the record."""
    out = []
    for p in people:
        nm = p.get("name") or "Someone in your household"
        out.append(f'<form method="post" action="/my/person"><input type="hidden" name="cid" value="{_e(p["id"])}">'
                   f'<button class="mp-person si-person" type="submit"><span class="mb-avatar" aria-hidden="true">'
                   f'{_e(ui.initials(nm))}</span>{_e(nm)}{ui.icon("chevron", 18)}</button></form>')
    return f'<div class="si-people">{"".join(out)}</div>'
