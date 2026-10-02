"""
founder_charter.py: the Founding Charter a new founding-seat holder sees.

Stripe returns the buyer's tab to /billing/success (stripe_billing). When
that Checkout Session was a founder seat (metadata founder_seat=1) and it
finished, the page shows this charter instead of the plain "You're in."
Kevin approved the design on 2026-09-22.

Everything on it is real: the business name comes from the businesses
row, the seat number from the live founder count, the price and the
allowance from pricing_config. It claims nothing that did not happen:
there is no public-record anchor, no QR code and no hash on it, because
none of that is wired for a charter yet.

This module only renders. stripe_billing gathers the data and falls back
to the plain page if anything here raises.
"""
from __future__ import annotations

import datetime
import html as _html
from typing import Dict

# Inter Tight and JetBrains Mono 400/500 already load in the marketing
# shell; the charter adds the 600 mono weight and the script face its
# signature is set in.
FONTS_HEAD = (
    '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@600'
    '&family=Pinyon+Script&display=swap" rel="stylesheet">'
)

# Every font and color carries a literal value or a literal fallback: the
# shell defines --font-heading / --font-mono / --font-body, and the
# charter must still read right if that ever changes.
CHARTER_CSS = r"""
  /* ===== the Founding Charter (billing success, founder seat) ===== */
  .fxp{padding:56px 0 96px}
  .fxp .container{max-width:1000px}
  .fxp-box{position:relative;width:100%;margin:0 auto;animation:fxMat .9s cubic-bezier(.2,.8,.2,1) both}
  .fxp-banner{display:flex;justify-content:center;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px;font:600 11px var(--font-mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.14em;text-transform:uppercase;color:#34D399}
  .fxp-after{margin-top:28px;display:flex;flex-direction:column;align-items:center;gap:14px;text-align:center}
  .fxp-note{max-width:56ch;font-size:14px;line-height:1.6;color:#949AA6}
  @property --fxa{syntax:'<angle>';inherits:false;initial-value:0deg}
  @keyframes fxSpin{to{--fxa:360deg}}
  @keyframes fxPulse{50%{opacity:.35}}
  @keyframes fxRot{to{transform:rotate(360deg)}}
  @keyframes fxMat{0%{opacity:0;transform:scale(.96);filter:blur(10px) brightness(2)}60%{opacity:1;filter:blur(0) brightness(1.3)}100%{opacity:1;transform:none;filter:none}}
  @keyframes fxWrite{from{clip-path:inset(-40px 100% -40px -60px)}to{clip-path:inset(-40px -60px -40px -60px)}}
  @keyframes fxLaser{0%{left:0;opacity:1}92%{left:100%;opacity:1}100%{left:100%;opacity:0}}
  @keyframes fxSign{70%{stroke-dashoffset:0;fill:transparent}100%{stroke-dashoffset:0;fill:#e9fbff;stroke:#22D3EE;filter:drop-shadow(0 0 6px rgba(34,211,238,.7))}}
  .fxc{--mx:50%;--my:30%;--fx-display:var(--font-heading,'Inter Tight','Inter',system-ui,sans-serif);--fx-mono:var(--font-mono,'JetBrains Mono',ui-monospace,monospace);--fx-body:var(--font-body,'Inter',system-ui,sans-serif);
    position:relative;border-radius:20px;overflow:hidden;isolation:isolate;text-align:left;color:#F7F8FA;
    background:linear-gradient(160deg,rgba(18,24,40,.94),rgba(8,11,20,.96));box-shadow:0 40px 90px -30px #000,0 0 80px -30px rgba(46,125,255,.45)}
  .fxc::before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1.2px;z-index:3;pointer-events:none;
    background:conic-gradient(from var(--fxa),#22D3EE,#2E7DFF,#7C5CFF,#E040FB,#F3C56B,#22D3EE);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;animation:fxSpin 8s linear infinite;opacity:.9}
  .fxc .fx-holo{position:absolute;inset:0;z-index:0;pointer-events:none;mix-blend-mode:screen;opacity:.55;
    background:radial-gradient(38% 50% at var(--mx) var(--my),rgba(224,64,251,.22),transparent 70%),linear-gradient(115deg,transparent 25%,rgba(34,211,238,.12) 40%,rgba(224,64,251,.14) 50%,rgba(46,125,255,.12) 60%,transparent 75%);
    background-size:100% 100%,260% 100%;background-position:0 0,var(--mx) 0}
  .fxc .fx-lines{position:absolute;inset:0;z-index:0;pointer-events:none;opacity:.5}
  .fxc .fx-lines svg{width:100%;height:100%;display:block}
  .fxc .fx-corner{position:absolute;width:22px;height:22px;border:1.5px solid #22D3EE;z-index:2;opacity:.85;pointer-events:none}
  .fxc .fx-corner.tl{left:14px;top:14px;border-right:0;border-bottom:0}.fxc .fx-corner.tr{right:14px;top:14px;border-left:0;border-bottom:0}
  .fxc .fx-corner.bl{left:14px;bottom:14px;border-right:0;border-top:0}.fxc .fx-corner.br{right:14px;bottom:14px;border-left:0;border-top:0}
  .fxc .fx-in{position:relative;z-index:1}
  .fxc .fx-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;font:600 10.5px var(--fx-mono);letter-spacing:.2em;text-transform:uppercase;color:#7f8aa3}
  .fxc .fx-top .sn{color:#F3C56B}
  .fxc .fx-live{display:inline-flex;align-items:center;gap:8px;color:#22D3EE}
  .fxc .fx-live i{width:7px;height:7px;border-radius:50%;background:#22D3EE;box-shadow:0 0 10px #22D3EE;animation:fxPulse 1.8s ease-in-out infinite}
  .fxc .fx-title{margin:0;padding-bottom:.12em;font:600 clamp(34px,5vw,60px)/.95 var(--fx-display);letter-spacing:-.035em;background:linear-gradient(180deg,#fff 20%,#9fe9f7 60%,#5a8dff 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
  .fxc .fx-sub{margin-top:10px;font:500 10.5px var(--fx-mono);letter-spacing:.32em;color:#6f7b95;text-transform:uppercase}
  .fxc .fx-issued{display:block;font:600 10.5px var(--fx-mono);letter-spacing:.3em;color:#22D3EE;text-transform:uppercase}
  .fxc .fx-name-wrap{position:relative;margin-top:6px;max-width:100%}
  .fxc .fx-name-wrap::after{content:"";position:absolute;left:0;right:0;bottom:-2px;height:1px;background:linear-gradient(90deg,transparent,#22D3EE,#E040FB,transparent)}
  .fxc .fx-name{display:block;width:100%;padding:2px 0 6px;font:700 clamp(28px,4.4vw,54px)/1.08 var(--fx-display);letter-spacing:-.02em;color:#fff;overflow-wrap:anywhere;
    text-shadow:0 0 18px rgba(34,211,238,.55),0 0 42px rgba(46,125,255,.35)}
  .fxc .fx-laser{position:absolute;top:-4px;bottom:-4px;width:2px;left:0;background:#fff;box-shadow:0 0 12px 3px #22D3EE,0 0 30px 8px rgba(224,64,251,.5);opacity:0;pointer-events:none}
  .fxc .fx-name-wrap.write .fx-name{animation:fxWrite 1.2s cubic-bezier(.5,0,.25,1) .5s both}
  .fxc .fx-name-wrap.write .fx-laser{animation:fxLaser 1.2s cubic-bezier(.5,0,.25,1) .5s both}
  .fxc .fx-body{margin:16px 0 0;max-width:60ch;font:400 15px/1.6 var(--fx-body);color:#aeb7ca}
  .fxc .fx-body b{color:#fff;font-weight:600}
  .fxc .fx-terms{display:grid;gap:8px}
  .fxc .fx-term{border:1px solid rgba(120,160,255,.18);border-radius:12px;padding:10px 13px;background:rgba(10,14,26,.6)}
  .fxc .fx-term span{display:block;font:600 9.5px var(--fx-mono);letter-spacing:.2em;text-transform:uppercase;color:#6f7b95}
  .fxc .fx-term b{display:block;margin-top:5px;font:600 15px var(--fx-display);letter-spacing:-.01em;color:#fff}
  .fxc .fx-term b em{font-style:normal;color:#F3C56B}
  .fxc .fx-term small{display:block;margin-top:4px;font:500 10.5px var(--fx-mono);letter-spacing:.06em;color:#6f7b95}
  .fxc .fx-meter{margin-top:8px;height:4px;border-radius:4px;background:rgba(255,255,255,.08);overflow:hidden}
  .fxc .fx-meter i{display:block;height:100%;width:100%;background:linear-gradient(90deg,#2E7DFF,#22D3EE);box-shadow:0 0 10px #22D3EE}
  .fxc .fx-seal{position:relative;width:132px;height:132px;display:grid;place-items:center;flex:none}
  .fxc .fx-seal .ring{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from var(--fxa),#22D3EE,#2E7DFF,#7C5CFF,#E040FB,#F3C56B,#22D3EE);animation:fxSpin 6s linear infinite;
    -webkit-mask:radial-gradient(circle,transparent 58%,#000 59%,#000 64%,transparent 65%,transparent 70%,#000 71%);mask:radial-gradient(circle,transparent 58%,#000 59%,#000 64%,transparent 65%,transparent 70%,#000 71%);filter:drop-shadow(0 0 10px rgba(34,211,238,.6))}
  .fxc .fx-seal svg.rt{position:absolute;inset:0;width:100%;height:100%;animation:fxRot 24s linear infinite}
  .fxc .fx-seal .core{position:relative;text-align:center;line-height:1}
  .fxc .fx-seal .core b{display:block;font:700 30px var(--fx-display);letter-spacing:-.03em;background:linear-gradient(180deg,#FFF1C8,#F3C56B 60%,#c9973f);-webkit-background-clip:text;background-clip:text;color:transparent}
  .fxc .fx-seal .core span{display:block;margin-top:4px;font:600 8.5px var(--fx-mono);letter-spacing:.24em;color:#9fe9f7}
  .fx-cta{display:inline-flex;align-items:center;justify-content:center;height:48px;padding:0 22px;border-radius:999px;font:700 14px var(--font-body,'Inter',system-ui,sans-serif);color:#05060a;text-decoration:none;white-space:nowrap;
    background:linear-gradient(90deg,#22D3EE,#7fb2ff 50%,#E040FB);box-shadow:0 10px 34px -10px #22D3EE;transition:transform .2s,filter .2s}
  .fx-cta:hover{transform:translateY(-2px);filter:brightness(1.08)}
  .fx-cta:focus-visible{outline:2px solid #22D3EE;outline-offset:3px}
  .fxc-full{padding:40px 48px 30px}
  .fxc-full .fx-in{display:flex;flex-direction:column;align-items:center;text-align:center}
  .fxc-full .fx-top{width:100%}
  .fxc-full .fx-title{margin-top:22px}
  .fxc-full .fx-issued{margin-top:24px}
  .fxc-full .fx-name{text-align:center}
  .fxc-full .fx-name-wrap{width:min(640px,100%)}
  .fxc-full .fx-terms{margin-top:20px;width:100%;grid-template-columns:repeat(3,minmax(0,1fr));text-align:left}
  .fxc-full .fx-foot{margin-top:24px;width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:24px;align-items:end}
  .fxc .fx-sig{display:flex;flex-direction:column;align-items:center;min-width:0}
  .fxc .fx-sig svg{width:100%;max-width:300px;height:58px;overflow:visible}
  .fxc .fx-sig text{font-family:"Pinyon Script",cursive;font-size:34px;fill:transparent;stroke:#9fe9f7;stroke-width:.9;stroke-dasharray:900;stroke-dashoffset:900}
  .fxc .fx-sig.draw text{animation:fxSign 2.2s ease .3s forwards}
  .fxc .fx-sig .l{width:100%;margin-top:4px;border-top:1px solid rgba(120,160,255,.28);padding-top:7px;font:600 9.5px var(--fx-mono);letter-spacing:.2em;text-transform:uppercase;color:#6f7b95;text-align:center}
  .fxc .fx-stamp{display:flex;flex-direction:column;align-items:flex-end;gap:4px;min-width:0;text-align:right;padding-bottom:9px}
  .fxc .fx-stamp small{display:block;font:600 9.5px var(--fx-mono);letter-spacing:.2em;text-transform:uppercase;color:#22D3EE}
  .fxc .fx-stamp b{display:block;font:600 15px var(--fx-display);letter-spacing:-.01em;color:#fff}
  .fxc .fx-stamp code{display:block;font:500 11px var(--fx-mono);letter-spacing:.06em;color:#8d97ad}
  .fxc .fx-micro{margin-top:22px;width:100%;overflow:hidden;white-space:nowrap;font:500 8px var(--fx-mono);letter-spacing:.3em;color:rgba(159,233,247,.28);border-top:1px solid rgba(120,160,255,.14);padding-top:8px}
  @media (max-width:900px){
    .fxp{padding:32px 0 72px}
    .fxp .container{padding:0 16px}
    .fxc-full{padding:52px 20px 24px}
    .fxc-full .fx-terms{grid-template-columns:1fr}
    .fxc-full .fx-foot{grid-template-columns:1fr;justify-items:center;gap:18px}
    .fxc-full .fx-seal{grid-row:1}
    .fxc .fx-stamp{align-items:center;text-align:center;padding-bottom:0}
    .fxc .fx-top{justify-content:center;text-align:center}
    .fxc .fx-sub{font-size:10px;letter-spacing:.12em}
  }
  @media (max-width:720px){
    .fxp-after .fx-cta{width:100%}
  }
  @media (prefers-reduced-motion:reduce){
    .fxp-box{animation:none}
    .fxc::before,.fxc .fx-seal .ring,.fxc .fx-seal svg.rt,.fxc .fx-live i{animation:none}
    .fxc .fx-name-wrap.write .fx-name,.fxc .fx-name-wrap.write .fx-laser{animation:none}
    .fxc .fx-sig.draw text{animation:none}
    .fxc .fx-sig text{stroke-dashoffset:0;fill:#e9fbff}
  }
"""

