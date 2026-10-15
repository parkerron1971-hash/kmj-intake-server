"""
member_app_signin.py — the member app's front door: sign in, the code,
and the pages a member can land on before they're in (Kevin 2026-10-15:
"it's plain and it needs a good ui design to it... be creative with it").

A door left open. The church's own photo fills an arched doorway in the
middle of the screen, the door opens from a seam of light, and that light
falls on "Welcome home." The same photo, blurred, is the room around it.
Glass chips float by the door naming what's inside (messages, giving,
the Bible, prayer), and the form rises in a sheet from the foot of the
screen with the verse of the day under it. A church with no photos gets
leaded glass in the door, made from its own colours.

The code page keeps the door, small, with the code's message arriving in
it. The code goes into six cells. One real input lies over them, so
autofill, paste and screen readers work as before, and the page sends
itself once the sixth digit is in. The pages before sign-in (not open yet,
paused, try again, ask the office, who's signing in) stand in the same
room.

Everything works without script and holds still for reduced motion. The
script only picks the keyboard (email or number pad), mirrors the code
into its cells, and counts down the code's ten minutes and the minute
before a new one can be sent (rate_limit's member_code_email_minute).

Pure functions, no I/O beyond member_app_photos' look at the site folder.
"""
from __future__ import annotations

from html import escape
from string import Template
from typing import Any, Dict, List

import member_app_ui as ui


def _e(v: Any) -> str:
    return escape(str(v if v is not None else ""), quote=True)


class _Tokens(dict):
    """The palette for the stylesheet: $accent is the colour itself,
    $accent_20 is it at 20% opacity."""

    def __missing__(self, key: str) -> str:
        name, _, pct = key.rpartition("_")
        return ui._rgba(self[name], int(pct) / 100)


