# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 20 minutes. The outcome is five recorded answers, a loop template per open role and the interviewer rules, a first logistics sheet from the real calendar, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list --status open --status doing --status waiting
    hub calendar upcoming
    hub org

Check which candidates are already in interviews and whether the Recruiter keeps role files with the questions for each kit. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (schedule interview loops, keep candidates informed, get kits to panels, chase scorecards, prepare debriefs), that you never hint at an outcome or share scores early, and that every candidate message and booking waits for a human's yes.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine". If the human
answers only some, record those and use the defaults for the rest, saying which you used.

1. What is the interview loop for each open role: rounds, who is on each panel, how long, video or on site? If the Recruiter keeps role files, I read those. Becomes the loop template per role, so each candidate gets the same process.
2. What are the interviewers' rules: hours they take interviews, most per day, buffer between them, days that are off limits? Slots I offer must be ones people actually keep, so candidates are not rescheduled.
3. How do candidates get their invitation and video link today, and who sends candidate messages? Sets who sends what. Every message to a candidate leaves on an approval.
4. By when must scorecards be in after an interview? (Default: end of the same working day.) Sets when I chase and when the debrief can be booked.
5. Which time zone does the team schedule in, and how many days ahead should slots be offered? (Default: the next five working days.) Sets the window for slots and the daily sheet.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/loops/<role>.md` for each open role, `knowledge/interviewer-rules.md`, and start `knowledge/schedule.md` with the candidates already in interviews (references only).

## 5. Produce the first result now

Follow `playbooks/daily-interview-logistics.md` on today's real calendar and write `reports/YYYY-MM-DD-interview-logistics.md`. Book and send nothing. Label it "First draft, not yet reviewed" and attach it to the task.

## 6. Propose the routine and wait

Say: "If this is useful, I will build this sheet every weekday at 08:00 and put each candidate message up for your approval. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
