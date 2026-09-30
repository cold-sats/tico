# Work queue

Not a schedule of its own: the weekly sweep runs it, and a task from the owner can name it with a
scope (a surface, a page range, a date range). Budget 45 minutes per surface.

The outcome is one `publish` approval per surface whose payload lists every item, its lever, its
grounds and its text; then, once approved, the batch executed in the browser and every row's
outcome recorded. Nothing outside the approved payload is ever executed.

---

## 1. Give every row a lever

Read each row in scope with the review in front of you, not from the summary. Set `lever`:

| Lever | When | What it produces |
|---|---|---|
| `flag` | The review breaks a rule the platform publishes, quoted in `knowledge/surfaces.md`, and you can point at the words that break it | The ground, the platform's own wording, the quoted words, under 60 words of justification |
| `answer` | A BBB complaint, or a complaint on a surface that scores on responses | Under 150 words answering each point raised; or a request to BBB to close it as not a consumer complaint, when it is a pro's dispute |
| `reply` | A real customer experience we cannot and should not remove, on a surface that allows an owner reply | 40 to 80 words: acknowledge, what {{company_name}} is, where to get help. Nothing about the specifics |
| `none` | Already replied, already flagged and rejected, or a positive review | Nothing |

The strongest honest lever wins: flag over reply. A flag is never "it is negative".

## 2. Grounds that platforms honour

Use only grounds `knowledge/surfaces.md` lists for that surface, with its date. Starting set,
to be pruned by outcomes:

- **Marketing, not service** (flyers, door hangers, mailers, litter, cold calls): not a first-hand
  consumer experience of the service. Yelp: "reviews should be about your own consumer
  experience". Google: "reviews should reflect a genuine experience at a place or business".
- **Worker or contractor dispute** (pay holds, decertification, fines, "they never paid me"):
  Google prohibits reviews by current or former workers as conflict of interest; Yelp excludes
  employment and contractor grievances; BBB takes consumer complaints only.
- **Wrong business**: the review describes a company that is not {{company_name}} (a similarly named business) or an address {{company_name}} never served.
- **Duplicate or proxy**: a second review by the same person for the same event, or a review that
  only says to read the other reviews.
- **Abuse**: threats, personal data, an accusation of a crime with no first-hand event, hate.
- **Not a customer**: a competitor, a person who never booked (says so), a review of the company's
  hiring or an interview.

## 3. Draft the batch

One payload per surface: `{surface, items: [{ledger_id, url, lever, ground, quoted, text}]}`.
Order: newest first, then page one of the listing, then the rest. Cap a Yelp or Google batch at
50 items so a person can read it in ten minutes; the rest waits for the next sweep.

    hub approval request --kind publish --task <id> --payload '<json>'

Set every row's `status` to `drafted` with the approval id.

## 4. Execute the approved batch

Only after `hub approval show <id>` says approved, and only the items in it. Until the owner has
enabled the browser `act` access, hand the approved payload to a person and stop here; a person
executes it and you record the outcomes. Once it is enabled, through the browser connector with `act`:

    $HUB_DIR/connectors/browser.py repl --as reputation "..."

- Flags: the platform's report flow, one review at a time, the ground selected as the payload
  says, the justification pasted as written. Record `flagged` with the date.
- Replies and answers: the platform's owner reply or BBB response form, the text pasted as
  written. Record `replied` or `answered`.
- Claims and category changes: only when the payload includes them and the signed-in account is
  the business owner's; otherwise they are the owner's task, not yours.
- On a captcha, a sign-in wall or a rate limit: stop that surface, record how far you got, and
  finish the rest next sweep. Never retry a submitted item.

## 5. Track outcomes

Every later sweep re-reads each `flagged` row: still visible after 14 days is `rejected`, gone is
`upheld`. Write the ground's running upheld rate into `knowledge/surfaces.md`; a ground under 10%
upheld after 20 tries is retired for that surface.

## When a batch is refused

Read the note, remove or change the items it names, and request again once. A second refusal is
a `memory/learnings.md` entry and a line on the digest.