_CSS = Template("""
body.si::before{display:none;}
.si .mp-shell{display:flex;flex-direction:column;min-height:100vh;min-height:100svh;padding-bottom:0;}

/* the room: the door's photo, blurred and dimmed, behind everything */
.si-bg{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none;background:var(--surface);}
.si-bg>.mb-ph{position:absolute;inset:-48px;background:transparent;}
.si-bg>.mb-ph img{filter:grayscale(.3) blur(30px) saturate(1.5) brightness(.6);transform:scale(1.12);}
.si-bg>.mb-ph::after{opacity:.3;}
.si-bg::after{content:"";position:absolute;inset:0;background:
  radial-gradient(60% 38% at 50% 30%,$glow_45 0%,transparent 72%),
  linear-gradient(180deg,$ground_30 0%,$ground_62 48%,$ground_94 78%,var(--surface) 100%);}

/* the stage: brand, the door, the welcome */
.si-stage{position:relative;z-index:1;margin:0 -20px;padding:calc(16px + env(safe-area-inset-top,0px)) 20px 0;overflow:hidden;
  display:flex;flex-direction:column;align-items:center;text-align:center;--dh:clamp(180px,calc(52vh - 140px),320px);--dw:calc(var(--dh) * .74);}
@supports (height:1svh){.si-stage{--dh:clamp(180px,calc(52svh - 140px),320px);}}
.si-brand{height:40px;display:flex;align-items:center;justify-content:center;gap:10px;max-width:100%;position:relative;z-index:3;}
.si-logo{height:38px;width:auto;max-width:62vw;object-fit:contain;filter:drop-shadow(0 2px 14px rgba(0,0,0,.5));}
.si-name{font-family:var(--mb-display);font-size:13px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;margin:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.si-brand .mb-mark{width:32px;height:32px;border-radius:10px;}

.si-door{position:relative;width:100%;height:var(--dh);margin:14px 0 0;}
.si-halo{position:absolute;left:50%;top:0;width:var(--dw);height:var(--dh);margin-left:calc(var(--dw) / -2);border-radius:50% 50% 22px 22px / 37% 37% 22px 22px;
  box-shadow:0 30px 70px rgba(0,0,0,.5),0 0 90px $accent_30;}
.si-arch{position:absolute;left:50%;top:0;width:var(--dw);height:var(--dh);margin-left:calc(var(--dw) / -2);border-radius:50% 50% 22px 22px / 37% 37% 22px 22px;
  overflow:hidden;isolation:isolate;z-index:1;background:var(--mb-surface-2);clip-path:inset(0 round 50% 50% 22px 22px / 37% 37% 22px 22px);}
.si-arch>.mb-ph,.si-arch>.si-glass{position:absolute;inset:0;}
.si-arch>.mb-ph img{object-position:center 30%;filter:grayscale(.8) contrast(1.06) brightness(1.05);}
.si-arch>.mb-ph::after{opacity:.38;}
.si-arch::after{content:"";position:absolute;inset:0;border-radius:inherit;z-index:2;pointer-events:none;box-shadow:inset 0 0 0 1px $text_28;
  background:linear-gradient(180deg,$ground_45 0%,transparent 34%,transparent 58%,$accent_35 100%);}
.si-ring{position:absolute;left:50%;top:-12px;width:calc(var(--dw) + 24px);height:calc(var(--dh) + 12px);margin-left:calc(var(--dw) / -2 - 12px);
  border:1px solid $accent_50;border-bottom:0;border-radius:999px 999px 0 0;pointer-events:none;}
.si-ring-2{top:-26px;width:calc(var(--dw) + 52px);height:calc(var(--dh) + 26px);margin-left:calc(var(--dw) / -2 - 26px);border-color:$accent_22;}
.si-floor{position:absolute;left:50%;top:calc(var(--dh) - 30px);width:calc(var(--dw) * 2.4);height:100px;margin-left:calc(var(--dw) * -1.2);
  background:radial-gradient(50% 50% at 50% 30%,$accent_45 0%,$glow_20 45%,transparent 75%);filter:blur(4px);pointer-events:none;}
.si-rays{position:absolute;left:50%;top:calc(var(--dh) * .5);width:620px;height:520px;margin-left:-310px;pointer-events:none;
  background:repeating-conic-gradient(from 0deg at 50% 0%,$accent_22 0deg 2.5deg,transparent 2.5deg 9deg);
  -webkit-mask-image:radial-gradient(55% 80% at 50% 0%,#000 10%,transparent 72%);mask-image:radial-gradient(55% 80% at 50% 0%,#000 10%,transparent 72%);
  mix-blend-mode:screen;opacity:.5;transform-origin:50% 0;}

/* leaded glass, for a church with no photos yet */
.si-glass{display:block;overflow:hidden;background:
  linear-gradient(90deg,transparent calc(50% - 1.5px),$ground_85 calc(50% - 1.5px) calc(50% + 1.5px),transparent calc(50% + 1.5px)),
  repeating-linear-gradient(60deg,transparent 0 34px,$ground_70 34px 36px),
  repeating-linear-gradient(-60deg,transparent 0 34px,$ground_70 34px 36px),
  radial-gradient(60% 45% at 28% 18%,$accent_80,transparent 70%),
  radial-gradient(55% 50% at 80% 52%,$glow_95,transparent 72%),
  radial-gradient(80% 50% at 40% 100%,$fill_70,transparent 72%),
  linear-gradient(180deg,$glow,$ground);}
.si-glass::after{content:"";position:absolute;inset:-20%;background:linear-gradient(115deg,transparent 35%,rgba(255,255,255,.22) 50%,transparent 65%);
  transform:translateX(-60%);}

/* what's inside: chips by the door */
.si-chips{list-style:none;margin:0;padding:0;position:absolute;inset:0;z-index:2;pointer-events:none;}
.si-chip{position:absolute;display:inline-flex;align-items:center;gap:7px;padding:5px 12px 5px 5px;border-radius:999px;font-size:12.5px;
  font-weight:700;white-space:nowrap;color:var(--text-primary);background:$surface_62;border:1px solid $text_16;
  -webkit-backdrop-filter:blur(14px) saturate(1.4);backdrop-filter:blur(14px) saturate(1.4);box-shadow:0 12px 28px rgba(0,0,0,.4);}
.si-chip i{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;background:var(--mb-fill);color:var(--mb-on-fill);}
.si-chip:nth-child(odd){right:calc(50% + var(--dw) / 2 - 30px);}
.si-chip:nth-child(even){left:calc(50% + var(--dw) / 2 - 30px);}
.si-chip:nth-child(1){top:12%;}
.si-chip:nth-child(2){top:30%;}
.si-chip:nth-child(3){top:52%;}
.si-chip:nth-child(4){top:68%;}

/* the welcome */
.si-h{position:relative;z-index:3;margin:-46px 0 0;font-family:var(--mb-display);font-weight:900;font-stretch:64%;
  font-size:clamp(60px,18vw,84px);line-height:.84;letter-spacing:-.015em;text-shadow:0 8px 40px rgba(0,0,0,.55);}
.si-w{display:block;}
.si-l{display:inline-block;}
.si-home{position:relative;display:inline-block;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-stretch:normal;
  letter-spacing:-.03em;line-height:.98;color:var(--accent);padding:0 .1em;}
.si-swash{position:absolute;left:6%;bottom:-.1em;width:92%;height:.24em;overflow:visible;}
.si-swash path{fill:none;stroke:var(--accent);stroke-width:3;stroke-linecap:round;opacity:.85;}
.si-sub{position:relative;z-index:3;max-width:310px;margin:16px auto 0;font-size:15px;line-height:1.45;color:var(--text-secondary);text-wrap:balance;}

/* the sheet the form rises in */
.si-sheet{position:relative;z-index:4;flex:1;margin:18px -20px 0;padding:10px 20px calc(20px + env(safe-area-inset-bottom,0px));
  border-radius:30px 30px 0 0;background:$surface_80;border-top:1px solid $text_14;
  -webkit-backdrop-filter:blur(26px) saturate(1.5);backdrop-filter:blur(26px) saturate(1.5);box-shadow:0 -24px 60px rgba(0,0,0,.4);}
.si-grab{display:block;width:38px;height:5px;border-radius:9px;background:$text_18;margin:0 auto 16px;}
.si-form{gap:12px;}
.si-js label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}
.si-seg{position:relative;display:grid;grid-template-columns:1fr 1fr;padding:4px;border-radius:17px;background:$ground_60;border:1px solid var(--mb-line);}
.si-seg::before{content:"";position:absolute;top:4px;bottom:4px;left:4px;width:calc(50% - 4px);border-radius:13px;background:var(--mb-surface-2);
  box-shadow:0 6px 16px rgba(0,0,0,.35),inset 0 1px 0 $text_10;transition:transform .35s cubic-bezier(.3,1.3,.5,1);}
.si-seg[data-m="tel"]::before{transform:translateX(100%);}
.si-seg button{position:relative;z-index:1;min-height:42px;border:0;background:none;border-radius:13px;font:inherit;font-size:14px;font-weight:700;
  color:var(--text-muted);display:flex;align-items:center;justify-content:center;gap:7px;cursor:pointer;transition:color .2s ease;}
.si-seg button[aria-pressed="true"]{color:var(--text-primary);}
.si-seg button[aria-pressed="true"] .mb-ic{color:var(--accent);}
.si-seg button:focus-visible{outline:2px solid var(--focus);outline-offset:2px;}
.si-field{position:relative;}
.si-i{position:absolute;left:17px;top:50%;margin-top:-10px;display:flex;color:var(--text-muted);pointer-events:none;transition:color .2s ease;}
.si-i-mail,.si-i-tel,.si-field[data-m] .si-i-at{display:none;}
.si-field[data-m="email"] .si-i-mail,.si-field[data-m="tel"] .si-i-tel{display:flex;}
.si-field:focus-within .si-i{color:var(--accent);}
.si-field .mp-input{padding-left:48px;min-height:58px;font-size:17px;border-radius:18px;background:$ground_55;border-color:$text_14;
  transition:border-color .2s ease,box-shadow .2s ease;}
.si-field .mp-input::placeholder{color:var(--text-muted);opacity:.85;}
.si-field .mp-input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 4px $accent_22;}
.si-go{position:relative;overflow:hidden;min-height:58px;border-radius:18px;font-size:16.5px;
  box-shadow:0 16px 36px $fill_40,inset 0 1px 0 rgba(255,255,255,.25);}
.si-go::after{content:"";position:absolute;top:0;bottom:0;left:-60%;width:40%;transform:skewX(-20deg);pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);}
.si-go .mb-ic{transition:transform .2s ease;}
.si-go:hover .mb-ic{transform:translateX(3px);}
.si-go[aria-busy="true"]{opacity:.9;cursor:progress;}
.si-go[aria-busy="true"] .mb-ic{display:none;}
.si-go[aria-busy="true"]::before{content:"";width:18px;height:18px;border-radius:50%;border:2.5px solid currentColor;border-right-color:transparent;
  animation:si-spin .8s linear infinite;}
.si-note{margin:14px 0 0;font-size:13px;color:var(--text-muted);text-align:center;text-wrap:balance;}
.si-note .mb-ic{color:var(--accent);vertical-align:-3px;margin-right:6px;}
.si-verse{margin:26px 0 0;padding:22px 4px 0;border-top:1px solid var(--mb-line);text-align:center;}
.si-verse .mb-kick{color:var(--text-muted);letter-spacing:.2em;}
.si-verse blockquote{margin:10px auto 8px;max-width:330px;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:19px;line-height:1.35;
  color:var(--text-primary);text-wrap:balance;}
.si-verse blockquote i{font-style:normal;}
.si-verse cite{font-style:normal;font-size:12.5px;font-weight:600;color:var(--text-secondary);}
.si-foot{margin:26px 0 0;text-align:center;font-size:12px;color:var(--text-muted);}

/* the code */
.si-code,.si-status{position:relative;z-index:1;flex:1;display:flex;flex-direction:column;padding-top:calc(8px + env(safe-area-inset-top,0px));}
.si-code .mb-back{align-self:flex-start;}
.si-mini{position:relative;align-self:center;width:100%;height:var(--dh);margin:6px 0 0;--dh:168px;--dw:124px;}
.si-ping{position:absolute;z-index:3;left:50%;top:56%;width:min(290px,88%);transform:translateX(-50%);display:flex;align-items:center;gap:10px;
  padding:10px 12px;border-radius:18px;text-align:left;background:$surface_82;border:1px solid $text_16;
  -webkit-backdrop-filter:blur(18px) saturate(1.4);backdrop-filter:blur(18px) saturate(1.4);box-shadow:0 18px 40px rgba(0,0,0,.45);}
.si-ping>i{width:38px;height:38px;flex:none;border-radius:12px;display:grid;place-items:center;background:var(--mb-fill);color:var(--mb-on-fill);}
.si-ping-b{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.si-ping-b b{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.si-ping-b small{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--text-secondary);}
.si-ping-t{align-self:flex-start;font-size:11px;color:var(--text-muted);}
.si-dots{display:inline-flex;gap:4px;}
.si-dots u{width:6px;height:6px;border-radius:50%;background:var(--accent);text-decoration:none;}
.si-h2{margin:34px 0 10px;text-align:center;font-size:clamp(42px,12.5vw,54px);font-stretch:64%;line-height:.9;}
.si-to{text-align:center;color:var(--text-secondary);font-size:15px;max-width:340px;margin:0 auto 18px;}
.si-to strong{color:var(--text-primary);white-space:nowrap;}
.si-change{color:var(--accent);font-weight:700;text-decoration:none;white-space:nowrap;}
.si-otp-wrap{position:relative;}
.si-otp{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) 12px repeat(3,minmax(0,1fr));gap:7px;}
.si-otp i{height:66px;border-radius:17px;display:grid;place-items:center;font-style:normal;font-family:var(--mb-display);font-size:32px;
  font-weight:900;font-stretch:80%;background:$ground_55;border:1px solid $text_14;transition:border-color .15s ease,box-shadow .15s ease;}
.si-otp i.on{background:$surface_90;border-color:$accent_45;}
.si-otp b{align-self:center;height:3px;border-radius:2px;background:var(--text-muted);opacity:.6;}
.si-otp-wrap:focus-within .si-otp i.cur{border-color:var(--accent);box-shadow:0 0 0 4px $accent_22;}
.si-otp-wrap:focus-within .si-otp i.cur:empty::after{content:"";width:2px;height:30px;border-radius:1px;background:var(--accent);}
.si-otp-on .mp-code{position:absolute;inset:0;z-index:2;width:100%;height:100%;min-height:0;padding:0;border:0;background:transparent;box-shadow:none;
  color:transparent;-webkit-text-fill-color:transparent;caret-color:transparent;outline:none;}
.si-otp-on .mp-code::selection{background:transparent;}
.si-otp-on label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}
.si-timer{display:flex;justify-content:center;align-items:center;gap:6px;margin:2px 0 0;font-size:13px;color:var(--text-muted);
  font-variant-numeric:tabular-nums;}
.si-timer b{color:var(--text-secondary);}
.si-timer.si-out{color:var(--error);font-weight:600;}
.si-resend{margin:18px 0 0;text-align:center;}
.si-resend p{font-size:14px;color:var(--text-secondary);margin:0;}
.si-resend p+p{font-size:13px;color:var(--text-muted);margin-top:4px;}
.si-again{display:inline-flex;align-items:center;gap:7px;min-height:44px;margin:4px 0;padding:0 16px;border-radius:999px;border:1px solid $accent_35;
  background:$accent_10;color:var(--accent);font:inherit;font-size:14px;font-weight:700;cursor:pointer;font-variant-numeric:tabular-nums;}
.si-again:disabled{border-color:var(--mb-line);background:transparent;color:var(--text-muted);cursor:default;}
.si-again:focus-visible{outline:2px solid var(--focus);outline-offset:3px;}

/* before they're in: not open yet, paused, try again, ask the office, who's signing in */
.si-status{align-items:center;text-align:center;padding-top:calc(16px + env(safe-area-inset-top,0px));}
.si-status .si-mini{margin-top:26px;}
.si-medal{position:absolute;z-index:3;left:50%;bottom:-24px;width:62px;height:62px;margin-left:-31px;border-radius:21px;display:grid;place-items:center;
  background:var(--mb-fill);color:var(--mb-on-fill);box-shadow:0 14px 30px $fill_45,0 0 0 6px $ground_70;}
.si-status .si-h2{margin-top:52px;}
.si-status-b{max-width:350px;font-size:15px;color:var(--text-secondary);}
.si-status-b p{margin:0 0 10px;}
.si-acts{width:100%;max-width:360px;margin:14px auto 0;display:flex;flex-direction:column;gap:10px;}
.si-people{width:100%;max-width:400px;display:flex;flex-direction:column;gap:10px;margin:16px auto 0;}
.si-people form{margin:0;}
.si-person{display:flex;align-items:center;gap:14px;min-height:70px;padding:12px 14px;border-radius:20px;border:1px solid $text_14;
  background:$surface_72;-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);font-weight:700;}
.si-person .mb-avatar{width:44px;height:44px;box-shadow:none;}
.si-person>.mb-ic{margin-left:auto;color:var(--text-muted);flex:none;}

@media (max-height:720px){.si-chip:nth-child(n+3){display:none;}}
@media (min-width:600px){
  .si-sheet{margin:26px 0 40px;flex:none;border-radius:30px;border:1px solid $text_14;}
}
@keyframes si-spin{to{transform:rotate(360deg);}}
@media (prefers-reduced-motion:no-preference){
  .si-bg>.mb-ph img{animation:si-breathe 30s ease-in-out infinite alternate;}
  .si-arch{animation:si-open 1.4s .15s cubic-bezier(.7,0,.2,1) backwards;}
  .si-halo,.si-ring,.si-floor,.si-rays{animation:si-fade 1.2s .9s ease-out backwards;}
  .si-arch>.mb-ph img{animation:si-zoom 2.6s .15s cubic-bezier(.2,.8,.2,1) backwards,si-drift 26s 2.8s ease-in-out infinite alternate;}
  .si-glass::after{animation:si-shine 7s 1.6s ease-in-out infinite;}
  .si-door .si-ring{animation:si-fade 1.2s .9s ease-out backwards,si-ripple 5s 2.1s ease-in-out infinite;}
  .si-door .si-ring-2{animation:si-fade 1.2s 1.1s ease-out backwards,si-ripple 5s 3.4s ease-in-out infinite;}
  .si-rays{animation:si-fade 1.2s .9s ease-out backwards,si-sway 14s 2s ease-in-out infinite alternate;}
  .si-floor{animation:si-fade 1.2s .9s ease-out backwards,si-glow 5s 2s ease-in-out infinite alternate;}
  .si-chip{animation:si-chip .8s cubic-bezier(.2,1.3,.4,1) backwards,si-float 7s ease-in-out infinite;}
  .si-chip:nth-child(1){animation-delay:1.2s,2s;}
  .si-chip:nth-child(2){animation-delay:1.35s,2.6s;animation-duration:.8s,8s;}
  .si-chip:nth-child(3){animation-delay:1.5s,2.3s;animation-duration:.8s,6.5s;}
  .si-chip:nth-child(4){animation-delay:1.65s,3s;animation-duration:.8s,7.5s;}
  .si-l{animation:si-rise .9s cubic-bezier(.2,.9,.2,1) backwards;animation-delay:calc(.35s + var(--i) * 55ms);}
  .si-home{animation:si-focus 1.1s .85s cubic-bezier(.2,.8,.2,1) backwards;}
  .si-swash path{stroke-dasharray:260;stroke-dashoffset:0;animation:si-draw 1.2s 1.45s cubic-bezier(.6,0,.2,1) backwards;}
  .si-sub{animation:si-up .8s 1s cubic-bezier(.2,.8,.2,1) backwards;}
  .si-sheet{animation:si-sheet 1s .45s cubic-bezier(.2,.9,.2,1) backwards;}
  .si-go::after{animation:si-sheen 6s 2.4s ease-in-out infinite;}
  .si-mini .si-arch{animation:si-open 1.1s .1s cubic-bezier(.7,0,.2,1) backwards;}
  .si-ping{animation:si-ping .9s .9s cubic-bezier(.2,1.25,.4,1) backwards;}
  .si-dots u{animation:si-dot 1.4s ease-in-out infinite;}
  .si-dots u:nth-child(2){animation-delay:.12s;} .si-dots u:nth-child(3){animation-delay:.24s;}
  .si-dots u:nth-child(4){animation-delay:.36s;} .si-dots u:nth-child(5){animation-delay:.48s;} .si-dots u:nth-child(6){animation-delay:.6s;}
  .si-medal{animation:si-chip .8s .9s cubic-bezier(.2,1.3,.4,1) backwards;}
  .si-otp i.on{animation:si-pop .2s ease-out;}
  .si-otp-wrap:focus-within .si-otp i.cur:empty::after{animation:si-blink 1s steps(1) infinite;}
  .si .mp-err{animation:si-shake .45s ease-in-out;}
}
@keyframes si-open{0%,45%{clip-path:inset(0 49.4% 0 49.4% round 50% 50% 22px 22px / 37% 37% 22px 22px);filter:brightness(3.2) saturate(.4);}
  100%{clip-path:inset(0 round 50% 50% 22px 22px / 37% 37% 22px 22px);filter:brightness(1) saturate(1);}}
@keyframes si-zoom{from{transform:scale(1.22);}to{transform:scale(1.03);}}
@keyframes si-drift{from{transform:scale(1.03);}to{transform:scale(1.1) translateY(-6px);}}
@keyframes si-breathe{from{transform:scale(1.12);}to{transform:scale(1.22);}}
@keyframes si-fade{from{opacity:0;}}
@keyframes si-ripple{0%,100%{opacity:1;}50%{opacity:.35;}}
@keyframes si-sway{from{transform:rotate(-5deg);}to{transform:rotate(5deg);}}
@keyframes si-glow{from{opacity:.75;}to{opacity:1;}}
@keyframes si-shine{0%,55%{transform:translateX(-60%);}100%{transform:translateX(60%);}}
@keyframes si-chip{from{opacity:0;transform:translateY(10px) scale(.8);}}
@keyframes si-float{0%,100%{translate:0 0;}50%{translate:0 -7px;}}
@keyframes si-rise{from{opacity:0;transform:translateY(.5em) rotate(7deg);}}
@keyframes si-focus{from{opacity:0;filter:blur(12px);transform:translateY(.12em);}}
@keyframes si-draw{from{stroke-dashoffset:260;}}
@keyframes si-up{from{opacity:0;transform:translateY(12px);}}
@keyframes si-sheet{from{opacity:0;transform:translateY(60px);}}
@keyframes si-sheen{0%,70%{left:-60%;}100%{left:130%;}}
@keyframes si-ping{from{opacity:0;transform:translateX(-50%) translateY(-26px) scale(.9);}}
@keyframes si-dot{0%,100%{opacity:.35;transform:none;}40%{opacity:1;transform:translateY(-2px);}}
@keyframes si-pop{from{transform:scale(.88);}}
@keyframes si-blink{50%{opacity:0;}}
@keyframes si-shake{20%,60%{transform:translateX(-5px);}40%,80%{transform:translateX(5px);}}
""")


