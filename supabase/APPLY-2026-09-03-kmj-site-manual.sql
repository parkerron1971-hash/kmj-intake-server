-- APPLY-2026-09-03-kmj-site-manual.sql
-- Installs the hand-built KMJ Creative Solutions site (sites/kmj-creative-solutions/)
-- into its business_sites row and marks it html_source = "manual", which tells
-- public_site.py to serve it as-is (overrides + the business email filled at
-- serve time) and tells the composer's refresh path to leave it alone.
--
-- Apply AFTER the backend that understands html_source = "manual" is live on
-- main, otherwise {{BUSINESS_EMAIL}} shows literally until it deploys.
-- The previous page set is kept under site_config.manual_backup; see the
-- ROLLBACK file to put it back.
BEGIN;

UPDATE business_sites
SET
  html_content = $kmj$<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KMJ Creative Solutions — Elevate Your Vision, Amplify Your Impact</title>
<meta name="description" content="A solutionist practice. Coaching, consulting, and creative direction for founders and leaders who need clarity on the idea, the offer, and the shift in front of them.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&amp;family=Cormorant+Garamond:ital,wght@1,500&amp;family=Work+Sans:wght@400;500;600&amp;display=swap">
<style>
/* KMJ Creative Solutions — hand-built site (2026-09-03).
   Source of truth: sites/kmj-creative-solutions/. Built into the
   business_sites row by build.py; served by public_site.py under
   site_config.html_source == "manual". */
:root {
  --ink: #0F0E0B; --ink-2: #14120E; --text: #17150F; --body: #3E3A31; --muted: #6B655A;
  --cream: #F7F4EE; --cream-2: #FFFDF8;
  --gold: #D4A72C; --gold-deep: #B8922E; --gold-light: #F3D97A;
  --green: #7D8C3A; --green-deep: #5B6A22; --green-light: #A9B83A; --green-text: #6E7B2E;
  --gutter: clamp(20px, 5vw, 72px);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--cream); color: var(--text); font-family: 'Work Sans', 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 17px; line-height: 1.6; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
a { color: inherit; text-decoration: none; transition: color .25s ease; }
a:hover { color: var(--green); }
img { max-width: 100%; }
p, h1, h2, h3 { margin: 0; }
.wrap { max-width: 1440px; margin: 0 auto; padding-left: var(--gutter); padding-right: var(--gutter); }
.disp { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; line-height: 0.96; letter-spacing: -0.035em; }
.serif { font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 500; letter-spacing: 0; line-height: 1.15; }
.eyebrow { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--green-text); font-weight: 600; }
.eyebrow-gold { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.small { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 600; }
.muted { color: var(--muted); }
.dim { color: rgba(247,244,238,0.72); }
.lead { font-size: clamp(17px, 1.5vw, 21px); line-height: 1.55; }
.foil { background: linear-gradient(100deg, #8A6A14 0%, #D4A72C 22%, #F3D97A 40%, #C8981F 58%, #F0D46B 76%, #9C7A1A 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-dk { background: linear-gradient(100deg, #7A5C0A 0%, #B8922E 25%, #E0BC4A 45%, #A67F17 65%, #D4A72C 85%, #8A6A14 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-green { background: linear-gradient(100deg, #4A5619 0%, #7D8C3A 30%, #A9B83A 50%, #5B6A22 72%, #8FA32E 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.num { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; font-size: clamp(64px, 7vw, 96px); line-height: 0.8; letter-spacing: -0.05em; }
.btn { display: inline-flex; align-items: center; justify-content: center; min-height: 54px; padding: 0 30px; font-weight: 600; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; text-align: center; transition: background-color .25s ease, color .25s ease, border-color .25s ease, transform .25s ease; cursor: pointer; border: 0; font-family: inherit; }
.btn:hover { transform: translateY(-2px); }
.btn-gold { background: var(--gold); color: var(--ink); } .btn-gold:hover { background: var(--green-light); color: var(--ink); }
.btn-ink { background: var(--ink); color: var(--cream); } .btn-ink:hover { background: var(--green-deep); color: var(--cream); }
.btn-line { border: 2px solid var(--text); color: var(--text); background: transparent; } .btn-line:hover { border-color: var(--green); color: var(--green-deep); }
.btn-light { border: 2px solid rgba(247,244,238,0.5); color: var(--cream); background: transparent; } .btn-light:hover { border-color: var(--green-light); color: var(--green-light); }
.link-draw { position: relative; display: inline-block; }
.link-draw::after { content: ""; position: absolute; left: 0; bottom: -4px; height: 2px; width: 100%; background: currentColor; transform: scaleX(0); transform-origin: left; transition: transform .35s var(--ease); }
.link-draw:hover::after { transform: scaleX(1); }
.link-gold { color: var(--green-light); font-weight: 600; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }

/* dark bands */
.dark { position: relative; background: var(--ink); color: var(--cream); }
.dark::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: 0.07; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23n)' opacity='0.8'/></svg>"); }
.dark > * { position: relative; z-index: 1; }
.olive { background: var(--green-deep); }
.glow { position: absolute; border-radius: 50%; pointer-events: none; z-index: 0; }
.sig { position: absolute; pointer-events: none; z-index: 0; }

/* nav */
.nav { background: var(--ink); color: var(--cream); }
.nav .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-top: 16px; padding-bottom: 16px; }
.nav-logo img { height: 52px; width: auto; display: block; }
.nav-links { display: flex; align-items: center; gap: 32px; font-size: 14px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
.nav-links a { color: var(--cream); }
.nav-links .btn { min-height: 46px; padding: 0 22px; }
.nav-toggle { display: none; background: none; border: 0; color: var(--cream); width: 44px; height: 44px; cursor: pointer; padding: 0; }
.nav-toggle svg { display: block; margin: 0 auto; }

/* hero */
.hero { overflow: hidden; }
.hero .wrap { display: flex; flex-direction: column; gap: 36px; padding-top: clamp(56px, 7vw, 96px); }
.hero-head { display: flex; flex-direction: column; gap: 28px; max-width: 1180px; }
.hero h1 { font-size: clamp(48px, 8.6vw, 124px); color: var(--cream); }
.hero-then { display: flex; flex-direction: column; gap: 14px; align-self: flex-start; }
.hero-then .serif { font-size: clamp(34px, 4.4vw, 64px); }
.rule { display: block; height: 4px; background: linear-gradient(90deg, #D4A72C, #F3D97A, #D4A72C); transform-origin: left; transform: scaleX(0); animation: draw 1.1s var(--ease) .9s forwards; }
.hero-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-bottom: 72px; }
.hero-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 28px; }
.hero-copy .lead { max-width: 640px; color: rgba(247,244,238,0.8); }
.cta-row { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -132px; }
.quote-card { display: flex; flex-direction: column; gap: 12px; padding: 28px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.quote-card .serif { font-size: clamp(22px, 2vw, 30px); }
.sys-card { position: absolute; right: -36px; top: -150px; width: 300px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; z-index: 2; border-top: 3px solid var(--gold); animation: bob 6s ease-in-out infinite; }
.win { background: var(--ink-2); border: 1px solid rgba(247,244,238,0.14); box-shadow: 0 40px 80px rgba(0,0,0,0.45); }
.ring { position: absolute; z-index: 0; animation: spin 60s linear infinite; transform-origin: center; }
.spin { animation: spin 28s linear infinite; transform-origin: center; }
.cycle { display: inline-block; height: 1em; overflow: hidden; vertical-align: bottom; font-weight: 500; letter-spacing: 0; }
.cycle > span { display: block; animation: cycle 12s var(--ease) infinite; }
.cycle > span > i { display: block; height: 1em; line-height: 1; font-style: italic; }
.dot { position: relative; width: 10px; height: 10px; border-radius: 50%; background: var(--green-light); flex: none; }
.dot::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: var(--green-light); animation: ping 1.8s cubic-bezier(0, 0, 0.2, 1) infinite; }
.ticker { height: 1.5em; overflow: hidden; }
.ticker > div { animation: ticker 12s var(--ease) infinite; }
.bar { height: 8px; background: rgba(247,244,238,0.1); overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform-origin: left; animation: draw 1.4s var(--ease) forwards; }
.r1, .r2, .r3, .r4 { opacity: 0; animation: rise .9s var(--ease) forwards; }
.r1 { animation-delay: .1s; } .r2 { animation-delay: .3s; } .r3 { animation-delay: .5s; } .r4 { animation-delay: .7s; }
.breathe { animation: breathe 9s ease-in-out infinite; }

/* marquee */
.marquee-band { background: var(--gold); color: var(--ink); padding: 22px 0; overflow: hidden; }
.marquee { display: flex; width: max-content; gap: 48px; align-items: center; animation: marquee 32s linear infinite; }
.marquee:hover { animation-play-state: paused; }
.marquee > div { display: flex; align-items: center; gap: 48px; padding-right: 48px; }
.marquee .disp, .marquee .serif { font-size: clamp(26px, 2.8vw, 40px); white-space: nowrap; }

/* sections */
.section { padding-top: clamp(64px, 8vw, 112px); padding-bottom: clamp(64px, 8vw, 112px); }
.section-head { display: flex; justify-content: space-between; align-items: end; gap: 40px; flex-wrap: wrap; }
.section-head > div { display: flex; flex-direction: column; gap: 16px; }
.h2 { font-size: clamp(40px, 5vw, 72px); }
.h2-md { font-size: clamp(36px, 4.2vw, 60px); }
.h3 { font-size: clamp(28px, 2.6vw, 38px); }
.doors { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; margin-top: 56px; }
.card { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 20px; padding: 36px 32px 44px; background: var(--ink); color: var(--cream); transition: transform .35s var(--ease); }
.card::before { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform: scaleX(0); transform-origin: left; transition: transform .45s var(--ease); }
.card:hover { transform: translateY(-6px); } .card:hover::before { transform: scaleX(1); }
.card .link-gold { margin-top: auto; align-self: flex-start; }
.manifesto { position: relative; overflow: hidden; }
.manifesto .wrap { display: flex; flex-direction: column; gap: 28px; }
.manifesto .disp { font-size: clamp(40px, 6.4vw, 92px); max-width: 1240px; }
.moves { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.moves-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.moves-grid { grid-column: 6 / span 7; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 44px 40px; }
.move { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green); }
.move .disp:first-child { font-size: 26px; }
.move h3 { font-size: 32px; }
.proof { overflow: hidden; }
.proof .wrap { display: flex; flex-direction: column; gap: 64px; }
.proof-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; }
.proof-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 24px; }
.proof-copy .h2 { color: var(--cream); font-size: clamp(40px, 4.7vw, 68px); }
.proof-copy p { color: rgba(247,244,238,0.8); max-width: 560px; font-size: 18px; }
.proof-mock { grid-column: 8 / span 5; }
.mock { display: grid; grid-template-columns: 132px minmax(0, 1fr); overflow: hidden; transform: rotate(-1.5deg); }
.win-bar { grid-column: span 2; display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid rgba(247,244,238,0.1); }
.win-bar b { width: 10px; height: 10px; border-radius: 50%; background: rgba(247,244,238,0.18); }
.win-bar .small { color: rgba(247,244,238,0.45); margin-left: 8px; }
.side { padding: 12px 8px; border-right: 1px solid rgba(247,244,238,0.1); display: flex; flex-direction: column; gap: 2px; }
.side span { display: block; padding: 8px 10px; color: rgba(247,244,238,0.6); font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.side span.on { background: rgba(212,167,44,0.14); color: var(--gold); }
.mock-main { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.mock-msg { padding: 12px 14px; background: rgba(247,244,238,0.06); border-left: 3px solid var(--gold); font-size: 14px; line-height: 1.5; color: rgba(247,244,238,0.9); }
.trace { stroke-dasharray: 900; stroke-dashoffset: 900; animation: trace 2.6s var(--ease) .6s forwards; }
.mock-bars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.mock-bars > div { display: flex; flex-direction: column; gap: 6px; }
.mock-bars .small { color: rgba(247,244,238,0.5); }
.chips { display: flex; flex-direction: column; gap: 18px; padding-top: 40px; border-top: 1px solid rgba(247,244,238,0.14); }
.chips > div { display: flex; flex-wrap: wrap; gap: 10px; }
.chip { display: inline-flex; align-items: center; height: 40px; padding: 0 18px; border: 1px solid rgba(247,244,238,0.18); background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); font-size: 13px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; animation: chain 9.6s ease-in-out infinite; }
.chip:nth-child(1) { animation-delay: 0s; } .chip:nth-child(2) { animation-delay: 1.2s; } .chip:nth-child(3) { animation-delay: 2.4s; } .chip:nth-child(4) { animation-delay: 3.6s; } .chip:nth-child(5) { animation-delay: 4.8s; } .chip:nth-child(6) { animation-delay: 6s; } .chip:nth-child(7) { animation-delay: 7.2s; } .chip:nth-child(8) { animation-delay: 8.4s; }
.about-lite { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: center; }
.about-art { grid-column: span 5; position: relative; }
.about-art::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.art { position: relative; z-index: 1; height: clamp(320px, 36vw, 520px); background: linear-gradient(160deg, #5B6A22 0%, #8FA32E 45%, #D4A72C 100%); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.art img { width: 70%; height: auto; opacity: 0.9; }
.art .photo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 1; }
.about-art .spin { position: absolute; right: -40px; bottom: -40px; z-index: 2; }
.about-copy { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; }
.about-copy p { font-size: 18px; color: var(--body); }
.signoff { display: flex; align-items: center; flex-wrap: wrap; gap: 28px; margin-top: 8px; }
.signoff img { height: 64px; width: auto; }
.cta-band { position: relative; overflow: hidden; clip-path: polygon(0 56px, 100% 0, 100% 100%, 0 100%); padding-top: clamp(100px, 10vw, 136px); padding-bottom: clamp(64px, 6vw, 88px); }
.cta-band .wrap { display: flex; align-items: center; justify-content: space-between; gap: 40px; flex-wrap: wrap; }
.cta-band .h2 { color: var(--cream); }
.cta-band p { font-size: 19px; font-weight: 500; color: rgba(247,244,238,0.85); }
.cta-band .btn { min-height: 64px; padding: 0 40px; font-size: 15px; }

/* inner pages */
.page-hero { overflow: hidden; }
.page-hero .wrap { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-top: clamp(56px, 7vw, 96px); padding-bottom: clamp(56px, 6vw, 80px); }
.page-hero h1 { font-size: clamp(44px, 7.2vw, 104px); color: var(--cream); }
.page-hero .rule { width: 220px; }
.page-hero .lead { color: rgba(247,244,238,0.8); max-width: 640px; }
.page-hero-copy { grid-column: span 8; display: flex; flex-direction: column; gap: 24px; }
.page-hero-side { grid-column: 10 / span 3; }
.gold-card { display: flex; flex-direction: column; gap: 10px; padding: 28px; background: var(--gold); color: var(--ink); }
.gold-card .eyebrow { color: var(--ink); }
.gold-card .disp { font-size: 32px; }
.gold-card p { font-size: 15px; font-weight: 500; }
.gold-card .btn { margin-top: 10px; align-self: flex-start; }
.offer { padding: 56px 0; border-top: 3px solid var(--green); display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.offer-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.offer-head h2 { font-size: clamp(36px, 3.6vw, 52px); }
.offer-body { grid-column: span 5; display: flex; flex-direction: column; gap: 20px; }
.offer-body > p { font-size: 18px; color: var(--body); }
.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 24px; padding-top: 6px; }
.facts > div { display: flex; flex-direction: column; gap: 4px; }
.facts .eyebrow { color: var(--muted); }
.offer-price { grid-column: span 3; }
.offer-price .card { padding: 28px 28px 34px; gap: 16px; }
.offer-price .disp { font-size: clamp(26px, 2.4vw, 36px); color: var(--cream); }
.offer-price .dim { font-size: 14px; }
.offer-price .btn { align-self: flex-start; }
.who { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.who-head { grid-column: span 6; display: flex; flex-direction: column; gap: 16px; }
.who-head .h2 { color: var(--cream); font-size: clamp(36px, 4vw, 58px); }
.who-body { grid-column: 8 / span 5; display: flex; flex-direction: column; gap: 18px; font-size: 18px; font-weight: 500; color: rgba(247,244,238,0.88); }
.about-hero .page-hero-copy { grid-column: span 7; padding-bottom: 40px; }
.about-hero .page-hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -96px; }
.about-hero .page-hero-side::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.about-hero .art { height: clamp(320px, 33vw, 480px); border: 6px solid var(--gold); }
.about-hero .spin { position: absolute; left: -48px; top: -48px; z-index: 2; }
.story { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; padding-top: 160px; }
.stats { grid-column: span 3; display: flex; flex-direction: column; gap: 32px; }
.stat { display: flex; flex-direction: column; gap: 8px; padding-top: 18px; border-top: 3px solid var(--green); }
.stat .num { font-size: clamp(56px, 6vw, 88px); }
.stat span:last-child { font-size: 14px; color: var(--muted); }
.story-copy { grid-column: 5 / span 7; display: flex; flex-direction: column; gap: 24px; font-size: 19px; color: var(--body); line-height: 1.7; }
.story-copy h2 { font-size: clamp(32px, 3vw, 44px); color: var(--text); }
.story-copy h2 + p { margin-top: 0; }
.story-copy h2:not(:first-child) { margin-top: 16px; }
.values { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 40px; }
.values-head { grid-column: span 4; display: flex; flex-direction: column; gap: 10px; }
.values-head .h2 { color: var(--cream); font-size: clamp(36px, 3.9vw, 56px); }
.value { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green-light); }
.value .disp { font-size: 34px; color: var(--gold); }
.question { position: relative; overflow: hidden; text-align: center; }
.question .wrap { display: flex; flex-direction: column; gap: 24px; align-items: center; }
.question .serif { font-size: clamp(28px, 3.2vw, 46px); max-width: 980px; }
.question .spin { position: absolute; left: -120px; top: 50%; margin-top: -180px; opacity: 0.35; }
.contact-hero .wrap { align-items: start; }
.contact-copy { grid-column: span 5; display: flex; flex-direction: column; gap: 40px; }
.contact-copy > div:first-child { display: flex; flex-direction: column; gap: 22px; }
.contact-copy h1 { font-size: clamp(44px, 6.1vw, 88px); }
.contact-email { display: flex; flex-direction: column; gap: 6px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.2); }
.contact-email a { font-size: 18px; color: var(--cream); }
.contact-email a:hover { color: var(--gold); }
.contact-email .dim { font-size: 14px; }
.form-card { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; padding: 40px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.form-card h2 { font-size: clamp(28px, 2.6vw, 38px); }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 12px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
.field input, .field textarea { width: 100%; min-height: 54px; border: 2px solid var(--text); background: var(--cream-2); padding: 12px 16px; font: inherit; font-size: 16px; color: var(--text); border-radius: 0; }
.field textarea { min-height: 160px; resize: vertical; }
.field input:focus, .field textarea:focus { outline: none; border-color: var(--gold); }
.form-note { font-size: 14px; color: var(--muted); }
.form-note.ok { color: var(--green-deep); font-weight: 600; }
.form-note.err { color: #A33; font-weight: 600; }
.hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }

/* footer */
.footer { padding-top: 64px; padding-bottom: 40px; }
.footer-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 40px; flex-wrap: wrap; }
.footer-brand { display: flex; flex-direction: column; gap: 18px; }
.footer-brand img { height: 84px; width: auto; }
.footer-brand .serif { color: var(--gold); font-size: 26px; }
.footer-links { display: flex; flex-wrap: wrap; gap: 32px; font-size: 13px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-links a { color: rgba(247,244,238,0.85); }
.footer-links a:last-child { color: var(--gold); }
.footer-bottom { margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.16); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; font-size: 13px; color: rgba(247,244,238,0.55); }
.footer-bottom a { color: rgba(247,244,238,0.75); }

