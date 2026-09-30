# Tico HQ

Tico HQ (`hq/`) is the small public service the Tico team runs at `https://hq.tico.team`. It is not part of a company's install and
has its own image, database and compose file. An install reaches it only through its own server, and only for what is listed here;
[PRIVACY.md](../PRIVACY.md) is what an owner reads about it.

## Endpoints

| Endpoint | What it is for | Stores |
|---|---|---|
| `GET /v1/latest` | The release check. With the anonymous usage count on, it carries four fields (a random install id, the version and two yes/no activity flags) and answers the latest release, as GitHub would | One row per install id: first and last day seen, last version, last active days |
| `GET /v1/stats` | The public aggregate of that count | Nothing |
| `POST /v1/recruit` | Bot suggestions for one department while a company builds its org chart ([First run](onboarding.md#the-org-builder)) | Nothing |
| `GET /healthz` | Liveness | Nothing |

## `POST /v1/recruit`

```
{"department": "sales", "briefing": "Inbound demos and a few big accounts", "catalog_version": "ee9999fd8f2a",
 "about": {"what": "We sell scheduling software to clinics", "sells_to": "businesses", "software": true},
 "install_id": "<optional v4 UUID>"}
-> 200 {"bots": [{"template_id": "sales-lead", "why": "Heads Sales and reports to you"}, ...],
        "suggested_default": ["sales-lead"], "source": "model" | "local", "catalog_version": "ee9999fd8f2a"}
```

- **Input** is checked strictly: `department` is one in the catalog, `briefing` and `about.what` are strings of at most 500 characters,
  `sells_to` is `businesses`, `consumers`, `both` or empty, `software` is a boolean, `install_id` (optional) is a v4 UUID, and no other
  field is allowed. Anything else is `422 {"error": "invalid"}`, with nothing echoed back. A body over 4 KB is refused.
- **Answer.** Template ids from that department only, the head first, at most 8, each with a why of at most 140 characters, plain
  text on one line. The why is shown to a person; no bot follows it.
- **Model.** OpenAI GPT-6 Luna (`OPENAI_API_KEY`; `HQ_RECRUIT_MODEL` overrides the model) through the Responses API with a JSON schema
  whose template ids are an enum, `store: false`, a 4.5 second timeout and a short prompt holding only the department, its templates
  (id, name, summary, tags), the answer and the three facts. Every id is checked again against the catalog.
- **Spend cap.** At most `HQ_RECRUIT_DAILY_CAP` model calls a UTC day (default 2000), counted in memory. Past it, with no key, or on any
  model failure, HQ ranks locally (`source: "local"`) with the same recommender every install has.
- **Cache.** A model answer is kept in memory for an hour under a SHA-256 of the question and the catalog version; a repeat costs nothing.
- **Rate limits.** In memory, as salted hashes: 30 requests an hour per address and 100 a day per install id. Over either is `429`.
- **Logs.** Nothing logs a request or its body. A failed model call is logged as its exception type only.

### The catalog HQ reads

HQ has no templates of its own. `scripts/build_catalog_json.py` builds `hq/catalog.json` (the departments and each card's template,
name, department, icon, tags, suggest level, one-sentence summary and head flag, with no instructions) and copies the recommender
`backend/recruit_rank.py` to `hq/recruit_rank.py`. The Tico server builds its own catalog with the same function, so the two agree on
`catalog_version`. Run the script after changing a card or `templates/departments.yaml`; `--check` (run by the test suite) fails when
either copy is stale.

### Running it

`hq/recruit.py` adds the route to HQ's app with `recruit.install(app)`. Environment: `OPENAI_API_KEY` (without it every answer is local),
`HQ_RECRUIT_DAILY_CAP`, `HQ_RECRUIT_MODEL`. The tests are `hq/tests/test_recruit.py`, with the model mocked.
