# Compare vendors

Triggered by a purchase request task, and used by `playbooks/weekly-purchase-digest.md`. Budget 40
minutes for three to five vendors. The outcome is one comparison a human decides from and a draft
email for the questions still open. It follows public vendor-evaluation practice (see the sources in
docs/starter-bots.md): must-haves first, weighted scores, total cost, then references.

---

## 1. Read the request and what the team has

    hub task show <id>

Read `knowledge/criteria.md` and `knowledge/vendors.md`. Restate the need in one line: what job, for
whom, how many seats or units, by when. If the team already owns a tool that does it, say that first
and compare it too. Ask the requester one question with `hub task ask <id>` only if the need is unclear.

## 2. Shortlist three to five

From the request, public sources and any quotes attached, choose the realistic options. Drop any on the
avoid list. More than five buries the decision.

## 3. Apply the must-haves

For each vendor, pass or fail each must-have, with the page and date. A failure drops the vendor here,
with the evidence. "Not stated" is a gap to ask about, not a pass.

## 4. Score and cost the term

Score 1 to 5 against each criterion in `knowledge/criteria.md`, using the rubric: 1 does not meet the need,
3 meets it, 5 clearly exceeds it. Weighted total is score times weight, summed. Cost the whole term: price
as stated (with date and source), seats and tiers, setup, support tier, renewal rise, and the cost of
leaving. Say what the quote does not include.

## 5. Check claims

Security and compliance items are what the vendor claims (a trust page, a certificate it says exists);
label them "claimed". The standing questions in `knowledge/security-questions.md` (starter list: data
location, encryption at rest and in transit, single sign-on, access logs, breach notification time,
sub-processors, data export and deletion, an independent audit report) go in the draft email for any vendor
that will hold team data. Reviews are read as a signal, with the date, not as proof.

## 6. Write it

`reports/R-<id>-comparison.md` in the shape of `knowledge/examples/vendor-comparison.md`: headline with a
suggestion, must-haves, weighted scores, claims with sources, checks before deciding (two references
from finalists, an export sample, prices beyond the quote), and the draft email. The suggestion is
labelled as one. For a contract's terms, `hub task create --owner legal-review`.

## 7. Finish

`hub file publish reports/R-<id>-comparison.md`, attach the draft email, then `hub task update <id> --status
done --note`: the suggestion, the decide-by date, and what you could not read. A page that failed to load
makes that score provisional, and is said so. The human contacts vendors and decides; leave the build to BotOps.
