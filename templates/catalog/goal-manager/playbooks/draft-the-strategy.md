# Draft the strategy

A task titled "Draft the strategy" (a number after it means the owner asked again), or the owner asking you for the
strategy in their chat. The owner wants the Strategy page to say how the team means to win, in words they
recognise, so that every bot reads the same summary on every run and the goals have choices to hang from. You
write the draft; they publish it. A strategy with no trade-offs is a description, so "What we won't do" is part
of every draft.

The outcome is a draft the owner can publish after twenty minutes of their time: a summary of at most 400
characters, the vision, every section of the framework filled or marked unknown, and three to seven choices, each
with its why and what it rules out. Nothing else counts as good.

**Budget.** About 30 minutes of your time and at most eight questions to the owner over the whole interview. The
first draft is on the page within five minutes; after that you rewrite as you learn, never from scratch. When the
budget runs out, write what you have, mark what is missing, and hand it to the owner.

**Never invent a number.** A market size, a price, a share, a head count or a growth rate appears in a section only
when a market page or a source you read this run states it, cited the way the Librarian cites it. Otherwise the
section says "unknown" and the gap is a question for the owner or an Open question for the Librarian. No round
figures, no "typically", no "roughly" from your own memory.

**Your level decides how you write** (`level` in `hub goal ceo-bot`, read at the start). At **Acts on its own**
(level 3) you write the draft with `hub strategy draft` and the choices with `hub strategy choice`. Below it you
build the same draft in a file and file it as one `strategy_draft` proposal (step 6); you write nothing to the page.
At every level, publishing is the owner's click: `hub strategy publish` refuses you, and asking another way is not a
workaround.

---

## 1. Read what the team already knows

Start from the record, not from memory.

- `hub strategy show`: the current version, if there is one, and the draft. A draft the owner has already touched is
  theirs: keep their words and add to them. If a version is published, this run is a revision: read
  `hub strategy versions` and say in the draft note what changed and why.
- `hub strategy frameworks`: the lenses, each with its sections and interview questions. Use the framework the owner
  named in the task or the chat; otherwise the one the draft already has; otherwise **plain**. Do not ask which
  framework they want: offer to switch at the end if the words did not fit.
- The market: `hub market show company/self` (who the team is, from the Librarian's research), then
  `hub doc search --market "<the team's name>"`, the Overview and Theses pages, and Open questions. The market
  pages are the evidence the sections cite. If the market is empty, say so in the draft note: the Librarian's "Set
  up the market map" task fills it, and you do not do its research.
- `knowledge/company.md` and the setup answers in the task: what the team does, for whom, and the words it uses.
- The goals: `hub goal list --all`. A live goal often shows a choice the team already made without writing it down.

## 2. Commit to positions

Write the draft as if you were right, not as a menu. "We sell to small property managers who have outgrown
spreadsheets" is a position; "the team could target small or mid-size property managers" is a list. Where the
evidence supports two readings, pick the one the team's own behaviour shows (its pricing page, its customers, its
goals) and say in the section which fact made you pick it. The owner corrects a position in one sentence; they
cannot correct a list.

A summary is one paragraph, at most 400 characters: who the team serves, what it sells, how it wins. The vision is
one or two sentences, at most 400 characters, in the owner's words where you have them.

## 3. Write the first draft early

Within five minutes of starting. At level 3:

    hub strategy draft --summary "<paragraph>" --vision "<sentence>"
    hub strategy draft --section serve="<markdown>" --section sell="<markdown>"     # one call per section is fine

Section keys come from the framework (`hub strategy frameworks`); the server refuses a key the framework does not
have. A section you cannot fill yet says, in one line, what you would need to know. Rewrite the whole section when
you learn more; the page shows the owner the draft as you write, so keep it readable at every step.

Below level 3, write the same fields into `reports/<date>-strategy-draft.md` under one heading per field, and keep
rewriting that file instead.

## 4. Surface the choices

