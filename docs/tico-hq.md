# Tico HQ

Tico HQ (`hq/`) is the small public service the Tico team runs at `https://updates.tico.team`. It is not part of a team's install and
has its own image, database and compose file. An install reaches it only through its own server, and only for what is listed here;
[PRIVACY.md](../PRIVACY.md) is what an owner reads about it.

## Endpoints

| Endpoint | What it is for | Stores |
|---|---|---|
| `GET /v1/latest` | The release check. With the anonymous usage count on, it carries four fields (a random install id, the version and two yes/no activity flags) and answers the latest release, as GitHub would | One row per install id: first and last day seen, last version, last active days |
| `GET /v1/stats` | The public aggregate of that count | Nothing |
| `POST /v1/recruit` | Bot suggestions for one group while a team builds its team chart ([Finish setup](onboarding.md#the-team-builder)) | Nothing |
| `GET /healthz` | Liveness | Nothing |

## `POST /v1/recruit`

```
{"department": "sales", "briefing": "Inbound demos and a few big accounts", "catalog_version": "ee9999fd8f2a",
 "about": {"what": "We sell scheduling software to clinics", "sells_to": "businesses", "software": true},
 "install_id": "<optional v4 UUID>"}
-> 200 {"bots": [{"template_id": "sales-lead", "why": "Heads Sales and reports to you"}, ...],
        "suggested_default": ["sales-lead"], "source": "model" | "local", "catalog_version": "ee9999fd8f2a"}
```

- **Input** is checked strictly: `department` is a group in the templates, `briefing` and `about.what` are strings of at most 500 characters,
  `sells_to` is `businesses`, `consumers`, `both` or empty, `software` is a boolean, `install_id` (optional) is a v4 UUID, and no other
  field is allowed. Anything else is `422 {"error": "invalid"}`, with nothing echoed back. A body over 4 KB is refused.
- **Answer.** Template ids from that group only, the head first, at most 8, each with a why of at most 140 characters, plain
  text on one line. The why is shown to a human; no bot follows it.
- **Model.** OpenAI GPT-6 Luna (`OPENAI_API_KEY`; `HQ_RECRUIT_MODEL` overrides the model) through the Responses API with a JSON schema
  whose template ids are an enum, `store: false`, a 4.5 second timeout and a short prompt holding only the group, its templates
  (id, name, summary, tags), the answer and the three facts. Every id is checked again against the templates.
- **Spend cap.** At most `HQ_RECRUIT_DAILY_CAP` model calls a UTC day (default 2000), counted in memory. Past it, with no key, or on any
  model failure, HQ ranks locally (`source: "local"`) with the same recommender every install has.
- **Cache.** A model answer is kept in memory for an hour under a SHA-256 of the question and the template version; a repeat costs nothing.
- **Rate limits.** In memory, as salted hashes: 30 requests an hour per address and 100 a day per install id, inside HQ's limit of 60
  requests an hour per address for every route. Over any is `429`.
- **Logs.** Nothing logs a request or its body. A failed model call is logged as its exception type only.

### The templates HQ reads

HQ has no templates of its own. `scripts/build_catalog_json.py` builds `hq/catalog.json` (the groups and each card's template,
name, group, icon, tags, suggest level, one-sentence summary and head flag, with no instructions) and copies the recommender
`backend/recruit_rank.py` to `hq/recruit_rank.py`. The Tico server builds its own template list with the same function, so the two agree on
`catalog_version`. Run the script after changing a card or `templates/groups.yaml`; `--check` (run by the test suite) fails when
either copy is stale.

### Running it

`hq/app.py` adds the route with `recruit.install(app, address=address)`, so the client address comes from the same header as the
collector's. Set `OPENAI_API_KEY` (without it every answer is local), and optionally `HQ_RECRUIT_DAILY_CAP` and `HQ_RECRUIT_MODEL`, in
`hq/.env`; `hq/compose.yaml` passes them to the container. The tests are `hq/tests/test_recruit.py`, with the model mocked.
