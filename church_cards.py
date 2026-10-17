"""
church_cards.py — a church's cards and forms, and what came in on each.

The Forms page (Build → Forms & classes) and its Next steps road show every
card a guest can fill in, wherever it lives:

  * the cards written into the church's own website — a <form> marked
    data-church-form="connect-card" or "prayer-request", sent through
    POST /sites/{business_id}/contact-submit (public_site.py). These were
    invisible to the app: the Forms page listed intake_forms only and said
    "0 forms" to a church whose website was already taking connect cards;
  * the intake forms built in the app (intake_forms), sent through
    POST /intake/submit (intake_endpoint.py).

    website_cards(pages)       the cards in a site's HTML: kind, the page
                               each one is on, its questions in order and
                               the words on its send button (pure)
    cards(business_id)         the website's cards with how many came in,
                               and the same numbers for every intake form

What came in, from the rows each door already writes:

    website connect card   events  event_type=contact_note, source=
                                   website_contact_form, data.form=connect_card
    intake form            events  event_type=form_submit, data.form_id
    prayer / private care  ministry_care_requests (website: form_id null,
                                   submission.source "website prayer request";
                                   a private intake form: form_id)

A private card is NUMBERS ONLY here: never a name, a contact, an id of a
request or a word anyone wrote. The other cards carry who filled them in
(name and when), which is what the road's "moved on" and the page's
"filled it in lately" are drawn from; callers gate who may see that.

Returns None when a read failed, so a caller can tell "nothing came in"
from "couldn't look".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import church_reads as R

# How far back "what came in" looks: the same 90 days the care numbers use,
# so a prayer card's count here and Prayer & care's never disagree.
WINDOW_DAYS = R.CARE_WINDOW_DAYS
# "This month" on a card's stub.
RECENT_DAYS = 30
# Who filled a card in, most recent first. Enough to draw the road's
# moved-on lines for a church of any size we serve; the stub shows a few.
PEOPLE_CAP = 300

KINDS = {
    "connect_card": "Connect card",
    "prayer_request": "Prayer request",
}
PRIVATE_KINDS = {"prayer_request"}
WEBSITE_PRAYER_SOURCE = "website prayer request"

# Inputs that are not questions a guest answers.
_SKIP_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image", "file"}
# The honeypot every church form carries (forms.js: "the hidden field only
# bots fill in").
_HONEYPOT_NAMES = {"website"}
_TYPE_OF_INPUT = {"email": "email", "tel": "phone", "number": "number", "date": "date"}


def _squash(text: str) -> str:
    return " ".join((text or "").split())


class _Question:
    __slots__ = ("name", "label", "type", "required", "options", "order")

    def __init__(self, name: str, order: int):
        self.name = name
        self.label = ""
        self.type = "text"
        self.required = False
        self.options: List[str] = []
        self.order = order

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "label": self.label or self.name.replace("_", " ").capitalize(),
                               "type": self.type, "required": self.required}
        if self.options:
            out["options"] = self.options
        return out


class _FormReader(HTMLParser):
    """Walks one page and collects each data-church-form's questions."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: List[Dict[str, Any]] = []
        self._stack: List[Tuple[str, Optional[str], bool]] = []   # (tag, id, hidden)
        self._heading: Optional[List[str]] = None
        self._last_heading = ""
        self._form: Optional[Dict[str, Any]] = None
        self._questions: Dict[str, _Question] = {}
        self._label_for: Dict[str, str] = {}          # input id → label text
        self._id_name: Dict[str, str] = {}            # input id → field name
        self._label: Optional[Dict[str, Any]] = None  # open <label>
        self._legend: Optional[List[str]] = None
        self._fieldset: List[Dict[str, Any]] = []     # open fieldsets: legend, names
        self._option: Optional[Dict[str, Any]] = None
        self._select: Optional[str] = None
        self._button: Optional[List[str]] = None
        self._req_depth = 0

    # ── helpers ──
    def _hidden(self) -> bool:
        return any(h for _, _, h in self._stack)

    def _nearest_id(self) -> Optional[str]:
        for _, el_id, _ in reversed(self._stack):
            if el_id:
                return el_id
        return None

    def _q(self, name: str) -> _Question:
        q = self._questions.get(name)
        if q is None:
            q = self._questions[name] = _Question(name, len(self._questions))
        return q

    def _text(self, data: str):
        if self._req_depth:
            return
        for buf in (self._heading, self._legend, self._button):
            if buf is not None:
                buf.append(data)
        if self._label is not None:
            self._label["text"].append(data)
        if self._option is not None:
            self._option["text"].append(data)

    # ── parser hooks ──
    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        classes = set(a.get("class", "").split())
        hidden = a.get("aria-hidden") == "true" or "hp" in classes or "hidden" in a
        void = tag in ("input", "img", "br", "hr", "meta", "link", "source", "wbr")
        if not void:
            self._stack.append((tag, a.get("id") or None, hidden))

        if self._form is None:
            if tag in ("h1", "h2", "h3"):
                self._heading = []
            if tag == "form" and a.get("data-church-form"):
                kind = a["data-church-form"].strip().replace("-", "_")
                self._form = {"kind": kind, "anchor": self._nearest_id(), "heading": self._last_heading}
                self._questions, self._label_for, self._id_name = {}, {}, {}
            return

        if tag == "span" and "req" in classes:
            self._req_depth += 1
            if self._label is not None:
                self._label["required"] = True
            if self._legend is not None and self._fieldset:
                self._fieldset[-1]["required"] = True
            return
        if self._req_depth and not void:
            self._req_depth += 1
            return
        if tag == "fieldset":
            self._fieldset.append({"legend": "", "names": [], "required": False})
        elif tag == "legend":
            self._legend = []
        elif tag == "label":
            self._label = {"for": a.get("for") or "", "text": [], "inputs": [], "required": False}
        elif tag == "button" and a.get("type", "submit") == "submit":
            self._button = []
        elif tag in ("input", "textarea", "select"):
            name = (a.get("name") or "").strip()
            itype = (a.get("type") or "text").lower() if tag == "input" else tag
            if not name or name in _HONEYPOT_NAMES or self._hidden() or itype in _SKIP_INPUT_TYPES:
                if tag == "select":
                    self._select = None
                return
            q = self._q(name)
            if "required" in a:
                q.required = True
            if tag == "textarea":
                q.type = "textarea"
            elif tag == "select":
                q.type = "select"
                self._select = name
            elif itype in ("radio", "checkbox"):
                q.type = itype
            else:
                q.type = _TYPE_OF_INPUT.get(itype, "text")
            if a.get("id"):
                self._id_name[a["id"]] = name
            if self._fieldset:
                fs = self._fieldset[-1]
                if name not in fs["names"]:
                    fs["names"].append(name)
            if self._label is not None:
                self._label["inputs"].append((name, itype))
        elif tag == "option" and self._select:
            self._option = {"value": a.get("value"), "text": []}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        # Pop to the matching open tag (tolerates sloppy HTML).
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

        if self._form is None:
            if tag in ("h1", "h2", "h3") and self._heading is not None:
                self._last_heading = _squash("".join(self._heading))
                self._heading = None
            elif tag == "section":
                self._last_heading = ""
            return

        if self._req_depth:
            self._req_depth -= 1
            return
        if tag == "legend" and self._legend is not None:
            if self._fieldset:
                self._fieldset[-1]["legend"] = _squash("".join(self._legend))
            self._legend = None
        elif tag == "fieldset" and self._fieldset:
            fs = self._fieldset.pop()
            for name in fs["names"]:
                q = self._q(name)
                if q.type in ("radio", "checkbox") and fs["legend"]:
                    q.label = q.label or fs["legend"]
                    q.required = q.required or fs["required"]
        elif tag == "label" and self._label is not None:
            lab = self._label
            text = _squash("".join(lab["text"]))
            choice = next(((n, t) for n, t in lab["inputs"] if t in ("radio", "checkbox")), None)
            if choice and text:
                q = self._q(choice[0])
                if text not in q.options:
                    q.options.append(text)
            elif lab["for"]:
                self._label_for[lab["for"]] = text
                if lab["required"]:
                    self._label_for[lab["for"] + "\0req"] = "1"
            elif lab["inputs"] and text:
                q = self._q(lab["inputs"][0][0])
                q.label = q.label or text
                q.required = q.required or lab["required"]
            self._label = None
        elif tag == "option" and self._option is not None:
            text = _squash("".join(self._option["text"]))
            value = self._option["value"]
            if self._select and text and value != "":
                q = self._q(self._select)
                if text not in q.options:
                    q.options.append(text)
            self._option = None
        elif tag == "select":
            self._select = None
        elif tag == "button" and self._button is not None:
            self._form["submit"] = _squash("".join(self._button))
            self._button = None
        elif tag == "form":
            for el_id, name in self._id_name.items():
                q = self._questions.get(name)
                if q is None:
                    continue
                if el_id in self._label_for and not (q.type in ("radio", "checkbox") and q.label):
                    q.label = q.label or self._label_for[el_id]
                if self._label_for.get(el_id + "\0req"):
                    q.required = True
            # A lone checkbox is a yes/no question: its label is the question.
            for q in self._questions.values():
                if q.type == "checkbox" and not q.label and len(q.options) == 1:
                    q.label, q.options, q.type = q.options[0], [], "yesno"
            self._form["questions"] = [q.as_dict() for q in sorted(self._questions.values(), key=lambda x: x.order)]
            self.forms.append(self._form)
            self._form = None
            self._fieldset, self._label, self._legend, self._select = [], None, None, None

    def handle_data(self, data):
        self._text(data)


