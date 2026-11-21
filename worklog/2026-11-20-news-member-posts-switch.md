---
title: "Mission Control's News room turns members' posting on or off (backend)"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin: 'finish'. The remaining Look 5.1 piece after the tidy-ups: the member-posting on/off switch in Mission Control's News room, and held posts and moments named as such."
status: shipped
prs: [kmj-intake-server#2025, solutionist-studio#1667]
migrations: []
left_undone:
  - "The app's toggle and held wording are solutionist-studio#1667 (frontend repo). It reads the fields added here and looks like today's room until they're live."
  - "The switch is shown only where members can post today (member_lumen.at_church): Love City while MEMBER_LUMEN is preview or owner, every church once it is on."
decisions:
  - "POST /church/news/settings takes member_posts (admin seat, the same gate as the other News settings). Off writes settings.member_portal.member_posts = false; on removes the key, the same default member_posts.on() reads. It shares one member_portal dict with alerts, so both in one call keep both. The owner's preview switch (/my/post/switch, member_posts.save_switch) is unchanged."
  - "After a change this server drops its kept church row (member_cache.forget_church) and logs who switched it (office:<user id>). Other replicas catch up when their kept row expires, as with the preview switch."
  - "GET /church/news settings carries member_posts (where it stands) and member_posts_here (member_lumen.at_church: on everywhere, owner/preview only at the platform owner's own church, never off), because only the new look has the composer."
related: [2026-11-20-lumen-tidy-ups.md]
---
No new table, column or member-page read. The News view's new member_posts_here asks member_lumen, which
reads the church's owner at most once per view (member_asks.platform_church), in Mission Control only.

Tests: test_the_office_turns_members_posting_off_and_on (403 for a member seat, off, on, another setting
leaves it), test_the_switch_shows_only_where_the_new_look_is (every MEMBER_LUMEN mode), and the News view
test pins settings. church_news, news_alerts, member_posts, member_moments, news_share, church_groups_office
and member_lumen pass. test_celebrations fails the same 3 on clean main when the machine's date isn't UTC's
(the tests mix date.today() with a UTC clock); CI runs in UTC.
