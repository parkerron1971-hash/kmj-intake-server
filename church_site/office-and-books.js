/* office-and-books.js: the Office and Books room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;

  /* the hero: a bank row comes in, already matched to its payout */
  var hero = document.getElementById('obHero');
  if (hero) L.loop(hero, [[0, function () { hero.classList.add('incoming'); }], [1500, function () { hero.classList.remove('incoming'); }]], 7500);

  /* month-end: six checks, then the month locks */
  var st = document.getElementById('obCloseSt'), card = document.getElementById('obClose');
  if (st && card) {
    var checks = card.querySelectorAll('.ob-chk'), n = card.querySelector('[data-to]'), bar = card.querySelector('.ob-prog i');
    var steps = [[0, function () { st.classList.add('working'); checks.forEach(function (c) { c.classList.remove('d'); c.querySelector('small').textContent = 'Left'; }); n.textContent = '0 of 6'; bar.style.setProperty('--w', '0%'); }]];
    checks.forEach(function (c, i) {
      steps.push([700 + i * 450, function () { c.classList.add('d'); c.querySelector('small').textContent = 'Done'; n.textContent = (i + 1) + ' of 6'; bar.style.setProperty('--w', ((i + 1) / 6 * 100) + '%'); }]);
    });
    steps.push([3700, function () { st.classList.remove('working'); }]);
    L.loop(st, steps, 9000);
  }

  /* sorting: nothing is booked until a person says yes */
  var so = document.getElementById('obSort');
  if (so) {
    var q = so.querySelector('.ob-queue'), sugs = so.querySelectorAll('.ob-sug.ok, .ob-sug[data-ok]');
    sugs.forEach(function (s) { s.setAttribute('data-ok', ''); });
    var steps2 = [[0, function () { sugs.forEach(function (s) { s.classList.remove('ok'); }); }]];
    sugs.forEach(function (s, i) {
      steps2.push([1200 + i * 900, function () { L.tap(q, s.querySelector('.yes')); }]);
      steps2.push([1450 + i * 900, function () { s.classList.add('ok'); }]);
    });
    L.loop(so, steps2, 8000);
  }
})();