def _path(page: str, anchor: Optional[str]) -> str:
    base = "/" if page in ("home", "index", "") else f"/{page}"
    return base + (f"#{anchor}" if anchor else "")


def website_cards(pages: Dict[str, str]) -> List[Dict[str, Any]]:
    """The church cards written into a site's pages, one entry per kind,
    in page order (home first). Each lists every place it appears; its
    questions are read from the first. Pure: no reads.

        [{kind, title, places: [{page, path}], questions: [...], submit}]
    """
    found: Dict[str, Dict[str, Any]] = {}
    order = sorted(pages, key=lambda p: (p != "home", p))
    for page in order:
        html = pages.get(page)
        if not isinstance(html, str) or "data-church-form" not in html:
            continue
        reader = _FormReader()
        try:
            reader.feed(html)
            reader.close()
        except Exception:  # a page we cannot read is left out, never fatal
            continue
        for f in reader.forms:
            kind = f["kind"]
            if kind not in KINDS:
                continue
            place = {"page": page, "path": _path(page, f.get("anchor"))}
            card = found.get(kind)
            if card is None:
                found[kind] = {
                    "kind": kind,
                    "title": KINDS[kind],
                    "places": [place],
                    "questions": f.get("questions") or [],
                    "submit": f.get("submit") or "Send",
                }
            elif place not in card["places"]:
                card["places"].append(place)
    return list(found.values())