# The name's laser and the signature run from CSS alone (their classes are
# in the markup), so the page reads the same with scripts off. The script
# only adds the holographic light that follows the pointer and the
# circuit lines behind the card.
CHARTER_JS = r"""<script>
(function () {
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var card = document.querySelector('[data-fxc]');
  if (!card) return;
  function lines() {
    var host = card.querySelector('.fx-lines'); if (!host) return;
    var w = card.clientWidth, h = card.clientHeight; if (!w || !h) return;
    var s = '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">', rows = Math.max(6, Math.round(h / 60));
    for (var i = 0; i < rows; i++) {
      var y = h * (i + .5) / rows, x = 0, d = 'M0 ' + y.toFixed(1), step = w / 8;
      for (var k = 0; k < 8; k++) { x += step; var dy = Math.random() < .35 ? (Math.random() < .5 ? -1 : 1) * 16 : 0; d += ' H' + (x - 10).toFixed(1) + ' L' + x.toFixed(1) + ' ' + (y + dy).toFixed(1); y += dy; }
      s += '<path d="' + d + '" fill="none" stroke="' + (i % 3 ? 'rgba(46,125,255,.16)' : 'rgba(34,211,238,.2)') + '" stroke-width=".8"/>';
    }
    host.innerHTML = s + '</svg>';
  }
  if (window.ResizeObserver) new ResizeObserver(lines).observe(card);
  lines();
  if (reduce) return;
  card.addEventListener('pointermove', function (e) {
    var r = card.getBoundingClientRect();
    card.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%');
    card.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%');
  });
  var t0 = performance.now();
  (function drift(now) {
    var k = (now - t0) / 1000;
    if (!card.matches(':hover')) {
      card.style.setProperty('--mx', (50 + 40 * Math.sin(k * .35)).toFixed(1) + '%');
      card.style.setProperty('--my', (35 + 20 * Math.cos(k * .27)).toFixed(1) + '%');
    }
    requestAnimationFrame(drift);
  })(t0);
})();
</script>"""