def css(biz: Dict[str, Any], theme: Dict[str, Any]) -> str:
    return _CSS.substitute(_Tokens(ui.palette(biz, theme)))


# ─── pieces ──────────────────────────────────────────────────────────


def _pic(biz: Dict[str, Any], site) -> str:
    import member_app_photos as photos
    return photos.welcome(photos.photos(biz, site))


def _room(pic: str) -> str:
    """The door's photo, blurred, as the room around everything."""
    return f'<div class="si-bg" aria-hidden="true">{ui.photo(pic) if pic else ""}</div>'


def _brand(biz: Dict[str, Any], site, theme: Dict[str, Any]) -> str:
    import member_app_photos as photos
    name = (biz.get("name") or "").strip() or "Your church"
    word = photos.wordmark(site)
    if word:
        return f'<div class="si-brand"><img class="si-logo" src="{_e(word)}" alt="{_e(name)}"></div>'
    logo = theme.get("logo_url") or ""
    mark = f'<span class="mb-mark" aria-hidden="true"><img src="{_e(logo)}" alt=""></span>' if logo else ""
    return f'<div class="si-brand">{mark}<p class="si-name">{_e(name)}</p></div>'


def _arch(pic: str) -> str:
    inside = ui.photo(pic, eager=True) if pic else '<span class="si-glass" aria-hidden="true"></span>'
    return (f'<span class="si-halo" aria-hidden="true"></span><span class="si-ring" aria-hidden="true"></span>'
            f'<span class="si-ring si-ring-2" aria-hidden="true"></span><div class="si-arch" aria-hidden="true">{inside}</div>')


