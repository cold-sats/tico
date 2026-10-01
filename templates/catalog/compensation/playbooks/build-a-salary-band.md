# Build a salary band

Triggered by a task asking for a band for a role family, or by a role with no band. Budget 45 minutes.
The outcome is a proposed band per level with its source, for an owner to accept. Nothing is published.

---

## 1. Define the role

From the level guide (`hub doc ask "What does <level> mean for <role family>?"`) and the role brief:
scope, level, location rule. A band is for a role family and level, not for a person.

## 2. Gather market data

In this order of trust: the salary survey the team buys (attached to the task), the payroll provider's
benchmark, public ranges published for comparable roles in the same market (`hub doc fetch <url>`,
at least three, with dates). Record each data point's source, date, location and level match.

## 3. Set the midpoint

Apply `knowledge/philosophy.md`: the market median for "pay at market", a higher percentile for roles the
team chose to lead on. Adjust for location only if the philosophy says so, and say by how much.

## 4. Set the spread

Minimum and maximum around the midpoint: about 30 percent spread for entry levels, 40 to 50 percent for
senior levels. State the overlap with the level above and below.

## 5. Check against current pay

Using the payroll export attached for this purpose: how many people in the role family fall below the
minimum or above the maximum (counts in the page, references in an attachment for the owners).

## 6. Hand over

Attach the proposal with its sources and record requested bands in `knowledge/bands.md` with the date and owner. A band from fewer than three data
points is marked provisional.
