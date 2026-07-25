# __tests__/conftest.py
import os

# The easel step (canvas self-review, Director's Cut arc 2) launches
# real chromium screenshots and a vision call when left on — unit tests
# must never pay for either (a local playwright install made the whole
# canvas suite take 60s+ and would have burned API tokens with a key in
# the env). Tests that exercise the switch itself re-enable it via
# mock.patch.dict.
os.environ.setdefault("CANVAS_VISION_LOOP", "off")

# Same rule for builder v2's vision loop (the eyes): screenshots + a
# vision call belong to real builds, never to unit tests.
os.environ.setdefault("SITE_V2_VISION_LOOP", "off")
