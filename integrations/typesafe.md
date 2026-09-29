---
service: typesafe
title: "Decisions: TypeSafe Jev (optional)"
kind: api
summary: Jev, TypeSafe's System One model, is the optional provider behind decision questions. It reads a JSON state against typed questions (yes/no, choice, score; the same format as OpenRouter's Decisions API) and answers with calibrated probabilities; a decision tool every bot has through the hub, never a writer.
access: "`hub_decisions` (MCP) or `hub decisions` (CLI) inside any turn; the hub holds the key and calls https://api.typesafe.ai/v1/systemone"
credentials:
  - TYPESAFE_API_KEY — on the server only, from TICO_TYPESAFE_SECRET_ARN; the same key the Slack gateway routes with. No bot carries it.
declared_as: |
  # Nothing: `hub_decisions` is a hub tool, like `hub_sql`. Only a bot that must call TypeSafe
  # from its own software (thousands of calls a run) declares a key of its own:
  - service: typesafe
    can: [use]
    env: TYPESAFE_API_KEY
    note: "direct calls from software/; the owner grants the key"
writes: never
owner: owner
aliases: [jev, system-one, decisions, judge]
---

## What it is

A model that does not generate. One call takes any JSON `state` and a map of typed questions
and returns, in about two hundred milliseconds, a calibrated answer per question: a `choice`
over named options with a probability distribution and a confidence, a `score` on ordered
levels, or a `noul`, the probability that a statement is true. Every question in the call is
evaluated against the same state, in parallel and in isolation. It writes no prose, so it
cannot invent a fact, a quote or a number; what it can do is decide, and say how sure it is.

That is what it is good for: classify, route, dedupe, gate, rank, flag. It is not a harness
and not a writer. When the output has to be text or a plan, the bot's own model does that,
and Jev decides which of the results to keep.

## What data it has

None of the company's. It is a model endpoint; what a caller sends is what it sees, for that
call. The hub's audit keeps the label, the questions' ids, the value and confidence per answer,
the token usage and the latency of every call, and never the state.

## How a bot uses it

Read `skills/decisions/SKILL.md` first. Then, inside a turn:

- **MCP**: `hub_decisions` with `state`, `questions` and a `label`.
- **CLI**: `hub decisions --set mail-triage --state-file message.json`, or
  `--questions-file q.json` for questions of your own. `hub decisions --list` shows the sets.
- **Mail**: `mail inbox --untriaged --format brief --decisions` puts a `decision:` line with a suggestion
  under every message before any thread is opened; `mail draft` records Jev's gate beside the
  reviewer's verdict.

The shared question sets are `questions/*.json` in the hub checkout (`questions/README.md`):
a versioned file with the questions, the state fields they expect and the thresholds to act at.
Send a set's `questions` and its `id@version` as the label. A question of your own is fine for a
one-off decision; a decision several bots make the same way becomes a set, by pull request.

## Rules

- Judge, never generate. If the answer you need is text, this is the wrong tool.
- Send data as named fields, not a paragraph of instructions; the questions carry the
  instructions. The model never sees a question's id, only its options and their descriptions.
- Act on the best option when you only need the best option; threshold only when doing nothing
  is a real outcome, and make the threshold asymmetric where the costs are. Under a set's
  threshold, do what you did before: read it yourself, or leave it for a person.
- Never coerce: an answer under threshold is not a weak yes.
- Label every call. Unlabelled calls cannot be read back or calibrated.
- The key is the hub's. Do not ask for it, copy it, or call the API from a turn.
- Metered: $0.042 per million input tokens, output free. A day's budget per actor is enforced
  by the hub (`GET /api/v2/judge` says how much is left); a loop that spends it is a bug.
- Ask everything in one call. Questions are answered in parallel against one state, so the
  whole decision tree, speculative branches included, goes in one request and code reads the
  answers it needs. A second call is for when the first answer changes what to fetch or ask.
- Keep the arithmetic, counting, date comparison and lookups in code; Jev reads numbers and
  dates as text (`skills/decisions/SKILL.md`, "What the decision model is bad at").

## Recipes

- Sort a listing before opening anything: one call per row, eight in flight, then open only
  the rows the answers say to.
- Dedupe against what exists: the `covered` set, the existing items as options plus `new`;
  merge above `same`, flag between `review` and `same`, treat as new below.
- Gate a draft: the `mail-draft-gate` set, six nouls; rewrite once when any is flagged, then
  let the reviewer decide.
- Read a month back: `hub sql "SELECT ts, actor, target, detail_json FROM events WHERE
  action='judge.call' AND target='mail-triage@1' ORDER BY ts DESC LIMIT 200"`.

## Gotchas

- A `noul` has no separate confidence: 0.5 is a coin toss; distance from 0.5 is how sure.
- A `score` is probability-weighted and fractional (`1.3` between level 1 and level 2), not a
  category. Round only when you mean to.
- A choice with no escape option forces a pick. Give a list `other`, `none` or `new`.
- 422 means the request shape, not the content: an unknown key on a question, a criteria map
  with one option, levels outside two to ten. `clients/judge.py` refuses these before sending.
- Rate limits move with demand (1,200 requests a minute today); 429 and 529 are retried twice
  with backoff by the client, then `judge_unavailable`.
- Context: 64k tokens a call, and 32k for the state plus the longest question. The client
  refuses a state over about 120k characters; keep it far under that, because accuracy falls
  with unrelated material well before the limit.
- `instructions`, an option's description, a level and a noul's `true`/`false` each take a
  string or JSON structure (an object of named parts, a list); `null` is an option with no
  description. The client accepts all of these.
- `jev-latest` moves when TypeSafe ships a release; the answer's `model` field reports the
  versioned id (`jev-1.13.0` today) and the audit keeps it. A threshold tuned on one version
  is worth re-checking on the next; pinning the version in `clients/judge.py` is a hub change.
- The state is not treated as hostile: text written to argue for its own classification can
  move the answer. Tight criteria and low thresholds on the protections, never trust.
- English is the primary language; others answer with lower accuracy.
- The live docs are the source of truth for the request shape, limits, models and cookbooks:
  `https://docs.typesafe.ai/llms.txt` is the index, and every page reads as Markdown with
  `.md` appended (`.../api.md`, `.../primitives/advanced.md`, `.../model-jaggedness/jev-1.13.md`).
  This page and the skill are how the company uses it.

## Learnings

What bots and people learn about this integration is added with `hub learn typesafe "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
