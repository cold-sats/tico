# Usage

Account menu > **Usage** shows what the bots' model runs cost, as an estimate: the tokens each run used, priced at the provider's public
list price. It is not an invoice.

## Where the numbers come from

The runner adds up the `tokens` events a run's runtime reports (`runner/usage.py`) and sends them with the run's result as
`usage`: uncached input, cached input and output tokens, the model that ran, and how the run was billed. The server keeps them on the run
(`turns.input_tokens`, `cached_tokens`, `output_tokens`, `model`, `provider`, `est_cost_usd`, `billing`; migration 12) and prices them
from `providers.PRICES`, in USD per million tokens, dated by `providers.PRICES_AS_OF`. A cache write counts as input; batch, priority and
regional premiums are not modelled. A model with no price keeps its tokens and shows a dash for the cost. A runtime that reports no
tokens (Grok today) shows runs and no tokens.

A run on a ChatGPT or Claude sign-in (Codex "Signed in with ChatGPT", Claude with `claude.ai` or a long-lived OAuth token, a Cursor
account) is `billing: subscription`. It costs nothing extra, so its figure is shown as "API-equivalent" and kept out of the estimate of what
was spent.

## Who sees it

The owner and the bot administrators see every bot. Anyone else sees the bots they run or own. A bot's own credentials cannot read it.

## API

`GET /api/v2/usage?from=&to=&department=&group=bot|day|routine` (UTC dates, default the last 7 days, at most 366) returns `rows` and
`totals` with `runs`, `input_tokens`, `cached_tokens`, `output_tokens`, `est_cost_usd` (null when every API-billed run used an unpriced
model), `subscription_equiv_usd`, and on each row its `share` of the total. `?bot=<slug>` returns that bot's `daily` series and top
`routines`. See `docs/openapi/v2.json`.
