"""A manager's reports keep the order someone put them in on the team chart (backend/report_order.py): stored on the
server for every viewer, a new report goes last, and only someone who may put reports under that manager orders them."""
from backend.tests.test_api import api, get, headers, post, put, setup_attempt  # noqa: F401
from backend.tests.test_org_chart import revision, roster


def order(api, manager, token="ana-test"):
    return [r["id"] for r in get(api, "org/order/" + manager, token=token)["reports"]]


def report_to(api, bot, boss, token="ana-test", expected=200):
    post(api, f"bots/{bot}/definition", {"reports_to": boss, "expected_revision": revision(api, bot)},
         token=token, expected=expected)


def chart(api):
    roster(api, [{"id": "ana", "email": "ana@acme.example", "name": "Ana", "primary_for": ["*"]},
                 {"id": "ben", "email": "ben@acme.example", "name": "Ben", "reports_to": "ana"},
                 {"id": "cara", "email": "cara@acme.example", "name": "Cara", "reports_to": "ana"}])
    for bot in ("ops", "finance", "doc-updater"):
        report_to(api, bot, "coo")


def test_the_order_is_kept_for_everyone_and_a_new_report_goes_last(api):
    chart(api)
    assert order(api, "coo") == ["doc-updater", "finance", "ops"]          # nobody placed them: by name
    put(api, "org/order/coo", {"reports": ["ops", "doc-updater", "finance"]})
    assert order(api, "coo") == order(api, "coo", token="cara-test") == ["ops", "doc-updater", "finance"]
    places = {e["name"]: e.get("report_position") for e in api.get("/api/employees", headers=headers("cara-test")).json()}
    assert places["ops"] == 0 and places["finance"] == 2 and places["cpo"] is None
    # Naming two swaps just those two; the others keep their places.
    put(api, "org/order/coo", {"reports": ["finance", "ops"]})
    assert order(api, "coo") == ["finance", "doc-updater", "ops"]
    # A new report goes last, whatever its name; one that leaves and comes back is new again.
    report_to(api, "cpo", "coo")
    assert order(api, "coo") == ["finance", "doc-updater", "ops", "cpo"]
    report_to(api, "ops", "human:ben")
    report_to(api, "ops", "coo")
    assert order(api, "coo") == ["finance", "doc-updater", "cpo", "ops"]
    # Humans are ordered under a human the same way, and only direct reports can be named.
    put(api, "org/order/ana", {"reports": ["cara", "ben"]})
    assert order(api, "human:ana")[:2] == ["cara", "ben"]
    for wrong in (["nobody"], ["ben"], ["ops", "ops"]):
        put(api, "org/order/coo", {"reports": wrong}, expected=422)
    get(api, "org/order/nobody", expected=404)
    report_to(api, "finance", "inbox")                     # only Ana sees the mail bot: to Cara it is nobody
    get(api, "org/order/inbox", token="cara-test", expected=404)
    assert order(api, "inbox") == ["finance"]


def test_only_someone_who_may_put_reports_there_orders_them(api):
    chart(api)
    put(api, "org/order/coo", {"reports": ["ops", "finance", "doc-updater"]})
    # Cara is a member nothing reports up to: she sees the order and may not change it.
    view = get(api, "org/order/coo", token="cara-test")
    assert view["can_order"] is False
    put(api, "org/order/coo", {"reports": ["finance", "ops"]}, token="cara-test", expected=403)
    # Nor may she move a report onto another manager: nothing moves, and the order stays.
    report_to(api, "ops", "human:cara", token="cara-test", expected=403)
    assert order(api, "coo") == ["ops", "finance", "doc-updater"]
    # Once the COO reports to her, she may order its reports.
    report_to(api, "coo", "human:cara")
    assert get(api, "org/order/coo", token="cara-test")["can_order"] is True
    put(api, "org/order/coo", {"reports": ["finance", "ops"]}, token="cara-test")
    # A bot orders its own reports, and no other bot's.
    _, _, coo = setup_attempt(api, "coo")
    _, _, ops = setup_attempt(api, "ops")
    put(api, "org/order/coo", {"reports": ["doc-updater", "ops", "finance"]}, token=coo["token"])
    put(api, "org/order/coo", {"reports": ["ops"]}, token=ops["token"], expected=403)
    assert order(api, "coo") == ["doc-updater", "ops", "finance"]
