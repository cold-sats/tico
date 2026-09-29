"""Listening's observation store and the shared intake (backend/listening.py): save what a sweep
saw, score it with the judge, route it, and let each receiver accept or reject what it was sent."""

from backend import listening as L
from backend.store import H
from backend.tests.test_api import api, get, headers, post, setup_attempt  # noqa: F401

RECEIVERS = ("listening", "market-analyst", "content-social", "influencer", "sales-ops", "doc-updater", "recruiting")

# The destinations a company writes in registry/listening.yaml; the hub ships none.
DESTINATIONS = """
destinations:
  market:   {category: market, threshold: 0.70, receiver: bot:market-analyst, what: a concrete fact about a company in the market}
  content:  {category: content, threshold: 0.75, receiver: content-social, readers: [bot:doc-updater], what: a question a post could answer}
  creators: {category: creator, threshold: 0.75, receiver: bot:influencer, what: a creator the company may want to reach}
  partners: {category: partner, threshold: 0.75, receiver: bot:recruiting, what: a consultancy or trainer, a partner lead}
  leads:    {category: lead, threshold: 0.75, receiver: bot:sales-ops, unless: {category: vendor_pitch, threshold: 0.70}, what: a team lead who might use the product}
"""


def _bots(api):
    (api.app.state.store.settings.registry_dir / L.LISTENING_FILE).write_text(DESTINATIONS)
    with api.app.state.store.transaction() as c:
        for slug in RECEIVERS:
            if not H.bot(c, slug):
                c.execute("INSERT INTO bots (slug, display_name, runtime, model, effort, cwd, host, state, created) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", (slug, slug, "fake", "fake", "low", "", "keeper", "active", H.now()))
            if not c.execute("SELECT 1 FROM bot_config WHERE bot=?", (slug,)).fetchone():
                c.execute("INSERT INTO bot_config (bot, config_json, team, operator, description, reports_to, repo) "
                          "VALUES (?,?,?,?,?,?,?)", (slug, "{}", "marketing", "ana", slug, "cmo", "emp-" + slug))


def _token(api, slug):
    return setup_attempt(api, slug)[2]["token"]


def _post(native_id, text, author="@host1"):
    return {"native_id": native_id, "url": f"https://x.com/{author.strip('@')}/status/{native_id}",
            "author": author, "author_url": f"https://x.com/{author.strip('@')}", "content": text,
            "published_at": "2026-09-23T10:00:00Z"}


class FakeJudge:
    """Scores by keyword so a test says which categories a post should clear."""

    def __init__(self):
        self.calls = []

    def __call__(self, state, questions, label=None):
        self.calls.append((state, label))
        text = state["content"].lower()
        answers = {qid: {"type": "noul", "noul": 0.05} for qid in questions}
        for qid in questions:
            if f"[{qid}]" in text:
                answers[qid]["noul"] = 0.9
        return {"answers": answers, "ms": 1, "model": "fake-judge", "usage": {}}


def test_only_listening_and_the_owner_save_runs_and_judgments(api):
    _bots(api)
    coo = _token(api, "coo")
    post(api, "listening/runs", {"source": "x", "query": "q", "status": "ok"}, token=coo, expected=403)
    post(api, "listening/runs", {"source": "X Bookmarks", "query": "q", "status": "ok"}, expected=422)
    saved = post(api, "listening/runs", {"source": "x", "query": "q", "status": "ok", "items": [_post("9", "hi")]})
    post(api, "listening/judgments", {"judgments": [{"item_id": saved["items"][0]["id"], "question_set": "x@1",
                                                     "scores": {"lead": 0.9}}]}, token=coo, expected=403)
    post(api, "listening/judgments", {"judgments": [{"item_id": saved["items"][0]["id"], "question_set": "x@1",
                                                     "scores": {"lead": 1.5}}]}, expected=422)


