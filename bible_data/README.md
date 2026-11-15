# Bible text

Read by `bible_text.py` for the member app's Bible (`/my/bible`) and ChurchSavvy's scripture slides.

| File | Translation | Source | Licence | Downloaded |
| --- | --- | --- | --- | --- |
| `kjv.tsv.gz` | King James Version (1769 standard text) | eBible.org `eng-kjv_vpl.zip` | Public domain | 2026-10-02 |
| `web.tsv.gz` | World English Bible | eBible.org `eng-web_vpl.zip` | Public domain ("World English Bible" is a trademark of eBible.org) | 2026-10-02 |
| `bsb.tsv.gz` | Berean Standard Bible | eBible.org `engbsb_vpl.zip` (eBible's 2026-10-30 build) | Public domain: "Public Domain ... Contributor: BSB Publishing, LLC" (the zip's `engbsb_about.htm`); berean.bible/terms.htm: dedicated to the public domain on April 30, 2023, "All uses are freely permitted", attribution appreciated but not required | 2026-11-15 |
| `asv.tsv.gz` | American Standard Version (1901) | eBible.org `eng-asv_vpl.zip` (eBible's 2026-10-30 build) | Public domain: "This public domain Bible translation is brought to you courtesy of eBible.org" (the zip's `eng-asv_about.htm`) | 2026-11-15 |

Format: gzip'd UTF-8 lines `BOOK<TAB>chapter<TAB>verse<TAB>text` for the 66 books (no Apocrypha), using the book codes in `bible_text.BOOKS` (the same codes the eBible files use). KJV keeps its `[supplied words]` (shown in italics) and `¶` paragraph marks; ASV keeps its `[supplied words]` too; WEB and BSB have neither.

How BSB and ASV were made (2026-11-15): each zip downloaded from `https://ebible.org/Scriptures/` into its own empty folder, read in place (never unpacked), its `_vpl.txt` lines (`GEN 1:1 In the beginning…`) written out in the format above. Checked: 66 books in order, 1,189 chapters, 31,086 verses each, no verse twice, no empty verse; John 3:16, Psalm 23:1 and Genesis 1:1 read as expected.

- Both leave out the 16 verses modern texts print only in a footnote (Matthew 17:21, 18:11, 23:14; Mark 7:16, 9:44, 9:46, 11:26, 15:28; Luke 17:36, 23:17; John 5:4; Acts 8:37, 15:34, 24:7, 28:29; Romans 16:24). The ASV file lists them with no words, so they were left out; the BSB file doesn't list them.
- The ASV file opens a bracket before Selah ("[Selah") 74 times and never closes it. Those are written plainly ("Selah"), as the KJV writes it. Its brackets around John 7:53 to 8:11 (opened in one verse, closed in another) are kept; slides drop them.

sha256 of the downloads: `engbsb_vpl.zip` 72ecd9e0131e82737b76e1f2d706c85771d6054b6350673f80f49c839133f45e, `eng-asv_vpl.zip` 6c41b8020cba9cf7041689f2356c55859e28023405537388be08bad93df2b050.

Licensed translations (NIV, ESV, NLT, …) are not here: they need a publisher's licence. Sermon notes take a passage the pastor pastes from their own Bible instead (`bible_text.LICENSED` lists those versions with each publisher's copyright notice); nothing is fetched.
