"""LGS Phase 4 tests — Growth Objective spawn engine + Chief context block.

Mocks the sb_clients service-role helpers with a path-routed fake so we can
assert: objective insert, module spawn (incl. restricted skip), workflow clone
(incl. reactive-trigger disabled per Fork 21), milestone creation, linked-id
backfill, and the growth context block. No live DB.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import growth_objective_agent as goa


class FakeService:
    """Routes sb_clients service-role calls against an in-memory fixture."""

    def __init__(self, business_type="coach", blueprint=None, templates=None,
                 existing_modules=None, existing_workflows=None):
        self.business_type = business_type
        self.blueprint = blueprint or {}      # slug -> row
        self.templates = templates or {}      # slug -> workflow template row
        self.existing_modules = existing_modules or []
        self.existing_workflows = existing_workflows or []
        self.posts = []                        # (path, body)
        self.patches = []                      # (path, body)
        self._id = 0

    def get(self, path):
        if "/businesses?" in path and "select=type" in path:
            return [{"type": self.business_type}]
        if "/custom_modules?" in path and "select=slug" in path:
            return [{"slug": s} for s in self.existing_modules]
        if "/business_type_module_blueprint?" in path:
            # parse module_slug=eq.<slug>
            slug = path.split("module_slug=eq.")[1].split("&")[0]
            row = self.blueprint.get(slug)
            return [row] if row else []
        if "/workflow_definitions?" in path and "select=slug" in path:
            return [{"slug": s} for s in self.existing_workflows]
        if "/workflow_definitions?" in path and "business_id=is.null" in path:
            slug = path.split("slug=eq.")[1].split("&")[0]
            t = self.templates.get(slug)
            return [t] if t else []
        return []

    def post(self, path, body):
        self.posts.append((path, body))
        self._id += 1
        return [{**body, "id": f"new-{self._id}"}]

    def patch(self, path, body):
        self.patches.append((path, body))
        return [body]


def _install(fake):
    return [
        patch.object(goa.sb_clients, "sb_get_as_service", side_effect=fake.get),
        patch.object(goa.sb_clients, "sb_post_as_service", side_effect=fake.post),
        patch.object(goa.sb_clients, "sb_patch_as_service", side_effect=fake.patch),
    ]


class CreateObjectiveTests(unittest.TestCase):

    def _run(self, fake, payload):
        ps = _install(fake)
        for p in ps:
            p.start()
        try:
            return goa.create_growth_objective("biz-1", payload)
        finally:
            for p in reversed(ps):
                p.stop()

    def test_bare_objective_no_spawns(self):
        fake = FakeService()
        res = self._run(fake, {"title": "Launch group program"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["objective"]["title"], "Launch group program")
        self.assertEqual(res["spawn_report"]["modules_created"], [])
        self.assertEqual(res["spawn_report"]["workflows_created"], [])

    def test_requires_title(self):
        fake = FakeService()
        res = self._run(fake, {"decision_summary": "no title"})
        self.assertFalse(res["ok"])

    def test_module_spawn_creates_from_blueprint(self):
        fake = FakeService(blueprint={
            "cohorts": {"module_slug": "cohorts", "module_name": "Cohorts",
                        "schema": {"fields": []}, "agent_config": {}, "sort_order": 1},
        })
        res = self._run(fake, {"title": "Group program", "spawns": {"modules": ["cohorts"]}})
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["spawn_report"]["modules_created"]), 1)
        # custom_modules POST happened
        self.assertTrue(any(p[0] == "/custom_modules" for p in fake.posts))

    def test_module_spawn_skips_restricted(self):
        fake = FakeService(blueprint={
            "giving": {"module_slug": "giving", "module_name": "Giving",
                       "schema": {}, "agent_config": {"access_level": "restricted"}},
        })
        res = self._run(fake, {"title": "Stewardship", "spawns": {"modules": ["giving"]}})
        self.assertTrue(res["ok"])
        # Restricted module NOT spawned — Giving guard holds in the spawn path too.
        self.assertEqual(res["spawn_report"]["modules_created"], [])
        self.assertFalse(any(p[0] == "/custom_modules" for p in fake.posts))

    def test_module_spawn_skips_existing(self):
        fake = FakeService(
            existing_modules=["cohorts"],
            blueprint={"cohorts": {"module_slug": "cohorts", "module_name": "C",
                                   "schema": {}, "agent_config": {}}},
        )
        res = self._run(fake, {"title": "x", "spawns": {"modules": ["cohorts"]}})
        self.assertEqual(res["spawn_report"]["modules_created"], [])

    def test_workflow_clone_disables_reactive_trigger(self):
        fake = FakeService(templates={
            "enroll-on-pay": {"name": "Enroll on payment", "slug": "enroll-on-pay",
                              "trigger": {"event_type": "payment.succeeded"},
                              "steps": [{"action": "log"}], "enabled": True},
        })
        res = self._run(fake, {"title": "Auto-enroll", "spawns": {"workflows": ["enroll-on-pay"]}})
        self.assertEqual(len(res["spawn_report"]["workflows_created"]), 1)
        wf_post = [b for (p, b) in fake.posts if p == "/workflow_definitions"][0]
        # Fork 21: a payment.* (reactive) trigger is cloned DISABLED.
        self.assertFalse(wf_post["enabled"])
        self.assertEqual(wf_post["source"], "growth_objective")

    def test_workflow_clone_enables_non_reactive(self):
        fake = FakeService(templates={
            "weekly-checkin": {"name": "Weekly check-in", "slug": "weekly-checkin",
                               "trigger": {"event_type": "schedule.weekly"},
                               "steps": [{"action": "log"}], "enabled": True},
        })
        res = self._run(fake, {"title": "Cadence", "spawns": {"workflows": ["weekly-checkin"]}})
        wf_post = [b for (p, b) in fake.posts if p == "/workflow_definitions"][0]
        self.assertTrue(wf_post["enabled"])  # non-reactive → enabled

    def test_milestones_created(self):
        fake = FakeService()
        res = self._run(fake, {"title": "Launch", "spawns": {
            "milestones": [{"title": "Define offer"}, {"title": "First cohort"}]}})
        self.assertEqual(res["spawn_report"]["milestones_created"], 2)

    def test_linked_ids_backfilled(self):
        fake = FakeService(blueprint={
            "cohorts": {"module_slug": "cohorts", "module_name": "C", "schema": {}, "agent_config": {}}})
        res = self._run(fake, {"title": "x", "spawns": {"modules": ["cohorts"]}})
        # A PATCH to growth_objectives with linked_module_ids happened.
        self.assertTrue(any("linked_module_ids" in b for (_, b) in fake.patches))


class GrowthContextBlockTests(unittest.TestCase):

    def test_empty_when_no_active(self):
        with patch.object(goa, "list_objectives", return_value=[]):
            self.assertEqual(goa.growth_context_block("biz-1"), "")

    def test_renders_active_objectives(self):
        objs = [
            {"title": "Group program", "status": "active",
             "metrics": {"target": "12 members"}, "target_date": "2026-09-01"},
            {"title": "Recurring revenue", "status": "at_risk", "metrics": {}},
            {"title": "Old done", "status": "achieved", "metrics": {}},  # excluded
        ]
        with patch.object(goa, "list_objectives", return_value=objs):
            block = goa.growth_context_block("biz-1")
        self.assertIn("Group program", block)
        self.assertIn("12 members", block)
        self.assertIn("at_risk", block)
        self.assertNotIn("Old done", block)  # achieved not surfaced
        self.assertIn("Growth Partner", block)


if __name__ == "__main__":
    unittest.main()