def test_the_judge_scores_every_category_and_a_post_goes_to_every_inbox_it_clears(api):
    _bots(api)
    listening = _token(api, "listening")
    judge_engine = FakeJudge()
    api.app.state.judge = judge_engine
    saved = post(api, "listening/runs", {"source": "x", "query": "q", "status": "ok", "items": [
        _post("1", "Creator with 40k followers asks how to price sprints [creator] [content]"),
        _post("2", "Atlia raised a seed round [market]"),
        _post("3", "nice weather today")]}, token=listening)
    ids = [i["id"] for i in saved["items"]]
    judged = post(api, "listening/judge", {"limit": 10}, token=listening)
    assert judged["question_set"] == "listening-item@5" and judged["judged"] == 3 and not judged["errors"]
    assert len(judge_engine.calls) == 3 and judge_engine.calls[0][1] == "listening-item@5"
    assert set(judge_engine.calls[0][0]) == {"source", "url", "author", "published_at", "content"}
    by_item = {r["judgment"]["item_id"]: sorted(o["destination"] for o in r["intake"]) for r in judged["results"]}
    assert by_item == {ids[0]: ["content", "creators"], ids[1]: ["market"], ids[2]: []}
    # Every category's probability is kept, not only the ones that routed.
    scores = judged["results"][0]["judgment"]["scores"]
    assert set(scores) == {"market", "content", "lead", "vendor_pitch", "creator", "partner"}
    # Each call is audited as a judge call against Listening's budget.
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM events WHERE actor='bot:listening' AND action='judge.call' "
                         "AND target='listening-item@5'").fetchone()[0] == 3
    # Nothing is left to judge from this set, so a second pass calls the judge for nothing.
    assert post(api, "listening/judge", {"limit": 10}, token=listening)["judged"] == 0
    assert len(judge_engine.calls) == 3
    # Reclassification: a new judgment adds the inbox the post now clears and leaves the rest alone.
    before = get(api, "intake?destination=creators", token=listening)["items"]
    redo = post(api, "listening/judgments", {"judgments": [
        {"item_id": ids[0], "question_set": "listening-item@6", "scores": {"creator": 0.2, "market": 0.95}},
        {"item_id": ids[0], "question_set": "listening-item@6", "scores": {"creator": 0.2, "market": 0.95}}]},
        token=listening)["results"]
    assert [o["destination"] for o in redo[0]["intake"]] == ["market"] and redo[1]["intake"] == []
    after = get(api, "intake?destination=creators", token=listening)["items"]
    assert [(r["id"], r["judgment_id"]) for r in after] == [(r["id"], r["judgment_id"]) for r in before]
    trace = get(api, f"listening/items/{ids[0]}", token=listening)
    assert trace["current"]["question_set"] == "listening-item@6" and len(trace["judgments"]) == 3
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM intake_items WHERE item_id=?", (ids[0],)).fetchone()[0] == 3


def test_a_receiver_sees_and_resolves_only_its_own_inbox(api):
    _bots(api)
    listening = _token(api, "listening")
    api.app.state.judge = FakeJudge()
    saved = post(api, "listening/runs", {"source": "x", "query": "q", "status": "ok", "items": [
        _post("1", "Creator asks how teams handle standups [creator] [content]")]}, token=listening)
    post(api, "listening/judge", {}, token=listening)
    sales = _token(api, "influencer")
    inbox = get(api, "intake", token=sales)["items"]
    assert [i["destination"] for i in inbox] == ["creators"]
    assert inbox[0]["post"]["author"] == "@host1" and inbox[0]["routed_because"] == "creator >= 0.75"
    get(api, "intake?destination=content", token=sales, expected=403)
    content_id = get(api, "intake?destination=content", token=listening)["items"][0]["id"]
    post(api, f"intake/{content_id}/resolve", {"status": "accepted", "receiver_ref": "x"}, token=sales, expected=403)
    sid = inbox[0]["id"]
    post(api, f"intake/{sid}/resolve", {"status": "accepted"}, token=sales, expected=422)
    post(api, f"intake/{sid}/resolve", {"status": "rejected"}, token=sales, expected=422)
    done = post(api, f"intake/{sid}/resolve", {"status": "accepted", "receiver_ref": "instagram:@host1"}, token=sales)
    assert done["intake"]["status"] == "accepted" and done["intake"]["decided_at"]
    # Saying it again is harmless; changing the verdict is refused.
    assert post(api, f"intake/{sid}/resolve", {"status": "accepted", "receiver_ref": "instagram:@host1"},
                token=sales)["intake"]["id"] == sid
    post(api, f"intake/{sid}/resolve", {"status": "rejected", "reason": "a travel account"}, token=sales, expected=409)
    assert get(api, "intake", token=sales)["items"] == []
    assert get(api, "intake?status=accepted", token=sales)["items"][0]["receiver_ref"] == "instagram:@host1"
    # A receiver traces what it was sent; another bot cannot open the post at all.
    assert get(api, f"listening/items/{saved['items'][0]['id']}", token=sales)["intake"][0]["destination"] == "creators"
    get(api, f"listening/items/{saved['items'][0]['id']}", token=_token(api, "finance"), expected=403)
    stats = get(api, "listening/stats", token=listening)
    assert stats["destinations"]["creators"]["precision"] == 1.0 and stats["destinations"]["content"]["new"] == 1
    assert stats["coverage"]["x"]["ok"]["runs"] == 1


