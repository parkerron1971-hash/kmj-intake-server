"""Studio Brut Hero — Pass 4.0g Phase B.

Eleven-variant Hero section library authored from Studio Brut's DNA
(see STUDIO_BRUT_DESIGN.md in the parent directory). Each variant is
one Python function in variants/ returning an HTML <section> string.

Studio Brut variants are NOT mirrors of Cathedral variants — they're
invented from the design doc's principles: color-block architecture,
type-as-graphic, asymmetry baseline, sharp commits, density over
breathing room.

Public surface:
  types.py          Pydantic models for compositions + treatments
                    (own VariantId Literal, own IMAGE_USING_VARIANTS)
  primitives/       Shared rendering fragments — heading uses weight
                    contrast (not italic emphasis), ornament_marker
                    emits squares/bars/circles (never diamonds),
                    type_ornament for oversized letterforms.
  treatments/       Eight treatment translators interpreting the
                    shared dimension framework through Studio Brut's
                    DNA values.
  variants/         11 hero variants (Phase B).
"""
