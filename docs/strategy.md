# Strategy

**Strategy** (`#/strategy`) is where a team writes down how it means to win, keeps that honest against the market
and its own results, and lets the org chart and the goals follow from it. The page is short on purpose: a summary
every bot reads on every run, a few sections, and a short list of **choices**, the bets the team lives by. The
owner and the [CEO Bot](ceo-bot.md) write it together; the owner publishes it; the [Librarian](librarian.md) keeps
the evidence under it current. **Market** is a tab of the section (`#/strategy/market`; `#/market` redirects
there), unchanged in what it does.

Three activities make one loop:

| Activity | Who | What it produces |
|---|---|---|
| Craft the strategy | the owner and the CEO Bot | the Strategy page: summary, sections, choices |
| Craft the market | the Librarian | the market graph and pages under the Market tab |
| Compare | the CEO Bot | fit checks: does the evidence still support the choices? If not, proposals |

Results close the loop: goals link to choices, KPIs colour the goals, so each choice shows whether it is paying off.
In Rumelt's words it is a diagnosis (the market and the results), a guiding policy (the choices) and coherent actions
(the org chart, the goals, the tasks).

This page is the model, the frameworks, who may do what, setup, how a change reaches the bots, and the API.

## The page

- **Summary.** One paragraph, at most 400 characters. This is the text every bot gets in its run context, so it says
  who the team serves, what it sells and how it wins, and nothing else.
- **Vision.** One or two sentences, at most 400 characters. Every framework has it; it is the Vision the Goals page
  used to keep in its Company section.
- **Sections.** A handful of markdown sections. Which ones depends on the framework (below). The default set is
  *Who we serve · What we sell · How we win · Pricing · Channels · Brand and voice · What we won't do*. **What we
  won't do** is required: a strategy with no trade-offs is a description.
- **Choices.** Three to seven short records, each a `statement` (a decision that could turn out wrong), a `why`, what
  it `rules_out`, and a `status`: `proposed`, `active` or `retired`. This is the spine of the page and what goals link
  to. The label shown depends on the framework; the default is **Bets**. A retired choice keeps its goals; the page
  shows them under "retired".
- **Evidence and results.** A section or a choice cites market theses and evidence from the Market tab. Each choice
  shows the goals that serve it and their colours, from [Goals and KPIs](goals-and-kpis.md). Linking a goal to a
  choice is optional: the page offers "not tied to a choice" as a filter, never as a nag.
- **Versions.** Publishing makes a numbered version with a note. There is always exactly one draft; publishing stamps
  it as version *n* and opens a fresh draft copied from it. Older versions stay readable and any two can be diffed,
  field by field, with the choices added, retired or changed between them.

### On choices

Every framework reduces a strategy to a short list of decisions that could be wrong: Rumelt's guiding policy, Playing
to Win's where-to-play and how-to-win, OGSM's strategies, V2MOM's methods. A software team's "charge as if fully
automated and use humans behind it" is one; so is a car dealership's "service and used cars carry the margin; new
cars are priced to bring people in". Most teams already live by three or four of these without having written them
down. The CEO Bot's interview exists to surface them, each with why and what it rules out. The record is the same for
every framework; only the word on the page changes.

## Frameworks are lenses

The owner picks a framework; the stored shape is the same. A framework is one YAML file in
`backend/strategy_frameworks/` with its section keys and titles, the label for the choices, and the interview
questions the CEO Bot picks from. `hub strategy frameworks` and `GET /api/v2/strategy/frameworks` list them.

| Framework | Sections | Choices label |
|---|---|---|
| **Plain** (default) | serve, sell, win, price, reach, brand, not | Bets |
| **Rumelt's kernel** | diagnosis, policy, actions | Guiding policy |
| **Playing to Win** | aspiration, where, how, capabilities, systems | Choices |
| **OGSM** | objective, goals, strategies, measures | Strategies |
| **V2MOM** | vision, values, methods, obstacles, measures | Methods |
| **Positioning** (Dunford) | alternatives, attributes, value, customers, category | Positions |

