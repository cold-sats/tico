# Plan a trip

Triggered by a task: "Dana needs to be in Denver for the studio expo, 14 to 16 October". Budget 25
minutes. The outcome is a trip plan with two or three options, a recommendation, and after the
traveller agrees, a booking request in front of the approver.

---

## 1. Pin the trip down

    hub task show <id>

Traveller, purpose, where exactly (the venue address, not just the city), the first and last
commitments there, and anything fixed (a talk at 09:00 on the first day). Check their calendar if
connected. One question to the traveller if something is missing.

## 2. Find the options

Search public fares and hotel prices for the exact dates. For each option: carrier or hotel, times,
fare rules (refundable, change fee, bags), total including ground transport, distance to the venue,
price seen and time seen. Three at most: cheapest within policy, best for the schedule, preferred
supplier if within about 5 percent.

## 3. Check it

Against `knowledge/policy.md`: class, hotel limit, advance booking. Name any exception and why. Entry
requirements for international trips from the official government page with its date; tell the
traveller to confirm passport validity and visas themselves.

## 4. Recommend and ask

Write `reports/trip-<traveller>-<date>.md` in the shape of `knowledge/examples/trip-plan.md`. Ask the
traveller to pick (`hub task ask <id>`). Then the booking request goes to the approver with
`hub approval request --kind spend`: option, total, fare rules, within policy or the exception.

## 5. After it is booked

File confirmation numbers in `knowledge/trips.md`, build the itinerary (times in local time, addresses,
check-in rules, the local contact, what to do if a leg is cancelled) and send it to the traveller.
