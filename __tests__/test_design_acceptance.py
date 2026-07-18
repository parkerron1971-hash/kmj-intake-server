# __tests__/test_design_acceptance.py
# ─────────────────────────────────────────────────────────────────────
# A5 (2026-07-18) — opt-in wrapper for scripts/design_acceptance.py.
# Skipped in normal CI (the suite runs on in-memory fakes; the harness
# needs live Supabase + Anthropic + playwright). Run deliberately with:
#   ACCEPTANCE_RUN=1 ACCEPTANCE_BUSINESS_ID=<fixture-id> \
#       pytest __tests__/test_design_acceptance.py -q
# ─────────────────────────────────────────────────────────────────────

import os
import unittest


@unittest.skipUnless(
    os.environ.get("ACCEPTANCE_RUN") == "1"
    and bool(os.environ.get("ACCEPTANCE_BUSINESS_ID")),
    "design acceptance is opt-in (ACCEPTANCE_RUN=1 + ACCEPTANCE_BUSINESS_ID)")
class TestDesignAcceptance(unittest.TestCase):
    def test_kmj_fixture_all_modes(self):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from scripts.design_acceptance import run_build, check_run, check_parity

        biz = os.environ["ACCEPTANCE_BUSINESS_ID"]
        modes = [m.strip() for m in
                 os.environ.get("ACCEPTANCE_MODES", "anthropic,moonshot,fallback").split(",")
                 if m.strip()]
        runs = {}
        failures = []
        for mode in modes:
            run = run_build(biz, mode)
            runs[mode] = run
            failures.extend(f"{mode}: {f}" for f in check_run(run))
        for a, b in (("anthropic", "moonshot"), ("fallback", "moonshot")):
            if a in runs and b in runs:
                failures.extend(f"parity {a}~{b}: {f}"
                                for f in check_parity(runs[a], runs[b]))
        self.assertEqual(failures, [],
                         "design acceptance failures:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
