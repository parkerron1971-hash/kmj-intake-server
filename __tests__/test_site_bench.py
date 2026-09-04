"""The site bench runs with zero model calls (2026-09-04). It hands back
exactly what the Director and the builder would be handed, and grades a
page with the builder's own laws. Playwright is not exercised here."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "site_bench.py")
FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "marrow_and_steel.json")


def _run(*argv):
    r = subprocess.run([sys.executable, SCRIPT, *argv], capture_output=True,
                       text=True, encoding="utf-8", cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout


def test_director_prompt_carries_everything_the_bench_fixed():
    out = _run("director", "--fixture", FIXTURE)
    assert "THE OWNER'S WORDS" in out
    assert "Price list on the site, people always ask." in out     # uncut
    assert '"duration_min": 45' in out                              # durations ride
    assert "Years the owner stated" in out and "14 years" in out    # stated tenure
    assert "MUST DECIDE" in out and "TODAY'S HOURS" in out          # the vertical list
    assert "BOOKING: ON" in out


def test_builder_prompt_and_real_data(tmp_path):
    spec = tmp_path / "spec.txt"
    spec.write_text("1. OVERVIEW\nA dark shop page.\n", encoding="utf-8")
    out = _run("builder", "--fixture", FIXTURE, "--spec", str(spec))
    assert "THE APPROVED SPEC" in out and "A dark shop page." in out
    assert "THE REAL DATA" in out and "THE OWNER'S WORDS" in out
    assert "IMG_4471.jpg" in out


def test_validate_grades_a_page_with_the_builders_laws(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        "<!DOCTYPE html><html><head><title>t</title></head><body>"
        "<nav>x</nav><p>Cutting for 14 years. 25 years of fades.</p>"
        "<form method='POST' action='x'></form><footer></footer></body></html>",
        encoding="utf-8")
    out = json.loads(_run("validate", "--fixture", FIXTURE, str(page)))
    assert out["parse"] == "ok"
    tenure = " ".join(out["check_tenure"])
    assert "14 years" not in tenure, "the owner's stated years pass"
    assert "25 years" in tenure, "an invented number still fails"
    assert out["violations_total"] >= 1
