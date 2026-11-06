/* website-and-sermons.js: the Website and Sermons room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;
  var flip = function (el, cls, onAt, period) {
    if (el) L.loop(el, [[0, function () { el.classList.add(cls); }], [onAt, function () { el.classList.remove(cls); }]], period);
  };

  /* the hero: Sunday's message appears on the site and in Watch */
  flip(document.getElementById('wsHero'), 'fresh', 1400, 7500);
  /* sermons: the note members get when a new message is up */
  flip(document.getElementById('wsSermons'), 'quiet', 1500, 7500);

  /* events: the last kitchen spot is taken, and that job's form closes */
  var ev = document.getElementById('wsEvents'), k = document.getElementById('wsKitchen');
  if (ev && k) {
    var n = k.querySelector('[data-to]'), bar = k.querySelector('s i');
    L.loop(ev, [
      [0, function () { ev.classList.add('quiet'); k.classList.remove('isfull'); L.reset(n); bar.style.setProperty('--w', '83%'); }],
      [1700, function () { L.count(n, 300); bar.style.setProperty('--w', '100%'); }],
      [2300, function () { k.classList.add('isfull'); }],
      [3300, function () { ev.classList.remove('quiet'); }]
    ], 8000);
  }

  /* visitors: a late question, answered from the site */
  flip(document.getElementById('wsVis'), 'thinking', 1900, 7500);
})();
