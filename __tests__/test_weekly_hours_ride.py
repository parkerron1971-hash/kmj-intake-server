"""The weekly hours reach the builder (2026-10-04, the library grows).
The hours card and the times strip light "Open now" and "Next" from
data-day / data-open / data-close / data-tz. Those must come from the
business's own availability settings, in its own timezone, or the light
would be a guess. Pins: every day is listed (closed days too), the
timezone is repaired the way availability repairs it, the open-all-week
default (nothing set) is not a week, and the line rides THE REAL DATA."""
import builder_v2

WEEK = {"timezone": "America/New York",
        "weekly": {"tue": [{"start": "09:00", "end": "18:00"}],
                   "sat": [{"start": "10:00", "end": "14:00"}, {"start": "15:00", "end": "17:00"}],
                   "mon": [], "wed": [{"start": "9", "end": "5"}]}}


def _ctx(av=None):
    return {"business": {"id": "b", "name": "Marrow & Steel", "type": "barbershop"},
            "offerings": [], "testimonials": [], "gallery": [], "contact": {},
            "settings": {"availability": av} if av is not None else {},
            "site": {"site_config": {}}, "dna": {}, "bundle": {}}


def test_every_day_is_listed_with_its_data_day_and_the_business_timezone():
    block = builder_v2.weekly_hours_block(_ctx(WEEK))
    assert "timezone America/New_York" in block, "repaired like availability repairs it"
    assert "- Sunday (data-day 0): closed" in block
    assert "- Tuesday (data-day 2): 09:00 to 18:00" in block
    assert "- Saturday (data-day 6): 10:00 to 14:00, 15:00 to 17:00" in block
    assert "- Wednesday (data-day 3): closed" in block, "a malformed span is not an hour"
    assert block.count("data-day") == 7


def test_no_hours_set_means_no_week():
    assert builder_v2.weekly_hours_block(_ctx()) == ""
    assert builder_v2.weekly_hours_block(_ctx({"weekly": {"mon": [], "tue": []}})) == ""
    assert builder_v2.weekly_hours_block({"settings": "bad"}) == ""


def test_an_unusable_timezone_is_left_out_not_invented():
    block = builder_v2.weekly_hours_block(_ctx({"timezone": "Mars/Olympus",
                                                "weekly": {"fri": [{"start": "08:00", "end": "12:00"}]}}))
    assert "Friday (data-day 5): 08:00 to 12:00" in block and "timezone" not in block


def test_the_week_rides_the_real_data_and_its_times_pass_the_truth_law():
    data = builder_v2.assemble_real_data(_ctx(WEEK), "b")
    assert "WEEKLY HOURS" in data and "Tuesday (data-day 2): 09:00 to 18:00" in data
    page = '<p>Tuesday 09:00 to 18:00</p><tr data-day="2" data-open="09:00" data-close="18:00">'
    assert builder_v2.check_truth(page, data) == []
