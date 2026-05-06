"""Ghost numbers: large translucent numerals drifting in section backgrounds."""


def render_styles() -> str:
    """CSS for ghost numbers. Include once per page."""
    return """
<style>
.ghost-number {
  position: absolute;
  font-family: var(--font-display, Georgia, serif);
  font-size: clamp(4rem, 9vw, 7rem);
  line-height: 1;
  color: rgba(255,255,255,0.04);
  pointer-events: none;
  z-index: 0;
  will-change: transform;
}
.ghost-number.dark { color: rgba(0,0,0,0.04); }
@media (prefers-reduced-motion: reduce) {
  .ghost-number { transform: none !important; }
}
</style>
"""


def render_script() -> str:
    """JS for parallax drift. Include once per page."""
    return """
<script>
(function() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var ghosts = document.querySelectorAll('.ghost-number');
  if (!ghosts.length) return;
  var ticking = false;
  function drift() {
    ghosts.forEach(function(el, i) {
      if (!el.parentElement) return;
      var rect = el.parentElement.getBoundingClientRect();
      var move = rect.top * -0.03 * (i + 1);
      el.style.transform = 'translate3d(0,' + move + 'px,0)';
    });
    ticking = false;
  }
  window.addEventListener('scroll', function() {
    if (!ticking) { requestAnimationFrame(drift); ticking = true; }
  }, { passive: true });
  drift();
})();
</script>
"""


def render_inline(number: str, position: str = "top-right", strand: str = "light") -> str:
    """Render an inline ghost number HTML.
    position: 'top-right' | 'top-left' | 'center'
    strand: 'light' (white text) | 'dark' (black text)
    """
    pos_styles = {
        "top-right": "top:1rem; right:1rem;",
        "top-left": "top:1rem; left:1rem;",
        "center": "top:50%; left:50%; transform:translate(-50%,-50%);",
    }.get(position, "top:1rem; right:1rem;")

    strand_class = "dark" if strand == "dark" else ""
    return f'<span class="ghost-number {strand_class}" style="{pos_styles}">{number}</span>'
