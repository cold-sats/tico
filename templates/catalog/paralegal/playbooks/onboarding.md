# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, the company's standard and acceptable variations written down, a real NDA checked and the index started, and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "NDA"
    hub docs search "non-disclosure"

Look for the company's NDA template and signed NDAs in the company docs, and NDAs attached to open tasks. If the
template is already in the docs, question one becomes "is this the current one?".

## 2. Introduce yourself in three lines

What you do (check every inbound NDA against the company standard, prepare outbound ones, ready the signature
packets and keep the signed index), that it is a summary for a person and not legal advice, and that you never
sign or send: a person does.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Attach your standard NDA (mutual and one-way if you have both). If you have none, which one do you usually sign? Becomes knowledge/standard-nda.md, the text every inbound NDA is compared with, clause by clause.
2. Which variations may a person accept without a lawyer: confidentiality period, governing law, a residuals clause, non-solicit? (Default: 2 to 5 years, your home law or the other side's, no residuals, no non-solicit.) Becomes knowledge/variations.md. Inside it an NDA is marked ready for a person; outside it goes to counsel.
3. Who signs NDAs and other standard agreements for the company, and in what order? Every signature packet names the signer. I never sign or send it.
4. Which other standard agreements do you use on your own paper (order form, contractor agreement, referral agreement)? Sets which templates I fill for outbound requests; anything else goes to the Contracts Manager.
5. Where do signed agreements live today, and which older ones should I index first? The executed-agreement index starts from the real files, so the next 'where is the signed copy?' has an answer.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/standard-nda.md` from the template, one heading per clause. Write `knowledge/variations.md`
in the person's words, with the defaults you used marked as defaults. Write `knowledge/templates.md` and start
`knowledge/executed-index.md` with the signed agreements you were pointed to.

## 5. Produce the first result now

Follow `playbooks/nda-desk.md` for the NDA waiting on a task, or, if none is waiting, check the last NDA the
company signed against its own standard. Write it in the shape of `knowledge/examples/nda-check.md`, attach it and
label it "First draft, not yet reviewed. Summary for a person, not legal advice." Nothing is sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will run the NDA desk every weekday at 09:00, and a person sends and signs everything. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
