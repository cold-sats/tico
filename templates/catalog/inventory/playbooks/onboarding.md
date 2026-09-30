# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 30 minutes. The outcome is five recorded answers, an item plan computed from real
exports, a first reorder list, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "supplier"
    hub docs search "price list"

If exports are already attached, read them first: the item count, the date range and which columns
exist (SKU, name, units sold per day or per order, stock on hand, cost) tell you what to ask.

## 2. Introduce yourself in three lines

What you do (reorder points per item, a weekly reorder list, purchase orders ready for approval), that
you never place an order or change the shop's records, and that every number shows its inputs.

## 3. Ask, in one message

Numbered, each with its one-line why and a default.

1. Where do stock and sales live, and can you export 90 days of sales and today's stock per item? Every number starts there.
2. Your main suppliers: lead time, minimum order, how you order? Lead time sets the reorder point.
3. How much buffer, and how many months of cover is too much? (Default: worst lead time seen; over 4 months is overstock.)
4. Who approves purchase orders, up to what? (Default: the Operations Manager.)
5. When should the list land; any seasonal or discontinued items? (Default: Mondays 07:30.)

## 4. Record

Answers to `state.md` under `## Answers`, dated. Compute `knowledge/items.md` from the exports as in
`AGENT.md`, "How you compute". An item with under 30 days of sales history is marked "too new to
plan" and left for a human.

## 5. Produce the first result now

Follow `playbooks/weekly-reorder-list.md`. Attach it labelled "First draft, not yet reviewed".
Purchase orders are on the page, not sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will build this list every Monday at 07:30 from that week's exports. Say
yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
