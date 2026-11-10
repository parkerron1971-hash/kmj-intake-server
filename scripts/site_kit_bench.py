"""The kit test: assemble pages from finished sections and grade them like the builder's.

Kevin, 2026-11-10: "fix the two gaps first and make it happen." Two pages:
  barber      Marrow & Steel, the bench barbershop with two photos. Its blueprint
              is the one the builder's page was built from (graded 27/40), so the
              comparison is the same design decisions, assembled instead of written.
  foodtruck   Smoke Signal BBQ, a made-up truck with no photos that moves around:
              the kit has no section for this week's stops, so the hybrid writes one.

Nothing here can touch production data or customers:
  * every secret except the Anthropic key is deleted before anything is imported
  * the database address doesn't exist; database, messaging and payment hosts are
    refused at the socket
It spends on production's Anthropic key: the food truck's blueprint (about 90 cents),
the words (a few cents each), one custom section (about 20 cents), and the grader
(about 30 cents a page). Every finished step is saved, so a rerun doesn't pay twice.

usage (from the Railway-linked checkout, so the key is present):
  railway run python <kit worktree>/scripts/site_kit_bench.py --dry      assemble only, no model calls
  railway run python <kit worktree>/scripts/site_kit_bench.py            both pages
  railway run python <kit worktree>/scripts/site_kit_bench.py barber --regrade
"""
import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("names", nargs="*")
parser.add_argument("--dry", action="store_true", help="no model calls: assemble from saved sheets or a stub")
parser.add_argument("--out", default=str(Path(os.environ.get("TEMP") or "/tmp") / "site-kit-bench"))
parser.add_argument("--barber-spec", default="", help="the builder test's saved blueprint for the barber")
parser.add_argument("--testbuild", default="", help="the builder test's folder: its fixtures and blueprints are reused")
parser.add_argument("--regrade", action="store_true")
parser.add_argument("--no-grade", action="store_true")
parser.add_argument("--cap-cents", type=float, default=400)
ARGS = parser.parse_args()

keep = os.environ.get("ANTHROPIC_API_KEY", "")
for name in list(os.environ):
    upper = name.upper()
    if name != "ANTHROPIC_API_KEY" and any(w in upper for w in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DSN", "SUPABASE", "DATABASE")):
        del os.environ[name]
os.environ.update(SUPABASE_URL="http://bench.invalid", SUPABASE_SERVICE_ROLE_KEY="bench", SUPABASE_ANON="bench",
                  PYTHONIOENCODING="utf-8")
if not keep and not ARGS.dry:
    sys.exit("No ANTHROPIC_API_KEY: run it with `railway run` from the linked checkout.")
_real = socket.getaddrinfo
REFUSED = ("supabase", "twilio", "resend", "stripe", "sentry", "docuseal", "livekit", "plaid", "bench.invalid")


def _guard(host, *a, **k):
    if isinstance(host, str) and any(r in host.lower() for r in REFUSED):
        raise OSError(f"refused in the kit bench: {host}")
    return _real(host, *a, **k)


socket.getaddrinfo = _guard
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
os.chdir(TREE)
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "scripts"))

import api_usage_logger  # noqa: E402
import site_kit  # noqa: E402

ROWS = api_usage_logger.capture_in_memory()
FIXTURES = {
    "barber": TREE / "scripts/fixtures/marrow_and_steel.json",
    "foodtruck": TREE / "scripts/fixtures/smoke_signal_bbq.json",
    "lovecity": TREE / "scripts/fixtures/marrow_and_steel.json",      # replaced from --testbuild
    "gracepoint": TREE / "scripts/fixtures/gracepoint_church.json",
    "harborlight": TREE / "scripts/fixtures/harbor_light_church.json",
    "speaker": TREE / "scripts/fixtures/renee_okafor_speaker.json",
    "lc_bulletin": TREE / "scripts/fixtures/marrow_and_steel.json",   # replaced from --testbuild
    "lc_leader": TREE / "scripts/fixtures/marrow_and_steel.json",     # replaced from --testbuild
    "lc_magazine": TREE / "scripts/fixtures/marrow_and_steel.json",   # replaced from --testbuild
}
# the builder test (11-09) saved these, so their blueprints are free and their pages compare
SAVED = {"barber": ("barber_two_photos.json", "barber_two_photos"), "lovecity": ("love_city.json", "love_city"),
         "lc_bulletin": ("love_city_bulletin.json", ""), "lc_leader": ("love_city_leader.json", ""),
         "lc_magazine": ("love_city_magazine.json", "")}
