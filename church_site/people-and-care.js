/* people-and-care.js: the People and Care room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;

  /* the hero: a guest's card lands on the board, then on the leader's Lead tab */
  var hero = document.getElementById('pcHero');
  if (hero) L.loop(hero, [
    [0, function () { hero.classList.add('arriving', 'handing'); }],
    [1100, function () { hero.classList.remove('arriving'); }],
    [2500, function () { hero.classList.remove('handing'); }]
  ], 9000);

  /* shepherds: you move a family, then approve, and each shepherd gets one email */
  var sh = document.getElementById('shepherds'), map = document.getElementById('pcMap');
  if (sh && map) {
    var ok = sh.querySelector('.pc-ok');
    L.loop(sh, [
      [0, function () { map.classList.remove('moved'); sh.classList.remove('sent'); }],
      [1500, function () { map.classList.add('moved'); }],
      [3200, function () { L.tap(ok, sh.querySelector('[data-t="go"]')); }],
      [3500, function () { sh.classList.add('sent'); }]
    ], 8500);
  }

  /* Sundays: one tap counts the family */
  var sun = document.getElementById('pcSun');
  if (sun) {
    var mems = sun.querySelectorAll('.pc-mem'), scr = sun.querySelector('.lit-screen');
    var steps = [[0, function () { mems.forEach(function (m) { m.classList.remove('on'); }); }]];
    mems.forEach(function (m, i) { steps.push([900 + i * 450, function () { L.tap(scr, m); m.classList.add('on'); }]); });
    steps.push([2600, function () { L.tap(scr, sun.querySelector('[data-t="here"]')); }]);
    L.loop(sun, steps, 7500);
  }

  /* prayer: sent to the prayer team, it reaches the Intercessor leader */
  var pr = document.getElementById('pcPray');
  if (pr) {
    var ps = pr.querySelector('.lit-screen');
    L.loop(pr, [
      [0, function () { pr.classList.add('asking'); }],
      [1700, function () { L.tap(ps, pr.querySelector('[data-t="ask"]')); }],
      [2100, function () { pr.classList.remove('asking'); }]
    ], 8000);
  }
})();
