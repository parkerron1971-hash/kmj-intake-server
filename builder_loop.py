"""
builder_loop.py — THE BUILDER WITH TOOLS (2026-08-29, the builder bench).

Kevin: "make sure we can figure out a way to build a quality design and
creative features so that the website experience is top tier … open the
capabilities more so it can create on a higher level."

builder_v2 is one sighted pass: a prompt carrying the Blueprint and a
flattened dump of real data, one document out, one surgical repair, one
look at screenshots AFTER it is finished. The builder never sees the
owner's photos (it gets URLs), never sees its own page until it is done,
and cannot ask a question mid-build. Everything creative had to be
decided upstream, in words.

This module gives the same builder a small, real toolset and a budget:

  look(url)             see a photo, the brand mark, a reference page
  render(html, width)   render its own draft and get the screenshots back,
                        plus the builder's deterministic laws and stand-in
                        findings — WHILE building
  data(section)         the real offerings / testimonials / faq / store /
                        contact / gallery / business, whole, on demand
  vocabulary(name)      a design language, a move, or a framework in full
  finish(html)          hand the document in

The fence is the point:
  · BUILDER_LOOP_MAX_TOOLS calls (default 8) and the shared output-token
    budget (builder_v2._output_budget). When either runs out the loop
    forces finish and keeps the best document it has seen — the last
    rendered draft if there is one. Never nothing.
  · Everything downstream is unchanged: armor, laws, the surgical repair,
    the eyes, the judge. The loop only replaces the single authoring call.
  · Off by default (BUILDER_V2_LOOP=on turns it on) until benched.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import builder_v2 as v2
import llm_call

logger = logging.getLogger("builder_loop")

LOOP_MAX_TOOLS_DEFAULT = 8
RENDER_WIDTHS = (1440, 390)


def enabled() -> bool:
    return (os.environ.get("BUILDER_V2_LOOP") or "off").strip().lower() \
        in ("on", "1", "true", "yes")


def max_tools() -> int:
    try:
        return max(1, int(os.environ.get("BUILDER_LOOP_MAX_TOOLS")
                          or LOOP_MAX_TOOLS_DEFAULT))
    except ValueError:
        return LOOP_MAX_TOOLS_DEFAULT


# ─── the tools, as the API sees them ─────────────────────────────────

TOOLS: List[Dict[str, Any]] = [
    {"name": "look",
     "description": "See an image from the real data (a gallery piece, the "
                    "brand mark, an owner upload) or a reference page the "
                    "owner loved. Use it to read the palette, the density, "
                    "the typography personality that already exists in their "
                    "work before you commit to yours.",
     "input_schema": {"type": "object",
                      "properties": {"url": {"type": "string"}},
                      "required": ["url"]}},
    {"name": "render",
     "description": "Render a complete draft of the page and see it the way "
                    "a visitor scrolls it (desktop top/middle/bottom, phone "
                    "top), with the builder's deterministic laws and stand-in "
                    "findings on that exact draft. Fix what you see, then "
                    "render again or finish.",
     "input_schema": {"type": "object",
                      "properties": {"html": {"type": "string"},
                                     "note": {"type": "string",
                                              "description": "what you want to check"}},
                      "required": ["html"]}},
    {"name": "data",
     "description": "The real data for one section, whole: offerings, "
                    "testimonials, faq, store, contact, gallery, business.",
     "input_schema": {"type": "object",
                      "properties": {"section": {"type": "string"}},
                      "required": ["section"]}},
    {"name": "vocabulary",
     "description": "Read a design language (mural, monograph, ledger), a "
                    "named move (THE THREAD, THE STAGE LIGHT, …), or a page "
                    "framework (gallery_studio, story_arc, …) in full — its "
                    "beliefs, its brief, its CSS primitives.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "finish",
     "description": "Hand in the complete HTML document. Call this once, "
                    "after at least one render whose findings you addressed.",
     "input_schema": {"type": "object",
                      "properties": {"html": {"type": "string"}},
                      "required": ["html"]}},
]

ROOM = """
== THE ROOM (you have tools) ==
You are not writing blind. Before you commit to a palette or a type
personality, LOOK at the owner's real work (every image url in the real
data is one call away). When a section wants the whole of something,
ask data() for it. When the spec names a language, a move or a
framework you want to execute exactly, read it with vocabulary().