def _chips(biz: Dict[str, Any]) -> str:
    """Four things that are inside, by the door: what this church has
    turned on first."""
    import member_portal_messaging as mpm
    from giving_router import giving_is_active
    have = []
    if mpm.turned_on(biz):
        have.append(("chat", "Messages"))
    if giving_is_active(biz):
        have.append(("heart", "Give"))
    have += [("book", "Bible"), ("pray", "Prayer"), ("users", "Groups"), ("calendar", "Events")]
    return ('<ul class="si-chips" aria-hidden="true">'
            + "".join(f'<li class="si-chip"><i>{ui.icon(ic, 14)}</i>{_e(label)}</li>' for ic, label in have[:4])
            + "</ul>")


def _welcome() -> str:
    letters = "".join(f'<span class="si-l" style="--i:{i}">{c}</span>' for i, c in enumerate("Welcome"))
    swash = ('<svg class="si-swash" viewBox="0 0 200 20" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
             '<path d="M3 15 C 50 4, 120 2, 197 9"/></svg>')
    return (f'<h1 class="si-h"><span class="mp-sr">Welcome home.</span>'
            f'<span class="si-w" aria-hidden="true">{letters}</span>'
            f'<span class="si-home" aria-hidden="true">home.{swash}</span></h1>')


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
    pic = _pic(biz, site)
    err = f'<p class="mp-err" role="alert">{_e(error)}</p>' if error else ""
    return f"""{_room(pic)}
<section class="si-stage">
  {_brand(biz, site, theme)}
  <div class="si-door"><span class="si-rays" aria-hidden="true"></span><span class="si-floor" aria-hidden="true"></span>{_arch(pic)}{_chips(biz)}</div>
  {_welcome()}
  <p class="si-sub">Messages, groups, giving and what's coming up at {_e(name)}, all in one place.</p>
</section>
<section class="si-sheet" aria-label="Sign in">
  <span class="si-grab" aria-hidden="true"></span>
  <form class="mp-form si-form" method="post" action="/my/code">
    <div class="si-seg" role="group" aria-label="Sign in with" hidden>
      <button type="button" data-m="email" aria-pressed="true">{ui.icon('mail', 17)}Email</button>
      <button type="button" data-m="tel" aria-pressed="false">{ui.icon('phone', 17)}Mobile number</button>
    </div>
    <label for="mp-email">Email or mobile number</label>
    <div class="si-field"><span class="si-i si-i-at">{ui.icon('at')}</span><span class="si-i si-i-mail">{ui.icon('mail')}</span><span class="si-i si-i-tel">{ui.icon('phone')}</span>
      <input class="mp-input" id="mp-email" name="email" type="text" autocomplete="username" autocapitalize="off" spellcheck="false" required value="{_e(email)}"></div>
    {err}
    <button class="mp-go si-go" type="submit"><span>Send my code</span>{ui.icon('arrow', 19)}</button>
  </form>
  <p class="si-note">{ui.icon('shield', 16)}No password to remember. We'll send you a 6-digit code.</p>
  {_verse()}
  {_foot(biz)}
</section>"""


