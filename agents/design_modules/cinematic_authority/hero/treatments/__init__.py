"""Treatment-to-CSS-variable translators. Each treatment file exports
one function that takes the treatment value and returns a dict of CSS
variable name → value. The render layer merges all three dicts and
injects them as inline :root-scoped styles on the section.

Treatments compose orthogonally — color, spacing, and emphasis-weight
are independent dimensions of the same section. 3 × 3 × 3 = 27 unique
treatment combinations per variant.
"""

from .color_emphasis import color_emphasis_vars
from .spacing_density import spacing_density_vars
from .emphasis_weight import emphasis_weight_vars

__all__ = [
    "color_emphasis_vars",
    "spacing_density_vars",
    "emphasis_weight_vars",
]