Every framework has an implicit `vision` section. Switching frameworks keeps the summary, the vision, the choices and
any section whose key the new framework also has; the rest stays readable in the version history. The draft
refuses a section key its framework does not have. Checks such as 7 Powers, Blue Ocean or Porter's five forces are not
page shapes; they come later as questions the CEO Bot runs against a draft.

## Who may do what

| | Read | Write the draft and choices | Publish |
|---|---|---|---|
| The owner | yes | yes, inline on the page or with `hub strategy draft` | yes, with a note |
| Any human on the team | yes | no | no |
| The CEO Bot | yes | at **Acts on its own** only; at **Passive** and **Suggests actions** it proposes a `strategy_draft` the owner confirms | never |
| Every other bot, and an external agent over MCP | yes (`hub strategy show`, `hub strategy summary`) | no | never |

No bot publishes a version, at any level: `POST /strategy/publish` from a bot is refused, and the CEO Bot's
instructions say asking another way is not a workaround. Publishing is the one click that tells the whole team
something changed, so it stays a person's. The owner's level choice for the CEO Bot is on
[Your CEO Bot](ceo-bot.md#the-three-levels).

## What the CEO Bot does with it

Strategy is the CEO Bot's first job, before the org chart proposals and the goals
([Your CEO Bot](ceo-bot.md#strategy)). Its playbooks are the product (`templates/catalog/goal-manager/playbooks/`):

- **Draft the strategy** (`draft-the-strategy.md`): a task "Draft the strategy", or the owner asking in chat. It reads
  the market pages (`hub market show company/self`, `hub doc search --market`), the setup answers and
  `knowledge/company.md`, picks the framework the owner chose (plain unless told), writes a first draft within five
  minutes and rewrites as it learns. It commits to positions instead of listing options, surfaces the choices the team
  already lives by, fills "What we won't do", and interviews the owner one question at a time (in chat, or as one
  card at a time from a task), asking only what the draft cannot answer, at most eight questions. It never invents a
  number: a figure appears only when a market page or a source it read states it. It ends by asking the owner to
  publish. Below level 3 the whole draft is one `strategy_draft` proposal in the owner's Needs you.
- **Strategy check** (`strategy-check.md`): the fit check, monthly. It reads `hub strategy show`, `hub market delta`,
  the goal colours and the latest KPI readings, compares them with the active choices, and files proposals (never
  edits) where evidence contradicts a choice or a choice has no goal, then one short report. **The routine is
  declared in the template and stays off** (`enabled: false`, never armed by the server) until the fit-check work is
  finished; a run of it while off ends with one line saying so.
- Goals: when the owner asks for goals, or after a version is published, it suggests one or two per active choice
  with `choice_id` set, and the Monday note names each active choice that no goal serves.

The Librarian reads the strategy too: "Set up the market map" takes the team's website from `hub strategy show`
when its task has none, and the daily curate routine says in its report when an insight contradicts an active
choice and names the CEO Bot in the task so it can check. The Librarian curates the market, not the strategy
([Librarian](librarian.md#setting-up-the-market)). The optional Strategy Analyst template (quarterly plans) reads
`hub strategy show` first and plans each quarter against the active choices.

## Setup

Once the setup wizard's Strategy step ships (it is being built after the backend and the page), setup's first question
changes from "build your org chart" to **"What are you building?"**:

1. **What are you building.** An existing team pastes its website and one line about it; a new idea is described in a
   few sentences. Research starts the moment a URL lands: the server fetches the site (home, about, pricing, customers)
   and drafts a profile while the owner keeps going.
2. **Strategy.** A conversation, not a form. The CEO Bot asks one question at a time on the left, picking the ones the
   draft could not answer; the Strategy page fills in on the right as they talk, and the owner edits inline. **Looks
   right** publishes version 1. During setup this runs on the server with the team's model provider, because a
   self-hosted install has no bot computer yet; after setup the CEO Bot takes over.
3. **Org.** Recruit proposes groups and bots from the summary and the choices, each citing the choice it serves.
4. Computer, agent and review as today.
5. After setup the CEO Bot proposes the first goals, one or two per choice, as Decide cards, and the Librarian's "Set
   up the market map" task is filed from the website.

Until then, the Strategy page starts from what the Goals page held: an install with a Vision or a Description and no
strategy gets a draft under the plain framework with that vision and the description as *What we sell*, and the
owner or the CEO Bot takes it from there. The Market tab's own first run (the Librarian's four questions) is unchanged
([Librarian](librarian.md#first-run-setup)).

## Changing the strategy

The owner edits the draft and publishes; each version carries a note. Publishing tells every bot three ways:

- a `strategy.published` routine event, subject `v{n}`, so a routine can run `--on strategy.published`
  ([Routines](routines.md));
- one quiet note to each active bot: "Strategy v{n} published: {note}. Run `hub strategy show`.";
- the new summary in every bot's run context from its next run, under a **Team strategy** header
  ([Agent context](agent-context.md)). Until a version is published, nothing is added.

Realignment after a change (goals that no longer fit, groups to add or shrink, instructions that still say the old
positioning) is the same mechanism as the strategy check: the CEO Bot proposes and a person approves. Those
propagation rules are not written yet; today the Monday note and the goals' choice links are what show the drift.

## `hub` and the API

```
hub strategy show                       the current version and the draft, with the choices and goals_by_choice
hub strategy summary                    the plain text every bot gets in context
hub strategy draft [--framework F] [--summary S] [--vision V] [--section KEY=TEXT ...]
hub strategy publish --note "<why>"     owner only; a bot gets a refusal
hub strategy versions                   n, note, who published, when
hub strategy diff <from> <to>           field by field, plus the choices added, retired or changed
hub strategy choice add | update <id> | retire <id>
hub strategy frameworks
hub goal create ... --choice <id>       hub goal update <id> --choice <id>
```

Every command has an MCP tool of the same name and arguments (`hub_strategy_show`, `hub_strategy_draft`,
`hub_strategy_publish` ...). The stable routes, under `/api/v2`, are in [openapi/v2.json](openapi/v2.json):

| Route | Who | What it does |
|---|---|---|
| `GET /strategy` | any reader | `{draft, current, choices, label, frameworks, goals_by_choice}`; `current` is the latest published version or null; `goals_by_choice` maps a choice id to `[{id, title, colour}]` |
| `PUT /strategy/draft` | the owner; the CEO Bot at level 3 | partial `{framework?, summary?, vision?, sections?}`; section keys are checked against the framework; summary and vision at most 400 characters |
| `POST /strategy/publish` | the owner only, never a bot | `{note}`; answers the new version |
| `GET /strategy/versions`, `/strategy/versions/{n}` | any reader | the list (`n`, `note`, `published`, `published_by`); one version |
| `GET /strategy/diff?from=&to=` | any reader | the per-field diff of two versions, plus choices added, retired and changed |
| `POST /strategy/choices` | the owner; the CEO Bot at level 3 | `{statement, why?, rules_out?, status?}`; answers the choice |
| `POST /strategy/choices/{id}` | the same | partial update, including `rank` and `status` |
| `GET /strategy/summary` | any bot or human | plain text: the summary, one line per active choice, then "version N" |
| `GET /strategy/frameworks` | any reader | the frameworks as listed above |

Goals take `choice_id` on `POST /goals` and `POST /goals/{id}` and return it in `GET /goals` and `/goals/tree`
([Goals and KPIs](goals-and-kpis.md#hub-and-the-api)). Every change is a row in `strategy_events`, like
`market_events`. The tables are `strategy_versions` (one draft row at a time; `n` is null on the draft) and
`strategy_choices` (`since_n` and `until_n` say which versions a choice was active in).

Related: [Goals and KPIs](goals-and-kpis.md), [Your CEO Bot](ceo-bot.md), [Librarian](librarian.md),
[Routines](routines.md), [Agent context](agent-context.md).
