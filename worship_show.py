# worship_show.py — the show engine under Sunday's screens (ChurchSavvy,
# step 2). Pure: no network, no database.
#
# A service is a list of items. This file says what an item may hold
# (clean_item), what a church's look may hold (clean_look), and how a
# service becomes slides (compile_show): every item's slides, in order,
# each slide one of a few kinds every screen knows how to draw:
#
#   lyric          {label, lines}              a song, a few lines at a time
#   verse          {label, translation, verses: [{chapter, verse, text}]}
#   text           {kicker, text}              a sermon point, a welcome line
#   announcement   {title, when, body, image_url, link}
#   image / video  {url, title} / {url, loop}
#   countdown      {to, title}                 counts down to a time
#
# Who sees an item: `show` is "all" (each screen follows its own rules),
# "room" (the people in the seats only; the stream keeps the camera) or
# "online" (the stream only). Screens decide how a slide looks for them
# (a full slide in the room, a lower third on the stream, one wide line on
# an LED wall, the band's or pastor's view on stage); the engine only
# decides what the slides are.
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import bible_text as bt
import worship_lyrics as wl
import worship_scripture as ws

ITEM_KINDS = ("section", "song", "scripture", "text", "announcement", "media", "countdown")
SHOW = ("all", "room", "online")
ROLES = ("room", "online", "led", "stage", "lobby")
MAX_ITEMS = 80
MAX_TEXT_SLIDES = 30
_ID = re.compile(r"^[a-z0-9-]{1,24}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HTTPS = re.compile(r"^https://[^\s\"'<>]{3,500}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT = re.compile(r"^[\w\s-]{2,40}$")


def _text(raw: Dict[str, Any], key: str, limit: int, label: str) -> str:
    v = raw.get(key)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError(f"{label} should be text")
    v = v.strip()
    if len(v) > limit:
        raise ValueError(f"{label} is too long (at most {limit} characters)")
    return v


def _url(raw: Dict[str, Any], key: str, label: str) -> str:
    v = _text(raw, key, 500, label)
    if v and not _HTTPS.match(v):
        raise ValueError(f"{label} must be an https:// link")
    return v


def clean_item(raw: Any) -> Dict[str, Any]:
    """One item of a service, checked. Raises ValueError with words a person can act on."""
    if not isinstance(raw, dict):
        raise ValueError("Each item needs a kind")
    kind = raw.get("kind")
    if kind not in ITEM_KINDS:
        raise ValueError(f"“{kind}” isn't a kind of item")
    iid = str(raw.get("id") or "")
    if not _ID.match(iid):
        raise ValueError("Each item needs its own id")
    show = raw.get("show") or "all"
    if show not in SHOW:
        raise ValueError("An item shows to everyone, the room only, or online only")
    out: Dict[str, Any] = {"id": iid, "kind": kind, "show": show,
                           "notes": _text(raw, "notes", 500, "Notes for the booth"),
                           "who": _text(raw, "who", 60, "Who leads it")}
    minutes = raw.get("minutes")
    if minutes in (None, ""):
        out["minutes"] = None
    elif isinstance(minutes, (int, float)) and 0 <= minutes <= 240:
        out["minutes"] = round(float(minutes), 1)
    else:
        raise ValueError("Minutes is a number from 0 to 240")

    if kind == "section":
        out["title"] = _text(raw, "title", 60, "A section's name") or "Section"
    elif kind == "song":
        # Empty is a slot ("pick a song"): templates and drafts hold one.
        sid = str(raw.get("song_id") or "")
        if sid and not _UUID.match(sid):
            raise ValueError("Pick a song from the library")
        out["song_id"] = sid or None
        arr = str(raw.get("arrangement_id") or "")
        out["arrangement_id"] = arr if re.match(r"^[a-z0-9-]{1,20}$", arr) else None
    elif kind == "scripture":
        ref = _text(raw, "ref", 60, "The passage")
        tr = str(raw.get("translation") or bt.DEFAULT)
        if tr not in bt.TRANSLATIONS:
            raise ValueError("That Bible version isn't here yet")
        # Empty is a slot ("pick a passage"), like a song's; a typed one must be found.
        found = ws.lookup(ref, tr) if ref else None
        if ref and not found:
            raise ValueError(f"“{ref}” isn't a passage we can find. Try John 3:16 or Psalm 23")
        out["ref"] = found.label() if found else ""
        out["translation"] = tr
        out.update(_clean_passage_choices(raw))
    elif kind == "text":
        out["title"] = _text(raw, "title", 80, "The title")
        slides = raw.get("slides") or []
        if not isinstance(slides, list) or not 1 <= len(slides) <= MAX_TEXT_SLIDES:
            raise ValueError(f"Text has 1 to {MAX_TEXT_SLIDES} slides")
        clean = []
        for s in slides:
            if not isinstance(s, dict):
                raise ValueError("Each slide needs its words")
            text = _text(s, "text", 400, "A slide's words")
            if not text:
                raise ValueError("A slide has no words")
            clean.append({"kicker": _text(s, "kicker", 60, "A slide's small heading"), "text": text})
        out["slides"] = clean
    elif kind == "announcement":
        out["title"] = _text(raw, "title", 80, "The announcement's title")
        if not out["title"]:
            raise ValueError("Give the announcement a title")
        out["when"] = _text(raw, "when", 80, "When it happens")
        out["body"] = _text(raw, "body", 400, "The announcement's words")
        out["image_url"] = _url(raw, "image_url", "The picture")
        out["link"] = _text(raw, "link", 300, "The link")
    elif kind == "media":
        out["url"] = _url(raw, "url", "The picture or video")
        if not out["url"]:
            raise ValueError("Pick a picture or video")
        mk = raw.get("media_kind") or "image"
        if mk not in ("image", "video"):
            raise ValueError("Media is a picture or a video")
        out["media_kind"] = mk
        out["title"] = _text(raw, "title", 80, "The title")
        out["loop"] = bool(raw.get("loop"))
    elif kind == "countdown":
        out["title"] = _text(raw, "title", 60, "The countdown's words") or "We start soon"
        to = _text(raw, "to", 40, "The time it counts to")
        if to:
            try:
                datetime.fromisoformat(to.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("The countdown needs a time to count to")
        out["to"] = to or None
    return out


MAX_FIXES = 60
SLIDE_SIZES = ("small", "std", "big")
SLIDE_ALIGNS = ("center", "left")


def _clean_passage_choices(raw: Dict[str, Any]) -> Dict[str, Any]:
    """How a planned passage goes up (the passage editor, canvas board 32):
    how it splits, where the booth broke it by hand, this Sunday's own words
    for a verse, what shows beside the words, and its size and alignment."""
    split = raw.get("split") or "fit"
    if split not in ws.SPLITS:
        raise ValueError("A passage splits to fit, one verse a slide, or in bigger blocks")
    breaks = raw.get("breaks")
    if breaks is not None:
        if not isinstance(breaks, list) or len(breaks) > 200 or not all(isinstance(b, str) and ws.VERSE_KEY.match(b) for b in breaks):
            raise ValueError("Slide breaks name a verse, like 23:4")
        breaks = sorted(set(breaks), key=lambda k: tuple(int(x) for x in k.split(":")))
    fixes_in = raw.get("fixes") or {}
    if not isinstance(fixes_in, dict) or len(fixes_in) > MAX_FIXES:
        raise ValueError(f"A passage keeps up to {MAX_FIXES} fixed verses")
    fixes: Dict[str, str] = {}
    for key, text in fixes_in.items():
        if not ws.VERSE_KEY.match(str(key)) or not isinstance(text, str):
            raise ValueError("A fixed verse names its verse, like 23:4")
        t = re.sub(r"\s+", " ", text).strip()
        if len(t) > 600:
            raise ValueError("A fixed verse is at most 600 letters")
        if t:
            fixes[str(key)] = t
    size = raw.get("size") or None
    if size is not None and size not in SLIDE_SIZES:
        raise ValueError("The words are small, standard or big")
    align = raw.get("align") or None
    if align is not None and align not in SLIDE_ALIGNS:
        raise ValueError("The words sit centered or on the left")
    return {"split": split, "breaks": breaks, "fixes": fixes,
            "show_ref": raw.get("show_ref") is not False, "show_nums": raw.get("show_nums") is not False,
            "show_version": raw.get("show_version") is not False, "size": size, "align": align}


def clean_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        raise ValueError(f"A service has at most {MAX_ITEMS} items")
    out, seen = [], set()
    for r in raw:
        item = clean_item(r)
        if item["id"] in seen:
            raise ValueError("Two items share an id")
        seen.add(item["id"])
        out.append(item)
    return out


# ─── the look ────────────────────────────────────────────────────────

DEFAULT_LOOK: Dict[str, Any] = {
    "background": {"kind": "brand", "color": None, "url": None, "dim": 0.55},
    "size": "std", "caps": False, "align": "center", "font": None,
    "translation": bt.DEFAULT,
    "lower_third": {"style": "bar", "position": "bottom"},
    # A church with no Solutionist brand kit (ChurchSavvy on its own) sets
    # its colors and logo here; a brand kit, when there is one, wins.
    "brand": {"primary": None, "accent": None, "background": None, "logo_url": None},
}


def clean_look(raw: Any) -> Dict[str, Any]:
    """A church's look, checked; anything missing takes the default."""
    raw = raw if isinstance(raw, dict) else {}
    bg_raw = raw.get("background") if isinstance(raw.get("background"), dict) else {}
    kind = bg_raw.get("kind") or "brand"
    if kind not in ("brand", "color", "image", "video"):
        raise ValueError("The background is your brand, a color, a photo or a moving photo")
    color = bg_raw.get("color")
    if color is not None and (not isinstance(color, str) or not _COLOR.match(color)):
        raise ValueError("A color looks like #2E1A47")
    url = bg_raw.get("url")
    if url is not None and (not isinstance(url, str) or not _HTTPS.match(url)):
        raise ValueError("The background must be an https:// link")
    if kind == "color" and not color:
        raise ValueError("Pick the background color")
    if kind in ("image", "video") and not url:
        raise ValueError("Pick the background photo or video")
    dim = bg_raw.get("dim", DEFAULT_LOOK["background"]["dim"])
    if not isinstance(dim, (int, float)) or not 0 <= dim <= 0.85:
        raise ValueError("Darkening is 0 to 0.85")
    size = raw.get("size") or "std"
    if size not in ("small", "std", "big"):
        raise ValueError("Words are smaller, standard or larger")
    align = raw.get("align") or "center"
    if align not in ("center", "left"):
        raise ValueError("Words sit in the center or on the left")
    font = raw.get("font")
    if font is not None and (not isinstance(font, str) or not _FONT.match(font)):
        raise ValueError("That isn't a font name")
    tr = raw.get("translation") or bt.DEFAULT
    if tr not in bt.TRANSLATIONS:
        raise ValueError("That Bible version isn't here yet")
    lt_raw = raw.get("lower_third") if isinstance(raw.get("lower_third"), dict) else {}
    style = lt_raw.get("style") or "bar"
    position = lt_raw.get("position") or "bottom"
    if style not in ("bar", "shadow") or position not in ("bottom", "top"):
        raise ValueError("The lower third is a bar or words with a shadow, at the bottom or the top")
    br_raw = raw.get("brand") if isinstance(raw.get("brand"), dict) else {}
    brand: Dict[str, Any] = {}
    for key in ("primary", "accent", "background"):
        v = br_raw.get(key)
        if v not in (None, "") and (not isinstance(v, str) or not _COLOR.match(v)):
            raise ValueError("A color looks like #2E1A47")
        brand[key] = v or None
    logo = br_raw.get("logo_url")
    if logo not in (None, "") and (not isinstance(logo, str) or not _HTTPS.match(logo)):
        raise ValueError("The logo must be an https:// link")
    brand["logo_url"] = logo or None
    return {
        "background": {"kind": kind, "color": color, "url": url, "dim": round(float(dim), 2)},
        "size": size, "caps": bool(raw.get("caps")), "align": align, "font": font or None,
        "translation": tr, "lower_third": {"style": style, "position": position},
        "brand": brand,
    }


# ─── a service, as slides ────────────────────────────────────────────


def _song_slides(item: Dict[str, Any], song: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not item.get("song_id"):
        return {"title": "Pick a song", "missing": "pick", "slides": []}
    if not song:
        return {"title": "A song that was taken out", "missing": "song", "slides": []}
    arrs = song.get("arrangements") or []
    arr = next((a for a in arrs if a.get("id") == item.get("arrangement_id")), None) or (arrs[0] if arrs else None)
    order = arr["order"] if arr else [s["id"] for s in song.get("sections") or []]
    slides = [{"kind": "lyric", "label": s["label"], "section_id": s["section_id"], "lines": s["lines"]}
              for s in wl.slides_for_song(song, order, int(song.get("lines_per_slide") or 2))]
    out: Dict[str, Any] = {"title": song.get("title") or "Untitled song", "slides": slides,
                           "song": {"key": song.get("song_key"), "authors": song.get("authors") or "",
                                    "ccli_number": song.get("ccli_number"), "copyright": song.get("copyright") or "",
                                    "public_domain": bool(song.get("public_domain")),
                                    "arrangement": arr["name"] if arr else None,
                                    "order": [next((s.get("label") for s in song.get("sections") or [] if s["id"] == sid), sid)
                                              for sid in order]}}
    if not slides:
        out["missing"] = "words"
    return out


def _scripture_slides(item: Dict[str, Any]) -> Dict[str, Any]:
    tr = item.get("translation") or bt.DEFAULT
    if not item.get("ref"):
        return {"title": "Pick a passage", "missing": "pick", "slides": []}
    ref = ws.lookup(item.get("ref") or "", tr)
    if not ref:
        return {"title": item.get("ref") or "A passage", "missing": "passage", "slides": []}
    short = bt.TRANSLATIONS[tr]["short"]
    # What shows beside the words, and the passage's own size and alignment (None: the church's look).
    opts = {"ref": item.get("show_ref") is not False, "nums": item.get("show_nums") is not False,
            "version": item.get("show_version") is not False, "size": item.get("size"), "align": item.get("align")}
    split = ws.slides(ref, tr, split=item.get("split") or "fit", breaks=item.get("breaks"), fixes=item.get("fixes") or None)
    slides = [{"kind": "verse", "label": s["label"], "translation": short, "verses": s["verses"], "opts": opts} for s in split]
    return {"title": f"{ref.label()} · {short}", "slides": slides}


def compile_item(item: Dict[str, Any], songs: Dict[str, Dict[str, Any]], starts_at: Optional[str] = None) -> Dict[str, Any]:
    """One item with its slides. `songs` maps song id → the song row (sections, arrangements…)."""
    base = {k: item.get(k) for k in ("id", "kind", "show", "notes", "who", "minutes")}
    kind = item["kind"]
    if kind == "section":
        body: Dict[str, Any] = {"title": item.get("title") or "Section", "slides": []}
    elif kind == "song":
        body = _song_slides(item, songs.get(item.get("song_id") or ""))
    elif kind == "scripture":
        body = _scripture_slides(item)
    elif kind == "text":
        body = {"title": item.get("title") or (item["slides"][0]["kicker"] if item.get("slides") else "") or "Slides",
                "slides": [{"kind": "text", "kicker": s.get("kicker") or "", "text": s["text"]} for s in item.get("slides") or []]}
    elif kind == "announcement":
        body = {"title": item["title"], "slides": [{"kind": "announcement", "title": item["title"], "when": item.get("when") or "",
                                                     "body": item.get("body") or "", "image_url": item.get("image_url") or "",
                                                     "link": item.get("link") or ""}]}
    elif kind == "media":
        mk = item.get("media_kind") or "image"
        slide = {"kind": mk, "url": item["url"], "title": item.get("title") or ""}
        if mk == "video":
            slide["loop"] = bool(item.get("loop"))
        body = {"title": item.get("title") or ("Video" if mk == "video" else "Picture"), "slides": [slide]}
    else:  # countdown
        body = {"title": item.get("title") or "Countdown",
                "slides": [{"kind": "countdown", "to": item.get("to") or starts_at, "title": item.get("title") or "We start soon"}]}
    return {**base, **body}


def compile_show(service: Dict[str, Any], songs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The whole service as slides, in order, with a count the booth can show."""
    items = [compile_item(i, songs, service.get("starts_at")) for i in service.get("items") or []]
    return {
        "service": {"id": service.get("id"), "title": service.get("title"), "starts_at": service.get("starts_at"),
                    "updated_at": service.get("updated_at")},
        "items": items,
        "slide_count": sum(len(i["slides"]) for i in items),
        "missing": [{"id": i["id"], "title": i["title"], "missing": i["missing"]} for i in items if i.get("missing")],
    }


def song_ids(items: List[Dict[str, Any]]) -> List[str]:
    return sorted({i["song_id"] for i in items if i.get("kind") == "song" and i.get("song_id")})


# ─── what's on screen now ────────────────────────────────────────────

MODES = ("show", "black", "logo", "clear")
# What may go up on the spot, and the kinds of slide each brings.
ADHOC_KINDS = {"verse": ("verse",), "song": ("lyric",), "text": ("text",)}


def clean_live(raw: Any) -> Dict[str, Any]:
    """What the booth says is on screen. A passage put up on the spot rides along in `adhoc`."""
    if not isinstance(raw, dict):
        raise ValueError("Nothing to show")
    mode = raw.get("mode") or "show"
    if mode not in MODES:
        raise ValueError("A screen shows the slide, black, the logo or no words")
    sid = raw.get("service_id")
    if sid is not None and (not isinstance(sid, str) or not _UUID.match(sid)):
        raise ValueError("That isn't a service")
    item = raw.get("item_id")
    if item is not None and (not isinstance(item, str) or not _ID.match(item)):
        raise ValueError("That isn't an item")
    slide = raw.get("slide", 0)
    if not isinstance(slide, int) or not 0 <= slide <= 500:
        raise ValueError("That isn't a slide")
    out: Dict[str, Any] = {"service_id": sid, "item_id": item, "slide": slide, "mode": mode,
                           "show_key": str(raw.get("show_key") or "")[:64]}
    adhoc = raw.get("adhoc")
    if adhoc is not None:
        # Up on the spot, no plan needed: a passage, a song from the library,
        # or words typed in the booth. Each slide is one the screens can draw.
        if not isinstance(adhoc, dict) or adhoc.get("kind") not in ADHOC_KINDS:
            raise ValueError("On the spot is a passage, a song or words you type")
        slides = adhoc.get("slides")
        if not isinstance(slides, list) or not 1 <= len(slides) <= 60:
            raise ValueError("Something on the spot has 1 to 60 slides")
        if any(not isinstance(sl, dict) or sl.get("kind") not in ADHOC_KINDS[adhoc["kind"]] for sl in slides):
            raise ValueError("Those slides don't match what's going up")
        out["adhoc"] = {"kind": adhoc["kind"], "title": str(adhoc.get("title") or "")[:80], "slides": slides}
    message = raw.get("message")
    if message is not None:
        if not isinstance(message, str) or len(message) > 120:
            raise ValueError("A message to the stage is at most 120 characters")
        out["message"] = message.strip() or None
    timer = raw.get("timer")
    if timer is not None:
        if not isinstance(timer, dict) or not isinstance(timer.get("ends_at"), str):
            raise ValueError("A timer needs the time it ends")
        out["timer"] = {"label": str(timer.get("label") or "")[:40], "ends_at": timer["ends_at"][:40]}
    return out