Then build the whole document and RENDER it. You will see the page the
way a visitor scrolls it and the exact laws that draft breaks. Fix what
you see — dimmed reveals, bare ground beside a headline or a form,
stand-ins for photographs, a door url that is not the exact one given —
and render again. Finish only when the render shows a page you would
sign. You have a budget of {n} tool calls; spend them on looking and on
rendering, not on asking for what the real data already says.
""".strip()


# ─── tool execution ──────────────────────────────────────────────────

def _image_block(url: str) -> Dict[str, Any]:
    return {"type": "image", "source": {"type": "url", "url": url}}


def _jpeg_block(data: bytes) -> Dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(data).decode()}}


class ToolBox:
    """Executes the builder's tools against one business's context.
    Remembers the last rendered document (the loop's 'never nothing')."""

    def __init__(self, ctx: Dict[str, Any], business_id: str, real_data: str,
                 endpoint: str, screenshots: Optional[Callable[[str], Any]] = None):
        self.ctx = ctx
        self.business_id = business_id
        self.real_data = real_data
        self.endpoint = endpoint
        self.screenshots = screenshots or v2._screenshot_walk
        self.last_render: Optional[str] = None
        self.last_findings: List[str] = []
        self.renders = 0
        self.looks = 0
        self.allowed_urls = set(self._urls_in(real_data))

    @staticmethod
    def _urls_in(text: str) -> List[str]:
        import re
        return re.findall(r"https?://\S+", text or "")

    def look(self, url: str) -> List[Dict[str, Any]]:
        self.looks += 1
        u = (url or "").strip().rstrip(").,")
        # Only what the real data names (an owner's image or reference) —
        # the builder reads the owner's world, it does not browse.
        if not any(u == a.rstrip(").,") for a in self.allowed_urls):
            return [{"type": "text", "text": f"{u} is not in the real data — "
                                             "look only at the owner's images and references."}]
        return [{"type": "text", "text": f"IMAGE — exact url: {u}"}, _image_block(u)]

    def render(self, html: str, note: str = "") -> List[Dict[str, Any]]:
        self.renders += 1
        doc = v2._parse_doc(html or "")
        if not doc:
            return [{"type": "text", "text": "That is not a complete HTML document "
                                             "(<!DOCTYPE html> … </html>). Send the whole page."}]
        armored, dropped = v2.armor_scripts(doc, allowed_fetch=self.endpoint)
        armored, stripped = v2.armor_external(armored)
        laws = (v2.check_truth(armored, self.real_data)
                + v2.check_tenure(armored, self.real_data)
                + v2.check_coverage(armored, self.real_data)
                + v2.check_grammar(armored) + v2.check_head(armored)
                + v2.check_interactions(armored)
                + v2.check_connected(armored, self.real_data)
                + v2.armor_violations(dropped, self.endpoint))
        standins = v2.check_stand_ins(armored)
        self.last_render = doc
        self.last_findings = laws + standins
        out: List[Dict[str, Any]] = []
        lines = [f"RENDER {self.renders}" + (f" — {note}" if note else "")]
        if laws or standins:
            lines.append(f"LAWS BROKEN ON THIS DRAFT ({len(laws)}) — each one costs a "
                         "repair round if it reaches the gate; fix them here:")
            lines += [f"- {l}" for l in laws[:10]]
            lines += [f"- {s}" for s in standins[:3]]
        else:
            lines.append("No law broken on this draft.")
        if stripped:
            lines.append(f"External requests stripped by the armor: {stripped[:4]}")
        out.append({"type": "text", "text": "\n".join(lines)})
        shots = None
        try:
            shots = self.screenshots(armored)
        except Exception as e:
            logger.info(f"[loop] screenshots unavailable: {e}")
        if shots:
            for label, jpeg in shots:
                out.append({"type": "text", "text": f"View — {label}:"})
                out.append(_jpeg_block(jpeg))
        else:
            out.append({"type": "text", "text": "(No screenshots available in this "
                                                "environment — judge from the laws.)"})
        return out

    def data(self, section: str) -> List[Dict[str, Any]]:
        s = (section or "").strip().lower()
        try:
            if s == "business":
                payload: Any = self.ctx.get("business") or {}
            elif s == "gallery":
                payload = [{"url": g.get("url"), "alt": g.get("alt") or g.get("caption")}
                           for g in (self.ctx.get("gallery") or []) if isinstance(g, dict)]
            elif s in ("offerings", "testimonials", "faq", "store", "contact", "about",
                       "statband"):
                import atelier
                payload = atelier._section_data(s, {}, self.ctx)
            else:
                return [{"type": "text", "text": f"No section called '{s}'. Sections: "
                                                 "business, gallery, offerings, testimonials, "
                                                 "faq, store, contact, about, statband."}]
        except Exception as e:
            return [{"type": "text", "text": f"data({s}) unavailable: {type(e).__name__}"}]
        text = json.dumps(payload, ensure_ascii=False)[:12000]
        return [{"type": "text", "text": f"[{s}]\n{text or '(nothing on file)'}"}]

    def vocabulary(self, name: str) -> List[Dict[str, Any]]:
        key = (name or "").strip()
        low = key.lower()
        try:
            import design_languages
            if low in design_languages.LANGUAGES:
                lang = design_languages.LANGUAGES[low]
                text = (f"LANGUAGE {lang.get('label', low)}\nbelieves: {lang.get('believes')}\n"
                        f"sings for: {lang.get('sings')}\nfails: {lang.get('fails')}\n\n"
                        f"{lang.get('brief', '')}\n\nCSS floor:\n{lang.get('css', '')}")
                return [{"type": "text", "text": text[:14000]}]
        except Exception:
            pass
        try:
            import design_moves
            for mname, mv in design_moves.MOVES.items():
                if mname.lower() == low or mname.lower() == "the " + low:
                    text = (f"MOVE {mname} ({mv.group})\nintent: {mv.intent}\n"
                            f"recur: {mv.recur}\n\nprimitive CSS (validator-legal):\n{mv.css}")
                    return [{"type": "text", "text": text[:8000]}]
        except Exception:
            pass
        try:
            import page_frameworks
            if low in page_frameworks.FRAMEWORKS:
                fw = page_frameworks.FRAMEWORKS[low]
                return [{"type": "text", "text": f"FRAMEWORK {fw.get('label')}\nwhy: {fw.get('why')}\n"
                                                 f"order: {fw.get('order')}\nabout: {fw.get('about_variant')}"}]
        except Exception:
            pass
        return [{"type": "text", "text": f"Nothing called '{key}'. Languages: mural, monograph, "
                                         "ledger. Moves: THE THREAD, TYPE AS IMAGE, THE CEREMONY, "
                                         "THE EXHIBITION, THE ECHO FRAME, THE STAGE LIGHT, THE FOIL, "
                                         "THE EMBOSS, THE TEAR, THE KINETIC HERO, THE DEPTH, THE ORBIT, "
                                         "THE PIN. Frameworks: portrait_consultant, gallery_studio, "
                                         "storefront, editorial_monolith, story_arc."}]

    def run(self, name: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        if name == "look":
            return self.look(str(args.get("url") or ""))
        if name == "render":
            return self.render(str(args.get("html") or ""), str(args.get("note") or ""))
        if name == "data":
            return self.data(str(args.get("section") or ""))
        if name == "vocabulary":
            return self.vocabulary(str(args.get("name") or ""))
        return [{"type": "text", "text": f"Unknown tool {name}."}]


# ─── the loop ────────────────────────────────────────────────────────

def _text_of(msg: Any) -> str:
    return "".join(getattr(b, "text", "") for b in getattr(msg, "content", [])
                   if getattr(b, "type", None) == "text")


def _tool_uses(msg: Any) -> List[Any]:
    return [b for b in getattr(msg, "content", []) if getattr(b, "type", None) == "tool_use"]


def _stream(client, *, model: str, max_tokens: int, system: str,
            messages: List[Dict[str, Any]], tools: List[Dict[str, Any]],
            tool_choice: Optional[Dict[str, Any]], sampling: Dict[str, Any]):
    kw: Dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system,
                              messages=messages, tools=tools, timeout=900.0, **sampling)
    if tool_choice:
        kw["tool_choice"] = tool_choice
    with client.messages.stream(**kw) as s:
        for _ in s.text_stream:
            pass
        return s.get_final_message()


def run_loop(spec_text: str, ctx: Dict[str, Any], business_id: str,
             spend: Dict[str, Any], progress_cb: Optional[Callable[[int, str], None]] = None,
             toolbox: Optional[ToolBox] = None, client: Any = None,
             model: Optional[str] = None) -> Dict[str, Any]:
    """The authoring stage with tools. Returns {"html": doc|None,
    "report": {...}}; the caller (builder_v2.run_builder_v2) carries on
    with armor, laws, repair and eyes exactly as before."""
    import model_ladder
    real_data = v2.assemble_real_data(ctx, business_id)
    endpoint = v2.contact_endpoint(business_id)
    box = toolbox or ToolBox(ctx, business_id, real_data, endpoint)
    model = model or v2._model()
    report: Dict[str, Any] = {"tool_calls": 0, "renders": 0, "looks": 0,
                              "forced_finish": None, "tools_used": []}

    def _progress(pct: int, stage: str):
        try:
            if progress_cb:
                progress_cb(pct, stage)
        except Exception:
            pass

    if client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"html": None, "report": {**report, "error": "no ANTHROPIC_API_KEY"}}
        client = llm_call.sdk_client(key=key, timeout=900.0, max_retries=1)

    system = v2._SYSTEM + "\n\n" + ROOM.format(n=max_tools())
    user = v2.build_user_prompt(spec_text, real_data)
    turns: List[Dict[str, Any]] = [{"role": "user", "content": user}]
    sampling = model_ladder.sampling_kwargs(model, v2.V2_TEMPERATURE)
    final_html: Optional[str] = None
    cap = max_tools()

    for round_no in range(cap + 2):
        budget_ok = v2._budget_left(spend)
        force = (report["tool_calls"] >= cap) or not budget_ok
        _progress(48 + min(20, round_no * 3),
                  "The builder looks, renders, corrects" if not force else "Handing in")
        try:
            msg = _stream(client, model=model, max_tokens=v2._max_tokens(), system=system,
                          messages=list(turns), tools=TOOLS,
                          tool_choice={"type": "tool", "name": "finish"} if force else None,
                          sampling=sampling)
        except Exception as e:
            logger.error(f"[loop] call failed: {type(e).__name__}: {e}")
            break
        v2._record_spend(spend, model, getattr(msg, "usage", None))
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(endpoint="/composer/builder-v2", model=model,
                               input_tokens=getattr(u, "input_tokens", 0) or 0,
                               output_tokens=getattr(u, "output_tokens", 0) or 0,
                               business_id=business_id, task_type="builder_v2_loop")
        except Exception:
            pass
        uses = _tool_uses(msg)
        if not uses:
            # the model answered in prose — a whole document in the text
            # counts as a hand-in; anything else ends the loop empty
            doc = v2._parse_doc(_text_of(msg))
            if doc:
                final_html = doc
            break
        turns.append({"role": "assistant", "content": msg.content})
        results: List[Dict[str, Any]] = []
        done = False
        for use in uses:
            name = getattr(use, "name", "")
            args = getattr(use, "input", {}) or {}
            report["tool_calls"] += 1
            report["tools_used"].append(name)
            if name == "finish":
                doc = v2._parse_doc(str(args.get("html") or ""))
                if doc:
                    final_html = doc
                    done = True
                    results.append({"type": "tool_result", "tool_use_id": use.id,
                                    "content": [{"type": "text", "text": "Received."}]})
                else:
                    results.append({"type": "tool_result", "tool_use_id": use.id,
                                    "content": [{"type": "text",
                                                 "text": "That is not a complete HTML document — "
                                                         "send the whole page to finish."}]})
                continue
            results.append({"type": "tool_result", "tool_use_id": use.id,
                            "content": box.run(name, args)})
        if done:
            break
        turns.append({"role": "user", "content": results})
        if force:
            # the model was told to finish and did not — take the last render
            break

    report["renders"] = box.renders
    report["looks"] = box.looks
    if final_html is None and box.last_render:
        final_html = box.last_render
        report["forced_finish"] = "last render kept (budget or tool cap reached)"
        logger.warning(f"[loop] {business_id[:8]}: no finish — keeping the last rendered draft")
    elif final_html is None:
        report["forced_finish"] = "no document produced"
    return {"html": final_html, "report": report}
