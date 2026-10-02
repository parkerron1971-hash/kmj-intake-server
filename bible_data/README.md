# Bible text

Read by `bible_text.py` for the member app's Bible (`/my/bible`).

| File | Translation | Source | Licence |
| --- | --- | --- | --- |
| `kjv.tsv.gz` | King James Version (1769 standard text) | eBible.org `eng-kjv_vpl.zip` | Public domain |
| `web.tsv.gz` | World English Bible | eBible.org `eng-web_vpl.zip` | Public domain ("World English Bible" is a trademark of eBible.org) |

Format: gzip'd UTF-8 lines `BOOK<TAB>chapter<TAB>verse<TAB>text` for the 66 books (no Apocrypha), downloaded 2026-10-02. KJV keeps its `[supplied words]` (shown in italics) and `¶` paragraph marks; WEB has neither.

Licensed translations (NIV, ESV, NLT, …) are not here: they need a publisher's licence, usually through a Bible API.