def code_body(biz: Dict[str, Any], site, *, email: str, shown: str, texted: bool, error: str = "") -> str:
    """`shown` is the address or number as the member reads it back."""
    name = (biz.get("name") or "").strip() or "the church"
    pic = _pic(biz, site)
    err = f'<p class="mp-err" role="alert">{_e(error)}</p>' if error else ""
    # A fresh code (no error) gets its ten minutes counted down and the
    # minute before another can be sent.
    timer = '' if error else '<p class="si-timer" hidden>Works for <b>10:00</b></p>'
    wait = '' if error else ' data-wait="60"'
    dots = "".join("<u></u>" for _ in range(6))
    return f"""{_room(pic)}
<div class="si-code">
  <a class="mb-back" href="/my">{ui.icon('back', 16)}Back</a>
  <div class="si-mini" aria-hidden="true">{_arch(pic)}
    <div class="si-ping"><i>{ui.icon('chat' if texted else 'mail', 19)}</i><span class="si-ping-b"><b>{_e(name)}</b>
      <small>Your sign-in code <span class="si-dots">{dots}</span></small></span><span class="si-ping-t">now</span></div></div>
  <h1 class="si-h2">Check your {'texts' if texted else 'email'}</h1>
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
    <button class="mp-go si-go" type="submit"><span>Sign in</span>{ui.icon('arrow', 19)}</button>
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
    pic = _pic(biz, site)
    acts = f'<div class="si-acts">{actions}</div>' if actions else ""
    return f"""{_room(pic)}
<section class="si-status">
  {_brand(biz, site, theme)}
  <div class="si-mini" aria-hidden="true">{_arch(pic)}<span class="si-medal">{ui.icon(icon, 26)}</span></div>
  <h1 class="si-h2">{_e(title)}</h1>
  <div class="si-status-b">{body}</div>
  {acts}
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

