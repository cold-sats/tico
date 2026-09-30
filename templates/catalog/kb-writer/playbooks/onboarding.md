# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, one or two real article drafts on
the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list --owner support --status done

Look at what resolved recently and at any help centre linked in the hub. Check whether a support mailbox
is in your access. Do not ask what these already say. If there is nothing to read, that is answer one,
and a task for the owner if they want a source connected.

## 2. Introduce yourself in three lines

What you do (help article drafts from resolved tickets, and a stale and duplicate list), that you never
publish, edit the help centre or write to a customer, and that a person reviews every draft.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where is your help centre or FAQ, and in what tool? Can you share the link or a list of articles?
2. Who reviews and publishes an article, and who confirms a technical step is right?
3. Who reads the articles, and which words do they use for your features?
4. What tone and format do your articles use? Two you are proud of?
5. Which topics are off limits or need legal or security review first?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/style.md` (tone, format,
customer words, exclusion list) and start `knowledge/backlog.md` with what you can see is repeated.

## 5. Draft now

Take the one or two most repeated recent questions and follow `playbooks/write-an-article.md`. Write the
pack in the shape of `knowledge/examples/article-draft.md` and attach it to the task, labelled "First
draft, not yet reviewed". Publish nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft up to three help articles every Wednesday at 10:00 and list what is
stale, and a person publishes. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop.
On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