@keyframes rise { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
@keyframes draw { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes bob { 0%, 100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-14px) rotate(-2deg); } }
@keyframes ping { 0% { transform: scale(1); opacity: .9; } 100% { transform: scale(2.6); opacity: 0; } }
@keyframes chain { 0%, 100% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } 12% { background: #D4A72C; color: #0F0E0B; border-color: #D4A72C; } 24% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } }
@keyframes trace { to { stroke-dashoffset: 0; } }
@keyframes cycle { 0%, 18% { transform: translateY(0); } 25%, 43% { transform: translateY(-20%); } 50%, 68% { transform: translateY(-40%); } 75%, 93% { transform: translateY(-60%); } 100% { transform: translateY(-80%); } }
@keyframes ticker { 0%, 30% { transform: translateY(0); } 33%, 63% { transform: translateY(-100%); } 66%, 96% { transform: translateY(-200%); } 100% { transform: translateY(-300%); } }
@keyframes breathe { 0%, 100% { opacity: .5; transform: scale(1); } 50% { opacity: .85; transform: scale(1.08); } }

@media (max-width: 1100px) {
  .hero-copy { grid-column: span 12; }
  .hero-side { grid-column: span 12; margin-bottom: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
  .sys-card { position: static; width: auto; animation: none; }
  .hero-grid { padding-bottom: 56px; }
  .ring { display: none; }
  .doors { grid-template-columns: 1fr; }
  .moves-head, .moves-grid { grid-column: span 12; }
  .proof-copy, .proof-mock { grid-column: span 12; }
  .mock { transform: none; }
  .about-art, .about-copy { grid-column: span 12; }
  .page-hero-copy { grid-column: span 12; }
  .page-hero-side { grid-column: span 12; }
  .about-hero .page-hero-copy, .about-hero .page-hero-side { grid-column: span 12; margin-bottom: 0; }
  .about-hero .page-hero-side { padding-bottom: 24px; }
  .story { padding-top: 64px; }
  .stats, .story-copy { grid-column: span 12; }
  .stats { flex-direction: row; flex-wrap: wrap; }
  .stats .stat { flex: 1 1 200px; }
  .values { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .values-head { grid-column: span 2; }
  .offer-head, .offer-body, .offer-price { grid-column: span 12; }
  .who-head, .who-body { grid-column: span 12; }
  .contact-copy, .form-card { grid-column: span 12; }
}
@media (max-width: 720px) {
  body { font-size: 16px; }
  .nav-toggle { display: block; }
  .nav-links { display: none; position: absolute; left: 0; right: 0; top: 100%; flex-direction: column; align-items: stretch; gap: 0; background: var(--ink); padding: 8px var(--gutter) 20px; z-index: 20; border-top: 1px solid rgba(247,244,238,0.12); }
  .nav-links.open { display: flex; }
  .nav-links a { padding: 14px 0; border-bottom: 1px solid rgba(247,244,238,0.08); }
  .nav-links .btn { margin-top: 12px; }
  .nav { position: relative; }
  .hero-side { grid-template-columns: 1fr; }
  .sig { display: none; }
  .moves-grid { grid-template-columns: 1fr; }
  .mock { grid-template-columns: 1fr; }
  .side { flex-direction: row; flex-wrap: wrap; border-right: 0; border-bottom: 1px solid rgba(247,244,238,0.1); }
  .values { grid-template-columns: 1fr; }
  .values-head { grid-column: span 1; }
  .facts, .mock-bars { grid-template-columns: 1fr; }
  .form-card { padding: 24px; }
  .question .spin { display: none; }
  .cta-band { clip-path: polygon(0 28px, 100% 0, 100% 100%, 0 100%); }
  .move h3 { font-size: 26px; }
}
@media (prefers-reduced-motion: reduce) {
  .r1, .r2, .r3, .r4 { opacity: 1; animation: none; }
  .rule, .bar i { transform: none; animation: none; }
  .ring, .spin, .marquee, .sys-card, .breathe, .dot::after, .chip, .ticker > div, .cycle > span { animation: none; }
  .trace { stroke-dashoffset: 0; animation: none; }
}

</style>
</head>
<body>
<header class="nav">
  <div class="wrap">
    <a class="nav-logo" href="/" aria-label="KMJ Creative Solutions home"><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions"></a>
    <button class="nav-toggle" type="button" aria-label="Open menu" aria-expanded="false" data-nav-toggle>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>
    </button>
    <nav class="nav-links sxm-header-pagenav" data-nav-links aria-label="Primary">
      <a href="/about" class="link-draw">About</a>
      <a href="/services" class="link-draw">Services</a>
      <a href="/contact" class="link-draw">Contact</a>
      <a href="/book" class="btn btn-gold">Book a Discovery Call</a>
    </nav>
  </div>
</header>

<main>
<section class="hero dark">
  <div class="glow breathe" style="width: 520px; height: 520px; right: -120px; top: -140px; background: radial-gradient(circle, rgba(212,167,44,0.42), rgba(212,167,44,0) 70%);"></div>
  <div class="glow breathe" style="width: 420px; height: 420px; left: 30%; bottom: -160px; background: radial-gradient(circle, rgba(125,140,58,0.32), rgba(125,140,58,0) 70%); animation-delay: 4s;"></div>
  <img class="sig" src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="" style="right: 24px; top: 20px; width: min(640px, 44vw); opacity: 0.2;">
  <svg class="ring" width="240" height="240" viewBox="0 0 200 200" style="top: 300px; right: 92px;" aria-hidden="true">
    <defs><path id="ring-path" d="M100,100 m-78,0 a78,78 0 1,1 156,0 a78,78 0 1,1 -156,0"></path></defs>
    <text font-family="Bricolage Grotesque, Helvetica, Arial, sans-serif" font-size="13" font-weight="700" letter-spacing="3.2" fill="#D4A72C"><textPath href="#ring-path">ELEVATE YOUR VISION · AMPLIFY YOUR IMPACT · KMJ CREATIVE SOLUTIONS · </textPath></text>
    <g fill="none" stroke="#D4A72C" stroke-width="1"><circle cx="100" cy="100" r="58"></circle><circle cx="100" cy="100" r="40" stroke-dasharray="3 5"></circle></g>
    <circle cx="100" cy="100" r="7" fill="#A9B83A"></circle>
  </svg>
  <div class="wrap">
    <div class="hero-head">
      <p class="eyebrow-gold r1" data-override-target="home.hero.eyebrow">A solutionist practice · Coaching · Consulting · Creative direction</p>
      <h1 class="disp r2">Get clear on the <span class="cycle serif"><span><i class="foil">business</i><i class="foil">idea</i><i class="foil">offer</i><i class="foil">shift</i><i class="foil">business</i></span></span> you're meant to build.</h1>
      <div class="hero-then r3">
        <p class="serif foil" data-override-target="home.hero.then">Then build it.</p>
        <span class="rule" style="width: 100%;"></span>
      </div>
    </div>
    <div class="hero-grid r4">
      <div class="hero-copy">
        <p class="lead" data-override-target="home.hero.lead">KMJ Creative Solutions is Kevin McCloud Jr.'s practice for founders and leaders who need clarity: on the idea, the offer, and the shift in front of them. Coaching, consulting, and creative direction under one roof.</p>
        <div class="cta-row">
          <a href="/book" class="btn btn-gold">Book a Discovery Call</a>
          <a href="#how" class="btn btn-light">How the work goes</a>
          <span class="dim" style="font-size: 14px;">30 minutes · no fee · no pitch</span>
        </div>
      </div>
      <div class="hero-side">
        <div class="quote-card">
          <p class="serif" data-override-target="home.hero.quote">"We don't just deliver projects. We elevate your entire vision."</p>
          <p class="eyebrow">Kevin McCloud Jr., Founder</p>
        </div>
        <div class="sys-card win" aria-hidden="true">
          <div style="display: flex; align-items: center; gap: 10px;"><span class="dot"></span><span class="small" style="color: #A9B83A;">From the Solutionist System</span></div>
          <div class="ticker serif" style="font-size: 21px; color: #F7F4EE;">
            <div>Your discovery call is confirmed.</div>
            <div>Invoice sent. Reminder set.</div>
            <div>New inquiry from the site. Filed.</div>
            <div>Your discovery call is confirmed.</div>
          </div>
          <div class="bar"><i style="width: 72%; animation-delay: .8s;"></i></div>
        </div>
      </div>
    </div>
  </div>
</section>

<div class="marquee-band" aria-hidden="true">
  <div class="marquee">
    <div>
      <span class="disp">Elevate your vision.</span><svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#5B6A22"></path></svg>
      <span class="disp">Amplify your impact.</span><svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#5B6A22"></path></svg>
      <span class="serif">Coaching · Consulting · Creative direction</span><svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#5B6A22"></path></svg>
    </div>
    <div>
      <span class="disp">Elevate your vision.</span><svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#5B6A22"></path></svg>
      <span class="disp">Amplify your impact.</span><svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#5B6A22"></path></svg>
      <span class="serif">Coaching · Consulting · Creative direction</span><svg width="22" height="22" viewBox="0 0 24 24"><path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#5B6A22"></path></svg>
    </div>
  </div>
</div>

<section class="section" id="doors">
  <div class="wrap">
    <div class="section-head">
      <div>
        <p class="eyebrow">Three doors, one practice</p>
        <h2 class="disp h2" style="max-width: 820px;">Wherever you're stuck, <span class="serif foil-green" style="font-weight: 500;">there's a way in.</span></h2>
      </div>
      <p class="muted" style="max-width: 380px; font-size: 16px;" data-override-target="home.doors.intro">The same work at three depths. Start with a discovery call and we'll tell you which door fits, plainly.</p>
    </div>
    <div class="doors">
      <article class="card">
        <p class="num foil">01</p>
        <p class="eyebrow-gold">Coaching</p>
        <h3 class="disp h3" data-override-target="home.door1.title">Embrace the Shift</h3>
        <p class="dim" data-override-target="home.door1.body">A ninety-day intensive for the founder with a calling and a half-formed idea. Twelve weekly sessions, homework between them, honest accountability. You leave with a launched offer and a rhythm you can keep.</p>
        <a href="/services#coaching" class="link-draw link-gold">The ninety-day frame →</a>
      </article>
      <article class="card">
        <p class="num foil">02</p>
        <p class="eyebrow-gold">Consulting</p>
        <h3 class="disp h3" data-override-target="home.door2.title">Clarity for a business in motion</h3>
        <p class="dim" data-override-target="home.door2.body">For the owner or leader who is already running something and needs fresh thinking: the next idea, where the innovation is, and whether the economics of the offer actually hold. Focused sessions, written notes, a decision you can act on.</p>
        <a href="/services#consulting" class="link-draw link-gold">How a session works →</a>
      </article>
      <article class="card">
        <p class="num foil">03</p>
        <p class="eyebrow-gold">Creative direction</p>
        <h3 class="disp h3" data-override-target="home.door3.title">When the idea needs a face</h3>
        <p class="dim" data-override-target="home.door3.body">Brand, messaging, and the visual voice of what you're building, in service of the first two doors. We make the idea look like itself, so the marketplace recognizes it on sight.</p>
        <a href="/services#creative" class="link-draw link-gold">By project →</a>
      </article>
    </div>
  </div>
</section>

<section class="section manifesto">
  <img class="sig" src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="" style="left: -80px; bottom: -60px; width: min(900px, 70vw); opacity: 0.08;">
  <div class="wrap">
    <p class="eyebrow">A conviction, stated plainly</p>
    <p class="disp" data-override-target="home.manifesto">Most people don't need more <span class="serif" style="font-weight: 500; color: #6B655A;">information.</span> They need a <span class="serif foil-dk" style="font-weight: 500;">witness</span> and a <span class="serif foil-green" style="font-weight: 500;">rhythm.</span></p>
  </div>
</section>

<section class="section" id="how" style="padding-top: 32px;">
  <div class="wrap moves">
    <div class="moves-head">
      <p class="eyebrow">How the work goes</p>
      <h2 class="disp h2-md">From stuck to started, in four moves.</h2>
    </div>
    <div class="moves-grid">
      <div class="move"><p class="disp foil-dk">01</p><h3 class="disp" data-override-target="home.move1.title">Discovery</h3><p class="muted" data-override-target="home.move1.body">Thirty minutes. Who are you, who do you serve, and what is actually in the way. We listen for the calling beneath the question.</p></div>
      <div class="move"><p class="disp foil-dk">02</p><h3 class="disp" data-override-target="home.move2.title">Name the shift</h3><p class="muted" data-override-target="home.move2.body">We pull the vision into focus and say out loud where you're going. Before strategy, before design, the destination gets a name.</p></div>
      <div class="move"><p class="disp foil-dk">03</p><h3 class="disp" data-override-target="home.move3.title">A weekly rhythm</h3><p class="muted" data-override-target="home.move3.body">We meet, you do the work between meetings, and we review what was promised, done, and learned. No drama, no shame, only the steady record of a thing being built.</p></div>
      <div class="move"><p class="disp foil-dk">04</p><h3 class="disp" data-override-target="home.move4.title">Launch, witnessed</h3><p class="muted" data-override-target="home.move4.body">The offer goes into the world. Named, priced, seen. Then a rhythm you can keep without me in the room.</p></div>
    </div>
  </div>
</section>

<section class="section dark proof" id="proof">
  <div class="glow breathe" style="width: 560px; height: 560px; right: 10%; top: -200px; background: radial-gradient(circle, rgba(212,167,44,0.3), rgba(212,167,44,0) 70%);"></div>
  <div class="wrap">
    <div class="proof-grid">
      <div class="proof-copy">
        <p class="eyebrow-gold">The proof</p>
        <h2 class="disp h2" data-override-target="home.proof.title">I built the tool <span class="serif foil" style="font-weight: 500;">I wished my clients had.</span></h2>
        <p data-override-target="home.proof.body">Every founder I sat with needed the same things: a place to hold the plan, the people, the money, and the follow-through. So I built it. The Solutionist System is the byproduct of this practice, and it's what my clients run their businesses on.</p>
        <div class="cta-row"><a href="https://mysolutionist.app" class="btn btn-gold" target="_blank" rel="noopener">See the Solutionist System</a></div>
      </div>
      <div class="proof-mock" aria-hidden="true">
        <div class="win mock">
          <div class="win-bar"><b></b><b></b><b></b><span class="small">mysolutionist.app</span></div>
          <div class="side"><span class="on">Chief</span><span>Bookings</span><span>Money</span><span>Contacts</span><span>Site</span><span>Email</span></div>
          <div class="mock-main">
            <div style="display: flex; align-items: center; gap: 10px;"><span class="dot"></span><span class="small" style="color: #A9B83A;">Chief · on duty</span></div>
            <div class="mock-msg">Two discovery calls booked this week. The website form brought in one of them. Want me to send the prep note?</div>
            <svg viewBox="0 0 320 90" width="100%" height="90" preserveAspectRatio="none" style="display: block;"><path class="trace" d="M0 78 C 30 70, 50 74, 70 58 S 110 52, 130 46 S 170 40, 190 30 S 240 28, 260 18 S 300 12, 320 6" fill="none" stroke="#D4A72C" stroke-width="2.5"></path><path d="M0 90 L0 78 C 30 70, 50 74, 70 58 S 110 52, 130 46 S 170 40, 190 30 S 240 28, 260 18 S 300 12, 320 6 L320 90 Z" fill="rgba(212,167,44,0.08)"></path></svg>
            <div class="mock-bars">
              <div><span class="small">Bookings</span><div class="bar"><i style="width: 80%;"></i></div></div>
              <div><span class="small">Follow-through</span><div class="bar"><i style="width: 64%; animation-delay: .3s;"></i></div></div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="chips">
      <p class="eyebrow-gold">What the practice runs on</p>
      <div><span class="chip">Chief</span><span class="chip">Bookings</span><span class="chip">Invoices</span><span class="chip">Contacts</span><span class="chip">SMS</span><span class="chip">Email</span><span class="chip">Website</span><span class="chip">Insights</span></div>
    </div>
  </div>
</section>

<section class="section" id="kevin">
  <div class="wrap about-lite">
    <div class="about-art">
      <div class="art"><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="Kevin McCloud Jr., founder of KMJ Creative Solutions"></div>
      <svg class="spin" width="120" height="120" viewBox="0 0 100 100" aria-hidden="true"><g fill="none" stroke="#7D8C3A" stroke-width="1.5"><circle cx="50" cy="50" r="46"></circle><path d="M50 4v92M4 50h92M17.5 17.5l65 65M82.5 17.5l-65 65"></path></g><circle cx="50" cy="50" r="6" fill="#D4A72C"></circle></svg>
    </div>
    <div class="about-copy">
      <p class="eyebrow">The solutionist</p>
      <h2 class="disp h2-md">I connect the dots <span class="serif foil-dk" style="font-weight: 500;">for a living.</span></h2>
      <p data-override-target="home.kevin.p1">I spent ten years in pastoral ministry, first as an associate and then as a lead pastor. Across those years a quieter practice grew beside the public one: people would sit across from me with an idea, a calling, a half-formed plan, and we would talk it into shape together. I didn't call it coaching then. I called it the work.</p>
      <p data-override-target="home.kevin.p2">KMJ Creative Solutions is that work with a name. It started in childhood, seeing problems and connecting them to solutions. Today it means sitting with your story, understanding where you are and where you want to be, and building the bridge between the two.</p>
      <div class="signoff"><a href="/about" class="btn btn-line">More about Kevin</a><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="Kevin McCloud Jr."></div>
    </div>
  </div>
</section>

{{PRODUCTS_SECTION}}
<!-- Gallery and testimonials stay off this design. The tokens below keep the
     platform's live-injection path from appending them before </body>.
     {{GALLERY_SECTION}}{{TESTIMONIALS_SECTION}} -->

<section class="cta-band dark olive">
  <img class="sig" src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="" style="right: -40px; top: 40px; width: min(560px, 40vw); opacity: 0.14;">
  <div class="wrap">
    <div style="display: flex; flex-direction: column; gap: 14px;">
      <h2 class="disp h2" data-override-target="home.cta.title">Ready to step out <span class="serif foil" style="font-weight: 500;">and build?</span></h2>
      <p data-override-target="home.cta.body">Tell me where you're stuck. I'll bring the room, the light, and the plan.</p>
    </div>
    <a href="/book" class="btn btn-gold">Book a Discovery Call</a>
  </div>
</section>

</main>
<footer class="footer dark">
  <div class="wrap">
    <div class="footer-top">
      <div class="footer-brand">
        <img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions">
        <p class="serif">Elevate your vision. Amplify your impact.</p>
      </div>
      <nav class="footer-links" aria-label="Footer">
        <a href="/about" class="link-draw">About</a>
        <a href="/services" class="link-draw">Services</a>
        <a href="/contact" class="link-draw">Contact</a>
        <a href="/book" class="link-draw">Book a Discovery Call</a>
      </nav>
    </div>
    <div class="footer-bottom">
      <span>© 2026 KMJ Creative Solutions</span>
      <a href="mailto:{{BUSINESS_EMAIL}}" data-needs-email>{{BUSINESS_EMAIL}}</a>
    </div>
  </div>
</footer>
<script>
(function () {
  var t = document.querySelector('[data-nav-toggle]');
  var l = document.querySelector('[data-nav-links]');
  if (t && l) {
    t.addEventListener('click', function () {
      var open = l.classList.toggle('open');
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  var f = document.querySelector('[data-contact-form]');
  if (f) {
    var note = f.querySelector('[data-form-note]');
    var btn = f.querySelector('button[type="submit"]');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (f.querySelector('[name="website"]').value) { return; }
      var body = {
        name: f.querySelector('[name="name"]').value.trim(),
        email: f.querySelector('[name="email"]').value.trim(),
        message: f.querySelector('[name="message"]').value.trim()
      };
      if (!body.name || !body.email || !body.message) {
        note.textContent = 'Please fill in all three fields.'; note.className = 'form-note err'; return;
      }
      btn.disabled = true; note.textContent = 'Sending…'; note.className = 'form-note';
      fetch('https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/contact-submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j.status !== 'error', j: j }; }); })
        .then(function (res) {
          if (res.ok) { f.reset(); note.textContent = 'Thank you. Your message is in. I will be in touch to set up a conversation.'; note.className = 'form-note ok'; }
          else { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; }
        })
        .catch(function () { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; })
        .then(function () { btn.disabled = false; });
    });
  }
})();
</script>

</body>
</html>
$kmj$,
  site_config = (COALESCE(site_config, '{}'::jsonb)
    || jsonb_build_object(
      'manual_backup', jsonb_build_object(
        'saved_at', now(),
        'html_content', html_content,
        'html_source', site_config->'html_source',
        'generated_pages', site_config->'generated_pages',
        'site_pages', site_config->'site_pages'
      ),
      'html_source', 'manual',
      'site_type', 'multi-page',
      'site_pages', '["home","about","services","contact"]'::jsonb,
      'generated_pages', jsonb_build_object(
      'about', $kmj$<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>About Kevin McCloud Jr. — KMJ Creative Solutions</title>
<meta name="description" content="Ten years in pastoral ministry, a practice in creative counsel, and the Solutionist System built from it.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&amp;family=Cormorant+Garamond:ital,wght@1,500&amp;family=Work+Sans:wght@400;500;600&amp;display=swap">
<style>
/* KMJ Creative Solutions — hand-built site (2026-09-03).
   Source of truth: sites/kmj-creative-solutions/. Built into the
   business_sites row by build.py; served by public_site.py under
   site_config.html_source == "manual". */
:root {
  --ink: #0F0E0B; --ink-2: #14120E; --text: #17150F; --body: #3E3A31; --muted: #6B655A;
  --cream: #F7F4EE; --cream-2: #FFFDF8;
  --gold: #D4A72C; --gold-deep: #B8922E; --gold-light: #F3D97A;
  --green: #7D8C3A; --green-deep: #5B6A22; --green-light: #A9B83A; --green-text: #6E7B2E;
  --gutter: clamp(20px, 5vw, 72px);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--cream); color: var(--text); font-family: 'Work Sans', 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 17px; line-height: 1.6; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
a { color: inherit; text-decoration: none; transition: color .25s ease; }
a:hover { color: var(--green); }
img { max-width: 100%; }
p, h1, h2, h3 { margin: 0; }
.wrap { max-width: 1440px; margin: 0 auto; padding-left: var(--gutter); padding-right: var(--gutter); }
.disp { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; line-height: 0.96; letter-spacing: -0.035em; }
.serif { font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 500; letter-spacing: 0; line-height: 1.15; }
.eyebrow { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--green-text); font-weight: 600; }
.eyebrow-gold { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.small { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 600; }
.muted { color: var(--muted); }
.dim { color: rgba(247,244,238,0.72); }
.lead { font-size: clamp(17px, 1.5vw, 21px); line-height: 1.55; }
.foil { background: linear-gradient(100deg, #8A6A14 0%, #D4A72C 22%, #F3D97A 40%, #C8981F 58%, #F0D46B 76%, #9C7A1A 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-dk { background: linear-gradient(100deg, #7A5C0A 0%, #B8922E 25%, #E0BC4A 45%, #A67F17 65%, #D4A72C 85%, #8A6A14 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-green { background: linear-gradient(100deg, #4A5619 0%, #7D8C3A 30%, #A9B83A 50%, #5B6A22 72%, #8FA32E 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.num { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; font-size: clamp(64px, 7vw, 96px); line-height: 0.8; letter-spacing: -0.05em; }
.btn { display: inline-flex; align-items: center; justify-content: center; min-height: 54px; padding: 0 30px; font-weight: 600; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; text-align: center; transition: background-color .25s ease, color .25s ease, border-color .25s ease, transform .25s ease; cursor: pointer; border: 0; font-family: inherit; }
.btn:hover { transform: translateY(-2px); }
.btn-gold { background: var(--gold); color: var(--ink); } .btn-gold:hover { background: var(--green-light); color: var(--ink); }
.btn-ink { background: var(--ink); color: var(--cream); } .btn-ink:hover { background: var(--green-deep); color: var(--cream); }
.btn-line { border: 2px solid var(--text); color: var(--text); background: transparent; } .btn-line:hover { border-color: var(--green); color: var(--green-deep); }
.btn-light { border: 2px solid rgba(247,244,238,0.5); color: var(--cream); background: transparent; } .btn-light:hover { border-color: var(--green-light); color: var(--green-light); }
.link-draw { position: relative; display: inline-block; }
.link-draw::after { content: ""; position: absolute; left: 0; bottom: -4px; height: 2px; width: 100%; background: currentColor; transform: scaleX(0); transform-origin: left; transition: transform .35s var(--ease); }
.link-draw:hover::after { transform: scaleX(1); }
.link-gold { color: var(--green-light); font-weight: 600; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }

/* dark bands */
.dark { position: relative; background: var(--ink); color: var(--cream); }
.dark::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: 0.07; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23n)' opacity='0.8'/></svg>"); }
.dark > * { position: relative; z-index: 1; }
.olive { background: var(--green-deep); }
.glow { position: absolute; border-radius: 50%; pointer-events: none; z-index: 0; }
.sig { position: absolute; pointer-events: none; z-index: 0; }

/* nav */
.nav { background: var(--ink); color: var(--cream); }
.nav .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-top: 16px; padding-bottom: 16px; }
.nav-logo img { height: 52px; width: auto; display: block; }
.nav-links { display: flex; align-items: center; gap: 32px; font-size: 14px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
.nav-links a { color: var(--cream); }
.nav-links .btn { min-height: 46px; padding: 0 22px; }
.nav-toggle { display: none; background: none; border: 0; color: var(--cream); width: 44px; height: 44px; cursor: pointer; padding: 0; }
.nav-toggle svg { display: block; margin: 0 auto; }

/* hero */
.hero { overflow: hidden; }
.hero .wrap { display: flex; flex-direction: column; gap: 36px; padding-top: clamp(56px, 7vw, 96px); }
.hero-head { display: flex; flex-direction: column; gap: 28px; max-width: 1180px; }
.hero h1 { font-size: clamp(48px, 8.6vw, 124px); color: var(--cream); }
.hero-then { display: flex; flex-direction: column; gap: 14px; align-self: flex-start; }
.hero-then .serif { font-size: clamp(34px, 4.4vw, 64px); }
.rule { display: block; height: 4px; background: linear-gradient(90deg, #D4A72C, #F3D97A, #D4A72C); transform-origin: left; transform: scaleX(0); animation: draw 1.1s var(--ease) .9s forwards; }
.hero-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-bottom: 72px; }
.hero-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 28px; }
.hero-copy .lead { max-width: 640px; color: rgba(247,244,238,0.8); }
.cta-row { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -132px; }
.quote-card { display: flex; flex-direction: column; gap: 12px; padding: 28px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.quote-card .serif { font-size: clamp(22px, 2vw, 30px); }
.sys-card { position: absolute; right: -36px; top: -150px; width: 300px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; z-index: 2; border-top: 3px solid var(--gold); animation: bob 6s ease-in-out infinite; }
.win { background: var(--ink-2); border: 1px solid rgba(247,244,238,0.14); box-shadow: 0 40px 80px rgba(0,0,0,0.45); }
.ring { position: absolute; z-index: 0; animation: spin 60s linear infinite; transform-origin: center; }
.spin { animation: spin 28s linear infinite; transform-origin: center; }
.cycle { display: inline-block; height: 1em; overflow: hidden; vertical-align: bottom; font-weight: 500; letter-spacing: 0; }
.cycle > span { display: block; animation: cycle 12s var(--ease) infinite; }
.cycle > span > i { display: block; height: 1em; line-height: 1; font-style: italic; }
.dot { position: relative; width: 10px; height: 10px; border-radius: 50%; background: var(--green-light); flex: none; }
.dot::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: var(--green-light); animation: ping 1.8s cubic-bezier(0, 0, 0.2, 1) infinite; }
.ticker { height: 1.5em; overflow: hidden; }
.ticker > div { animation: ticker 12s var(--ease) infinite; }
.bar { height: 8px; background: rgba(247,244,238,0.1); overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform-origin: left; animation: draw 1.4s var(--ease) forwards; }
.r1, .r2, .r3, .r4 { opacity: 0; animation: rise .9s var(--ease) forwards; }
.r1 { animation-delay: .1s; } .r2 { animation-delay: .3s; } .r3 { animation-delay: .5s; } .r4 { animation-delay: .7s; }
.breathe { animation: breathe 9s ease-in-out infinite; }

/* marquee */
.marquee-band { background: var(--gold); color: var(--ink); padding: 22px 0; overflow: hidden; }
.marquee { display: flex; width: max-content; gap: 48px; align-items: center; animation: marquee 32s linear infinite; }
.marquee:hover { animation-play-state: paused; }
.marquee > div { display: flex; align-items: center; gap: 48px; padding-right: 48px; }
.marquee .disp, .marquee .serif { font-size: clamp(26px, 2.8vw, 40px); white-space: nowrap; }

/* sections */
.section { padding-top: clamp(64px, 8vw, 112px); padding-bottom: clamp(64px, 8vw, 112px); }
.section-head { display: flex; justify-content: space-between; align-items: end; gap: 40px; flex-wrap: wrap; }
.section-head > div { display: flex; flex-direction: column; gap: 16px; }
.h2 { font-size: clamp(40px, 5vw, 72px); }
.h2-md { font-size: clamp(36px, 4.2vw, 60px); }
.h3 { font-size: clamp(28px, 2.6vw, 38px); }
.doors { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; margin-top: 56px; }
.card { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 20px; padding: 36px 32px 44px; background: var(--ink); color: var(--cream); transition: transform .35s var(--ease); }
.card::before { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform: scaleX(0); transform-origin: left; transition: transform .45s var(--ease); }
.card:hover { transform: translateY(-6px); } .card:hover::before { transform: scaleX(1); }
.card .link-gold { margin-top: auto; align-self: flex-start; }
.manifesto { position: relative; overflow: hidden; }
.manifesto .wrap { display: flex; flex-direction: column; gap: 28px; }
.manifesto .disp { font-size: clamp(40px, 6.4vw, 92px); max-width: 1240px; }
.moves { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.moves-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.moves-grid { grid-column: 6 / span 7; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 44px 40px; }
.move { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green); }
.move .disp:first-child { font-size: 26px; }
.move h3 { font-size: 32px; }
.proof { overflow: hidden; }
.proof .wrap { display: flex; flex-direction: column; gap: 64px; }
.proof-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; }
.proof-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 24px; }
.proof-copy .h2 { color: var(--cream); font-size: clamp(40px, 4.7vw, 68px); }
.proof-copy p { color: rgba(247,244,238,0.8); max-width: 560px; font-size: 18px; }
.proof-mock { grid-column: 8 / span 5; }
.mock { display: grid; grid-template-columns: 132px minmax(0, 1fr); overflow: hidden; transform: rotate(-1.5deg); }
.win-bar { grid-column: span 2; display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid rgba(247,244,238,0.1); }
.win-bar b { width: 10px; height: 10px; border-radius: 50%; background: rgba(247,244,238,0.18); }
.win-bar .small { color: rgba(247,244,238,0.45); margin-left: 8px; }
.side { padding: 12px 8px; border-right: 1px solid rgba(247,244,238,0.1); display: flex; flex-direction: column; gap: 2px; }
.side span { display: block; padding: 8px 10px; color: rgba(247,244,238,0.6); font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.side span.on { background: rgba(212,167,44,0.14); color: var(--gold); }
.mock-main { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.mock-msg { padding: 12px 14px; background: rgba(247,244,238,0.06); border-left: 3px solid var(--gold); font-size: 14px; line-height: 1.5; color: rgba(247,244,238,0.9); }
.trace { stroke-dasharray: 900; stroke-dashoffset: 900; animation: trace 2.6s var(--ease) .6s forwards; }
.mock-bars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.mock-bars > div { display: flex; flex-direction: column; gap: 6px; }
.mock-bars .small { color: rgba(247,244,238,0.5); }
.chips { display: flex; flex-direction: column; gap: 18px; padding-top: 40px; border-top: 1px solid rgba(247,244,238,0.14); }
.chips > div { display: flex; flex-wrap: wrap; gap: 10px; }
.chip { display: inline-flex; align-items: center; height: 40px; padding: 0 18px; border: 1px solid rgba(247,244,238,0.18); background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); font-size: 13px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; animation: chain 9.6s ease-in-out infinite; }
.chip:nth-child(1) { animation-delay: 0s; } .chip:nth-child(2) { animation-delay: 1.2s; } .chip:nth-child(3) { animation-delay: 2.4s; } .chip:nth-child(4) { animation-delay: 3.6s; } .chip:nth-child(5) { animation-delay: 4.8s; } .chip:nth-child(6) { animation-delay: 6s; } .chip:nth-child(7) { animation-delay: 7.2s; } .chip:nth-child(8) { animation-delay: 8.4s; }
.about-lite { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: center; }
.about-art { grid-column: span 5; position: relative; }
.about-art::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.art { position: relative; z-index: 1; height: clamp(320px, 36vw, 520px); background: linear-gradient(160deg, #5B6A22 0%, #8FA32E 45%, #D4A72C 100%); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.art img { width: 70%; height: auto; opacity: 0.9; }
.art .photo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 1; }
.about-art .spin { position: absolute; right: -40px; bottom: -40px; z-index: 2; }
.about-copy { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; }
.about-copy p { font-size: 18px; color: var(--body); }
.signoff { display: flex; align-items: center; flex-wrap: wrap; gap: 28px; margin-top: 8px; }
.signoff img { height: 64px; width: auto; }
.cta-band { position: relative; overflow: hidden; clip-path: polygon(0 56px, 100% 0, 100% 100%, 0 100%); padding-top: clamp(100px, 10vw, 136px); padding-bottom: clamp(64px, 6vw, 88px); }
.cta-band .wrap { display: flex; align-items: center; justify-content: space-between; gap: 40px; flex-wrap: wrap; }
.cta-band .h2 { color: var(--cream); }
.cta-band p { font-size: 19px; font-weight: 500; color: rgba(247,244,238,0.85); }
.cta-band .btn { min-height: 64px; padding: 0 40px; font-size: 15px; }

/* inner pages */
.page-hero { overflow: hidden; }
.page-hero .wrap { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-top: clamp(56px, 7vw, 96px); padding-bottom: clamp(56px, 6vw, 80px); }
.page-hero h1 { font-size: clamp(44px, 7.2vw, 104px); color: var(--cream); }
.page-hero .rule { width: 220px; }
.page-hero .lead { color: rgba(247,244,238,0.8); max-width: 640px; }
.page-hero-copy { grid-column: span 8; display: flex; flex-direction: column; gap: 24px; }
.page-hero-side { grid-column: 10 / span 3; }
.gold-card { display: flex; flex-direction: column; gap: 10px; padding: 28px; background: var(--gold); color: var(--ink); }
.gold-card .eyebrow { color: var(--ink); }
.gold-card .disp { font-size: 32px; }
.gold-card p { font-size: 15px; font-weight: 500; }
.gold-card .btn { margin-top: 10px; align-self: flex-start; }
.offer { padding: 56px 0; border-top: 3px solid var(--green); display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.offer-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.offer-head h2 { font-size: clamp(36px, 3.6vw, 52px); }
.offer-body { grid-column: span 5; display: flex; flex-direction: column; gap: 20px; }
.offer-body > p { font-size: 18px; color: var(--body); }
.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 24px; padding-top: 6px; }
.facts > div { display: flex; flex-direction: column; gap: 4px; }
.facts .eyebrow { color: var(--muted); }
.offer-price { grid-column: span 3; }
.offer-price .card { padding: 28px 28px 34px; gap: 16px; }
.offer-price .disp { font-size: clamp(26px, 2.4vw, 36px); color: var(--cream); }
.offer-price .dim { font-size: 14px; }
.offer-price .btn { align-self: flex-start; }
.who { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.who-head { grid-column: span 6; display: flex; flex-direction: column; gap: 16px; }
.who-head .h2 { color: var(--cream); font-size: clamp(36px, 4vw, 58px); }
.who-body { grid-column: 8 / span 5; display: flex; flex-direction: column; gap: 18px; font-size: 18px; font-weight: 500; color: rgba(247,244,238,0.88); }
.about-hero .page-hero-copy { grid-column: span 7; padding-bottom: 40px; }
.about-hero .page-hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -96px; }
.about-hero .page-hero-side::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.about-hero .art { height: clamp(320px, 33vw, 480px); border: 6px solid var(--gold); }
.about-hero .spin { position: absolute; left: -48px; top: -48px; z-index: 2; }
.story { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; padding-top: 160px; }
.stats { grid-column: span 3; display: flex; flex-direction: column; gap: 32px; }
.stat { display: flex; flex-direction: column; gap: 8px; padding-top: 18px; border-top: 3px solid var(--green); }
.stat .num { font-size: clamp(56px, 6vw, 88px); }
.stat span:last-child { font-size: 14px; color: var(--muted); }
.story-copy { grid-column: 5 / span 7; display: flex; flex-direction: column; gap: 24px; font-size: 19px; color: var(--body); line-height: 1.7; }
.story-copy h2 { font-size: clamp(32px, 3vw, 44px); color: var(--text); }
.story-copy h2 + p { margin-top: 0; }
.story-copy h2:not(:first-child) { margin-top: 16px; }
.values { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 40px; }
.values-head { grid-column: span 4; display: flex; flex-direction: column; gap: 10px; }
.values-head .h2 { color: var(--cream); font-size: clamp(36px, 3.9vw, 56px); }
.value { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green-light); }
.value .disp { font-size: 34px; color: var(--gold); }
.question { position: relative; overflow: hidden; text-align: center; }
.question .wrap { display: flex; flex-direction: column; gap: 24px; align-items: center; }
.question .serif { font-size: clamp(28px, 3.2vw, 46px); max-width: 980px; }
.question .spin { position: absolute; left: -120px; top: 50%; margin-top: -180px; opacity: 0.35; }
.contact-hero .wrap { align-items: start; }
.contact-copy { grid-column: span 5; display: flex; flex-direction: column; gap: 40px; }
.contact-copy > div:first-child { display: flex; flex-direction: column; gap: 22px; }
.contact-copy h1 { font-size: clamp(44px, 6.1vw, 88px); }
.contact-email { display: flex; flex-direction: column; gap: 6px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.2); }
.contact-email a { font-size: 18px; color: var(--cream); }
.contact-email a:hover { color: var(--gold); }
.contact-email .dim { font-size: 14px; }
.form-card { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; padding: 40px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.form-card h2 { font-size: clamp(28px, 2.6vw, 38px); }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 12px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
.field input, .field textarea { width: 100%; min-height: 54px; border: 2px solid var(--text); background: var(--cream-2); padding: 12px 16px; font: inherit; font-size: 16px; color: var(--text); border-radius: 0; }
.field textarea { min-height: 160px; resize: vertical; }
.field input:focus, .field textarea:focus { outline: none; border-color: var(--gold); }
.form-note { font-size: 14px; color: var(--muted); }
.form-note.ok { color: var(--green-deep); font-weight: 600; }
.form-note.err { color: #A33; font-weight: 600; }
.hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }

/* footer */
.footer { padding-top: 64px; padding-bottom: 40px; }
.footer-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 40px; flex-wrap: wrap; }
.footer-brand { display: flex; flex-direction: column; gap: 18px; }
.footer-brand img { height: 84px; width: auto; }
.footer-brand .serif { color: var(--gold); font-size: 26px; }
.footer-links { display: flex; flex-wrap: wrap; gap: 32px; font-size: 13px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-links a { color: rgba(247,244,238,0.85); }
.footer-links a:last-child { color: var(--gold); }
.footer-bottom { margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.16); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; font-size: 13px; color: rgba(247,244,238,0.55); }
.footer-bottom a { color: rgba(247,244,238,0.75); }

@keyframes rise { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
@keyframes draw { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes bob { 0%, 100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-14px) rotate(-2deg); } }
@keyframes ping { 0% { transform: scale(1); opacity: .9; } 100% { transform: scale(2.6); opacity: 0; } }
@keyframes chain { 0%, 100% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } 12% { background: #D4A72C; color: #0F0E0B; border-color: #D4A72C; } 24% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } }
@keyframes trace { to { stroke-dashoffset: 0; } }
@keyframes cycle { 0%, 18% { transform: translateY(0); } 25%, 43% { transform: translateY(-20%); } 50%, 68% { transform: translateY(-40%); } 75%, 93% { transform: translateY(-60%); } 100% { transform: translateY(-80%); } }
@keyframes ticker { 0%, 30% { transform: translateY(0); } 33%, 63% { transform: translateY(-100%); } 66%, 96% { transform: translateY(-200%); } 100% { transform: translateY(-300%); } }
@keyframes breathe { 0%, 100% { opacity: .5; transform: scale(1); } 50% { opacity: .85; transform: scale(1.08); } }

@media (max-width: 1100px) {
  .hero-copy { grid-column: span 12; }
  .hero-side { grid-column: span 12; margin-bottom: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
  .sys-card { position: static; width: auto; animation: none; }
  .hero-grid { padding-bottom: 56px; }
  .ring { display: none; }
  .doors { grid-template-columns: 1fr; }
  .moves-head, .moves-grid { grid-column: span 12; }
  .proof-copy, .proof-mock { grid-column: span 12; }
  .mock { transform: none; }
  .about-art, .about-copy { grid-column: span 12; }
  .page-hero-copy { grid-column: span 12; }
  .page-hero-side { grid-column: span 12; }
  .about-hero .page-hero-copy, .about-hero .page-hero-side { grid-column: span 12; margin-bottom: 0; }
  .about-hero .page-hero-side { padding-bottom: 24px; }
  .story { padding-top: 64px; }
  .stats, .story-copy { grid-column: span 12; }
  .stats { flex-direction: row; flex-wrap: wrap; }
  .stats .stat { flex: 1 1 200px; }
  .values { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .values-head { grid-column: span 2; }
  .offer-head, .offer-body, .offer-price { grid-column: span 12; }
  .who-head, .who-body { grid-column: span 12; }
  .contact-copy, .form-card { grid-column: span 12; }
}
@media (max-width: 720px) {
  body { font-size: 16px; }
  .nav-toggle { display: block; }
  .nav-links { display: none; position: absolute; left: 0; right: 0; top: 100%; flex-direction: column; align-items: stretch; gap: 0; background: var(--ink); padding: 8px var(--gutter) 20px; z-index: 20; border-top: 1px solid rgba(247,244,238,0.12); }
  .nav-links.open { display: flex; }
  .nav-links a { padding: 14px 0; border-bottom: 1px solid rgba(247,244,238,0.08); }
  .nav-links .btn { margin-top: 12px; }
  .nav { position: relative; }
  .hero-side { grid-template-columns: 1fr; }
  .sig { display: none; }
  .moves-grid { grid-template-columns: 1fr; }
  .mock { grid-template-columns: 1fr; }
  .side { flex-direction: row; flex-wrap: wrap; border-right: 0; border-bottom: 1px solid rgba(247,244,238,0.1); }
  .values { grid-template-columns: 1fr; }
  .values-head { grid-column: span 1; }
  .facts, .mock-bars { grid-template-columns: 1fr; }
  .form-card { padding: 24px; }
  .question .spin { display: none; }
  .cta-band { clip-path: polygon(0 28px, 100% 0, 100% 100%, 0 100%); }
  .move h3 { font-size: 26px; }
}
@media (prefers-reduced-motion: reduce) {
  .r1, .r2, .r3, .r4 { opacity: 1; animation: none; }
  .rule, .bar i { transform: none; animation: none; }
  .ring, .spin, .marquee, .sys-card, .breathe, .dot::after, .chip, .ticker > div, .cycle > span { animation: none; }
  .trace { stroke-dashoffset: 0; animation: none; }
}

</style>
</head>
<body>
<header class="nav">
  <div class="wrap">
    <a class="nav-logo" href="/" aria-label="KMJ Creative Solutions home"><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions"></a>
    <button class="nav-toggle" type="button" aria-label="Open menu" aria-expanded="false" data-nav-toggle>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>
    </button>
    <nav class="nav-links sxm-header-pagenav" data-nav-links aria-label="Primary">
      <a href="/about" class="link-draw">About</a>
      <a href="/services" class="link-draw">Services</a>
      <a href="/contact" class="link-draw">Contact</a>
      <a href="/book" class="btn btn-gold">Book a Discovery Call</a>
    </nav>
  </div>
</header>

<main>
<section class="page-hero about-hero dark">
  <img class="sig" src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="" style="right: 40px; top: 24px; width: min(620px, 42vw); opacity: 0.16;">
  <div class="wrap">
    <div class="page-hero-copy">
      <p class="eyebrow-gold r1">About Kevin McCloud Jr.</p>
      <h1 class="disp r2">The work began long before <span class="serif foil" style="font-weight: 500;">it had a name.</span></h1>
      <span class="rule"></span>
      <p class="lead r3" data-override-target="about.hero.lead">Founder of KMJ Creative Solutions. Ten years in pastoral ministry. Builder of the Solutionist System. A solutionist for people who need clarity.</p>
    </div>
    <div class="page-hero-side r4">
      <div class="art"><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="Kevin McCloud Jr., founder of KMJ Creative Solutions"></div>
      <svg class="spin" width="110" height="110" viewBox="0 0 100 100" aria-hidden="true"><g fill="none" stroke="#A9B83A" stroke-width="1.5"><circle cx="50" cy="50" r="46"></circle><path d="M50 4v92M4 50h92M17.5 17.5l65 65M82.5 17.5l-65 65"></path></g><circle cx="50" cy="50" r="6" fill="#D4A72C"></circle></svg>
    </div>
  </div>
</section>

<section class="section" style="padding-top: 0;">
  <div class="wrap story">
    <div class="stats">
      <div class="stat"><span class="num foil-dk">10</span><span>years in pastoral ministry, associate then lead pastor</span></div>
      <div class="stat"><span class="num foil-dk">90</span><span>days in the Embrace the Shift frame</span></div>
      <div class="stat"><span class="num foil-dk">1</span><span>system built from the practice, the Solutionist System</span></div>
    </div>
    <div class="story-copy">
      <h2 class="disp">A pastoral beginning</h2>
      <p data-override-target="about.story.p1">I have spent the last decade in pastoral ministry, first as an associate and then as a lead pastor. Across those years a quieter practice grew alongside the public one. People would sit across from me with an idea, a calling, a half-formed plan, and we would talk it into shape together. I did not call it coaching then. I simply called it the work.</p>
      <p data-override-target="about.story.p2">What I learned is that purpose-driven people rarely arrive needing more information. They arrive needing a witness: someone who will hold their idea with care, ask the right question at the right moment, and walk with them through the disciplined weeks it takes to move from stuck to launched.</p>
      <h2 class="disp">From connecting dots to a practice</h2>
      <p data-override-target="about.story.p3">It started in childhood. I saw problems and connected them to solutions. It is simply how I am wired. KMJ Creative Solutions is that wiring with a name: a solutionist practice for people who need clarity and understanding, whether they are discovering a business for the first time or rethinking one they already run.</p>
      <p data-override-target="about.story.p4">The practice is moving with me. What began as creative work, the flyers and the campaigns, has grown into coaching and consulting on creativity, innovation, ideas, and the economics of what people build. Embrace the Shift is the name I give that movement, for my clients and for myself.</p>
      <h2 class="disp">The byproduct</h2>
      <p data-override-target="about.story.p5">Every founder I sat with needed the same things: a place to hold the plan, the people, the money, and the follow-through. So I built it. The Solutionist System is what came out of this practice, and it is what my clients run their businesses on. The form has changed. The posture has not.</p>
    </div>
  </div>
</section>

<section class="section dark">
  <div class="wrap values">
    <div class="values-head">
      <p class="eyebrow-gold">What holds the practice</p>
      <h2 class="disp h2">Four words I return to.</h2>
    </div>
    <div class="value"><span class="disp">Trust</span><span class="dim" data-override-target="about.value.trust">Earned in the first conversation, kept by every conversation that follows.</span></div>
    <div class="value"><span class="disp">Calling</span><span class="dim" data-override-target="about.value.calling">Profit is good. Purpose is better. The strongest businesses honor both.</span></div>
    <div class="value"><span class="disp">Discipline</span><span class="dim" data-override-target="about.value.discipline">Vision without a weekly rhythm is wishful thinking. We meet, we work, we ship.</span></div>
    <div class="value"><span class="disp">Vision</span><span class="dim" data-override-target="about.value.vision">The clearer you see the future, the easier the present becomes to walk.</span></div>
  </div>
</section>

<section class="section question">
  <svg class="spin" width="360" height="360" viewBox="0 0 100 100" aria-hidden="true"><g fill="none" stroke="#D4A72C" stroke-width="0.8"><circle cx="50" cy="50" r="46"></circle><circle cx="50" cy="50" r="30" stroke-dasharray="3 5"></circle><path d="M50 4v92M4 50h92M17.5 17.5l65 65M82.5 17.5l-65 65"></path></g></svg>
  <div class="wrap">
    <p class="serif" data-override-target="about.question">"Tell me about the version of this business you would still be proud of in ten years, and what is keeping you, today, from walking toward it."</p>
    <p class="eyebrow">The one question every first conversation begins with</p>
    <a href="/book" class="btn btn-ink" style="margin-top: 12px;">Book a Discovery Call</a>
  </div>
</section>

</main>
<footer class="footer dark">
  <div class="wrap">
    <div class="footer-top">
      <div class="footer-brand">
        <img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions">
        <p class="serif">Elevate your vision. Amplify your impact.</p>
      </div>
      <nav class="footer-links" aria-label="Footer">
        <a href="/about" class="link-draw">About</a>
        <a href="/services" class="link-draw">Services</a>
        <a href="/contact" class="link-draw">Contact</a>
        <a href="/book" class="link-draw">Book a Discovery Call</a>
      </nav>
    </div>
    <div class="footer-bottom">
      <span>© 2026 KMJ Creative Solutions</span>
      <a href="mailto:{{BUSINESS_EMAIL}}" data-needs-email>{{BUSINESS_EMAIL}}</a>
    </div>
  </div>
</footer>
<script>
(function () {
  var t = document.querySelector('[data-nav-toggle]');
  var l = document.querySelector('[data-nav-links]');
  if (t && l) {
    t.addEventListener('click', function () {
      var open = l.classList.toggle('open');
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  var f = document.querySelector('[data-contact-form]');
  if (f) {
    var note = f.querySelector('[data-form-note]');
    var btn = f.querySelector('button[type="submit"]');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (f.querySelector('[name="website"]').value) { return; }
      var body = {
        name: f.querySelector('[name="name"]').value.trim(),
        email: f.querySelector('[name="email"]').value.trim(),
        message: f.querySelector('[name="message"]').value.trim()
      };
      if (!body.name || !body.email || !body.message) {
        note.textContent = 'Please fill in all three fields.'; note.className = 'form-note err'; return;
      }
      btn.disabled = true; note.textContent = 'Sending…'; note.className = 'form-note';
      fetch('https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/contact-submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j.status !== 'error', j: j }; }); })
        .then(function (res) {
          if (res.ok) { f.reset(); note.textContent = 'Thank you. Your message is in. I will be in touch to set up a conversation.'; note.className = 'form-note ok'; }
          else { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; }
        })
        .catch(function () { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; })
        .then(function () { btn.disabled = false; });
    });
  }
})();
</script>

</body>
</html>
$kmj$,
      'services', $kmj$<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Services — KMJ Creative Solutions</title>
<meta name="description" content="Embrace the Shift, the ninety-day intensive. Clarity Sessions for a business in motion. Creative direction when the idea needs a face.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&amp;family=Cormorant+Garamond:ital,wght@1,500&amp;family=Work+Sans:wght@400;500;600&amp;display=swap">
<style>
/* KMJ Creative Solutions — hand-built site (2026-09-03).
   Source of truth: sites/kmj-creative-solutions/. Built into the
   business_sites row by build.py; served by public_site.py under
   site_config.html_source == "manual". */
:root {
  --ink: #0F0E0B; --ink-2: #14120E; --text: #17150F; --body: #3E3A31; --muted: #6B655A;
  --cream: #F7F4EE; --cream-2: #FFFDF8;
  --gold: #D4A72C; --gold-deep: #B8922E; --gold-light: #F3D97A;
  --green: #7D8C3A; --green-deep: #5B6A22; --green-light: #A9B83A; --green-text: #6E7B2E;
  --gutter: clamp(20px, 5vw, 72px);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--cream); color: var(--text); font-family: 'Work Sans', 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 17px; line-height: 1.6; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
a { color: inherit; text-decoration: none; transition: color .25s ease; }
a:hover { color: var(--green); }
img { max-width: 100%; }
p, h1, h2, h3 { margin: 0; }
.wrap { max-width: 1440px; margin: 0 auto; padding-left: var(--gutter); padding-right: var(--gutter); }
.disp { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; line-height: 0.96; letter-spacing: -0.035em; }
.serif { font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 500; letter-spacing: 0; line-height: 1.15; }
.eyebrow { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--green-text); font-weight: 600; }
.eyebrow-gold { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.small { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 600; }
.muted { color: var(--muted); }
.dim { color: rgba(247,244,238,0.72); }
.lead { font-size: clamp(17px, 1.5vw, 21px); line-height: 1.55; }
.foil { background: linear-gradient(100deg, #8A6A14 0%, #D4A72C 22%, #F3D97A 40%, #C8981F 58%, #F0D46B 76%, #9C7A1A 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-dk { background: linear-gradient(100deg, #7A5C0A 0%, #B8922E 25%, #E0BC4A 45%, #A67F17 65%, #D4A72C 85%, #8A6A14 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-green { background: linear-gradient(100deg, #4A5619 0%, #7D8C3A 30%, #A9B83A 50%, #5B6A22 72%, #8FA32E 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.num { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; font-size: clamp(64px, 7vw, 96px); line-height: 0.8; letter-spacing: -0.05em; }
.btn { display: inline-flex; align-items: center; justify-content: center; min-height: 54px; padding: 0 30px; font-weight: 600; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; text-align: center; transition: background-color .25s ease, color .25s ease, border-color .25s ease, transform .25s ease; cursor: pointer; border: 0; font-family: inherit; }
.btn:hover { transform: translateY(-2px); }
.btn-gold { background: var(--gold); color: var(--ink); } .btn-gold:hover { background: var(--green-light); color: var(--ink); }
.btn-ink { background: var(--ink); color: var(--cream); } .btn-ink:hover { background: var(--green-deep); color: var(--cream); }
.btn-line { border: 2px solid var(--text); color: var(--text); background: transparent; } .btn-line:hover { border-color: var(--green); color: var(--green-deep); }
.btn-light { border: 2px solid rgba(247,244,238,0.5); color: var(--cream); background: transparent; } .btn-light:hover { border-color: var(--green-light); color: var(--green-light); }
.link-draw { position: relative; display: inline-block; }
.link-draw::after { content: ""; position: absolute; left: 0; bottom: -4px; height: 2px; width: 100%; background: currentColor; transform: scaleX(0); transform-origin: left; transition: transform .35s var(--ease); }
.link-draw:hover::after { transform: scaleX(1); }
.link-gold { color: var(--green-light); font-weight: 600; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }

/* dark bands */
.dark { position: relative; background: var(--ink); color: var(--cream); }
.dark::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: 0.07; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23n)' opacity='0.8'/></svg>"); }
.dark > * { position: relative; z-index: 1; }
.olive { background: var(--green-deep); }
.glow { position: absolute; border-radius: 50%; pointer-events: none; z-index: 0; }
.sig { position: absolute; pointer-events: none; z-index: 0; }

/* nav */
.nav { background: var(--ink); color: var(--cream); }
.nav .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-top: 16px; padding-bottom: 16px; }
.nav-logo img { height: 52px; width: auto; display: block; }
.nav-links { display: flex; align-items: center; gap: 32px; font-size: 14px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
.nav-links a { color: var(--cream); }
.nav-links .btn { min-height: 46px; padding: 0 22px; }
.nav-toggle { display: none; background: none; border: 0; color: var(--cream); width: 44px; height: 44px; cursor: pointer; padding: 0; }
.nav-toggle svg { display: block; margin: 0 auto; }

/* hero */
.hero { overflow: hidden; }
.hero .wrap { display: flex; flex-direction: column; gap: 36px; padding-top: clamp(56px, 7vw, 96px); }
.hero-head { display: flex; flex-direction: column; gap: 28px; max-width: 1180px; }
.hero h1 { font-size: clamp(48px, 8.6vw, 124px); color: var(--cream); }
.hero-then { display: flex; flex-direction: column; gap: 14px; align-self: flex-start; }
.hero-then .serif { font-size: clamp(34px, 4.4vw, 64px); }
.rule { display: block; height: 4px; background: linear-gradient(90deg, #D4A72C, #F3D97A, #D4A72C); transform-origin: left; transform: scaleX(0); animation: draw 1.1s var(--ease) .9s forwards; }
.hero-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-bottom: 72px; }
.hero-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 28px; }
.hero-copy .lead { max-width: 640px; color: rgba(247,244,238,0.8); }
.cta-row { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -132px; }
.quote-card { display: flex; flex-direction: column; gap: 12px; padding: 28px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.quote-card .serif { font-size: clamp(22px, 2vw, 30px); }
.sys-card { position: absolute; right: -36px; top: -150px; width: 300px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; z-index: 2; border-top: 3px solid var(--gold); animation: bob 6s ease-in-out infinite; }
.win { background: var(--ink-2); border: 1px solid rgba(247,244,238,0.14); box-shadow: 0 40px 80px rgba(0,0,0,0.45); }
.ring { position: absolute; z-index: 0; animation: spin 60s linear infinite; transform-origin: center; }
.spin { animation: spin 28s linear infinite; transform-origin: center; }
.cycle { display: inline-block; height: 1em; overflow: hidden; vertical-align: bottom; font-weight: 500; letter-spacing: 0; }
.cycle > span { display: block; animation: cycle 12s var(--ease) infinite; }
.cycle > span > i { display: block; height: 1em; line-height: 1; font-style: italic; }
.dot { position: relative; width: 10px; height: 10px; border-radius: 50%; background: var(--green-light); flex: none; }
.dot::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: var(--green-light); animation: ping 1.8s cubic-bezier(0, 0, 0.2, 1) infinite; }
.ticker { height: 1.5em; overflow: hidden; }
.ticker > div { animation: ticker 12s var(--ease) infinite; }
.bar { height: 8px; background: rgba(247,244,238,0.1); overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform-origin: left; animation: draw 1.4s var(--ease) forwards; }
.r1, .r2, .r3, .r4 { opacity: 0; animation: rise .9s var(--ease) forwards; }
.r1 { animation-delay: .1s; } .r2 { animation-delay: .3s; } .r3 { animation-delay: .5s; } .r4 { animation-delay: .7s; }
.breathe { animation: breathe 9s ease-in-out infinite; }

/* marquee */
.marquee-band { background: var(--gold); color: var(--ink); padding: 22px 0; overflow: hidden; }
.marquee { display: flex; width: max-content; gap: 48px; align-items: center; animation: marquee 32s linear infinite; }
.marquee:hover { animation-play-state: paused; }
.marquee > div { display: flex; align-items: center; gap: 48px; padding-right: 48px; }
.marquee .disp, .marquee .serif { font-size: clamp(26px, 2.8vw, 40px); white-space: nowrap; }

/* sections */
.section { padding-top: clamp(64px, 8vw, 112px); padding-bottom: clamp(64px, 8vw, 112px); }
.section-head { display: flex; justify-content: space-between; align-items: end; gap: 40px; flex-wrap: wrap; }
.section-head > div { display: flex; flex-direction: column; gap: 16px; }
.h2 { font-size: clamp(40px, 5vw, 72px); }
.h2-md { font-size: clamp(36px, 4.2vw, 60px); }
.h3 { font-size: clamp(28px, 2.6vw, 38px); }
.doors { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; margin-top: 56px; }
.card { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 20px; padding: 36px 32px 44px; background: var(--ink); color: var(--cream); transition: transform .35s var(--ease); }
.card::before { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform: scaleX(0); transform-origin: left; transition: transform .45s var(--ease); }
.card:hover { transform: translateY(-6px); } .card:hover::before { transform: scaleX(1); }
.card .link-gold { margin-top: auto; align-self: flex-start; }
.manifesto { position: relative; overflow: hidden; }
.manifesto .wrap { display: flex; flex-direction: column; gap: 28px; }
.manifesto .disp { font-size: clamp(40px, 6.4vw, 92px); max-width: 1240px; }
.moves { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.moves-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.moves-grid { grid-column: 6 / span 7; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 44px 40px; }
.move { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green); }
.move .disp:first-child { font-size: 26px; }
.move h3 { font-size: 32px; }
.proof { overflow: hidden; }
.proof .wrap { display: flex; flex-direction: column; gap: 64px; }
.proof-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; }
.proof-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 24px; }
.proof-copy .h2 { color: var(--cream); font-size: clamp(40px, 4.7vw, 68px); }
.proof-copy p { color: rgba(247,244,238,0.8); max-width: 560px; font-size: 18px; }
.proof-mock { grid-column: 8 / span 5; }
.mock { display: grid; grid-template-columns: 132px minmax(0, 1fr); overflow: hidden; transform: rotate(-1.5deg); }
.win-bar { grid-column: span 2; display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid rgba(247,244,238,0.1); }
.win-bar b { width: 10px; height: 10px; border-radius: 50%; background: rgba(247,244,238,0.18); }
.win-bar .small { color: rgba(247,244,238,0.45); margin-left: 8px; }
.side { padding: 12px 8px; border-right: 1px solid rgba(247,244,238,0.1); display: flex; flex-direction: column; gap: 2px; }
.side span { display: block; padding: 8px 10px; color: rgba(247,244,238,0.6); font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.side span.on { background: rgba(212,167,44,0.14); color: var(--gold); }
.mock-main { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.mock-msg { padding: 12px 14px; background: rgba(247,244,238,0.06); border-left: 3px solid var(--gold); font-size: 14px; line-height: 1.5; color: rgba(247,244,238,0.9); }
.trace { stroke-dasharray: 900; stroke-dashoffset: 900; animation: trace 2.6s var(--ease) .6s forwards; }
.mock-bars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.mock-bars > div { display: flex; flex-direction: column; gap: 6px; }
.mock-bars .small { color: rgba(247,244,238,0.5); }
.chips { display: flex; flex-direction: column; gap: 18px; padding-top: 40px; border-top: 1px solid rgba(247,244,238,0.14); }
.chips > div { display: flex; flex-wrap: wrap; gap: 10px; }
.chip { display: inline-flex; align-items: center; height: 40px; padding: 0 18px; border: 1px solid rgba(247,244,238,0.18); background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); font-size: 13px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; animation: chain 9.6s ease-in-out infinite; }
.chip:nth-child(1) { animation-delay: 0s; } .chip:nth-child(2) { animation-delay: 1.2s; } .chip:nth-child(3) { animation-delay: 2.4s; } .chip:nth-child(4) { animation-delay: 3.6s; } .chip:nth-child(5) { animation-delay: 4.8s; } .chip:nth-child(6) { animation-delay: 6s; } .chip:nth-child(7) { animation-delay: 7.2s; } .chip:nth-child(8) { animation-delay: 8.4s; }
.about-lite { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: center; }
.about-art { grid-column: span 5; position: relative; }
.about-art::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.art { position: relative; z-index: 1; height: clamp(320px, 36vw, 520px); background: linear-gradient(160deg, #5B6A22 0%, #8FA32E 45%, #D4A72C 100%); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.art img { width: 70%; height: auto; opacity: 0.9; }
.art .photo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 1; }
.about-art .spin { position: absolute; right: -40px; bottom: -40px; z-index: 2; }
.about-copy { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; }
.about-copy p { font-size: 18px; color: var(--body); }
.signoff { display: flex; align-items: center; flex-wrap: wrap; gap: 28px; margin-top: 8px; }
.signoff img { height: 64px; width: auto; }
.cta-band { position: relative; overflow: hidden; clip-path: polygon(0 56px, 100% 0, 100% 100%, 0 100%); padding-top: clamp(100px, 10vw, 136px); padding-bottom: clamp(64px, 6vw, 88px); }
.cta-band .wrap { display: flex; align-items: center; justify-content: space-between; gap: 40px; flex-wrap: wrap; }
.cta-band .h2 { color: var(--cream); }
.cta-band p { font-size: 19px; font-weight: 500; color: rgba(247,244,238,0.85); }
.cta-band .btn { min-height: 64px; padding: 0 40px; font-size: 15px; }

/* inner pages */
.page-hero { overflow: hidden; }
.page-hero .wrap { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-top: clamp(56px, 7vw, 96px); padding-bottom: clamp(56px, 6vw, 80px); }
.page-hero h1 { font-size: clamp(44px, 7.2vw, 104px); color: var(--cream); }
.page-hero .rule { width: 220px; }
.page-hero .lead { color: rgba(247,244,238,0.8); max-width: 640px; }
.page-hero-copy { grid-column: span 8; display: flex; flex-direction: column; gap: 24px; }
.page-hero-side { grid-column: 10 / span 3; }
.gold-card { display: flex; flex-direction: column; gap: 10px; padding: 28px; background: var(--gold); color: var(--ink); }
.gold-card .eyebrow { color: var(--ink); }
.gold-card .disp { font-size: 32px; }
.gold-card p { font-size: 15px; font-weight: 500; }
.gold-card .btn { margin-top: 10px; align-self: flex-start; }
.offer { padding: 56px 0; border-top: 3px solid var(--green); display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.offer-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.offer-head h2 { font-size: clamp(36px, 3.6vw, 52px); }
.offer-body { grid-column: span 5; display: flex; flex-direction: column; gap: 20px; }
.offer-body > p { font-size: 18px; color: var(--body); }
.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 24px; padding-top: 6px; }
.facts > div { display: flex; flex-direction: column; gap: 4px; }
.facts .eyebrow { color: var(--muted); }
.offer-price { grid-column: span 3; }
.offer-price .card { padding: 28px 28px 34px; gap: 16px; }
.offer-price .disp { font-size: clamp(26px, 2.4vw, 36px); color: var(--cream); }
.offer-price .dim { font-size: 14px; }
.offer-price .btn { align-self: flex-start; }
.who { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.who-head { grid-column: span 6; display: flex; flex-direction: column; gap: 16px; }
.who-head .h2 { color: var(--cream); font-size: clamp(36px, 4vw, 58px); }
.who-body { grid-column: 8 / span 5; display: flex; flex-direction: column; gap: 18px; font-size: 18px; font-weight: 500; color: rgba(247,244,238,0.88); }
.about-hero .page-hero-copy { grid-column: span 7; padding-bottom: 40px; }
.about-hero .page-hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -96px; }
.about-hero .page-hero-side::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.about-hero .art { height: clamp(320px, 33vw, 480px); border: 6px solid var(--gold); }
.about-hero .spin { position: absolute; left: -48px; top: -48px; z-index: 2; }
.story { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; padding-top: 160px; }
.stats { grid-column: span 3; display: flex; flex-direction: column; gap: 32px; }
.stat { display: flex; flex-direction: column; gap: 8px; padding-top: 18px; border-top: 3px solid var(--green); }
.stat .num { font-size: clamp(56px, 6vw, 88px); }
.stat span:last-child { font-size: 14px; color: var(--muted); }
.story-copy { grid-column: 5 / span 7; display: flex; flex-direction: column; gap: 24px; font-size: 19px; color: var(--body); line-height: 1.7; }
.story-copy h2 { font-size: clamp(32px, 3vw, 44px); color: var(--text); }
.story-copy h2 + p { margin-top: 0; }
.story-copy h2:not(:first-child) { margin-top: 16px; }
.values { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 40px; }
.values-head { grid-column: span 4; display: flex; flex-direction: column; gap: 10px; }
.values-head .h2 { color: var(--cream); font-size: clamp(36px, 3.9vw, 56px); }
.value { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green-light); }
.value .disp { font-size: 34px; color: var(--gold); }
.question { position: relative; overflow: hidden; text-align: center; }
.question .wrap { display: flex; flex-direction: column; gap: 24px; align-items: center; }
.question .serif { font-size: clamp(28px, 3.2vw, 46px); max-width: 980px; }
.question .spin { position: absolute; left: -120px; top: 50%; margin-top: -180px; opacity: 0.35; }
.contact-hero .wrap { align-items: start; }
.contact-copy { grid-column: span 5; display: flex; flex-direction: column; gap: 40px; }
.contact-copy > div:first-child { display: flex; flex-direction: column; gap: 22px; }
.contact-copy h1 { font-size: clamp(44px, 6.1vw, 88px); }
.contact-email { display: flex; flex-direction: column; gap: 6px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.2); }
.contact-email a { font-size: 18px; color: var(--cream); }
.contact-email a:hover { color: var(--gold); }
.contact-email .dim { font-size: 14px; }
.form-card { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; padding: 40px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.form-card h2 { font-size: clamp(28px, 2.6vw, 38px); }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 12px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
.field input, .field textarea { width: 100%; min-height: 54px; border: 2px solid var(--text); background: var(--cream-2); padding: 12px 16px; font: inherit; font-size: 16px; color: var(--text); border-radius: 0; }
.field textarea { min-height: 160px; resize: vertical; }
.field input:focus, .field textarea:focus { outline: none; border-color: var(--gold); }
.form-note { font-size: 14px; color: var(--muted); }
.form-note.ok { color: var(--green-deep); font-weight: 600; }
.form-note.err { color: #A33; font-weight: 600; }
.hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }

/* footer */
.footer { padding-top: 64px; padding-bottom: 40px; }
.footer-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 40px; flex-wrap: wrap; }
.footer-brand { display: flex; flex-direction: column; gap: 18px; }
.footer-brand img { height: 84px; width: auto; }
.footer-brand .serif { color: var(--gold); font-size: 26px; }
.footer-links { display: flex; flex-wrap: wrap; gap: 32px; font-size: 13px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-links a { color: rgba(247,244,238,0.85); }
.footer-links a:last-child { color: var(--gold); }
.footer-bottom { margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.16); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; font-size: 13px; color: rgba(247,244,238,0.55); }
.footer-bottom a { color: rgba(247,244,238,0.75); }

@keyframes rise { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
@keyframes draw { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes bob { 0%, 100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-14px) rotate(-2deg); } }
@keyframes ping { 0% { transform: scale(1); opacity: .9; } 100% { transform: scale(2.6); opacity: 0; } }
@keyframes chain { 0%, 100% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } 12% { background: #D4A72C; color: #0F0E0B; border-color: #D4A72C; } 24% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } }
@keyframes trace { to { stroke-dashoffset: 0; } }
@keyframes cycle { 0%, 18% { transform: translateY(0); } 25%, 43% { transform: translateY(-20%); } 50%, 68% { transform: translateY(-40%); } 75%, 93% { transform: translateY(-60%); } 100% { transform: translateY(-80%); } }
@keyframes ticker { 0%, 30% { transform: translateY(0); } 33%, 63% { transform: translateY(-100%); } 66%, 96% { transform: translateY(-200%); } 100% { transform: translateY(-300%); } }
@keyframes breathe { 0%, 100% { opacity: .5; transform: scale(1); } 50% { opacity: .85; transform: scale(1.08); } }

@media (max-width: 1100px) {
  .hero-copy { grid-column: span 12; }
  .hero-side { grid-column: span 12; margin-bottom: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
  .sys-card { position: static; width: auto; animation: none; }
  .hero-grid { padding-bottom: 56px; }
  .ring { display: none; }
  .doors { grid-template-columns: 1fr; }
  .moves-head, .moves-grid { grid-column: span 12; }
  .proof-copy, .proof-mock { grid-column: span 12; }
  .mock { transform: none; }
  .about-art, .about-copy { grid-column: span 12; }
  .page-hero-copy { grid-column: span 12; }
  .page-hero-side { grid-column: span 12; }
  .about-hero .page-hero-copy, .about-hero .page-hero-side { grid-column: span 12; margin-bottom: 0; }
  .about-hero .page-hero-side { padding-bottom: 24px; }
  .story { padding-top: 64px; }
  .stats, .story-copy { grid-column: span 12; }
  .stats { flex-direction: row; flex-wrap: wrap; }
  .stats .stat { flex: 1 1 200px; }
  .values { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .values-head { grid-column: span 2; }
  .offer-head, .offer-body, .offer-price { grid-column: span 12; }
  .who-head, .who-body { grid-column: span 12; }
  .contact-copy, .form-card { grid-column: span 12; }
}
@media (max-width: 720px) {
  body { font-size: 16px; }
  .nav-toggle { display: block; }
  .nav-links { display: none; position: absolute; left: 0; right: 0; top: 100%; flex-direction: column; align-items: stretch; gap: 0; background: var(--ink); padding: 8px var(--gutter) 20px; z-index: 20; border-top: 1px solid rgba(247,244,238,0.12); }
  .nav-links.open { display: flex; }
  .nav-links a { padding: 14px 0; border-bottom: 1px solid rgba(247,244,238,0.08); }
  .nav-links .btn { margin-top: 12px; }
  .nav { position: relative; }
  .hero-side { grid-template-columns: 1fr; }
  .sig { display: none; }
  .moves-grid { grid-template-columns: 1fr; }
  .mock { grid-template-columns: 1fr; }
  .side { flex-direction: row; flex-wrap: wrap; border-right: 0; border-bottom: 1px solid rgba(247,244,238,0.1); }
  .values { grid-template-columns: 1fr; }
  .values-head { grid-column: span 1; }
  .facts, .mock-bars { grid-template-columns: 1fr; }
  .form-card { padding: 24px; }
  .question .spin { display: none; }
  .cta-band { clip-path: polygon(0 28px, 100% 0, 100% 100%, 0 100%); }
  .move h3 { font-size: 26px; }
}
@media (prefers-reduced-motion: reduce) {
  .r1, .r2, .r3, .r4 { opacity: 1; animation: none; }
  .rule, .bar i { transform: none; animation: none; }
  .ring, .spin, .marquee, .sys-card, .breathe, .dot::after, .chip, .ticker > div, .cycle > span { animation: none; }
  .trace { stroke-dashoffset: 0; animation: none; }
}

</style>
</head>
<body>
<header class="nav">
  <div class="wrap">
    <a class="nav-logo" href="/" aria-label="KMJ Creative Solutions home"><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions"></a>
    <button class="nav-toggle" type="button" aria-label="Open menu" aria-expanded="false" data-nav-toggle>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>
    </button>
    <nav class="nav-links sxm-header-pagenav" data-nav-links aria-label="Primary">
      <a href="/about" class="link-draw">About</a>
      <a href="/services" class="link-draw">Services</a>
      <a href="/contact" class="link-draw">Contact</a>
      <a href="/book" class="btn btn-gold">Book a Discovery Call</a>
    </nav>
  </div>
</header>

<main>
<section class="page-hero dark">
  <img class="sig" src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="" style="right: 40px; top: 24px; width: min(620px, 42vw); opacity: 0.16;">
  <div class="wrap">
    <div class="page-hero-copy">
      <p class="eyebrow-gold r1">Services</p>
      <h1 class="disp r2">Three doors into <span class="serif foil" style="font-weight: 500;">the same work.</span></h1>
      <span class="rule r3" style="opacity: 1;"></span>
      <p class="lead r3" data-override-target="services.hero.lead">Coaching when the business is still an idea. Consulting when it's already in motion. Creative direction when it needs a face. Every engagement begins with the same thirty-minute call.</p>
    </div>
    <div class="page-hero-side r4">
      <div class="gold-card">
        <p class="eyebrow">Start here</p>
        <p class="disp">Discovery Call</p>
        <p data-override-target="services.hero.card">Thirty minutes, no fee, no pitch. We listen for the calling beneath the question and tell you which door fits.</p>
        <a href="/book" class="btn btn-ink">Book the call</a>
      </div>
    </div>
  </div>
</section>

<section class="section" style="padding-top: 48px;">
  <div class="wrap">
    <div class="offer" id="coaching">
      <div class="offer-head">
        <p class="num foil-dk">01</p>
        <p class="eyebrow">Coaching</p>
        <h2 class="disp" data-override-target="services.coaching.title">Embrace the Shift</h2>
        <p class="muted">The ninety-day intensive</p>
      </div>
      <div class="offer-body">
        <p data-override-target="services.coaching.body">For the founder sitting on a half-baked idea, or a clear one without a runway. We meet weekly. You leave each session with work to do. Across ninety days the idea moves from private possibility to public offering, built on your values rather than a borrowed playbook.</p>
        <div class="facts">
          <div><span class="eyebrow">Cadence</span><span data-override-target="services.coaching.cadence">Twelve weekly sessions, sixty minutes each, by video or in person.</span></div>
          <div><span class="eyebrow">Method</span><span data-override-target="services.coaching.method">Frameworks, homework, accountability. Measured forward motion.</span></div>
          <div><span class="eyebrow">Outcome</span><span data-override-target="services.coaching.outcome">A launched offer, a clarified audience, a rhythm you can keep.</span></div>
          <div><span class="eyebrow">Posture</span><span data-override-target="services.coaching.posture">Pastoral in cadence. Strategic in framing. Honest throughout.</span></div>
        </div>
      </div>
      <div class="offer-price">
        <div class="card">
          <p class="eyebrow-gold">Investment</p>
          <p class="disp" data-override-target="services.coaching.price">Set in the discovery call</p>
          <p class="dim" data-override-target="services.coaching.companions">Companion pieces for graduates: the Quarterly Check, a single ninety-minute recalibration three months on, and The Shift Workbook, the frameworks in print.</p>
          <a href="/book" class="btn btn-gold">Begin the conversation</a>
        </div>
      </div>
    </div>

    <div class="offer" id="consulting">
      <div class="offer-head">
        <p class="num foil-dk">02</p>
        <p class="eyebrow">Consulting</p>
        <h2 class="disp" data-override-target="services.consulting.title">Clarity Sessions</h2>
        <p class="muted">For a business already in motion</p>
      </div>
      <div class="offer-body">
        <p data-override-target="services.consulting.body">You're running something real and you've hit a question that won't resolve on its own: what the next idea is, where the innovation actually lives, whether the economics of the offer hold at the price you're charging. We sit with the problem, work it through, and you leave with a decision and written notes you can act on the same week.</p>
        <div class="facts">
          <div><span class="eyebrow">Format</span><span data-override-target="services.consulting.format">A single focused session, or a short series when the question is bigger than one room.</span></div>
          <div><span class="eyebrow">Good for</span><span data-override-target="services.consulting.goodfor">Creativity, innovation, ideas, and the economics of what you sell.</span></div>
        </div>
      </div>
      <div class="offer-price">
        <div class="card">
          <p class="eyebrow-gold">Investment</p>
          <p class="disp" data-override-target="services.consulting.price">Set in the discovery call</p>
          <p class="dim" data-override-target="services.consulting.note">Per session. A series is scoped after we've talked.</p>
          <a href="/book" class="btn btn-gold">Book a session</a>
        </div>
      </div>
    </div>

    <div class="offer" id="creative" style="padding-bottom: 16px;">
      <div class="offer-head">
        <p class="num foil-dk">03</p>
        <p class="eyebrow">Creative direction</p>
        <h2 class="disp" data-override-target="services.creative.title">The idea, made visible</h2>
        <p class="muted">By project</p>
      </div>
      <div class="offer-body">
        <p data-override-target="services.creative.body">Once the vision is named, it needs a face the marketplace can recognize. Brand, messaging, and the visual voice of what you're building, in service of the coaching and consulting work rather than as a stand-alone design shop. Scoped per project after we've talked.</p>
      </div>
      <div class="offer-price">
        <div class="card">
          <p class="eyebrow-gold">Investment</p>
          <p class="disp" data-override-target="services.creative.price">Scoped per project</p>
          <a href="/contact" class="btn btn-gold">Ask about a project</a>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="section dark olive">
  <div class="wrap who">
    <div class="who-head">
      <p class="eyebrow-gold">Who this is for</p>
      <h2 class="disp h2" data-override-target="services.who.title">The one with a calling and a clearing, and an idea sitting between them.</h2>
    </div>
    <div class="who-body">
      <p data-override-target="services.who.p1">For the purpose-driven founder. For the faith-driven builder. For the coach, the salon owner, the consultant, the ministry leader who knows the work is meant for them but can't yet see the path from here to launched.</p>
      <p data-override-target="services.who.p2">We don't build for hustle. We build for vocation: businesses that hold their values when the pressure arrives. The shift is the work.</p>
    </div>
  </div>
</section>

</main>
<footer class="footer dark">
  <div class="wrap">
    <div class="footer-top">
      <div class="footer-brand">
        <img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions">
        <p class="serif">Elevate your vision. Amplify your impact.</p>
      </div>
      <nav class="footer-links" aria-label="Footer">
        <a href="/about" class="link-draw">About</a>
        <a href="/services" class="link-draw">Services</a>
        <a href="/contact" class="link-draw">Contact</a>
        <a href="/book" class="link-draw">Book a Discovery Call</a>
      </nav>
    </div>
    <div class="footer-bottom">
      <span>© 2026 KMJ Creative Solutions</span>
      <a href="mailto:{{BUSINESS_EMAIL}}" data-needs-email>{{BUSINESS_EMAIL}}</a>
    </div>
  </div>
</footer>
<script>
(function () {
  var t = document.querySelector('[data-nav-toggle]');
  var l = document.querySelector('[data-nav-links]');
  if (t && l) {
    t.addEventListener('click', function () {
      var open = l.classList.toggle('open');
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  var f = document.querySelector('[data-contact-form]');
  if (f) {
    var note = f.querySelector('[data-form-note]');
    var btn = f.querySelector('button[type="submit"]');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (f.querySelector('[name="website"]').value) { return; }
      var body = {
        name: f.querySelector('[name="name"]').value.trim(),
        email: f.querySelector('[name="email"]').value.trim(),
        message: f.querySelector('[name="message"]').value.trim()
      };
      if (!body.name || !body.email || !body.message) {
        note.textContent = 'Please fill in all three fields.'; note.className = 'form-note err'; return;
      }
      btn.disabled = true; note.textContent = 'Sending…'; note.className = 'form-note';
      fetch('https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/contact-submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j.status !== 'error', j: j }; }); })
        .then(function (res) {
          if (res.ok) { f.reset(); note.textContent = 'Thank you. Your message is in. I will be in touch to set up a conversation.'; note.className = 'form-note ok'; }
          else { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; }
        })
        .catch(function () { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; })
        .then(function () { btn.disabled = false; });
    });
  }
})();
</script>

</body>
</html>
$kmj$,
      'contact', $kmj$<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contact — KMJ Creative Solutions</title>
<meta name="description" content="Book a thirty-minute discovery call, or write and tell me where you stand.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&amp;family=Cormorant+Garamond:ital,wght@1,500&amp;family=Work+Sans:wght@400;500;600&amp;display=swap">
<style>
/* KMJ Creative Solutions — hand-built site (2026-09-03).
   Source of truth: sites/kmj-creative-solutions/. Built into the
   business_sites row by build.py; served by public_site.py under
   site_config.html_source == "manual". */
:root {
  --ink: #0F0E0B; --ink-2: #14120E; --text: #17150F; --body: #3E3A31; --muted: #6B655A;
  --cream: #F7F4EE; --cream-2: #FFFDF8;
  --gold: #D4A72C; --gold-deep: #B8922E; --gold-light: #F3D97A;
  --green: #7D8C3A; --green-deep: #5B6A22; --green-light: #A9B83A; --green-text: #6E7B2E;
  --gutter: clamp(20px, 5vw, 72px);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--cream); color: var(--text); font-family: 'Work Sans', 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 17px; line-height: 1.6; -webkit-font-smoothing: antialiased; overflow-x: hidden; }
a { color: inherit; text-decoration: none; transition: color .25s ease; }
a:hover { color: var(--green); }
img { max-width: 100%; }
p, h1, h2, h3 { margin: 0; }
.wrap { max-width: 1440px; margin: 0 auto; padding-left: var(--gutter); padding-right: var(--gutter); }
.disp { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; line-height: 0.96; letter-spacing: -0.035em; }
.serif { font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 500; letter-spacing: 0; line-height: 1.15; }
.eyebrow { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--green-text); font-weight: 600; }
.eyebrow-gold { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.small { font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 600; }
.muted { color: var(--muted); }
.dim { color: rgba(247,244,238,0.72); }
.lead { font-size: clamp(17px, 1.5vw, 21px); line-height: 1.55; }
.foil { background: linear-gradient(100deg, #8A6A14 0%, #D4A72C 22%, #F3D97A 40%, #C8981F 58%, #F0D46B 76%, #9C7A1A 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-dk { background: linear-gradient(100deg, #7A5C0A 0%, #B8922E 25%, #E0BC4A 45%, #A67F17 65%, #D4A72C 85%, #8A6A14 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.foil-green { background: linear-gradient(100deg, #4A5619 0%, #7D8C3A 30%, #A9B83A 50%, #5B6A22 72%, #8FA32E 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.num { font-family: 'Bricolage Grotesque', 'Segoe UI', Helvetica, Arial, sans-serif; font-weight: 800; font-size: clamp(64px, 7vw, 96px); line-height: 0.8; letter-spacing: -0.05em; }
.btn { display: inline-flex; align-items: center; justify-content: center; min-height: 54px; padding: 0 30px; font-weight: 600; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; text-align: center; transition: background-color .25s ease, color .25s ease, border-color .25s ease, transform .25s ease; cursor: pointer; border: 0; font-family: inherit; }
.btn:hover { transform: translateY(-2px); }
.btn-gold { background: var(--gold); color: var(--ink); } .btn-gold:hover { background: var(--green-light); color: var(--ink); }
.btn-ink { background: var(--ink); color: var(--cream); } .btn-ink:hover { background: var(--green-deep); color: var(--cream); }
.btn-line { border: 2px solid var(--text); color: var(--text); background: transparent; } .btn-line:hover { border-color: var(--green); color: var(--green-deep); }
.btn-light { border: 2px solid rgba(247,244,238,0.5); color: var(--cream); background: transparent; } .btn-light:hover { border-color: var(--green-light); color: var(--green-light); }
.link-draw { position: relative; display: inline-block; }
.link-draw::after { content: ""; position: absolute; left: 0; bottom: -4px; height: 2px; width: 100%; background: currentColor; transform: scaleX(0); transform-origin: left; transition: transform .35s var(--ease); }
.link-draw:hover::after { transform: scaleX(1); }
.link-gold { color: var(--green-light); font-weight: 600; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }

/* dark bands */
.dark { position: relative; background: var(--ink); color: var(--cream); }
.dark::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: 0.07; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23n)' opacity='0.8'/></svg>"); }
.dark > * { position: relative; z-index: 1; }
.olive { background: var(--green-deep); }
.glow { position: absolute; border-radius: 50%; pointer-events: none; z-index: 0; }
.sig { position: absolute; pointer-events: none; z-index: 0; }

/* nav */
.nav { background: var(--ink); color: var(--cream); }
.nav .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-top: 16px; padding-bottom: 16px; }
.nav-logo img { height: 52px; width: auto; display: block; }
.nav-links { display: flex; align-items: center; gap: 32px; font-size: 14px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
.nav-links a { color: var(--cream); }
.nav-links .btn { min-height: 46px; padding: 0 22px; }
.nav-toggle { display: none; background: none; border: 0; color: var(--cream); width: 44px; height: 44px; cursor: pointer; padding: 0; }
.nav-toggle svg { display: block; margin: 0 auto; }

/* hero */
.hero { overflow: hidden; }
.hero .wrap { display: flex; flex-direction: column; gap: 36px; padding-top: clamp(56px, 7vw, 96px); }
.hero-head { display: flex; flex-direction: column; gap: 28px; max-width: 1180px; }
.hero h1 { font-size: clamp(48px, 8.6vw, 124px); color: var(--cream); }
.hero-then { display: flex; flex-direction: column; gap: 14px; align-self: flex-start; }
.hero-then .serif { font-size: clamp(34px, 4.4vw, 64px); }
.rule { display: block; height: 4px; background: linear-gradient(90deg, #D4A72C, #F3D97A, #D4A72C); transform-origin: left; transform: scaleX(0); animation: draw 1.1s var(--ease) .9s forwards; }
.hero-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-bottom: 72px; }
.hero-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 28px; }
.hero-copy .lead { max-width: 640px; color: rgba(247,244,238,0.8); }
.cta-row { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -132px; }
.quote-card { display: flex; flex-direction: column; gap: 12px; padding: 28px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.quote-card .serif { font-size: clamp(22px, 2vw, 30px); }
.sys-card { position: absolute; right: -36px; top: -150px; width: 300px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; z-index: 2; border-top: 3px solid var(--gold); animation: bob 6s ease-in-out infinite; }
.win { background: var(--ink-2); border: 1px solid rgba(247,244,238,0.14); box-shadow: 0 40px 80px rgba(0,0,0,0.45); }
.ring { position: absolute; z-index: 0; animation: spin 60s linear infinite; transform-origin: center; }
.spin { animation: spin 28s linear infinite; transform-origin: center; }
.cycle { display: inline-block; height: 1em; overflow: hidden; vertical-align: bottom; font-weight: 500; letter-spacing: 0; }
.cycle > span { display: block; animation: cycle 12s var(--ease) infinite; }
.cycle > span > i { display: block; height: 1em; line-height: 1; font-style: italic; }
.dot { position: relative; width: 10px; height: 10px; border-radius: 50%; background: var(--green-light); flex: none; }
.dot::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: var(--green-light); animation: ping 1.8s cubic-bezier(0, 0, 0.2, 1) infinite; }
.ticker { height: 1.5em; overflow: hidden; }
.ticker > div { animation: ticker 12s var(--ease) infinite; }
.bar { height: 8px; background: rgba(247,244,238,0.1); overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform-origin: left; animation: draw 1.4s var(--ease) forwards; }
.r1, .r2, .r3, .r4 { opacity: 0; animation: rise .9s var(--ease) forwards; }
.r1 { animation-delay: .1s; } .r2 { animation-delay: .3s; } .r3 { animation-delay: .5s; } .r4 { animation-delay: .7s; }
.breathe { animation: breathe 9s ease-in-out infinite; }

/* marquee */
.marquee-band { background: var(--gold); color: var(--ink); padding: 22px 0; overflow: hidden; }
.marquee { display: flex; width: max-content; gap: 48px; align-items: center; animation: marquee 32s linear infinite; }
.marquee:hover { animation-play-state: paused; }
.marquee > div { display: flex; align-items: center; gap: 48px; padding-right: 48px; }
.marquee .disp, .marquee .serif { font-size: clamp(26px, 2.8vw, 40px); white-space: nowrap; }

/* sections */
.section { padding-top: clamp(64px, 8vw, 112px); padding-bottom: clamp(64px, 8vw, 112px); }
.section-head { display: flex; justify-content: space-between; align-items: end; gap: 40px; flex-wrap: wrap; }
.section-head > div { display: flex; flex-direction: column; gap: 16px; }
.h2 { font-size: clamp(40px, 5vw, 72px); }
.h2-md { font-size: clamp(36px, 4.2vw, 60px); }
.h3 { font-size: clamp(28px, 2.6vw, 38px); }
.doors { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; margin-top: 56px; }
.card { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 20px; padding: 36px 32px 44px; background: var(--ink); color: var(--cream); transition: transform .35s var(--ease); }
.card::before { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: linear-gradient(90deg, #D4A72C, #A9B83A); transform: scaleX(0); transform-origin: left; transition: transform .45s var(--ease); }
.card:hover { transform: translateY(-6px); } .card:hover::before { transform: scaleX(1); }
.card .link-gold { margin-top: auto; align-self: flex-start; }
.manifesto { position: relative; overflow: hidden; }
.manifesto .wrap { display: flex; flex-direction: column; gap: 28px; }
.manifesto .disp { font-size: clamp(40px, 6.4vw, 92px); max-width: 1240px; }
.moves { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.moves-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.moves-grid { grid-column: 6 / span 7; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 44px 40px; }
.move { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green); }
.move .disp:first-child { font-size: 26px; }
.move h3 { font-size: 32px; }
.proof { overflow: hidden; }
.proof .wrap { display: flex; flex-direction: column; gap: 64px; }
.proof-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; }
.proof-copy { grid-column: span 7; display: flex; flex-direction: column; gap: 24px; }
.proof-copy .h2 { color: var(--cream); font-size: clamp(40px, 4.7vw, 68px); }
.proof-copy p { color: rgba(247,244,238,0.8); max-width: 560px; font-size: 18px; }
.proof-mock { grid-column: 8 / span 5; }
.mock { display: grid; grid-template-columns: 132px minmax(0, 1fr); overflow: hidden; transform: rotate(-1.5deg); }
.win-bar { grid-column: span 2; display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid rgba(247,244,238,0.1); }
.win-bar b { width: 10px; height: 10px; border-radius: 50%; background: rgba(247,244,238,0.18); }
.win-bar .small { color: rgba(247,244,238,0.45); margin-left: 8px; }
.side { padding: 12px 8px; border-right: 1px solid rgba(247,244,238,0.1); display: flex; flex-direction: column; gap: 2px; }
.side span { display: block; padding: 8px 10px; color: rgba(247,244,238,0.6); font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.side span.on { background: rgba(212,167,44,0.14); color: var(--gold); }
.mock-main { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.mock-msg { padding: 12px 14px; background: rgba(247,244,238,0.06); border-left: 3px solid var(--gold); font-size: 14px; line-height: 1.5; color: rgba(247,244,238,0.9); }
.trace { stroke-dasharray: 900; stroke-dashoffset: 900; animation: trace 2.6s var(--ease) .6s forwards; }
.mock-bars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.mock-bars > div { display: flex; flex-direction: column; gap: 6px; }
.mock-bars .small { color: rgba(247,244,238,0.5); }
.chips { display: flex; flex-direction: column; gap: 18px; padding-top: 40px; border-top: 1px solid rgba(247,244,238,0.14); }
.chips > div { display: flex; flex-wrap: wrap; gap: 10px; }
.chip { display: inline-flex; align-items: center; height: 40px; padding: 0 18px; border: 1px solid rgba(247,244,238,0.18); background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); font-size: 13px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; animation: chain 9.6s ease-in-out infinite; }
.chip:nth-child(1) { animation-delay: 0s; } .chip:nth-child(2) { animation-delay: 1.2s; } .chip:nth-child(3) { animation-delay: 2.4s; } .chip:nth-child(4) { animation-delay: 3.6s; } .chip:nth-child(5) { animation-delay: 4.8s; } .chip:nth-child(6) { animation-delay: 6s; } .chip:nth-child(7) { animation-delay: 7.2s; } .chip:nth-child(8) { animation-delay: 8.4s; }
.about-lite { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: center; }
.about-art { grid-column: span 5; position: relative; }
.about-art::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.art { position: relative; z-index: 1; height: clamp(320px, 36vw, 520px); background: linear-gradient(160deg, #5B6A22 0%, #8FA32E 45%, #D4A72C 100%); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.art img { width: 70%; height: auto; opacity: 0.9; }
.art .photo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 1; }
.about-art .spin { position: absolute; right: -40px; bottom: -40px; z-index: 2; }
.about-copy { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; }
.about-copy p { font-size: 18px; color: var(--body); }
.signoff { display: flex; align-items: center; flex-wrap: wrap; gap: 28px; margin-top: 8px; }
.signoff img { height: 64px; width: auto; }
.cta-band { position: relative; overflow: hidden; clip-path: polygon(0 56px, 100% 0, 100% 100%, 0 100%); padding-top: clamp(100px, 10vw, 136px); padding-bottom: clamp(64px, 6vw, 88px); }
.cta-band .wrap { display: flex; align-items: center; justify-content: space-between; gap: 40px; flex-wrap: wrap; }
.cta-band .h2 { color: var(--cream); }
.cta-band p { font-size: 19px; font-weight: 500; color: rgba(247,244,238,0.85); }
.cta-band .btn { min-height: 64px; padding: 0 40px; font-size: 15px; }

/* inner pages */
.page-hero { overflow: hidden; }
.page-hero .wrap { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; align-items: end; padding-top: clamp(56px, 7vw, 96px); padding-bottom: clamp(56px, 6vw, 80px); }
.page-hero h1 { font-size: clamp(44px, 7.2vw, 104px); color: var(--cream); }
.page-hero .rule { width: 220px; }
.page-hero .lead { color: rgba(247,244,238,0.8); max-width: 640px; }
.page-hero-copy { grid-column: span 8; display: flex; flex-direction: column; gap: 24px; }
.page-hero-side { grid-column: 10 / span 3; }
.gold-card { display: flex; flex-direction: column; gap: 10px; padding: 28px; background: var(--gold); color: var(--ink); }
.gold-card .eyebrow { color: var(--ink); }
.gold-card .disp { font-size: 32px; }
.gold-card p { font-size: 15px; font-weight: 500; }
.gold-card .btn { margin-top: 10px; align-self: flex-start; }
.offer { padding: 56px 0; border-top: 3px solid var(--green); display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.offer-head { grid-column: span 4; display: flex; flex-direction: column; gap: 16px; }
.offer-head h2 { font-size: clamp(36px, 3.6vw, 52px); }
.offer-body { grid-column: span 5; display: flex; flex-direction: column; gap: 20px; }
.offer-body > p { font-size: 18px; color: var(--body); }
.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 24px; padding-top: 6px; }
.facts > div { display: flex; flex-direction: column; gap: 4px; }
.facts .eyebrow { color: var(--muted); }
.offer-price { grid-column: span 3; }
.offer-price .card { padding: 28px 28px 34px; gap: 16px; }
.offer-price .disp { font-size: clamp(26px, 2.4vw, 36px); color: var(--cream); }
.offer-price .dim { font-size: 14px; }
.offer-price .btn { align-self: flex-start; }
.who { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; }
.who-head { grid-column: span 6; display: flex; flex-direction: column; gap: 16px; }
.who-head .h2 { color: var(--cream); font-size: clamp(36px, 4vw, 58px); }
.who-body { grid-column: 8 / span 5; display: flex; flex-direction: column; gap: 18px; font-size: 18px; font-weight: 500; color: rgba(247,244,238,0.88); }
.about-hero .page-hero-copy { grid-column: span 7; padding-bottom: 40px; }
.about-hero .page-hero-side { grid-column: 9 / span 4; position: relative; margin-bottom: -96px; }
.about-hero .page-hero-side::before { content: ""; position: absolute; inset: 0; transform: translate(18px, 18px); border: 2px solid var(--gold); z-index: 0; }
.about-hero .art { height: clamp(320px, 33vw, 480px); border: 6px solid var(--gold); }
.about-hero .spin { position: absolute; left: -48px; top: -48px; z-index: 2; }
.story { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 32px; padding-top: 160px; }
.stats { grid-column: span 3; display: flex; flex-direction: column; gap: 32px; }
.stat { display: flex; flex-direction: column; gap: 8px; padding-top: 18px; border-top: 3px solid var(--green); }
.stat .num { font-size: clamp(56px, 6vw, 88px); }
.stat span:last-child { font-size: 14px; color: var(--muted); }
.story-copy { grid-column: 5 / span 7; display: flex; flex-direction: column; gap: 24px; font-size: 19px; color: var(--body); line-height: 1.7; }
.story-copy h2 { font-size: clamp(32px, 3vw, 44px); color: var(--text); }
.story-copy h2 + p { margin-top: 0; }
.story-copy h2:not(:first-child) { margin-top: 16px; }
.values { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 40px; }
.values-head { grid-column: span 4; display: flex; flex-direction: column; gap: 10px; }
.values-head .h2 { color: var(--cream); font-size: clamp(36px, 3.9vw, 56px); }
.value { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 3px solid var(--green-light); }
.value .disp { font-size: 34px; color: var(--gold); }
.question { position: relative; overflow: hidden; text-align: center; }
.question .wrap { display: flex; flex-direction: column; gap: 24px; align-items: center; }
.question .serif { font-size: clamp(28px, 3.2vw, 46px); max-width: 980px; }
.question .spin { position: absolute; left: -120px; top: 50%; margin-top: -180px; opacity: 0.35; }
.contact-hero .wrap { align-items: start; }
.contact-copy { grid-column: span 5; display: flex; flex-direction: column; gap: 40px; }
.contact-copy > div:first-child { display: flex; flex-direction: column; gap: 22px; }
.contact-copy h1 { font-size: clamp(44px, 6.1vw, 88px); }
.contact-email { display: flex; flex-direction: column; gap: 6px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.2); }
.contact-email a { font-size: 18px; color: var(--cream); }
.contact-email a:hover { color: var(--gold); }
.contact-email .dim { font-size: 14px; }
.form-card { grid-column: 7 / span 6; display: flex; flex-direction: column; gap: 22px; padding: 40px; background: var(--cream); color: var(--text); border-left: 6px solid var(--green); }
.form-card h2 { font-size: clamp(28px, 2.6vw, 38px); }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 12px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
.field input, .field textarea { width: 100%; min-height: 54px; border: 2px solid var(--text); background: var(--cream-2); padding: 12px 16px; font: inherit; font-size: 16px; color: var(--text); border-radius: 0; }
.field textarea { min-height: 160px; resize: vertical; }
.field input:focus, .field textarea:focus { outline: none; border-color: var(--gold); }
.form-note { font-size: 14px; color: var(--muted); }
.form-note.ok { color: var(--green-deep); font-weight: 600; }
.form-note.err { color: #A33; font-weight: 600; }
.hp { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }

/* footer */
.footer { padding-top: 64px; padding-bottom: 40px; }
.footer-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 40px; flex-wrap: wrap; }
.footer-brand { display: flex; flex-direction: column; gap: 18px; }
.footer-brand img { height: 84px; width: auto; }
.footer-brand .serif { color: var(--gold); font-size: 26px; }
.footer-links { display: flex; flex-wrap: wrap; gap: 32px; font-size: 13px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }
.footer-links a { color: rgba(247,244,238,0.85); }
.footer-links a:last-child { color: var(--gold); }
.footer-bottom { margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(247,244,238,0.16); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; font-size: 13px; color: rgba(247,244,238,0.55); }
.footer-bottom a { color: rgba(247,244,238,0.75); }

@keyframes rise { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
@keyframes draw { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes bob { 0%, 100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-14px) rotate(-2deg); } }
@keyframes ping { 0% { transform: scale(1); opacity: .9; } 100% { transform: scale(2.6); opacity: 0; } }
@keyframes chain { 0%, 100% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } 12% { background: #D4A72C; color: #0F0E0B; border-color: #D4A72C; } 24% { background: rgba(247,244,238,0.06); color: rgba(247,244,238,0.7); border-color: rgba(247,244,238,0.18); } }
@keyframes trace { to { stroke-dashoffset: 0; } }
@keyframes cycle { 0%, 18% { transform: translateY(0); } 25%, 43% { transform: translateY(-20%); } 50%, 68% { transform: translateY(-40%); } 75%, 93% { transform: translateY(-60%); } 100% { transform: translateY(-80%); } }
@keyframes ticker { 0%, 30% { transform: translateY(0); } 33%, 63% { transform: translateY(-100%); } 66%, 96% { transform: translateY(-200%); } 100% { transform: translateY(-300%); } }
@keyframes breathe { 0%, 100% { opacity: .5; transform: scale(1); } 50% { opacity: .85; transform: scale(1.08); } }

@media (max-width: 1100px) {
  .hero-copy { grid-column: span 12; }
  .hero-side { grid-column: span 12; margin-bottom: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
  .sys-card { position: static; width: auto; animation: none; }
  .hero-grid { padding-bottom: 56px; }
  .ring { display: none; }
  .doors { grid-template-columns: 1fr; }
  .moves-head, .moves-grid { grid-column: span 12; }
  .proof-copy, .proof-mock { grid-column: span 12; }
  .mock { transform: none; }
  .about-art, .about-copy { grid-column: span 12; }
  .page-hero-copy { grid-column: span 12; }
  .page-hero-side { grid-column: span 12; }
  .about-hero .page-hero-copy, .about-hero .page-hero-side { grid-column: span 12; margin-bottom: 0; }
  .about-hero .page-hero-side { padding-bottom: 24px; }
  .story { padding-top: 64px; }
  .stats, .story-copy { grid-column: span 12; }
  .stats { flex-direction: row; flex-wrap: wrap; }
  .stats .stat { flex: 1 1 200px; }
  .values { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .values-head { grid-column: span 2; }
  .offer-head, .offer-body, .offer-price { grid-column: span 12; }
  .who-head, .who-body { grid-column: span 12; }
  .contact-copy, .form-card { grid-column: span 12; }
}
@media (max-width: 720px) {
  body { font-size: 16px; }
  .nav-toggle { display: block; }
  .nav-links { display: none; position: absolute; left: 0; right: 0; top: 100%; flex-direction: column; align-items: stretch; gap: 0; background: var(--ink); padding: 8px var(--gutter) 20px; z-index: 20; border-top: 1px solid rgba(247,244,238,0.12); }
  .nav-links.open { display: flex; }
  .nav-links a { padding: 14px 0; border-bottom: 1px solid rgba(247,244,238,0.08); }
  .nav-links .btn { margin-top: 12px; }
  .nav { position: relative; }
  .hero-side { grid-template-columns: 1fr; }
  .sig { display: none; }
  .moves-grid { grid-template-columns: 1fr; }
  .mock { grid-template-columns: 1fr; }
  .side { flex-direction: row; flex-wrap: wrap; border-right: 0; border-bottom: 1px solid rgba(247,244,238,0.1); }
  .values { grid-template-columns: 1fr; }
  .values-head { grid-column: span 1; }
  .facts, .mock-bars { grid-template-columns: 1fr; }
  .form-card { padding: 24px; }
  .question .spin { display: none; }
  .cta-band { clip-path: polygon(0 28px, 100% 0, 100% 100%, 0 100%); }
  .move h3 { font-size: 26px; }
}
@media (prefers-reduced-motion: reduce) {
  .r1, .r2, .r3, .r4 { opacity: 1; animation: none; }
  .rule, .bar i { transform: none; animation: none; }
  .ring, .spin, .marquee, .sys-card, .breathe, .dot::after, .chip, .ticker > div, .cycle > span { animation: none; }
  .trace { stroke-dashoffset: 0; animation: none; }
}

</style>
</head>
<body>
<header class="nav">
  <div class="wrap">
    <a class="nav-logo" href="/" aria-label="KMJ Creative Solutions home"><img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions"></a>
    <button class="nav-toggle" type="button" aria-label="Open menu" aria-expanded="false" data-nav-toggle>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>
    </button>
    <nav class="nav-links sxm-header-pagenav" data-nav-links aria-label="Primary">
      <a href="/about" class="link-draw">About</a>
      <a href="/services" class="link-draw">Services</a>
      <a href="/contact" class="link-draw">Contact</a>
      <a href="/book" class="btn btn-gold">Book a Discovery Call</a>
    </nav>
  </div>
</header>

<main>
<section class="page-hero contact-hero dark">
  <img class="sig" src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/signature.webp?v=8f783a1087" alt="" style="right: 40px; top: 24px; width: min(620px, 42vw); opacity: 0.16;">
  <div class="wrap">
    <div class="contact-copy">
      <div>
        <p class="eyebrow-gold r1">Contact</p>
        <h1 class="disp r2">Begin the <span class="serif foil" style="font-weight: 500;">conversation.</span></h1>
        <span class="rule"></span>
        <p class="lead r3" data-override-target="contact.hero.lead">Whether the idea is fully formed or still half-baked, the door is open. Book the call, or write and tell me where you stand.</p>
      </div>
      <div class="gold-card r4">
        <p class="eyebrow">The fastest way in</p>
        <p class="disp">Discovery Call · 30 minutes</p>
        <p data-override-target="contact.card">No fee, no pitch. Pick a time that works and we'll talk.</p>
        <a href="/book" class="btn btn-ink">Book a Discovery Call</a>
      </div>
      <div class="contact-email r4">
        <span class="eyebrow-gold">Direct email</span>
        <a href="mailto:{{BUSINESS_EMAIL}}" data-needs-email>{{BUSINESS_EMAIL}}</a>
        <span class="dim" data-override-target="contact.email.note">Every inquiry is read personally and answered by name.</span>
      </div>
    </div>
    <form class="form-card r3" data-contact-form novalidate>
      <div>
        <h2 class="disp">Tell me where you stand.</h2>
        <p class="muted" style="font-size: 15px;">Three fields. Held in confidence.</p>
      </div>
      <div class="field"><label for="c-name">Your name</label><input id="c-name" name="name" type="text" autocomplete="name" required></div>
      <div class="field"><label for="c-email">Your email</label><input id="c-email" name="email" type="email" autocomplete="email" required></div>
      <div class="field"><label for="c-message">Where are you stuck?</label><textarea id="c-message" name="message" placeholder="The idea, the offer, the shift in front of you. A line or a letter, both are read." required></textarea></div>
      <div class="hp" aria-hidden="true"><label>Website<input name="website" type="text" tabindex="-1" autocomplete="off"></label></div>
      <button type="submit" class="btn btn-ink" style="align-self: flex-start;">Send my message</button>
      <p class="form-note" data-form-note aria-live="polite"></p>
    </form>
  </div>
</section>

</main>
<footer class="footer dark">
  <div class="wrap">
    <div class="footer-top">
      <div class="footer-brand">
        <img src="https://kmj-intake-server-production.up.railway.app/public/site-assets/kmj-creative-solutions/logo.webp?v=c1358cd28c" alt="KMJ Creative Solutions">
        <p class="serif">Elevate your vision. Amplify your impact.</p>
      </div>
      <nav class="footer-links" aria-label="Footer">
        <a href="/about" class="link-draw">About</a>
        <a href="/services" class="link-draw">Services</a>
        <a href="/contact" class="link-draw">Contact</a>
        <a href="/book" class="link-draw">Book a Discovery Call</a>
      </nav>
    </div>
    <div class="footer-bottom">
      <span>© 2026 KMJ Creative Solutions</span>
      <a href="mailto:{{BUSINESS_EMAIL}}" data-needs-email>{{BUSINESS_EMAIL}}</a>
    </div>
  </div>
</footer>
<script>
(function () {
  var t = document.querySelector('[data-nav-toggle]');
  var l = document.querySelector('[data-nav-links]');
  if (t && l) {
    t.addEventListener('click', function () {
      var open = l.classList.toggle('open');
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  var f = document.querySelector('[data-contact-form]');
  if (f) {
    var note = f.querySelector('[data-form-note]');
    var btn = f.querySelector('button[type="submit"]');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (f.querySelector('[name="website"]').value) { return; }
      var body = {
        name: f.querySelector('[name="name"]').value.trim(),
        email: f.querySelector('[name="email"]').value.trim(),
        message: f.querySelector('[name="message"]').value.trim()
      };
      if (!body.name || !body.email || !body.message) {
        note.textContent = 'Please fill in all three fields.'; note.className = 'form-note err'; return;
      }
      btn.disabled = true; note.textContent = 'Sending…'; note.className = 'form-note';
      fetch('https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/contact-submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok && j.status !== 'error', j: j }; }); })
        .then(function (res) {
          if (res.ok) { f.reset(); note.textContent = 'Thank you. Your message is in. I will be in touch to set up a conversation.'; note.className = 'form-note ok'; }
          else { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; }
        })
        .catch(function () { note.textContent = 'Something went wrong sending that. Please try again, or book a call instead.'; note.className = 'form-note err'; })
        .then(function () { btn.disabled = false; });
    });
  }
})();
</script>

</body>
</html>
$kmj$
      )
    )),
  status = 'published',
  updated_at = now()
WHERE slug = 'kmj-creative-solutions';

-- Expect: UPDATE 1
COMMIT;
