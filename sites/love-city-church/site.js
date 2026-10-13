(function () {
  // The menu: a full-screen panel. Without script its links simply show
  // under the header (the 'js' class that hides them is set in the head).
  var root = document.documentElement;
  var toggle = document.querySelector('[data-menu-toggle]');
  var menu = document.querySelector('[data-menu]');
  var word = document.querySelector('[data-menu-word]');
  if (!toggle || !menu) return;
  function set(open) {
    root.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (word) word.textContent = open ? 'Close' : 'Menu';
    if (open) { var first = menu.querySelector('a'); if (first) first.focus(); }
  }
  toggle.addEventListener('click', function () {
    set(toggle.getAttribute('aria-expanded') !== 'true');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && root.classList.contains('menu-open')) { set(false); toggle.focus(); }
  });
})();
