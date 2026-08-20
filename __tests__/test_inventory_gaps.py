# __tests__/test_inventory_gaps.py
#
# The three gaps this arc left open, closed 2026-08-20.
#
#   1. Selling used to be read-then-write, so two simultaneous orders on
#      the last unit could both succeed. It now goes through the
#      decrement_offering_stock() Postgres function, which locks the row
#      first. The test that matters is a DRIFT test: if anyone puts the
#      PATCH back, the race comes back silently and no customer-visible
#      behaviour changes until the day two people check out at once.
#
#   2. A product sold on an INVOICE never left the shelf. Closed with a
#      trigger rather than by patching call sites, because one of the
#      five paths that marks an invoice paid is the frontend PATCHing
#      PostgREST directly and cannot call Python at all.
#
#   3. A manager could count and receive but not add. Closed by
#      consequence, not by table: they can create a PRICE-LESS product,
#      which store_router._sellable_offerings already refuses to show,
#      so a manager still cannot publish something for sale.

import inventory_scan as iscan
import store_router


class _Rpc:
    """Stands in for the Postgres function."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, path, body, *a, **kw):
        self.calls.append((path, body))
        return self.reply


def _quiet(monkeypatch):
    """Silence the two best-effort side effects so the tests assert on
    the decrement contract and not on notification plumbing."""
    events = []
    alerts = []
    monkeypatch.setattr(store_router, "_emit_stock_event",
                        lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(store_router, "_maybe_low_stock_alert",
                        lambda *a, **k: alerts.append(a))
    return events, alerts


# ─── 1. The oversell race ────────────────────────────────────────────


def test_a_sale_goes_through_the_atomic_function(monkeypatch):
    # THE DRIFT TEST. A read-then-write decrement is indistinguishable
    # from this one until two people buy the last unit at the same
    # moment, so the guard has to be on the CALL, not the outcome.
    rpc = _Rpc([{"old_qty": 5, "new_qty": 3, "tracked": True}])
    monkeypatch.setattr(store_router.sb_clients, "sb_post_as_service", rpc)
    events, _ = _quiet(monkeypatch)

    out = store_router.sell_units("biz", "off", 2, reason="order abc", actor="sale")

    assert out == {"old_qty": 5, "new_qty": 3}
    assert len(rpc.calls) == 1
    path, body = rpc.calls[0]
    assert path == "/rpc/decrement_offering_stock"
    assert body == {"p_offering_id": "off", "p_business_id": "biz", "p_qty": 2}
    # The movement history still gets the true delta.
    (args, _kw) = events[0]
    assert args[0] == "biz" and args[1] == "off"
    assert _kw["delta"] == -2 and _kw["new_qty"] == 3


def test_an_untracked_product_is_not_an_error(monkeypatch):
    # Most offerings are services. A sale that touches one must return
    # quietly, or every caller has to special-case it and one of them
    # will forget.
    rpc = _Rpc([{"old_qty": None, "new_qty": None, "tracked": False}])
    monkeypatch.setattr(store_router.sb_clients, "sb_post_as_service", rpc)
    events, _ = _quiet(monkeypatch)

    assert store_router.sell_units("biz", "off", 2, reason="r", actor="sale") is None
    assert events == []          # no phantom movement row


def test_a_zero_or_negative_sale_never_reaches_the_database(monkeypatch):
    rpc = _Rpc([{"old_qty": 5, "new_qty": 5, "tracked": True}])
    monkeypatch.setattr(store_router.sb_clients, "sb_post_as_service", rpc)
    _quiet(monkeypatch)
    assert store_router.sell_units("biz", "off", 0, reason="r", actor="sale") is None
    assert store_router.sell_units("biz", "off", -3, reason="r", actor="sale") is None
    assert rpc.calls == []


def test_a_database_failure_does_not_take_the_webhook_down(monkeypatch):
    # This runs inside the Stripe webhook. An inventory problem must
    # never stop a payment being recorded.
    def boom(*a, **k):
        raise RuntimeError("postgres said no")
    monkeypatch.setattr(store_router.sb_clients, "sb_post_as_service", boom)
    events, _ = _quiet(monkeypatch)
    assert store_router.sell_units("biz", "off", 1, reason="r", actor="sale") is None
    assert events == []


def test_a_malformed_rpc_reply_is_survived(monkeypatch):
    for reply in (None, [], {}, [{"tracked": True}], "nonsense"):
        rpc = _Rpc(reply)
        monkeypatch.setattr(store_router.sb_clients, "sb_post_as_service", rpc)
        _quiet(monkeypatch)
        assert store_router.sell_units("biz", "off", 1, reason="r", actor="sale") is None


def test_the_low_stock_alert_still_fires_on_a_sale(monkeypatch):
    # The reorder brain hangs off this. If a sale stops feeding it, the
    # purchase order never gets drafted and nobody notices for weeks.
    rpc = _Rpc([{"old_qty": 3, "new_qty": 1, "tracked": True}])
    monkeypatch.setattr(store_router.sb_clients, "sb_post_as_service", rpc)
    _events, alerts = _quiet(monkeypatch)
    store_router.sell_units("biz", "off", 2, reason="r", actor="sale",
                            offering_name="Pomade", thresholds={"off": 2})
    assert len(alerts) == 1
    assert alerts[0][3] == 3 and alerts[0][4] == 1   # old, new


def test_mark_order_paid_no_longer_patches_inventory_directly():
    # The same drift guard, at the call site the race actually lived in.
    import inspect
    src = inspect.getsource(store_router.mark_order_paid)
    assert "sell_units(" in src
    assert '"inventory_qty": new_qty' not in src


# ─── 3. The stock-only product ───────────────────────────────────────


def test_slugify_makes_a_url_safe_name():
    assert iscan.slugify("Layrite Superhold Pomade 4oz!!") == "layrite-superhold-pomade-4oz"
    assert iscan.slugify("   ") == "product"          # never an empty slug
    assert iscan.slugify("///") == "product"
    assert len(iscan.slugify("x" * 200)) <= 60


def test_free_slug_steps_around_a_name_already_taken(monkeypatch):
    monkeypatch.setattr(iscan.sb_clients, "sb_get_as_service",
                        lambda p: [{"slug": "pomade"}, {"slug": "pomade-2"}])
    assert iscan.free_slug("biz", "pomade") == "pomade-3"


def test_free_slug_leaves_a_free_name_alone(monkeypatch):
    monkeypatch.setattr(iscan.sb_clients, "sb_get_as_service", lambda p: [])
    assert iscan.free_slug("biz", "pomade") == "pomade"


def test_a_manager_created_product_has_no_price():
    # THE ALARM. The price-less state IS the permission boundary: a
    # manager may make a product countable, never sellable. If a price
    # ever gets set here, a manager silently gains the ability to
    # publish a priced item to the practitioner's public storefront.
    import inspect
    src = inspect.getsource(iscan.create_stock_product)
    assert '"current_price": None' in src
    assert 'require_role(business_id, str(user.id), "manager")' in src


def test_a_priceless_product_cannot_reach_the_storefront():
    # The other half of that boundary, asserted where it is enforced.
    # store_router._sellable_offerings skips price <= 0, which is what
    # makes "no price" mean "not for sale" rather than "free".
    import inspect
    src = inspect.getsource(store_router._sellable_offerings)
    assert "if price <= 0:" in src
    assert "continue" in src


def test_stock_product_route_exists_and_is_authed():
    from auth_supabase import require_user
    paths = {}
    for r in iscan.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in paths.get("/store/inventory/{business_id}/product", set())
    for r in iscan.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_stock_product_body_rejects_nonsense():
    import pydantic
    for bad in ({"name": ""}, {"name": "x", "inventory_qty": -1}):
        try:
            iscan.StockProductBody(**bad)
        except pydantic.ValidationError:
            continue
        raise AssertionError(f"{bad} should have been rejected")
    ok = iscan.StockProductBody(name="Pomade")
    assert ok.inventory_qty == 0        # counted from zero, not untracked
