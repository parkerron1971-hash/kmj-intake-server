"""Professional gets its own texting number and three logins; Solutionist seven.

Kevin, 2026-10-22: "yes add the texting number to Professional as well.
also include people being able to login 3 for professional sizes and
solutionist size 7 ... with the different levels I [think] 79 a month should
have something else less [than] the 149 besides credits for chief."

These pin the ladder that answer set, and that Starter stays less than
Professional in more than Chief's credits.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import feature_gates as fg


def test_logins_are_one_three_seven():
    limits = fg.plan_limits()
    assert [limits[p]["max_seats"] for p in ("starter", "professional", "practice")] == [1, 3, 7]


def test_professional_has_its_own_texting_number_and_team_logins():
    assert fg.FEATURE_MIN_PLAN["dedicated_sms_number"] == "professional"
    assert fg.FEATURE_MIN_PLAN["multi_seat"] == "professional"
    pro, practice = fg.plan_features("professional"), fg.plan_features("practice")
    assert {"dedicated_sms_number", "multi_seat"} <= pro <= practice


def test_starter_is_less_than_professional_in_more_than_credits():
    starter, pro = fg.plan_features("starter"), fg.plan_features("professional")
    missing = pro - starter
    for key in ("dedicated_sms_number", "multi_seat", "period_close", "site_concierge", "marketing_week"):
        assert key in missing, key
    limits = fg.plan_limits()
    assert limits["starter"]["max_seats"] < limits["professional"]["max_seats"]
    assert limits["starter"]["plaid_connections"] < limits["professional"]["plaid_connections"]


def test_the_team_answer_on_the_site_matches_the_seats():
    import marketing_pages as mp
    html = mp.render_faq()
    assert "Professional includes three team seats and Solutionist seven" in html
