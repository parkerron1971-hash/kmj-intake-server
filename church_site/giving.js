/* giving.js: the Giving room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;

  /* the hero: Ruth gives, the office sees it land */
  var hero = document.getElementById('guHero');
  if (hero) {
    var nums = hero.querySelectorAll('[data-to]'), scr = hero.querySelector('.gu-hero-phone .lit-screen');
    var btn = hero.querySelector('.gu-hero-phone .gu-btn');
    L.loop(hero, [
      [0, function () { hero.classList.remove('press', 'sent', 'landed'); nums.forEach(L.reset); }],
      [1500, function () { hero.classList.add('press'); L.tap(scr, btn); }],
      [1800, function () { hero.classList.remove('press'); }],
      [2200, function () { hero.classList.add('sent'); }],
      [3000, function () { hero.classList.add('landed'); nums.forEach(function (n) { L.count(n); }); }],
      [5600, function () { hero.classList.remove('sent'); }]
    ], 9000, function () { hero.classList.add('landed'); nums.forEach(function (n) { L.count(n); }); });
  }

  /* monthly gifts: pause it, resume it, no call to the office */
  var rec = document.getElementById('guRecur');
  if (rec) {
    var rs = rec.querySelector('.lit-screen'), q = function (k) { return rec.querySelector('[data-t="' + k + '"]'); };
    L.loop(rec, [
      [0, function () { rec.classList.remove('sheet', 'paused'); }],
      [1400, function () { L.tap(rs, q('pause')); }],
      [1800, function () { rec.classList.add('sheet'); }],
      [3400, function () { L.tap(rs, q('go')); }],
      [3800, function () { rec.classList.remove('sheet'); rec.classList.add('paused'); }],
      [6600, function () { L.tap(rs, q('res')); }],
      [7000, function () { rec.classList.remove('paused'); }]
    ], 9400);
  }

  /* funds: full at rest; once the script is watching, the glass fills when it's seen */
  var funds = document.querySelector('.gu-funds');
  if (funds && !L.reduce) {
    funds.classList.add('armed');
    funds.querySelectorAll('.gu-jar [data-to]').forEach(L.reset);
  }

  /* statements: Chief has them ready; a person presses send */
  var st = document.getElementById('guState');
  if (st) {
    var card = st.querySelector('.gu-chief');
    L.loop(st, [
      [0, function () { st.classList.remove('sent'); }],
      [1800, function () { L.tap(card, st.querySelector('[data-t="send"]')); }],
      [2200, function () { st.classList.add('sent'); }]
    ], 8000, function () { st.classList.add('sent'); });
  }
})();
