#!/usr/bin/env python
# scripts/site_bench.py
# ─────────────────────────────────────────────────────────────────────
# THE SITE BENCH (2026-09-04, from the barbershop bench).
#
# Review a site build for free, before paying for one. The live build is
# one model call reading a Director blueprint plus a REAL DATA block,
# behind a stack of deterministic laws. This script runs the repo's own
# prompt assemblers and validators on a business — a JSON fixture, or a
# live business id — with ZERO model calls, and prints exactly what the
# models would be handed. A person (or a Claude session) then plays the
# model, and the same script grades the page the way builder_v2 would.
#
#   python scripts/site_bench.py director --fixture scripts/fixtures/marrow_and_steel.json
#       → the Director's exact user prompt (add --system for the system prompt)
#   python scripts/site_bench.py builder  --fixture ... --spec spec.txt
#       → builder_v2's exact user prompt (the blueprint + REAL DATA)
#   python scripts/site_bench.py realdata --fixture ...
#       → the REAL DATA block alone
#   python scripts/site_bench.py validate --fixture ... page.html
#       → every builder_v2 law on that page, as JSON
#   python scripts/site_bench.py shoot page.html [--out DIR]
#       → 1440 and 390 screenshots, fold + full page (needs playwright);
#         unreachable photo urls are swapped for labeled dark stand-ins
#
# --business <id> instead of --fixture reads the live context through
# site_composer.gather_context (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
# in the env) and, for `builder`, the approved blueprint on file.
#
# What the bench found the first time it ran (all fixed the same day):
# the owner's prompt cut at 600 chars, durations never reaching the
# authors, the tenure law stripping the owner's own "14 years", and the
# builder prompt banning the hexes its rule 7 required. Run it again
# whenever a prompt or a validator changes; it is the cheapest review
# loop this pipeline has.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SUPABASE_URL", "http://bench.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "bench")
os.environ.setdefault("SUPABASE_ANON", "bench")
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

RAILWAY = "https://kmj-intake-server-production.up.railway.app"


# ─── the fixture → ctx ───────────────────────────────────────────────

