# __tests__/test_worship_proclaim.py
#
# Reading a church's own Proclaim files (worship_proclaim.py). Pins: words
# come from whichever file holds the fuller copy (the song library or a
# service), times sung add up across arrangements, Proclaim's sample song
# is skipped, an untitled song is kept and flagged, the custom verse order
# carries over, and files that are not Proclaim's are refused. Fixtures are
# small SQLite files built here with public-domain words.

import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import worship_proclaim as wp


def xaml(*lines):
    out = []
    for ln in lines:
        out.append('<Paragraph Language="en-US" Margin="0,0,0,0" />' if ln == "" else
                   f'<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="{ln}" /></Paragraph>')
    return "".join(out)


AMAZING = xaml("{Verse1}", "Amazing grace! How sweet the sound", "That saved a wretch like me!", "",
               "{Verse2}", "'Twas grace that taught my heart to fear,", "And grace my fears relieved;")
HOLY = xaml("Holy, holy, holy! Lord God Almighty!", "Early in the morning our song shall rise to Thee;", "",
            "Holy, holy, holy! merciful and mighty!", "God in three Persons, blessed Trinity!")


def make_music(path, arrangements, usage):
    con = sqlite3.connect(path)
    con.execute("create table Arrangements (SyncId text, ArrangementId int, AccountId int, SongId int, SongDisplayTitle text,"
                " Arrangement text not null, Modified text, IsDeleted bool not null, SyncState int not null, SyncRevision integer)")
    con.execute("create table WorshipTeamSongData (WorshipTeamId int, SongId int, Year int, YtdUsage int, SongData text,"
                " LastUsed text, LastModified text)")
    for song_id, title, key, lyrics, deleted in arrangements:
        con.execute("insert into Arrangements values (?,?,?,?,?,?,?,?,?,?)",
                    (f"s{song_id}", song_id, 1, song_id, title,
                     json.dumps({"songId": song_id, "key": key, "lyrics": lyrics, "songDisplayTitle": title}), None, deleted, 0, 0))
    for song_id, year, ytd, last in usage:
        con.execute("insert into WorshipTeamSongData values (1,?,?,?,null,?,null)", (song_id, year, ytd, last))
    con.commit()
    con.close()


def make_presentations(path, items):
    con = sqlite3.connect(path)
    con.execute("create table Presentations (PresentationId text, Title text, IsDeleted bool not null)")
    con.execute("create table ServiceItems (RecordId integer primary key, ServiceItemId text, PresentationId text,"
                " ServiceItemKind text not null, Title text not null, Content text)")
    con.execute("insert into Presentations values ('p1', 'Sunday Mornings', 0)")
    for i, (title, content) in enumerate(items):
        con.execute("insert into ServiceItems (ServiceItemId, PresentationId, ServiceItemKind, Title, Content) values (?,?,?,?,?)",
                    (f"i{i}", "p1", "SongLyrics", title, json.dumps(content)))
    con.commit()
    con.close()


def build(tmp_path):
    music = tmp_path / "FaithlifeMusicManager.db"
    pres = tmp_path / "PresentationManager.db"
    make_music(music, [
        (11, "Amazing Grace", "G", AMAZING, 0),
        (22, "Holy, Holy, Holy", "D", "", 0),          # library has no words; a service does
        (33, "Example Song", "C", AMAZING, 0),           # Proclaim's sample
        (44, "", "G", HOLY, 0),                          # untitled, but sung a lot
        (55, "Deleted Song", "A", AMAZING, 1),
    ], [(11, 2026, 4, "2026-05-10T10:00:00"), (22, 2026, 2, "2026-04-01T10:00:00"), (44, 2026, 26, "2026-10-11T10:00:00")])
    make_presentations(pres, [
        ("Holy, Holy, Holy", {"_richtextfield:Lyrics": HOLY, "ProclaimArrangement": json.dumps({"songId": 22, "key": "D"})}),
        ("Amazing Grace", {"_richtextfield:Lyrics": AMAZING, "CustomOrderSequence": "Verse 2, Verse 1"}),
        ("Song Only In Services", {"_richtextfield:Lyrics": xaml("Fairest Lord Jesus,", "Ruler of all nature,")}),
    ])
    return [music, pres]


def by_title(result):
    return {s["title"]: s for s in result["songs"]}


def test_the_files_are_recognized_and_everything_else_is_refused(tmp_path):
    music, pres = build(tmp_path)
    assert wp.kind_of(music) == "music" and wp.kind_of(pres) == "presentations"
    junk = tmp_path / "notes.db"
    junk.write_bytes(b"not a database at all")
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("create table things (a int)").connection.close()
    assert wp.kind_of(junk) is None and wp.kind_of(other) is None


def test_words_come_from_whichever_file_has_them(tmp_path):
    songs = by_title(wp.read_proclaim(build(tmp_path)))
    holy = songs["Holy, Holy, Holy"]
    assert holy["has_words"] and holy["words_from"] == "service" and holy["key"] == "D"
    assert [s["label"] for s in holy["sections"]] == ["Verse 1", "Verse 2"]
    assert songs["Amazing Grace"]["words_from"] == "library"
    assert songs["Song Only In Services"]["has_words"]


def test_times_sung_and_last_sung_come_over(tmp_path):
    songs = by_title(wp.read_proclaim(build(tmp_path)))
    assert songs["Amazing Grace"]["times_sung_by_year"] == {2026: 4}
    assert songs["Amazing Grace"]["last_sung"] == "2026-05-10"
    assert songs["Song Only In Services"]["times_sung_by_year"] == {}


def test_the_sample_and_deleted_songs_are_skipped_and_untitled_is_flagged(tmp_path):
    result = wp.read_proclaim(build(tmp_path))
    titles = [s["title"] for s in result["songs"]]
    assert "Example Song" not in titles and "Deleted Song" not in titles
    untitled = [s for s in result["songs"] if s["needs_title"]]
    assert len(untitled) == 1 and untitled[0]["title"] == "Untitled song" and untitled[0]["times_sung_by_year"] == {2026: 26}
    assert titles[-1] == "Untitled song"
    assert result["summary"] == {"songs": 4, "with_words": 4, "without_words": 0, "untitled": 1, "services": 1, "files_read": 2}


def test_the_custom_order_from_a_service_carries_over(tmp_path):
    amazing = by_title(wp.read_proclaim(build(tmp_path)))["Amazing Grace"]
    labels = {s["id"]: s["label"] for s in amazing["sections"]}
    assert [labels[i] for i in amazing["order"]] == ["Verse 2", "Verse 1"]


def test_an_order_that_names_parts_the_song_lacks_falls_back_to_the_words(tmp_path):
    parsed = {"sections": [{"id": "v1", "kind": "verse", "number": 1, "label": "Verse 1", "lines": ["a"]}], "order": ["v1"]}
    assert wp._order_from_labels(parsed, "Verse 1, Bridge") is None
    assert wp._order_from_labels(parsed, "Versus 1, Verse 1") == ["v1", "v1"]
