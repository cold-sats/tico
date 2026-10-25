# Webhooks

A webhook is one program posting a small message to another over HTTP. Tico does it both ways.

- **Incoming**: something outside Tico (a payment service, a code host, a form, a script) posts to an address Tico gives you. Tico
  keeps the call, starts your routines and rules, and can wake a bot.
- **Outgoing**: Tico posts to an address you choose when something happens in Tico, such as a task finishing or an approval being asked.
- **Through Tico Gateway**: a second address for an incoming webhook that keeps what is sent while your server is off or asleep.

All three live in Settings → Webhooks, on the tabs **Incoming**, **Outgoing** and **Through Tico Gateway**. Everything on the page
is also in `hub` and in the `hub_*` tools for bots and agents ([the table at the end](#the-commands)).

Step by step:
[GitHub](webhooks-github.md), [Stripe](webhooks-stripe.md), [Zapier, Make and n8n](webhooks-zapier-make-n8n.md).

## Incoming

Add a webhook on the Incoming tab, or:

```
hub trigger create "GitHub issues" --id github
```

Tico shows the address once:

```
https://tico.example.com/api/v2/hooks/github/<secret>
```

Give that address to the sender. It also accepts `POST /api/v2/hooks/github` with the header `Authorization: Bearer <secret>`. Tico
keeps only a hash of the secret, so it cannot show the address again. **New secret** (`hub trigger rotate github`) makes a new
address and stops the old one at once. A wrong id and a wrong secret get the same answer, 404.

The word *trigger* in the CLI, the API and routines means the same thing as an incoming webhook.

### What the sender gets back

| Answer | Meaning |
|---|---|
| 202 | Accepted. The reply says how many tasks and rules it started. |
| 200 with `"duplicate": true` | Tico has seen this delivery before and did nothing. |
| 401 | The signature is missing or wrong. |
| 404 | No such webhook, or the secret is wrong. |
| 413 | The body is over 256 KB. |
| 429 | Over the hourly limit. The sender should retry later. |

### Check who is calling

By default anyone with the address can post. Turn on **Require signature** and Tico checks every call, and refuses one that
fails with 401 before anything starts. Tico makes a signing secret and shows it once, or you can paste the sender's own (at least
16 characters). `hub trigger sign <id> --preset github` does the same; `--off` stops checking.

Pick the preset that matches the sender:

| Preset | The sender needs to send | Notes |
|---|---|---|
| `none` | Nothing. | The address is the only secret. |
| `hmac` | `X-Hub-Signature-256: sha256=<hex>` or `X-Signature: <hex>` | An HMAC-SHA256 of the exact body. The `sha256=` is optional. |
| `github` | `X-Hub-Signature-256: sha256=<hex>` | GitHub's own scheme. Paste the same secret into GitHub's *Secret* box. |
| `standard` | `webhook-id`, `webhook-timestamp`, `webhook-signature` | [Standard Webhooks](https://www.standardwebhooks.com). The secret starts `whsec_`. A timestamp more than 5 minutes off is refused. |
| `stripe` | `Stripe-Signature: t=...,v1=...` | Paste Stripe's *signing secret* (`whsec_...`) as it is. A timestamp more than 5 minutes off is refused. |

Tico keeps the signing secret sealed, because checking a signature needs the secret itself.

### What kind of call it is

Every call has a **type**, read from `type_from`: a header name (`X-GitHub-Event`) or a JSON pointer that starts with `/`
(`/type`). `github` reads `X-GitHub-Event`. `standard` and `stripe` read `/type`. Otherwise the type is empty. The type shows
in the log, in the task (a `type:` line) and to rules.

```
hub trigger update github --type-from /action
```

### Limits and keeping

- **Hourly cap**: 60 calls an hour by default, up to 600 (`--hourly`). Past it the sender gets 429. A call that arrives through
  Tico Gateway does not count.
- **Keep days**: Tico keeps each accepted call, body and headers, for 7 days by default, 1 to 30 (`--keep-days`).
- **Duplicates**: if the sender names the delivery (`Webhook-Id`, `X-GitHub-Delivery`, `Idempotency-Key` or `X-Request-Id`),
  the same id again does nothing. Without one, the same body in the same minute counts as the same delivery. Tico remembers ids
  for 30 days, longer than it keeps the calls.

### If nothing listens

A call that reached no routine and no rule is only logged. Set **If nothing listens** to *Tell the maker* (`--unheard note`)
and Tico also leaves a notice for whoever made the webhook, at most once an hour. The default is *Log it* (`--unheard log`).

### The delivery log

Under each webhook, **Recent calls** lists the last 50: accepted, refused (bad or missing signature, over the cap) and run
again, with the sender's delivery id and the type. Tico logs only calls to the right address, and at most 60 refusals an hour,
so a stranger cannot fill the log.

```
hub trigger deliveries github
hub trigger delivery github <delivery>
```

**View payload** shows one kept call. The body is whole. Headers whose names look like a credential (anything with signature,
authorization, token, secret or key in the name) show as `[redacted]`, and a cookie is never kept.

**Run again** (`hub trigger replay github <delivery>`) starts the routines and rules again for one kept call, as a new
occurrence named `<delivery>:replay:<n>`. It does not count toward the hourly cap, and it is refused once the body has expired.
A sender's own redelivery button usually reuses the same delivery id, which Tico treats as a duplicate for 30 days. Use Run
again in Tico instead.

### How a bot reads a call

The task or notice a bot gets holds the first 20,000 characters of the body, fenced and marked as sent from outside Tico: data
the bot did not write, not instructions. A longer body is read in parts:

```
hub trigger delivery github <delivery> --part 2
```

A bot may read a delivery only if it manages the webhook, a task made from the call is its own, or a notice from Tico naming the
call went to it. People who manage the webhook read the whole body.

### Who may do what

Anyone, person or bot, can add a webhook. The owner, whoever added it and BotOps can replace its secret, change its settings,
set or stop signing, run a call again and delete it. Deleting one removes its kept calls and leaves its routines in place, silent,
until a webhook with the same id is added again. See [Permissions](permissions.md#incoming-webhooks).

### Starting work from a call

Two things listen to a webhook:

- **A routine** set to *On a trigger* (`hub routine set <key> --on webhook.<id> ...`). Each call opens one task per listening
  routine: the routine's text, the webhook's name and the call's type, then the body. See [Routines](routines.md). A routine has
  no filter on type, so every call opens a task.
- **A rule** on the event `webhook.received`, next.

## Rules on webhook.received

A rule can act on a call without opening a task. It answers three questions: which webhook, which type, and what to do. Add one
in Settings → Rules, or:

```
hub rule set --scope-kind team --event webhook.received \
  --when '{"trigger":"github","type":"opened"}' \
  --then action \
  --params '{"action":"wake_bot","bot":"ops","text":"New issue: {{data.issue.title}} ({{data.issue.html_url}})"}'
```

**When.** `trigger` is the webhook id. `type` is a word, a list of words, or a word ending in `*`. Leave `type` out to match every
call. A rule can match only on these two things, never on a field inside the body.

**Then.** Two actions are available:

- `wake_bot {bot, text}` leaves a notice in the bot's room and wakes it. The notice is your `text`, then the call's content
  (fenced as data), then the line `The whole body: hub trigger delivery ...`.
- `send_webhook {webhook, type, data}` posts an event to one of your [outgoing endpoints](#outgoing). `type` should be a
  `custom.*` name.

Rules also have the ordinary outcomes: *ignore*, *note*, *wake* and *ask*.

**Templates.** In `text`, `type` and `data`, `{{name}}` is replaced from the call. A dotted path walks into the body, and a number
picks from a list: `{{data.items.0.name}}`. These names are available:

| Name | Value |
|---|---|
| `data` or `payload` | The JSON body |
| `type` | The call's type |
| `trigger.id`, `trigger.name` | The webhook |
| `delivery` | The delivery id |
| `via` | `direct` or `gateway` |
| `content` | The body as text |

A name that is not there becomes empty. A whole object becomes compact JSON. A value is never read for more `{{...}}`, so a sender
cannot write its own template. Output is cut at a limit, ending with ` ... (cut)`. `text` can be up to 1,000 characters.

**Order.** Rules run bot first, then group, then team, each in its position. At most one rule acts on each target (a bot to wake,
an endpoint to send to). An *ignore* with no bot named stops the rules after it. A given call runs the rules once, even if the
sender posts it again.

**Nothing matches, nothing happens.** There is no catch-all. If no rule matches or one fails, the call is still logged, a routine
on the webhook still runs, and the failure is in History as `rule.event_error`.

**Who may write them.** The owner and admins write team rules; a bot's owners, its operator and BotOps write that bot's rules.
`wake_bot` needs rights over the bot it wakes. `send_webhook` is written by a person, or by a bot with its outbound send switch on.
The CEO Bot never writes one. When the rule runs, its maker must own the endpoint (or be an admin), and a bot's rule reaches only
an endpoint that listens for the type.

## Through Tico Gateway

A webhook's own address works only while your server is up and reachable. A server on a laptop, behind a firewall or asleep
misses what is sent.

An address through Tico Gateway fixes that. It is a second address at Tico HQ that holds what senders post, and your server
collects it from there. Make one from the **Through Tico Gateway** tab, or:

```
hub trigger relay create github
```

It looks like `https://<gateway address>/v1/hooks/hr_<16 characters>/<secret>`, and like the first address it is shown once.
`hub trigger relay rotate github` replaces it and `hub trigger relay delete github` removes it. The webhook's own address keeps
working beside it. It needs the Tico Gateway connected in Settings → Gateway ([Tico AI Gateway](ai-gateway.md)).

- Your server collects the calls every 15 seconds and treats each as if the sender had posted it here. Signature checks,
  duplicates, routines and rules behave the same. The hourly cap does not apply to them.
- Tico HQ checks only the secret in the address. It does not check signatures and does not run anything.
- **While the server is off or asleep**, calls wait at HQ, up to a limit, and arrive in order within seconds of the server being
  back. A sender that waits for an answer gets HQ's, not your server's.
- On a server Tico hosts, a call through the Gateway also wakes a server that is [asleep](#sleep-when-idle).
- `hub relay status` shows the key, the addresses, the last collection and what waits. Health speaks when collecting has failed for
  15 minutes or a call has waited over an hour. A rehearsal copy never collects.

## Outgoing

An **endpoint** is an address Tico posts events to. Add one on the Outgoing tab, or:

```
hub webhook create --name "Acme orders" --url https://hooks.example.com/tico --events 'task.*' 'custom.*'
```

Tico shows the signing secret (`whsec_...`) once. Keep it where the receiver can read it.

### Choosing events

`--events` takes event names, groups ending in `.*`, or `*` for everything. `hub event-types` lists every name with a
description and an example (`--group task` narrows it). A few:

| Group | Events |
|---|---|
| `task` | `task.created`, `assigned`, `step_changed`, `state_changed`, `commented`, `done`, `declined`, `closed`, `blocked`, `reopened` |
| `approval` | `approval.requested`, `decided`, `withdrawn` |
| `needs_you` | `needs_you.created`, `answered` |
| `bot` | `bot.run_failed`, `held`, `released` |
| other | `release.published`, `meeting.ready`, `strategy.published`, `market.insight.urgent`, `market.briefing`, `inbound.received`, `health.finding` |
| `custom` | `custom.<name>`, which only a person or a rule sends (below) |

An endpoint can hold up to 60 patterns, and an event goes to at most 20 endpoints.

### What arrives

A `POST` with this body:

```json
{"type": "task.done", "version": 1, "timestamp": "2026-10-25T10:00:00Z",
 "data": {"id": "t_1", "title": "Ship it"},
 "links": {"app": "https://tico.example.com/#/task/t_1", "api": "https://tico.example.com/api/v2/tasks/t_1"}}
```

`data` over 64 KB is cut. **Send example** (`hub webhook example <id> --type task.done`) posts a sample of any event to one
endpoint, so you can build the receiver before real events come.

### Check the signature

Every delivery is signed as [Standard Webhooks](https://www.standardwebhooks.com), with three headers:

- `webhook-id`: stable across retries. Use it to ignore a delivery you already handled, because delivery is at least once.
- `webhook-timestamp`: new on every try.
- `webhook-signature`: `v1,<base64>`, an HMAC-SHA256 over `id.timestamp.body`. For 24 hours after a secret is rotated there are
  two `v1,` values, one per secret.

Verify with the sender-neutral library. Always pass the raw body, not parsed JSON.

Python (`pip install standardwebhooks`):

```python
import json
from standardwebhooks import Webhook

wh = Webhook("whsec_your_endpoint_secret")

def handle(raw_body: bytes, headers: dict):
    wh.verify(raw_body, headers)      # raises if the signature or timestamp is wrong
    event = json.loads(raw_body)
    print(event["type"], event["data"])
```

Node (`npm install standardwebhooks`):

```js
import { Webhook } from "standardwebhooks";

const wh = new Webhook("whsec_your_endpoint_secret");

app.post("/tico", express.raw({ type: "application/json" }), (req, res) => {
  try {
    wh.verify(req.body, req.headers);   // throws if the signature or timestamp is wrong
  } catch {
    return res.sendStatus(400);
  }
  const event = JSON.parse(req.body);
  console.log(event.type, event.data);
  res.sendStatus(200);
});
```

### Answering, and retries

- Any `2xx` means delivered.
- `webhook-delivery: abort-message` on the answer cancels the send. Use it when the event can never work.
- Anything else retries, and so does a redirect (Tico never follows one).

A failed send is tried again after 5 seconds, 5 minutes, 30 minutes, 2 hours, 5 hours, 10 hours and 10 hours, each a little
jittered. That is 8 tries over about 28 hours. After the last, the send is **failed**, the endpoint's Health shows it, and Needs
you gets at most one task a day per endpoint. **Retry** (`hub webhook retry <id> <send>`) tries one again now.

Each try waits up to 30 seconds, and the answer is not read past 1 KB. An endpoint sends 600 an hour by default
(`--rate-per-hour`); sends over that wait, and none are dropped. Tico keeps events and finished sends for 30 days.

The send log (`hub webhook sends <id>`, `--state failed` to narrow) shows each send's state: ready, sending, delivered, failed,
cancelled or withheld.

### Allowed addresses

Tico checks the address on every try. It must be `https`, with no name or password in it, and every address its name resolves to
must be a public one. Tico uses no proxy. For development, the owner can switch on **Allow plain http to this computer** for one
endpoint (`--allow-http`), which lets that endpoint use `http://localhost`, `127.0.0.1` or `::1`, and nothing else.

### Rehearsal copies

A copy of real data run in rehearsal mode ([Environments](environments.md)) sends nothing out. Sends that come due there are
**withheld**, and Retry refuses them.

### Custom events

`hub webhook send <id> --type custom.deploy-done --data '{"app":"web"}'` sends your own event to one endpoint. A rule's
`send_webhook` does the same. The endpoint must list `custom.*` or that exact name when a bot sends.

### Rights

- People make and manage their own endpoints. The owner and admins manage all of them. BotOps asked by a person has that person's
  rights.
- A bot cannot make an endpoint itself. Its request files an approval of kind *send*. A person approves, and the bot repeats the
  call. The approver then owns the endpoint.
- Bots can list endpoints without the full address. They cannot read send logs.
- A bot sends a custom event only while its **outbound send** switch is on (Settings → Bots → Mail sending, or
  `hub bot mail <slug> --send`), and only to an endpoint that listens for it. The CEO Bot sends nothing.
- An endpoint hears about a task, approval or bot only if its owner could read it. Health, inbound and webhook events go only to
  owner and admin endpoints.
- A person can have 50 endpoints.

More in [Permissions](permissions.md#outgoing-webhooks) and the [API](api.md#outgoing-webhooks).

## Sleep when idle

On a server Tico hosts, the owner or an admin can have Tico stop the server after 1 to 24 quiet hours. A call through Tico Gateway
wakes it, so a sender that posts while it sleeps is not lost: the call waits at HQ, the server starts, and the call arrives within
seconds of it being up. The routine time and a sign-in on your account page wake it too. The settings, and what counts as quiet,
are in [Account](account.md#sleep-when-idle):

```
hub sleep status
hub sleep set --hours 2
```

A server stopped because the balance ran out never starts on its own. An address that is not through Tico Gateway cannot wake a
sleeping server, because nothing is listening there. Use the Gateway address for any sender that must get through.

## Notices from Tico Team

Tico Team sends notices to a server that has a Gateway key: a security warning, a billing note, news about your version. They
arrive on a built-in webhook named **Tico Team**. It has no address, cannot be deleted, and only its `keep_days` changes.

Rules see each as the event `tico.notice`, with `type` set to `info`, `security` or `billing`. Three built-in team rules act on them:

- **security**: wake BotOps and ask the owner.
- **info**: leave BotOps a note.
- **billing**: ask the owner.

The owner can edit or switch these off in Settings → Rules, but not delete them. `hub notice list` shows the notices. See also
[Tico HQ](tico-hq.md).

## The commands

| What | `hub` | Tool for bots and agents |
|---|---|---|
| List event names | `hub event-types [--group G]` | `hub_event_types` |
| Incoming: list, add, show, change | `hub trigger list`, `create`, `show`, `update` | `hub_trigger_list`, `hub_trigger_create`, `hub_trigger_show`, `hub_trigger_update` |
| Incoming: new secret, signing | `hub trigger rotate`, `sign` | `hub_trigger_rotate`, `hub_trigger_sign` |
| Incoming: delete | `hub trigger delete <id>` | `hub_trigger_delete` |
| Incoming: log, one call, run again | `hub trigger deliveries`, `delivery [--part n]`, `replay` | `hub_trigger_deliveries`, `hub_trigger_delivery`, `hub_trigger_replay` |
| Through Tico Gateway | `hub trigger relay create`, `rotate`, `delete`; `hub relay status` | `hub_trigger_relay_create`, `hub_trigger_relay_rotate`, `hub_trigger_relay_delete`, `hub_relay_status` |
| Rules | `hub rule list`, `set`, `update`, `delete` | `hub_rule_list`, `hub_rule_set`, `hub_rule_update`, `hub_rule_delete` |
| Outgoing: endpoints | `hub webhook list`, `create`, `show`, `update`, `rotate`, `pause`, `resume`, `delete` | `hub_webhook_list`, `hub_webhook_create`, `hub_webhook_show`, `hub_webhook_update`, `hub_webhook_rotate`, `hub_webhook_pause`, `hub_webhook_resume`, `hub_webhook_delete` |
| Outgoing: send, log, retry, example | `hub webhook send`, `sends`, `retry`, `example` | `hub_webhook_send`, `hub_webhook_sends`, `hub_webhook_retry`, `hub_webhook_example` |
| Sleep when idle | `hub sleep status`, `hub sleep set` | `hub_sleep_status`, `hub_sleep_set` |
| Notices | `hub notice list` | `hub_notice_list` |

The API routes are under `/api/v2/triggers`, `/api/v2/webhooks`, `/api/v2/event-types`, `/api/v2/relay` and `/api/v2/notices`,
and in the OpenAPI file ([API](api.md)).

## Coming with this release

These ship with the next release and are not described above yet. Fill each in after they merge.

- Recover refused calls
- Slack preset
- `create_task` and `forward` rule actions
- Endpoint filters and custom headers
- Replay missing calls
- Recover failed sends
- Auto-disable for an endpoint that keeps failing