def load_fixture(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ctx_from_fixture(fx: Dict[str, Any]) -> Dict[str, Any]:
    """The shape site_composer.gather_context returns, from a fixture.
    Only the keys the Director's and builder's assemblers read."""
    biz = fx.get("business") or {}
    bid = biz.get("id") or "00000000-0000-4000-8000-00000000bench"
    contact = dict(fx.get("contact") or {})
    contact.setdefault("submit_url", f"{RAILWAY}/sites/{bid}/contact-submit")
    booking_url = fx.get("booking_url") or ""
    tone = ((fx.get("discovery_dossier") or {}).get("taste") or {}).get("tone_words", {})
    tone_words = tone.get("value") if isinstance(tone, dict) else (tone or [])
    return {
        "business": {"id": bid, "name": biz.get("name") or "", "type": biz.get("type") or "",
                     "slug": biz.get("slug") or "bench", "created_at": biz.get("created_at") or ""},
        "settings": {"contact_email": contact.get("email", ""), "contact_phone": contact.get("phone", ""),
                     "address": contact.get("address", ""), "brand_kit": fx.get("brand_kit") or {},
                     **({"doc_defaults": {"founded": str(fx["founded_year"])}} if fx.get("founded_year") else {})},
        "voice_profile": {},
        "site": {"site_config": {"slots": fx.get("slots") or {},
                                 "discovery_dossier": fx.get("discovery_dossier") or {},
                                 "owner_brief": fx.get("owner_brief") or ""}},
        "owner_brief": fx.get("owner_brief") or "",
        "offerings": list(fx.get("offerings") or []),
        "testimonials": list(fx.get("testimonials") or []),
        "gallery": list(fx.get("gallery") or []),
        "faq": list(fx.get("faq") or []),
        "business_picture": {},
        "booking": {"enabled": bool(booking_url), "url": booking_url},
        "giving": {},
        "public_modules": [],
        "contact": contact,
        "footer": {},
        "bundle": {"voice": {"tone_words": tone_words or []},
                   "practitioner": {"name": fx.get("practitioner_name") or "", "email": contact.get("email", "")}},
        "dna": {},
        "site_prefs": {"tone_words": tone_words or []},
        "store": {"enabled": bool(fx.get("store_url"))},
        "connections": {"booking": bool(booking_url), "store": bool(fx.get("store_url"))},
        "cta_goal": "book" if booking_url else "contact",
        "color_source": "none",
        "_bench_fixture": fx,
    }


def _patch_for_fixture(fx: Dict[str, Any]) -> None:
    """The three seams that read the database, answered from the fixture."""
    import builder_v2
    import site_facts

    def _csb(business_id, ctx=None):
        lines: List[str] = []
        if fx.get("booking_url"):
            lines.append(f"- BOOKING: ON — every book/schedule action links to {fx['booking_url']}")
        if fx.get("store_url"):
            lines.append(f"- STORE: ON — the shop moment links to {fx['store_url']}")
        if not lines:
            return ""
        return ("CONNECTED SYSTEMS (working doors the owner turned on — each url below "
                "MUST appear on the page as a real link; never invent a door not listed here):\n"
                + "\n".join(lines))
    builder_v2.connected_systems_block = _csb
    site_facts._profile_row = lambda bid: dict(fx.get("profile") or {})
    try:
        import brand_mark
        mark = fx.get("brand_mark_url")
        brand_mark.real_data_block = (
            (lambda ctx, bid, name: f"THE BRAND MARK (the header logo, and nothing else): {mark}")
            if mark else
            (lambda ctx, bid, name: "THE BRAND MARK: none supplied. Set a typographic wordmark in the header."))
    except Exception:
        pass


def load_ctx(args) -> Dict[str, Any]:
    if args.fixture:
        fx = load_fixture(args.fixture)
        _patch_for_fixture(fx)
        return ctx_from_fixture(fx)
    if args.business:
        import site_composer
        return site_composer.gather_context(args.business)
    sys.exit("give --fixture PATH or --business ID")


def spec_plan_for(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    fx = ctx.get("_bench_fixture") or {}
    if fx.get("spec_plan"):
        return list(fx["spec_plan"])
    plan = [{"module": "hero", "variant": "cinematic", "content": {}}]
    if ctx.get("offerings"):
        plan.append({"module": "offerings", "variant": "menu", "content": {}})
    if ctx.get("gallery"):
        plan.append({"module": "gallery", "variant": "mosaic", "content": {}})
    if ctx.get("testimonials"):
        plan.append({"module": "testimonials", "variant": "spotlight", "content": {}})
    plan.append({"module": "about", "variant": "portrait", "content": {}})
    if ctx.get("faq"):
        plan.append({"module": "faq", "variant": "ledger", "content": {}})
    plan.append({"module": "contact", "variant": "standard", "content": {}})
    return plan


# ─── the commands ────────────────────────────────────────────────────

def director_prompt(ctx: Dict[str, Any]) -> str:
    import canvas_brief
    import discovery
    import site_facts
    import spec_author
    bid = (ctx.get("business") or {}).get("id") or ""
    plan = spec_plan_for(ctx)
    try:
        dossier = canvas_brief.compile_canvas_brief(ctx, None, plan)
    except Exception as e:
        dossier = f"(compile_canvas_brief failed offline: {e!r})"
    inventory = spec_author._inventory_digest(ctx, plan)
    dd = ((ctx.get("site") or {}).get("site_config") or {}).get("discovery_dossier")
    disc = discovery.dossier_digest(dd) if dd else ""
    facts = site_facts.facts_block(site_facts.build_facts(ctx, bid))
    vertical = ""
    try:
        import site_vertical_features
        vertical = site_vertical_features.block_for(str((ctx.get("business") or {}).get("type") or ""))
    except Exception:
        pass
    kwargs = dict(inventory=inventory, discovery=disc, facts=facts)
    if "vertical" in spec_author.build_user_prompt.__code__.co_varnames:
        kwargs["vertical"] = vertical
    return spec_author.build_user_prompt(dossier, plan, **kwargs)


def real_data(ctx: Dict[str, Any]) -> str:
    import builder_v2
    return builder_v2.assemble_real_data(ctx, (ctx.get("business") or {}).get("id") or "")


def builder_prompt(ctx: Dict[str, Any], spec_text: str) -> str:
    import builder_v2
    return builder_v2.build_user_prompt(spec_text, real_data(ctx))


def validate(ctx: Dict[str, Any], html: str) -> Dict[str, Any]:
    import builder_v2
    bid = (ctx.get("business") or {}).get("id") or ""
    rd = real_data(ctx)
    ep = builder_v2.contact_endpoint(bid)
    out: Dict[str, Any] = {}
    doc = builder_v2._parse_doc(html)
    out["parse"] = "ok" if doc else "FAILED (not a complete document)"
    doc = doc or html
    doc, dropped = builder_v2.armor_scripts(doc, ep)
    out["armor_scripts_dropped"] = dropped
    out["armor_violations"] = builder_v2.armor_violations(dropped, ep)
    doc, ext = builder_v2.armor_external(doc)
    out["armor_external_stripped"] = ext
    for name in ("check_truth", "check_tenure", "check_coverage", "check_grammar",
                 "check_head", "check_interactions", "check_stand_ins", "check_connected"):
        fn = getattr(builder_v2, name, None)
        if fn is None:
            continue
        try:
            out[name] = fn(doc, rd) if fn.__code__.co_argcount >= 2 else fn(doc)
        except Exception as e:
            out[name] = [f"(validator error: {e!r})"]
    _, n = builder_v2.annotate_editability(doc)
    out["editability_stamps_added_by_annotator"] = n
    out["bytes"] = len(doc.encode("utf-8"))
    out["violations_total"] = sum(len(v) for k, v in out.items()
                                  if k.startswith("check_") or k == "armor_violations")
    return out


_URL_RE = re.compile(r"https?://[^\s\"'<>)]+\.(?:jpe?g|png|webp|gif)", re.IGNORECASE)


def _stand_in(label: str, w: int = 900, h: int = 1125) -> str:
    g = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
         f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='#2b2724'/>"
         f"<stop offset='1' stop-color='#0d0c0b'/></linearGradient></defs>"
         f"<rect width='{w}' height='{h}' fill='url(#g)'/>"
         f"<text x='{w*0.05:.0f}' y='{h*0.94:.0f}' fill='#8d877c' font-family='Arial' "
         f"font-size='{min(w,h)*0.04:.0f}' letter-spacing='2'>PHOTO STAND-IN: {label}</text></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(g.encode()).decode()


def shoot(path: str, out_dir: str) -> List[str]:
    """Screenshots the way the builder's eyes take them, with stand-ins
    for photo urls that do not resolve (fixtures have none)."""
    from playwright.sync_api import sync_playwright
    html = open(path, encoding="utf-8").read()
    tag = os.path.splitext(os.path.basename(path))[0]
    seen: Dict[str, str] = {}

    def sub(m):
        u = m.group(0)
        if u not in seen:
            seen[u] = _stand_in(os.path.basename(u).rsplit(".", 1)[0].replace("&", "&amp;"))
        return seen[u]
    preview = _URL_RE.sub(sub, html)
    os.makedirs(out_dir, exist_ok=True)
    pv = os.path.join(out_dir, f"preview_{tag}.html")
    open(pv, "w", encoding="utf-8").write(preview)
    written = [pv]
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, h in ((1440, 900), (390, 844)):
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto("file:///" + os.path.abspath(pv).replace(os.sep, "/"))
            pg.wait_for_timeout(1500)
            pg.add_style_tag(content="html{scroll-behavior:auto!important}")
            total = pg.evaluate("document.body.scrollHeight")
            for y in range(0, int(total), max(300, h // 2)):
                pg.evaluate(f"window.scrollTo(0,{y})")
                pg.wait_for_timeout(100)
            pg.evaluate("window.scrollTo(0,0)")
            pg.wait_for_timeout(800)
            for kind, full in (("fold", False), ("full", True)):
                f = os.path.join(out_dir, f"shot_{tag}_{w}_{kind}.png")
                pg.screenshot(path=f, full_page=full)
                written.append(f)
        b.close()
    return written


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Review a site build with zero model calls.")
    ap.add_argument("command", choices=("director", "builder", "realdata", "validate", "shoot"))
    ap.add_argument("page", nargs="?", help="page.html for validate / shoot")
    ap.add_argument("--fixture", help="JSON fixture (see scripts/fixtures/)")
    ap.add_argument("--business", help="live business id (needs SUPABASE env)")
    ap.add_argument("--spec", help="blueprint text file for `builder`")
    ap.add_argument("--system", action="store_true", help="also print the system prompt")
    ap.add_argument("--out", default="bench_out", help="output dir for `shoot`")
    args = ap.parse_args(argv)

    if args.command == "shoot":
        if not args.page:
            sys.exit("shoot needs page.html")
        for f in shoot(args.page, args.out):
            print(f)
        return 0

    ctx = load_ctx(args)
    if args.command == "director":
        if args.system:
            import spec_author
            print("== SYSTEM ==\n" + spec_author._SYSTEM + "\n\n== USER ==")
        print(director_prompt(ctx))
    elif args.command == "realdata":
        print(real_data(ctx))
    elif args.command == "builder":
        if args.spec:
            spec = open(args.spec, encoding="utf-8").read()
        elif args.business:
            import spec_author
            spec = spec_author.approved_spec_text(args.business)
        else:
            sys.exit("builder needs --spec FILE (or --business with an approved blueprint)")
        if args.system:
            import builder_v2
            print("== SYSTEM ==\n" + builder_v2._SYSTEM + "\n\n== USER ==")
        print(builder_prompt(ctx, spec))
    elif args.command == "validate":
        if not args.page:
            sys.exit("validate needs page.html")
        html = open(args.page, encoding="utf-8").read()
        print(json.dumps(validate(ctx, html), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
