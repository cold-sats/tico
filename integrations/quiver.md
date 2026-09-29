---
service: quiver
title: QuiverAI
kind: api
summary: SVG generation for the Design bot; Arrow 2 via a metered Production key.
access: "The QuiverAI API with QUIVERAI_API_KEY from Settings → Credentials, granted to Design"
credentials:
  - QUIVERAI_API_KEY — hub Credentials (Settings → Credentials), env QUIVERAI_API_KEY, granted to bot:designer
declared_as: |
  - service: quiver
    can: [use]
    env: QUIVERAI_API_KEY
    note: SVG generation (Arrow 2)
writes: never
owner: owner
aliases: [quiverai, arrow]
---

## What it is

QuiverAI's Arrow models generate, vectorize, edit, and animate SVGs. Design uses **Arrow 2**
(`arrow-2`) for text-to-SVG. A metered Production key; not a system of record. Arrow 2 Telos
(`arrow-2-telos`) is the higher-fidelity variant; do not switch to it unless the owner asks.

## What data it has

Prompts, optional reference images, and the SVGs generated under the company's API project. Nothing
else of the company's.

## How a bot uses it

The Design bot declares `service: quiver` with `can: [use]` and runs
`python3 software/generate_svg.py` from its checkout. The runner injects
`QUIVERAI_API_KEY` for that turn from a hub Credentials grant. No other bot carries the key.

```bash
python3 software/generate_svg.py --prompt "…" --out reports/<task>/icon.svg
```

The script calls `POST https://api.quiver.ai/v1/svgs/generations` with `model: "arrow-2"` and
writes the returned SVG. Read `playbooks/svg-generation.md` before a generation. If the key is
missing, stop: the owner adds it in Settings → Credentials and grants it to Design.

## Rules

- SVG generation only. Slideshows, HTML ads, and page layouts stay on Claude Design.
- Public placement is publish-gated: the read-only period and `outbound_send: false` hold, and
  publishing needs a `publish` approval (`policies/approvals.md`).
- Buying credits or changing the plan is spend and needs a `spend` approval.
- Never print the key. Never put it in a prompt, a task, or a commit.
- Use `arrow-2`. Do not send Test keys (`sk_test_`) on real work; they hit the sandbox.

## Recipes

- One prompt, one SVG, then inspect the file before generating variants. Include subject, style,
  the company palette (teal #007E80 / #00A8AA, graphite #0F1214, page #FAFBFC), and composition in the
  prompt; put extra style rules in `--instructions`.
- Keep the SVG in the bot's working prefix in the bucket and link it from the task for review.

## Gotchas

- Arrow 2 bills by token usage, not a fixed price per SVG. Extra `--n` variants and long
  instructions cost more; generate once after the brief is locked.
- A catalog listing for `arrow-2` does not mean this key may call it. A 403 means the key
  lacks **Generate SVGs** (or the model) on the API Platform project.
- Native SVG streams emit drafts; only the final `content` (or a non-streaming `data[].svg`)
  is a finished file. Do not save a draft as the deliverable.

## Learnings

What bots and people learn about this integration is added with `hub learn quiver "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