OUT = Path(ARGS.out)


def spent() -> float:
    return sum(float(r.get("cents") or 0) for r in ROWS)


def by_task() -> dict:
    out = {}
    for r in ROWS:
        k = f"{r.get('task_type') or r.get('endpoint')}|{r.get('model')}"
        out[k] = round(out.get(k, 0) + float(r.get("cents") or 0), 2)
    return out


def load_fixture(name: str) -> dict:
    if ARGS.testbuild and name in SAVED:
        return json.loads((Path(ARGS.testbuild) / SAVED[name][0]).read_text(encoding="utf-8"))
    fx = json.loads(FIXTURES[name].read_text(encoding="utf-8"))
    if name == "barber":
        # the builder test's barber had two photos, not the bench's full gallery
        two = Path(ARGS.barber_spec).parent.parent.parent / "barber_two_photos.json" if ARGS.barber_spec else None
        if two and two.exists():
            fx = json.loads(two.read_text(encoding="utf-8"))
    return fx


def blueprint(name: str, fx: dict, out: Path) -> str:
    f = out / "spec.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    if name == "barber" and ARGS.barber_spec:
        spec = Path(ARGS.barber_spec).read_text(encoding="utf-8")
        f.write_text(spec, encoding="utf-8")
        return spec
    if ARGS.testbuild and SAVED.get(name, ("", ""))[1]:
        spec = (Path(ARGS.testbuild) / "out" / SAVED[name][1] / "spec.txt").read_text(encoding="utf-8")
        f.write_text(spec, encoding="utf-8")
        return spec
    if ARGS.dry:
        return ""
    import site_bench
    import spec_author
    fx2 = json.loads(json.dumps(fx)) if (ARGS.testbuild and name in SAVED) else site_bench.load_fixture(str(FIXTURES[name]))
    site_bench._patch_for_fixture(fx2)
    ctx = site_bench.ctx_from_fixture(fx2)
    t = time.time()
    spec = spec_author.author_spec(ctx["business"]["id"], ctx, None, site_bench.spec_plan_for(ctx)) or ""
    print(f"  blueprint: {time.time() - t:.0f}s, {len(spec):,} chars, ${spent() / 100:.2f} so far", flush=True)
    if spec:
        f.write_text(spec, encoding="utf-8")
    return spec


def stub_words(fx: dict) -> dict:
    name = (fx.get("business") or {}).get("name") or "The Shop"
    return {"hero": {"eyebrow": name, "lines": [name, "Book a chair"], "subhead": fx.get("owner_brief", "")[:140]},
            "board": {"eyebrow": "Prices", "headline": "Every price, posted"},
            "nav": [{"label": "Prices", "target": "board"}, {"label": "Visit", "target": "visit"}]}


def measure(page: Path, out: Path) -> dict:
    import craft_laws
    from playwright.sync_api import sync_playwright
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for label, w, h in (("computer", 1440, 900), ("phone", 390, 844)):
            c = b.new_context(viewport={"width": w, "height": h})
            pg = c.new_page()
            pg.goto(page.as_uri(), wait_until="load", timeout=60000)
            pg.wait_for_timeout(2000)
            m = pg.evaluate(craft_laws.RENDER_JS)
            d = pg.evaluate("""() => ({
              sideways: (() => { scrollTo(600, 0); const x = scrollX; scrollTo(0, 0); return x; })(),
              off_side: [...document.querySelectorAll('h1,h2,h3,p,a,li,span,b')].filter(el => {
                  const r = el.getBoundingClientRect(); return r.width > 0 && (r.right > innerWidth + 1 || r.left < -1)
                  && !el.closest('[aria-hidden="true"]') && getComputedStyle(el).position !== 'fixed'; }).length,
              screens: +(document.documentElement.scrollHeight / innerHeight).toFixed(1),
              photos: new Set([...document.images].filter(i => i.naturalWidth >= 300).map(i => i.currentSrc || i.src)).size,
              words: document.body.innerText.split(/\\s+/).filter(Boolean).length,
              objects: [...new Set([...document.querySelectorAll('[data-sx-object]')].map(e => e.dataset.sxObject))] })""")
            res[label] = dict(d, opening_px=m.get("opening_px"))
            total = pg.evaluate("document.documentElement.scrollHeight")
            for i, f in enumerate((0, .15, .3, .45, .6, .8)):
                pg.evaluate(f"scrollTo(0,{total * f})")
                pg.wait_for_timeout(450)
                pg.screenshot(path=str(out / f"{label}_{i}.jpg"), type="jpeg", quality=62)
            c.close()
        b.close()
    return res