The choices are the spine of the page: three to seven bets the team already lives by, most of them unwritten. Find
them in what the team does, not in what it says: a pricing page that undercuts every competitor is a bet on price;
a market page that shows one segment and five lookalikes is a bet on a niche; a goal to automate a workflow is a bet
on cost. Each choice is three fields:

- **statement**: one sentence, a decision that could turn out wrong ("Price weekly cleaning low enough that volume is
  the moat, and let bots do the booking").
- **why**: the evidence or belief behind it, with the market page or source it rests on when there is one.
- **rules_out**: what the team gives up by choosing it ("no enterprise contracts, no custom work"). A choice that rules
  out nothing is not a choice: rewrite it or drop it.

At level 3, `hub strategy choice add --statement "..." --why "..." --rules-out "..."` for each (status `proposed`
until the owner activates it on publish); `hub strategy choice update <id>` to reword and `hub strategy choice retire
<id>` for one the owner drops. Below level 3, they go in the draft file under `## Choices`, one block each.

The framework's own word for them (Bets, Guiding policy, Choices, Strategies, Methods, Positions) is what the
owner sees; use it in your questions.

**What we won't do** is required. Every framework has it as the `not` section, shown last, so write it the same way
whatever the framework: `hub strategy draft --section not="<markdown>"`. Fill it from the choices' `rules_out` lines
and from what the owner says no to; never leave it empty or soft.

## 5. Interview the owner, one question at a time

The framework's interview questions are a list to pick from, not a form. Before you ask one, check whether the draft
already answers it from the evidence; ask only the ones it cannot, and ask the one that would change the draft most
first. Put your current reading in the question so a "yes" is a full answer: "You look like a niche play against
bigger generalists: small property managers, priced under the enterprise tools. Is that right, and who do you lose
deals to?"

- In the owner's chat: ask in your reply and end the turn. Their answer is the next turn; rewrite the draft from it
  before you ask again.
- From a task: `hub task update <id> --status waiting --on <owner> --note "<the one question>"`. That is one card
  with your question; you are woken with their answer. One question at a time, never a list, and each one counts
  toward the owner's 5 a day (`asked_today` in `hub goal ceo-bot`).

Record each answer in the draft in their words, then ask the next. Stop asking when every section has a position and
the choices have a why and a rules-out each, or at eight questions, whichever comes first. Do not argue with an
answer: a position you think wrong goes in the draft as theirs, with the evidence that worried you beside it, in one
line.

## 6. Hand it to the owner

At level 3 the draft is on the page. End with one message to the owner, in chat or as the task note: the summary,
the choices in one line each, what is still unknown, and the ask: "Publish it from the Strategy page when it reads
right; I never publish." Offer, in one line, to switch frameworks if the sections fought the team's own words.

Below level 3, file the draft as one proposal the owner confirms, and nothing else:

    hub proposal create --kind strategy_draft --payload-file draft.json --reason "<one sentence: what this draft rests on>"

The payload is `{"framework": "plain", "summary": "...", "vision": "...", "sections": {"serve": "...", ...},
"choices": [{"statement": "...", "why": "...", "rules_out": "..."}]}`. Confirming writes the draft and the choices
as the owner; they still publish separately. Look at `hub proposal list` first: one pending `strategy_draft` at a
time, never a second beside it.

Then rewrite `state.md` (what the draft rests on, which questions were asked and answered, what the owner has not
answered yet), record a durable lesson about this team's words or sources in `knowledge/`, and commit this
repository. From a task, finish it with `hub task update <id> --status done --note "<the message above>"`.

## After the owner publishes

Every active bot gets a quiet note and the new summary in its next run's context; you do not tell them yourself.
Your next job is the goals: for each active choice with no goal (`goals_by_choice` in `hub strategy show`), suggest
one or two goals that serve it, each with `choice_id` set, as proposals or cards the owner accepts
(`playbooks/goals-make-sense.md`). Never create a team goal yourself.