def test_hub_sql_shows_posts_only_to_listening_the_owner_and_their_receivers(api):
    _bots(api)
    listening = _token(api, "listening")
    api.app.state.judge = FakeJudge()
    post(api, "listening/runs", {"source": "x", "query": "q", "status": "ok", "items": [
        _post("1", "A creator for team leads [creator]"), _post("2", "Atlia news [market]")]}, token=listening)
    post(api, "listening/judge", {}, token=listening)

    def rows(sql, token):
        return post(api, "sql", {"sql": sql}, token=token)["rows"]

    finance, sales = _token(api, "finance"), _token(api, "influencer")
    assert rows("SELECT count(*) FROM listen_runs", finance)[0][0] == 1
    assert rows("SELECT count(*) FROM listen_items", finance)[0][0] == 0
    assert rows("SELECT count(*) FROM intake_items", finance)[0][0] == 0
    assert rows("SELECT native_id FROM listen_items", sales) == [["1"]]
    assert rows("SELECT destination FROM intake_items", sales) == [["creators"]]
    assert rows("SELECT count(*) FROM listen_judgments", sales)[0][0] == 1
    assert rows("SELECT count(*) FROM listen_items", listening)[0][0] == 2
    assert rows("SELECT count(*) FROM listen_items", "ana-test")[0][0] == 2


def test_every_destination_names_a_category_the_question_set_asks(api):
    from clients import judge as J
    _bots(api)
    settings = api.app.state.store.settings
    questions = J.load_set(L.QUESTION_SET)["questions"]
    assert {cfg["category"] for cfg in L.destinations(settings).values()} <= set(questions)
    assert {cfg["unless"]["category"] for cfg in L.destinations(settings).values() if cfg.get("unless")} <= set(questions)
    assert all(q["type"] == "noul" for q in questions.values())
    assert all(0 < cfg["threshold"] <= 1 for cfg in L.destinations(settings).values())


def test_a_vendor_pitch_dressed_as_a_question_is_not_a_lead(api):
    """2026-09-24: both leads imported in the test sweep were vendors asking "X vs Y: how are you
    handling…". A pitch still counts for the market and content; it is never a lead."""
    _bots(api)
    listening = _token(api, "listening")
    api.app.state.judge = FakeJudge()
    saved = post(api, "listening/runs", {"source": "reddit", "query": "q", "status": "ok", "items": [
        _post("1", "Northwind vs Tracklight: how are you tracking sprints? [lead] [vendor_pitch] [content]"),
        _post("2", "Our PM tool broke the week of a launch, what do I do? [lead] [content]")]},
        token=listening)
    ids = [i["id"] for i in saved["items"]]
    judged = post(api, "listening/judge", {"limit": 10}, token=listening)
    by_item = {r["judgment"]["item_id"]: sorted(o["destination"] for o in r["intake"]) for r in judged["results"]}
    assert by_item == {ids[0]: ["content"], ids[1]: ["content", "leads"]}


def test_doc_updater_reads_the_content_inbox_for_community_research_and_decides_nothing(api):
    """2026-09-24: nobody kept the community research current after the COO review ended. Doc
    Updater reads leads' questions from the content inbox; Content still decides each item."""
    _bots(api)
    listening = _token(api, "listening")
    api.app.state.judge = FakeJudge()
    saved = post(api, "listening/runs", {"source": "reddit", "query": "q", "status": "ok", "items": [
        _post("1", "How do you keep a standup short? [content]"),
        _post("2", "Creator with 40k followers [creator]", author="@creator1")]}, token=listening)
    post(api, "listening/judge", {}, token=listening)
    docs = _token(api, "doc-updater")
    inbox = get(api, "intake", token=docs)["items"]
    assert [i["destination"] for i in inbox] == ["content"]
    get(api, "intake?destination=creators", token=docs, expected=403)
    post(api, f"intake/{inbox[0]['id']}/resolve", {"status": "rejected", "reason": "no"}, token=docs, expected=403)
    assert get(api, f"listening/items/{saved['items'][0]['id']}", token=docs)["intake"][0]["destination"] == "content"
    rows = post(api, "sql", {"sql": "SELECT i.content FROM listen_items i"}, token=docs)["rows"]
    assert [r["content"] if isinstance(r, dict) else r[0] for r in rows] == ["How do you keep a standup short? [content]"]


def test_a_consultancy_goes_to_the_partners_inbox(api):
    """A training consultancy went nowhere; partners are the company's channel."""
    _bots(api)
    listening = _token(api, "listening")
    api.app.state.judge = FakeJudge()
    post(api, "listening/runs", {"source": "reddit", "query": "q", "status": "ok", "items": [
        _post("1", "We run onboarding workshops for 40 teams a year [partner]")]}, token=listening)
    post(api, "listening/judge", {}, token=listening)
    pros = get(api, "intake", token=_token(api, "recruiting"))["items"]
    assert [i["destination"] for i in pros] == ["partners"] and pros[0]["routed_because"] == "partner >= 0.75"

