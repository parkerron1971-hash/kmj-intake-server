/* The home page, edited (2026-11-10): the few things its style sheet (overview_edit.css) can't do alone.
   Sent only while HOME_EDIT is on. Everything it adds is marked ep-only. */
(function () {
  'use strict';
  var root = document.documentElement;
  if (!root.classList.contains('ep')) return;
  root.classList.add('ep-js');
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return [].slice.call((r || document).querySelectorAll(s)); }
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

  /* the close: the hero's rose stands where a second kind of window stood */
  var win = $('#start .win-sm');
  if (win) { var r = el('div', 'ep-closerose ep-only'); r.setAttribute('aria-hidden', 'true'); win.parentNode.insertBefore(r, win); }

  /* one top bar: the strip's two links join the menu, on a phone and on a computer */
  var LINKS = $$('.ep-strip nav a').map(function (a, i) { return [a.href, a.textContent.replace(/\s+/g, ' ').trim(), i ? '' : 'coach']; });
  var sheet = $('.lv-menu .sheet'), nav = $('.lv-nav');
  if (sheet) {
    var cta = $('.cta', sheet);
    LINKS.forEach(function (l) { var a = el('a', 'ep-only ep-quiet', '<i style="background:#3A3F4E"></i>' + l[1]); a.href = l[0]; sheet.insertBefore(a, cta); });
  }
  if (nav) {
    var go = nav.querySelector('a[href*="/start"]');
    LINKS.forEach(function (l) { var a = el('a', 'ep-only ep-nav ' + l[2], l[1]); a.href = l[0]; nav.insertBefore(a, go); });
  }

  /* Chief: one conversation, with each promise pinned to the line that proves it.
     Every word is one the page already says; the foot is the tour's own line about History. */
  (function () {
    var body = $('#chief .mc-body'), pts = $$('#chief .mc-pt');
    if (!body || pts.length < 4) return;
    var cx = el('div', 'cx ep-only'); cx.id = 'epChief';
    var wave = '<span class="cx-wave" aria-hidden="true"><i style="height:6px"></i><i style="height:13px"></i><i style="height:18px"></i><i style="height:10px"></i><i style="height:15px"></i><i style="height:7px"></i><i style="height:11px"></i><i style="height:5px"></i></span>';
    var beats = [
      '<span class="cx-said">' + wave + '<span>What needs me this week?</span></span><span class="cx-cap">Said out loud, on a call from the phone</span>',
      '<span class="cx-l">Three things.</span><span class="cx-l">The Brooks family has missed three Sundays, and Elder Mark has them.</span><span class="cx-l">Two first-time guests from Sunday haven’t heard from anyone yet.</span><span class="cx-l soft">And 3 bank rows are waiting for a category.</span>',
      '<span class="cx-said"><span>Draft a welcome note to both guests.</span></span><span class="cx-l">Drafted. They wait for you, and nothing goes out until you send them.</span><span class="cx-btns" aria-hidden="true"><span>Read the notes</span><span>Not now</span></span>',
      '<span class="cx-hist"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C9BCFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 8v4l3 2"/></svg><small>On your History page</small><span>What you ask of it, listed in plain words.</span></span>'
    ];
    var html = '<div class="cx-card" aria-hidden="true"></div>' +
      '<div class="cx-head"><span class="cx-orb" aria-hidden="true"></span><span class="cx-who"><b>Chief</b><span>Grace Fellowship · sample</span></span><span class="cx-when">Monday, 8:40 AM</span></div>';
    beats.forEach(function (b, i) {
      html += '<div class="cx-beat" style="--i:' + (i + 1) + '" data-i="' + i + '">' + b + '</div>' +
        '<span class="cx-ld" style="--i:' + (i + 1) + '" data-i="' + i + '" aria-hidden="true"></span>' +
        '<div class="cx-note" style="--i:' + (i + 1) + '" data-i="' + i + '" tabindex="0"></div>';
    });
    cx.innerHTML = html; cx.setAttribute('role', 'group'); cx.setAttribute('aria-label', 'A sample conversation with Chief, with what each part shows');
    $$('.cx-note', cx).forEach(function (n, i) {
      var p = pts[i], svg = p.querySelector('svg').cloneNode(true), cp = svg.querySelector('clipPath'), g = svg.querySelector('g[clip-path]');
      if (cp && g) { cp.id = 'cxClip' + i; g.setAttribute('clip-path', 'url(#cxClip' + i + ')'); }
      var b = document.createElement('b'), s = document.createElement('span');
      b.textContent = p.querySelector('b').textContent; s.textContent = p.querySelector(':scope > span').textContent;
      n.appendChild(svg); n.appendChild(b); n.appendChild(s);
    });
    body.parentNode.insertBefore(cx, body); $('#chief').classList.add('ep-cx');

    function hot(i, on) {
      cx.classList.toggle('cx-hover', on);
      $$('[data-i]', cx).forEach(function (e) { e.classList.toggle('now', on && +e.getAttribute('data-i') === i); });
    }
    $$('.cx-note, .cx-beat', cx).forEach(function (e) {
      var i = +e.getAttribute('data-i');
      e.addEventListener('mouseenter', function () { if (!cx.classList.contains('cx-play')) hot(i, true); });
      e.addEventListener('mouseleave', function () { hot(i, false); });
      e.addEventListener('focus', function () { if (!cx.classList.contains('cx-play')) hot(i, true); });
      e.addEventListener('blur', function () { hot(i, false); });
    });

    /* plays once, the first time it is on screen; at rest everything is there to read */
    var played = false, still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    function play() {
      if (played || still || !root.classList.contains('ep')) return; played = true;
      cx.classList.add('cx-play');
      var t = 350;
      $$('.cx-beat', cx).forEach(function (beat, i) {
        [].slice.call(beat.children).forEach(function (line, k) {
          setTimeout(function () {
            line.classList.add('in');
            if (k === 0) $$('[data-i="' + i + '"]', cx).forEach(function (e) { e.classList.add('lit'); });
          }, t);
          t += line.classList.contains('cx-l') ? 1050 : 800;
        });
        t += 500;
      });
      setTimeout(function () { cx.classList.remove('cx-play'); $$('.in, .lit', cx).forEach(function (e) { e.classList.remove('in'); e.classList.remove('lit'); }); }, t + 1400);
    }
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es, io) { es.forEach(function (e) { if (e.isIntersecting) { play(); if (played) io.disconnect(); } }); }, { threshold: 0.3 }).observe(cx);
    }
  })();

  /* Moving: the left panel becomes a moving sheet. The counts are a sample; the page already says
     "You see the counts before anything is final". */
  (function () {
    var box = $('#move .mv-box'); if (!box) return;
    var head = el('div', 'ms-head ep-only', '<b>Moving sheet</b><span>Grace Fellowship · sample</span>');
    box.insertBefore(head, box.firstChild);
    var counts = ['480 people', '1,860 gifts', '12 groups', '96 sermons'];
    $$('.mv-items li', box).forEach(function (li, i) { if (counts[i]) li.appendChild(el('span', 'ms-n ep-only', counts[i])); });
    box.appendChild(el('p', 'ms-foot ep-only', 'Sample counts. You see yours before anything is final.'));
  })();

  /* The hero: eight real screens, one for each part, standing together.
     The pictures are the room pages' own; the names are the ones the page already uses. */
  (function () {
    var hx = $('#hero-rooms'), words = $$('.hx-sub .rk'); if (!hx || words.length < 8) return;
    var NAMES = ['People and care', 'Kids', 'Giving', 'Groups', 'Member app', 'Website', 'Office', 'Chief'];
    var O = [
      { k: 'chief', i: 7, l: 32.5, b: 9, w: 35, z: 3, d: 0, alt: 'The office home on a tablet: Good morning, Pastor James, with Chief’s notes for today and this week’s numbers.' },
      { k: 'website', i: 5, l: 4.5, b: 33, w: 37, z: 1, d: .12, back: 1, alt: 'The Grace Fellowship website, with Welcome home and the latest message.' },
      { k: 'giving', i: 2, l: 58.5, b: 31, w: 37, z: 1, d: .2, back: 1, alt: 'The giving overview for 2026, with recent gifts and funds.' },
      { k: 'people', i: 0, l: 17.6, b: 6, w: 12.6, z: 4, d: .3, alt: 'The welcome lead’s phone with a new card from Ana Ruiz.' },
      { k: 'app', i: 4, l: 69.8, b: 6, w: 12.6, z: 4, d: .36, alt: 'The member app home, with Prayer Night tonight.' },
      { k: 'groups', i: 3, l: 4, b: 4.5, w: 11.4, z: 5, d: .46, alt: 'The Young Families group in the member app, with Thursday’s gathering.' },
      { k: 'office', i: 6, l: 84.6, b: 4.5, w: 11.4, z: 5, d: .52, alt: 'The 2026 giving statement email on a phone.' },
      { k: 'kids', i: 1, l: 28.2, b: 3, w: 9, z: 6, d: .62, alt: 'A printed kids check-in tag for Maya, with a pickup code.' }
    ];
    var stage = el('div', 'pf-stage ep-only', '<span class="pf-floor" aria-hidden="true"></span><span class="pf-rose" aria-hidden="true"></span>'), by = [];
    stage.id = 'pfStage'; stage.setAttribute('role', 'group'); stage.setAttribute('aria-label', 'The eight parts of Solutionist, on a sample church’s screens');
    O.forEach(function (o) {
      var w = words[o.i], c = (w.style.getPropertyValue('--c') || '#F3C77A').trim(), a = el('a', 'pf-o' + (o.back ? ' back' : ''));
      a.href = w.href; a.setAttribute('data-k', o.k); a.setAttribute('data-i', o.i); a.setAttribute('aria-label', NAMES[o.i]);
      a.style.cssText = '--l:' + o.l + '%;--b:' + o.b + '%;--w:' + o.w + '%;--z:' + o.z + ';--d:' + o.d + 's;--c:' + c + (o.back ? ';--br:.8' : '');
      var img = document.createElement('img'); img.src = '/assets/home/pf-' + o.k + '.webp'; img.alt = o.alt; img.decoding = 'async';
      a.appendChild(img); a.appendChild(el('span', 'pf-nm', NAMES[o.i])); a.lastChild.setAttribute('aria-hidden', 'true');
      stage.appendChild(a); by[o.i] = { a: a, c: c };
    });
    hx.appendChild(stage);

    function prod() { return root.classList.contains('ep') && root.classList.contains('ep-prod'); }
    var held = -1, walk = -1, calm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    function paint() {
      var on = prod(), k = on ? (held >= 0 ? held : walk) : -1;
      stage.classList.toggle('has-hot', k >= 0); stage.classList.toggle('by-hand', on && held >= 0);
      by.forEach(function (o, i) { o.a.classList.toggle('hot', i === k); words[i].classList.toggle('ep-on', i === k); });
      if (on) hx.style.setProperty('--hx-c', k >= 0 ? by[k].c : '#F3C77A');
    }
    function hold(i) { held = i; paint(); }
    by.forEach(function (o, i) {
      o.a.addEventListener('mouseenter', function () { hold(i); }); o.a.addEventListener('mouseleave', function () { hold(-1); });
      o.a.addEventListener('focus', function () { hold(i); }); o.a.addEventListener('blur', function () { hold(-1); });
      words[i].addEventListener('mouseenter', function () { if (prod()) hold(i); }); words[i].addEventListener('mouseleave', function () { if (prod()) hold(-1); });
      words[i].addEventListener('focus', function () { if (prod()) hold(i); }); words[i].addEventListener('blur', function () { if (prod()) hold(-1); });
    });
    addEventListener('resize', paint);

    /* they rise into place once; then one light walks the eight, twice, naming each, and rests */
    var entered = false, t = 0;
    function enter() {
      if (entered || !prod()) return; entered = true;
      stage.classList.add('in'); setTimeout(function () { stage.classList.add('done'); }, 2100);
      if (calm) return;
      var n = 0;
      setTimeout(function tick() {
        if (!prod()) { walk = -1; paint(); t = setTimeout(tick, 1200); return; }
        if (n >= 16) { walk = -1; paint(); return; }
        if (held < 0) { walk = n % 8; n++; } paint();
        t = setTimeout(tick, 2500);
      }, 2400);
    }
    if ('IntersectionObserver' in window) new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) enter(); }); }, { threshold: 0.15 }).observe(stage);
    else enter();
    addEventListener('resize', function () { if (prod() && !entered) setTimeout(enter, 60); });
  })();

  /* pricing on a phone: the other three plans fold; this opens one */
  $$('.plans.four .pc').forEach(function (c, i) {
    var b = el('button', 'ep-more ep-only', 'See what’s in this plan'); b.type = 'button'; b.id = 'epMore' + i;
    b.addEventListener('click', function () { var open = c.classList.toggle('ep-open'); b.textContent = open ? 'Show less' : 'See what’s in this plan'; });
    c.appendChild(b);
  });

  /* small print: nothing a person is meant to read sits under 12px (pictures of screens are left alone) */
  function sweep() {
    var MOCK = '.sl-still, .tour-shots, .lw-pane, .lw-win, .dd-stack, .wk-main, .hx-devices, canvas, svg, .mc-wave';
    $$('#top p, #top span, section p, section span, section small, section li, section label, footer a, footer span').forEach(function (e) {
      if (e.closest(MOCK) || e.children.length) return;
      var cs = getComputedStyle(e), fs = parseFloat(cs.fontSize);
      if (fs && fs < 12 && e.textContent.trim().length > 2) e.classList.add('ep-min12');
    });
    $$('h1, h2, h3, h4, output, .pk-plan b').forEach(function (e) {
      if (e.closest('.sl-still, .tour-shots, .lw-pane, svg')) return;
      var cs = getComputedStyle(e), fs = parseFloat(cs.fontSize), ls = parseFloat(cs.letterSpacing);
      if (fs >= 22 && ls && ls / fs < -0.034 && !e.matches('.pz b')) e.classList.add('ep-loose');
    });
  }

  sweep(); setTimeout(sweep, 1800);
})();
