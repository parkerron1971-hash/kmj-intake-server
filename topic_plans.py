"""
topic_plans.py — short plans of scripture for what people walk through.

Kevin approved the member app's Plans design (2026-11-21, "go ahead"): under
"What are you walking through?" six topics open a short plan each: Anxiety,
Healing, Purpose, Marriage, Money and Grief. Like the built-in reading plans
(reading_plans.PLANS) they are written once, here, and every church uses
them: seven days each, a plain title a day and one to three well-known
passages. Nothing is quoted or paraphrased: the words a member reads are the
Bible's own, in their translation (bible_text), and each title only names
the passage.

They behave like the built-in reading plans: a member starts one on their own
day (member_plan_starts, "reading:topic-anxiety"), a day opens each day from
then, and each day read is a tick (reading_progress, plan_key
"topic-anxiety", the start date as its run), so Start, how far and finished
work the same way. Their keys fit both tables' checks (`[a-z0-9-]{1,40}`):
no migration.

    plan(key, started)   the plan in reading_plans' shape ({key, title,
                         start, days, own}), for reading_plans.read_days,
                         readable_upto, day_number, mark and streak
    day(key, n)          {"title", "refs": [Ref]} for day n
    label(key, n)        "1 Peter 5:6-7 · Psalm 55:22"
    href(key, n)         the first passage in the Bible reader
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import bible_text as bt

PREFIX = "topic-"

# key: {title (the tile's word), name (the plan's title), about, hue (the
# tile's colour class), icon, days: ((title, (passage, ...)), ...)}
TOPICS: Dict[str, Dict[str, Any]] = {
    "topic-anxiety": {
        "title": "Anxiety", "name": "When you're anxious", "hue": "a", "icon": "wind",
        "about": "Seven days in the passages people turn to when worry won't let go: what God says about fear, "
                 "the cares we carry, and His peace.",
        "days": (("Cast your cares on Him", ("1 Peter 5:6-7", "Psalm 55:22")),
                 ("Do not worry about tomorrow", ("Matthew 6:25-34",)),
                 ("The peace that guards your heart", ("Philippians 4:4-9",)),
                 ("When I am afraid", ("Psalm 56:3-4", "Isaiah 41:10")),
                 ("Let not your heart be troubled", ("John 14:1-3", "John 14:27")),
                 ("The Lord is my shepherd", ("Psalm 23",)),
                 ("Perfect peace", ("Isaiah 26:3-4", "2 Timothy 1:7")))},
    "topic-healing": {
        "title": "Healing", "name": "The God who heals", "hue": "b", "icon": "heal",
        "about": "Seven days with the God who heals: His promises to the hurting, and the people Jesus made whole.",
        "days": (("He heals the brokenhearted", ("Psalm 147:3", "Psalm 34:18")),
                 ("By His stripes", ("Isaiah 53:4-5",)),
                 ("Who heals all your diseases", ("Psalm 103:1-5",)),
                 ("Your faith has made you whole", ("Mark 5:25-34",)),
                 ("The prayer of faith", ("James 5:13-16",)),
                 ("My grace is sufficient", ("2 Corinthians 12:7-10",)),
                 ("No more pain", ("Revelation 21:3-5",)))},
    "topic-purpose": {
        "title": "Purpose", "name": "Made on purpose", "hue": "c", "icon": "compass",
        "about": "Seven days on why God made you and what He made you for.",
        "days": (("Fearfully and wonderfully made", ("Psalm 139:13-16",)),
                 ("Created for good works", ("Ephesians 2:10",)),
                 ("A future and a hope", ("Jeremiah 29:11-13",)),
                 ("All things work together", ("Romans 8:28-30",)),
                 ("He will direct your paths", ("Proverbs 3:5-6", "Proverbs 16:9")),
                 ("Seek first the kingdom", ("Matthew 6:33", "Micah 6:8")),
                 ("Whatever you do", ("Colossians 3:23-24", "1 Corinthians 10:31")))},
    "topic-marriage": {
        "title": "Marriage", "name": "Love that lasts", "hue": "d", "icon": "rings",
        "about": "Seven days in what the Bible says about love, covenant and a life built together.",
        "days": (("Not good to be alone", ("Genesis 2:18-24",)),
                 ("Love is patient, love is kind", ("1 Corinthians 13:4-8",)),
                 ("As Christ loved the church", ("Ephesians 5:21-33",)),
                 ("A threefold cord", ("Ecclesiastes 4:9-12",)),
                 ("Above all, put on love", ("Colossians 3:12-14",)),
                 ("Kind and forgiving", ("Ephesians 4:26-32",)),
                 ("Heirs together", ("1 Peter 3:7-9",)))},
    "topic-money": {
        "title": "Money", "name": "Money and enough", "hue": "e", "icon": "coin",
        "about": "Seven days on money, giving and contentment, from the One who owns it all.",
        "days": (("The earth is the Lord's", ("Psalm 24:1", "Deuteronomy 8:17-18")),
                 ("Where your treasure is", ("Matthew 6:19-24",)),
                 ("Content in every state", ("Philippians 4:11-13", "Hebrews 13:5")),
                 ("Godliness with contentment", ("1 Timothy 6:6-10", "1 Timothy 6:17-19")),
                 ("Honour the Lord first", ("Proverbs 3:9-10", "Malachi 3:10")),
                 ("A cheerful giver", ("2 Corinthians 9:6-8",)),
                 ("Faithful in little", ("Luke 16:10-13",)))},
    "topic-grief": {
        "title": "Grief", "name": "Comfort in grief", "hue": "f", "icon": "drop",
        "about": "Seven days of comfort for when you are missing someone, and the hope that holds.",
        "days": (("Blessed are those who mourn", ("Matthew 5:4", "Psalm 34:18")),
                 ("Jesus wept", ("John 11:32-36",)),
                 ("Through the valley", ("Psalm 23",)),
                 ("A time to mourn", ("Ecclesiastes 3:1-4",)),
                 ("Not without hope", ("1 Thessalonians 4:13-18",)),
                 ("The God of all comfort", ("2 Corinthians 1:3-4", "Psalm 46:1")),
                 ("I am the resurrection", ("John 11:25-26", "John 14:1-3")))},
}


def is_topic(key: Any) -> bool:
    return str(key or "") in TOPICS


def count(key: str) -> int:
    return len(TOPICS[key]["days"])


def plan(key: str, started: Optional[date]) -> Optional[Dict[str, Any]]:
    """A topic plan the member started, in reading_plans' shape (what
    read_days, readable_upto, day_number and mark read), or None."""
    if key not in TOPICS or not started:
        return None
    return {"key": key, "title": TOPICS[key]["name"], "start": started, "days": count(key), "own": True}


@lru_cache(maxsize=None)
def _refs(passage: str) -> Tuple[bt.Ref, ...]:
    return tuple(r for _, _, r in bt.find_refs(passage))


def day(key: str, n: int) -> Dict[str, Any]:
    """Day n of a topic plan: {"title", "refs": [Ref, ...]}; {} past its end."""
    days = TOPICS[key]["days"]
    if not 1 <= n <= len(days):
        return {}
    title, passages = days[n - 1]
    return {"title": title, "refs": [r for p in passages for r in _refs(p)]}


def label(key: str, n: int) -> str:
    """The day's passages, as said aloud: "1 Peter 5:6-7 · Psalm 55:22"."""
    return " · ".join(r.label() for r in day(key, n).get("refs") or [])


def href(key: str, n: int) -> str:
    """The day's first passage in the Bible reader, its verses marked."""
    refs = day(key, n).get("refs") or []
    return refs[0].href() if refs else "/my/bible"


@lru_cache(maxsize=None)
def minutes(key: str, tr: str = "kjv") -> int:
    """About how long a day takes, on average: its verses at 170 words a
    minute (member_lumen_bible.WPM), at least one."""
    words = 0
    for n in range(1, count(key) + 1):
        for ref in day(key, n)["refs"]:
            words += sum(t.count(" ") + 1 for _, _, t in bt.verses(ref, tr))
    return max(1, round(words / 170 / max(1, count(key))))


def all_refs() -> List[Tuple[str, int, str]]:
    """(key, day, passage) for every passage written here (the tests read
    each one in every translation)."""
    return [(k, i, p) for k, t in TOPICS.items() for i, (_, ps) in enumerate(t["days"], 1) for p in ps]