def _stats(times: List[datetime], now: datetime) -> Dict[str, Any]:
    recent = now - timedelta(days=RECENT_DAYS)
    last = max(times) if times else None
    return {
        "last_30": sum(1 for t in times if t >= recent),
        "last_90": len(times),
        "last_at": R._iso(last) if last else None,
    }


def _people(rows: List[Tuple[str, datetime]], names: Dict[str, str]) -> List[Dict[str, Any]]:
    """Distinct people, most recent first."""
    seen: Dict[str, datetime] = {}
    for cid, at in rows:
        if cid and (cid not in seen or at > seen[cid]):
            seen[cid] = at
    ordered = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:PEOPLE_CAP]
    return [{"contact_id": cid, "name": names.get(cid, "Someone"), "at": R._iso(at)} for cid, at in ordered]


def cards(business_id: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    biz = str(business_id)
    since = R._iso(now - timedelta(days=WINDOW_DAYS))

    sites = R._get(f"/business_sites?business_id=eq.{biz}&limit=1"
                   "&select=slug,status,html_content,generated_pages:site_config->generated_pages,"
                   "offline:site_config->offline,custom_domain:site_config->>custom_domain,"
                   "custom_domain_status:site_config->>custom_domain_status")
    notes = R._get(f"/events?business_id=eq.{biz}&event_type=eq.contact_note"
                   f"&source=eq.website_contact_form&created_at=gte.{since}"
                   "&select=contact_id,created_at,form:data->>form&order=created_at.desc&limit=5000")
    submits = R._get(f"/events?business_id=eq.{biz}&event_type=eq.form_submit&created_at=gte.{since}"
                     "&select=contact_id,created_at,form_id:data->>form_id&order=created_at.desc&limit=5000")
    care = R._get(f"/ministry_care_requests?business_id=eq.{biz}&created_at=gte.{since}"
                  "&select=form_id,created_at,source:submission->>source&limit=5000")
    if sites is None or notes is None or submits is None or care is None:
        return None

    # ── the website's cards ──
    site = sites[0] if sites else None
    pages: Dict[str, str] = {}
    if site and site.get("slug"):
        gen = site.get("generated_pages")
        if isinstance(gen, dict):
            pages.update({str(k): v for k, v in gen.items() if isinstance(v, str)})
        if isinstance(site.get("html_content"), str):
            pages["home"] = site["html_content"]
    web = website_cards(pages)
    domain = (site or {}).get("custom_domain") if (site or {}).get("custom_domain_status") == "verified" else None
    address = (domain or f"{site['slug']}.mysolutionist.app") if site and site.get("slug") else None
    live = bool(site and site.get("status") == "published" and not site.get("offline"))

    # ── what came in ──
    connect_rows: List[Tuple[str, datetime]] = []
    for r in notes:
        at = R._parse(r.get("created_at"))
        if at and r.get("form") == "connect_card":
            connect_rows.append((str(r.get("contact_id") or ""), at))
    by_form: Dict[str, List[Tuple[str, datetime]]] = {}
    for r in submits:
        at = R._parse(r.get("created_at"))
        fid = str(r.get("form_id") or "")
        if at and fid:
            by_form.setdefault(fid, []).append((str(r.get("contact_id") or ""), at))
    web_prayer: List[datetime] = []
    private_by_form: Dict[str, List[datetime]] = {}
    for r in care:
        at = R._parse(r.get("created_at"))
        if not at:
            continue
        if r.get("form_id"):
            private_by_form.setdefault(str(r["form_id"]), []).append(at)
        elif str(r.get("source") or "") == WEBSITE_PRAYER_SOURCE:
            web_prayer.append(at)

    ids = {cid for cid, _ in connect_rows if cid}
    for rows in by_form.values():
        ids |= {cid for cid, _ in rows if cid}
    names = R._names(biz, sorted(ids))
    if names is None:
        return None

    for card in web:
        if card["kind"] in PRIVATE_KINDS:
            card["stats"] = _stats(web_prayer, now)
        else:
            card["stats"] = _stats([at for _, at in connect_rows], now)
            card["people"] = _people(connect_rows, names)

    return {
        "window_days": WINDOW_DAYS,
        "website": {"address": address, "live": live, "cards": web},
        "forms": {fid: {"stats": _stats([at for _, at in rows], now), "people": _people(rows, names)}
                  for fid, rows in by_form.items()},
        "private_forms": {fid: {"stats": _stats(times, now)} for fid, times in private_by_form.items()},
    }
