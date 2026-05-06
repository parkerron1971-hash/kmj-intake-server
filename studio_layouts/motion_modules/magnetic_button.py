"""Magnetic button: CTA that follows cursor on hover within a small radius."""


def render_styles() -> str:
    """CSS for magnetic effect. Include once per page."""
    return """
<style>
.magnetic { transition: transform 0.3s ease-out; }
@media (prefers-reduced-motion: reduce) {
  .magnetic { transition: none !important; transform: none !important; }
}
</style>
"""


def render_script() -> str:
    """JS for magnetic effect. Include once per page."""
    return """
<script>
(function() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if ('ontouchstart' in window) return;
  var magnets = document.querySelectorAll('.magnetic');
  if (!magnets.length) return;
  var threshold = 80;
  magnets.forEach(function(el) {
    el.addEventListener('mousemove', function(e) {
      var rect = el.getBoundingClientRect();
      var relX = e.clientX - rect.left - rect.width / 2;
      var relY = e.clientY - rect.top - rect.height / 2;
      var dist = Math.sqrt(relX * relX + relY * relY);
      if (dist < threshold) {
        el.style.transform = 'translate(' + (relX * 0.08) + 'px,' + (relY * 0.08) + 'px)';
      }
    });
    el.addEventListener('mouseleave', function() { el.style.transform = ''; });
  });
})();
</script>
"""
