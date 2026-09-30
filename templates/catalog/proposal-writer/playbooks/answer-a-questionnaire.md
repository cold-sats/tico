# Answer a questionnaire or RFP

Triggered by a task with a security questionnaire, an RFP or a buyer's list of questions. Budget 90
minutes for fifty questions. The outcome is a draft answer per question, each marked reused, adapted or
new, and a list of what a named owner must answer. Nothing is sent.

---

## 1. Read and sort the questions

    hub task show <id>

Sort each question: product, commercial, security, legal, compliance, references. Note the deadline and
any required format.

## 2. Match to the library

For each question search `knowledge/library/` and past answers. An exact or near match under twelve
months old: reuse and mark **reused** with the entry and its date. A match that needs adapting: adapt
lightly, keep the facts, mark **adapted**. No match: mark **new**.

## 3. Draft only what you can source

A product answer is drafted from the product docs (`hub docs search`) with the source named. A security,
legal or compliance answer without an approved entry is not drafted: write `[owner: <name>]` and the
question. A reference request is a gap for the seller unless the customer is in `knowledge/proof.md`.

## 4. Write the return file

In the buyer's format if given, else in a table: question, draft answer, status, source, owner. Put the
counts at the top: reused, adapted, new, waiting on a person.

## 5. Hand over and learn

Attach it to the task. Once a named owner confirms a new answer, add it to `knowledge/library/` with the
owner and date. `hub task update <id> --status done --note`: counts, open owners, deadline risk.