def run(name: str) -> None:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fx = load_fixture(name)
    bid = (fx.get("business") or {}).get("id") or ""
    print(f"\n=== {name}: {fx['business']['name']} ({fx['business']['type']}), photos={len(fx.get('gallery') or [])}")
    spec = blueprint(name, fx, out)
    layout = site_kit.kit_layout(spec, fx) or ("booking" if not spec else "")
    print(f"  layout: {layout or 'NOT IN THE KIT'}")
    if not layout:
        return
    wf = out / "words.json"
    if wf.exists():
        words = json.loads(wf.read_text(encoding="utf-8"))
    elif ARGS.dry or not spec:
        words = stub_words(fx)
        print("  words: a stub (dry run)")
    else:
        t = time.time()
        words = site_kit.write_words(spec, fx, bid, layout)
        wf.write_text(json.dumps(words, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"  words: {time.time() - t:.0f}s, ${spent() / 100:.2f} so far; custom asked: "
              f"{[c.get('id') for c in words.get('custom') or [] if c.get('id')]}", flush=True)
    cf = out / "custom.json"
    custom = []
    if cf.exists():
        custom = json.loads(cf.read_text(encoding="utf-8"))
    elif not ARGS.dry:
        for brief in [c for c in words.get("custom") or [] if c.get("id") and c.get("brief")][:2]:
            if spent() >= ARGS.cap_cents:
                print("  STOP: at the cap; no custom section")
                break
            t = time.time()
            c = site_kit.write_custom(brief, words, fx, bid)
            ok, why = site_kit.custom_ok(c["html"], c["css"])
            print(f"  custom {c['id']}: {time.time() - t:.0f}s, ok={ok} {why}, ${spent() / 100:.2f} so far", flush=True)
            custom.append(c)
        cf.write_text(json.dumps(custom, indent=1, ensure_ascii=False), encoding="utf-8")
    t = time.time()
    html = site_kit.assemble(fx, words, custom, layout)
    ms = (time.time() - t) * 1000
    page = out / "page.html"
    page.write_text(html, encoding="utf-8")
    print(f"  assembled in {ms:.0f} ms, {len(html):,} bytes -> {page}")
    m = measure(page, out)
    (out / "measure.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    print("  measured:", json.dumps(m)[:600], flush=True)
    gf = out / "grade.json"
    if ARGS.dry or ARGS.no_grade or (gf.exists() and not ARGS.regrade):
        if gf.exists():
            print("  grade (saved):", json.loads(gf.read_text(encoding="utf-8")).get("total"))
        return
    if spent() >= ARGS.cap_cents:
        print("  STOP: at the cap; not grading")
        return
    import vision_grader
    v = vision_grader.grade(html, bid) or {}
    keys = ("first_viewport_impact", "balance", "motif_visibility", "rhythm")
    v["total"] = sum(int(v.get(k) or 0) for k in keys)
    gf.write_text(json.dumps(v, indent=1, default=str), encoding="utf-8")
    print(f"  GRADE {v['total']}/40:", json.dumps({k: v.get(k) for k in keys + ("template_smell", "broken", "broken_where")})[:600])
    print("  notes:", json.dumps(v.get("notes"))[:900], flush=True)


def main() -> None:
    print("key present:", bool(keep), "| dry:", ARGS.dry, "| out:", OUT)
    try:
        socket.getaddrinfo("example.supabase.co", 443)
        print("socket guard FAILED")
        return
    except OSError as e:
        print("socket guard holds:", e)
    for name in ARGS.names or ["barber", "foodtruck"]:
        try:
            run(name)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  {name} crashed: {type(e).__name__}: {e}", flush=True)
        print(f"  --- spent so far: ${spent() / 100:.2f}", flush=True)
    print("\nby task:", json.dumps(by_task(), indent=0))
    print(f"TOTAL ${spent() / 100:.2f}")


main()
