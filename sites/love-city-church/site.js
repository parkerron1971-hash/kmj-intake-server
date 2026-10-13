(function () {
  // The phone menu. Without script the links simply show, stacked (the
  // 'js' class that hides them is set in the head).
  var toggle = document.querySelector('[data-nav-toggle]');
  var links = document.querySelector('[data-nav-links]');
  if (!toggle || !links) return;
  function set(open) {
    links.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  toggle.addEventListener('click', function () {
    set(toggle.getAttribute('aria-expanded') !== 'true');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && links.classList.contains('open')) { set(false); toggle.focus(); }
  });
})();