def issued_date(today: datetime.date | None = None) -> str:
    """'September 22, 2026'. Built by hand: %-d is not portable."""
    d = today or datetime.date.today()
    return f"{d:%B} {d.day}, {d.year}"


def seat_label(seat: int) -> str:
    """Two digits, the way the seat is numbered everywhere: 7 -> '07'."""
    return f"{int(seat):02d}"


def seat_count_word(limit: int) -> str:
    """'fifty' for the fifty seats the offer was ruled at; any other cap
    (FOUNDER_SEAT_LIMIT is a dial) is written as its number, so the
    charter never names a count the offer does not have."""
    return "fifty" if int(limit) == 50 else str(int(limit))


def charter_content(*, business_name: str, seat: int, seat_limit: int,
                    price_dollars: int, list_dollars: int, credits: int,
                    issued: str, trial: bool, app_home: str) -> str:
    """The page body. business_name is raw and escaped here; every other
    value is a number or a string this codebase wrote."""
    name = _html.escape((business_name or "").strip() or "Your business")
    nn = seat_label(seat)
    of = seat_label(seat_limit)
    price = f"${int(price_dollars)}"
    credits_txt = f"{int(credits):,}"
    status = "your trial has started" if trial else "payment confirmed"
    date = _html.escape(issued)
    word = seat_count_word(seat_limit)
    word_cap = word[:1].upper() + word[1:]
    micro = f"FOUNDING&middot;SEAT&middot;{nn}&middot;OF&middot;{of}&middot;PRICE&middot;LOCKED&middot;" * 14
    list_line = (f"<small>Professional lists at ${int(list_dollars)}</small>"
                 if int(list_dollars) > int(price_dollars) else "")
    trial_line = (" Your trial has started, and you won't be charged until it ends."
                  if trial else "")
    return f"""
<section class="page-hero fxp">
  <div class="container">
    <div class="fxp-box">
      <div class="fxp-banner" role="status"><span>&#9679; Seat {nn} claimed &middot; {status}</span></div>
      <article class="fxc fxc-full" data-fxc aria-labelledby="fxTitle">
        <div class="fx-holo" aria-hidden="true"></div><div class="fx-lines" aria-hidden="true"></div>
        <span class="fx-corner tl"></span><span class="fx-corner tr"></span><span class="fx-corner bl"></span><span class="fx-corner br"></span>
        <div class="fx-in">
          <div class="fx-top"><span>The Solutionist System</span><span class="fx-live"><i></i>Seat {nn} &middot; yours</span><span class="sn">N&ordm; {nn} / {of}</span></div>
          <h1 class="fx-title" id="fxTitle">Founding Charter</h1>
          <div class="fx-sub">Protocol 01 &middot; Price lock &middot; {word_cap} seats</div>
          <span class="fx-issued">Issued to</span>
          <div class="fx-name-wrap write"><span class="fx-name">{name}</span><span class="fx-laser" aria-hidden="true"></span></div>
          <p class="fx-body">Holder of <b>Seat {nn} of {word}</b> on The Solutionist System, at <b>{price} a month</b>. The price is written into this charter and never raised for as long as the seat is held.</p>
          <div class="fx-terms">
            <div class="fx-term"><span>The seat</span><b>Professional &middot; every room &middot; Chief</b></div>
            <div class="fx-term"><span>The price</span><b><em>{price}</em> / month &middot; locked</b>{list_line}</div>
            <div class="fx-term"><span>The allowance</span><b>{credits_txt} AI actions / month</b><div class="fx-meter" aria-hidden="true"><i></i></div></div>
          </div>
          <div class="fx-foot">
            <div class="fx-sig draw"><svg viewBox="0 0 340 58" role="img" aria-label="Signature: The Solutionist System"><text x="170" y="42" text-anchor="middle">The Solutionist System</text></svg><span class="l">Issued by</span></div>
            <div class="fx-seal" aria-hidden="true"><div class="ring"></div>
              <svg class="rt" viewBox="0 0 132 132"><defs><path id="fxRingC" d="M66,66 m-52,0 a52,52 0 1,1 104,0 a52,52 0 1,1 -104,0"/></defs><text font-family="JetBrains Mono, monospace" font-size="7.2" font-weight="600" letter-spacing="2.6" fill="#9fe9f7"><textPath href="#fxRingC">FOUNDING &middot; {word.upper()} SEATS &middot; PRICE LOCKED &middot; SEAT {nn} &middot;</textPath></text></svg>
              <div class="core"><b>{price}</b><span>/MO LOCKED</span></div></div>
            <div class="fx-stamp"><small>Issued</small><b>{date}</b><code>Seat {nn} of {of}</code></div>
          </div>
          <div class="fx-micro" aria-hidden="true">{micro}</div>
        </div>
      </article>
    </div>
    <div class="fxp-after">
      <a class="fx-cta" href="{app_home}">Open your workspace &rarr;</a>
      <p class="fxp-note">This tab can be closed. Your workspace is in the tab you came from, and it unlocks on its own the moment Stripe confirms.{trial_line} If it still shows the paywall, hit <em>Check again</em> there.</p>
    </div>
  </div>
</section>
"""


def render_page(values: Dict, *, render_shell) -> str:
    """The whole page, in the marketing shell. render_shell is
    marketing_pages._render_shell (passed in so a failed import surfaces
    in the caller, which falls back)."""
    content = charter_content(**values)
    return render_shell(
        title="Your Founding Charter",
        description="Your founding seat on The Solutionist System, and the terms it locks.",
        content_html=content, path="/billing", active="",
        extra_css=CHARTER_CSS, extra_scripts=CHARTER_JS, head_extra=FONTS_HEAD)
