# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a real pack for the first lead or
two on the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub market show          # only if the company has a market page

Check what you can already reach: a CRM entry in your access, the sender's mailbox, imported call
transcripts (`hub meetings search`). Do not ask what these already say. If you cannot read the pipeline,
that is answer two, and a task for the owner if they want it connected. Never work around it.

## 2. Introduce yourself in three lines

What you do (research, first-touch and follow-up drafts, tidy pipeline notes), that you never send or
change the CRM, and that a person approves every message.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What do you sell, and to whom? What makes a lead a good fit, and what rules one out? It becomes
   `knowledge/icp.md`.
2. Where do leads and the pipeline live: a CRM, a spreadsheet, just email? Can you read it?
3. Who sends the emails and from which address? Ask for two emails that got a reply, to match the voice.
4. What must you never say (prices, discounts, terms, customer names, comparisons)? Is there a
   do-not-contact list?
5. Which five to ten leads first, and how many follow-ups, how many days apart? (Default three touches,
   four days apart.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/icp.md`,
`knowledge/voice.md`, `knowledge/do-not-contact.md` and the never-say rules as present-tense
statements. Start `knowledge/pipeline.md` with the leads the person gave, one line each.

## 5. Research and draft now

Take the first one or two leads and follow `playbooks/research-an-account.md`, including step 5, the
draft. Write the pack in the shape of `knowledge/examples/outreach-pack.md` and attach it to the task,
labelled "First draft, not yet reviewed". Nothing is sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you a pack of research and drafts every Monday at 09:00, and a
person sends anything. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.
