# The Assistant

Every person has one private chat with the company's assistant (the `coo` bot; you may have renamed it): a personal
operator that knows how Tico is laid out and does things in it on your behalf. It is the **Assistant** tab, first on
your own page (`#/person/<you>`), and **Ask the Assistant…** at the bottom of search (⌘K), which opens the same chat with
your words in the box. It works on a phone too.

Ask it to find a meeting, a doc, a file or a task; to tell you what is waiting on you; to make a task; to hand work to the
right bot; to ask BotOps for a new bot; or how something works. It answers briefly and links what it names (tasks,
meetings, docs, files, bots, people), and the links open inside the app.

## Private to you

The chat is a personal room (`scope: personal`, `room_key: assistant`) owned by you. Only you can read it or post in it.
The company owner and administrators cannot read anyone else's, and no other route reaches the assistant: the ordinary
chat routes still refuse it (`403`). If the company has no assistant (archived at setup, as v0.2.1 allows, or never picked), the tab says the Assistant is
off instead of failing, and the owner gets **Turn on Assistant** there and at the top of **Settings > Bots**. One click
restores the archived assistant (same bot, same history, renamed to the company's assistant name) or, if there is none,
adds it from the catalog; then it puts it on the computer BotOps runs on and activates it, and every person's Assistant
tab starts working (`POST /api/v2/assistant/turn-on`). With no computer enrolled yet it is left planned and the button
says so; enroll one and press it again. Anyone else is told to ask the owner.

## Two speeds

Bot turns take 30 seconds or more, so lookups never wait for one. The server answers these itself, from Tico's own data
and as you (what you may see, nothing more), with no runner turn and no model:

| You ask | It answers from |
|---|---|
| What is waiting on me | Needs you |
| Search / find / look up *x* (add *tasks, docs, meetings, files, people, bots* to narrow) | tasks, docs, meetings, bots' files, people, bots |
| Open / go to / where is *x* | the same search, with the best link first (or a page: Settings, Tasks…) |
| What did *bot* do today | the bot's updates and the tasks it touched in the last 24 hours |
| Help: how do I … | `docs/*.md`: a short excerpt and a link |

The intent router is keywords and sentence shape first. When the company has a [decisions](../questions/README.md)
provider, an unclear short message is classified by a `choice` question (`assistant-intent@1`); otherwise it goes to the
model; the text of such a message is sent to the company's configured decisions provider to be classified. Anything that asks for something to be done always goes to the model. Everything else is a turn of the
assistant bot on the company runner, shown as "thinking" until it answers.

## It acts as you, never more

During your chat turn the assistant's `hub` tools and the hub MCP tools are **your own**: the server maps the turn's
credential to you (`Auth.assistant_principal`), so every check is the one that applies to you. It cannot see another
person's private meeting, change settings you cannot, or read a private bot's work you may not see. Only a turn you
started in your own Assistant chat acts for you; its other work (Slack routing, meeting deliveries, routines) stays the
assistant's own. Every write it makes is recorded as yours **via assistant**: the audit `events` carry `"via":
"assistant"`, task history rows and comments carry `via`, and the UI shows "<name> (via Assistant)".

**Direct writes only ever touch you:** creating a task for yourself, updating your own task (not finishing, declining or
closing it, and not handing it to someone else), commenting on a task you can see, marking updates read, a quiet note.
Everything else the server refuses (`403 confirm_required`) and the assistant must propose, including a task for a bot or
another person (how it routes work and asks BotOps for a bot), messaging or chatting any bot, and running a task now.

**Every proposal is shown for what it is.** The card carries the server's own one-line description (route kind and target
name, never the bot's words), the request body as a key: value list, and the exact field changes for a task update. Only routes
on an allowlist can be proposed (never tokens, sign-in, runner enrollment, this assistant or anything that returns a secret);
the path must be plain (`/api/v2/...` without `//`, `..`, `%` or `\`), and exactly that path runs. Only the status and an
error's detail are kept of the result, never the answer's body.

**Anything with a side effect that matters is proposed, and only your click runs it:** approving or declining a Needs-you
item, sending anything outside the company, spending, changing people, access or settings, archiving or deleting,
activating a bot. The assistant calls `hub assistant propose` (`hub_assistant_propose`, `POST /api/v2/assistant/actions`)
with the exact API operation. That leaves a **pending action** and a Confirm / Cancel card in your chat. The server
refuses these operations when the assistant tries them itself (`403 confirm_required`). **Confirm** runs the recorded
operation through the same routes with *your* credential, once (a claim makes a second click a `409`), and
records `assistant.action.confirmed` and the operation's own events via assistant. The bot cannot confirm or cancel
(`403`; a confirm run carries a secret made at click time, bound to the stored method and path, valid for two minutes and then failed), a personal API token cannot either, another person sees `404`, and an unconfirmed proposal expires after
24 hours.

## API

Stable v2 (`docs/openapi/v2.json`, tag **Assistant**). All signed-in people; the confirm and cancel routes need your
own session, not a personal token.

| Request | Answer |
|---|---|
| `GET /api/v2/assistant` | `{"available", "state", "bot", "name", "can_turn_on", "room_id", "messages": [...], "has_more", "next_before", "execution", "actions": {id: action}, "pending": [...]}`. Creates your room the first time. `execution` is the assistant's current run (null when idle): show a thinking state while it is set and poll again. A message whose `refs.action` names an id in `actions` is a Confirm / Cancel card; `refs.fast` marks a server answer; `refs.links` lists what it linked. |
| `POST /api/v2/assistant/messages` `{"text"}` | `{"message", "reply", "fast", "intent"}`. `fast: true` carries the answer as `reply`; otherwise the bot is working. `409 assistant_off` when it is off. |
| `POST /api/v2/assistant/turn-on` | Owner only. `{"bot", "state", "restored", "placed"}`. |
| `POST /api/v2/assistant/actions` `{"summary", "method", "path", "body"}` | A proposal `{"action": {...}}` (what the assistant's tool calls). |
| `GET /api/v2/assistant/actions/{id}` | `{"action": {"status": "pending"\|"running"\|"done"\|"failed"\|"cancelled"\|"expired", "result": {...}}}` |
| `POST /api/v2/assistant/actions/{id}/confirm` | Runs it as you. `{"action": {...}}` with the result of the operation. |
| `POST /api/v2/assistant/actions/{id}/cancel` | Drops it. |

Names come with ids (`from_name`, `owner_name`, and an `actors` map), as elsewhere in v2. A custom frontend (see
[custom-frontend.md](custom-frontend.md)) can embed the Assistant with these routes alone.

## For the assistant bot

Its instructions are `templates/catalog/assistant/AGENT.md` and `playbooks/assistant-chat.md`: how Tico is organised,
how to route work to the right bot, to answer briefly with links, never to act beyond you, and to propose (never do)
anything with a side effect. They live in the bot's repository; edit them there or through BotOps.
