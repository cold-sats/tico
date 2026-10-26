# Factory simulation

`python -m evals.factory.run [scenario ...] [--seed N] [--explain] [--json]` runs the Dev board end to end against
the real server, in-process, on a fake clock: real API calls with each bot's own attempt token, real GitHub webhooks
for pull requests, and the real scheduler pass every five simulated minutes. Only the bots' replies and time are made
up, so a run tells you what the queue, the wake rules and the board do with a whole team over a day, in seconds.

- `world.py`: the disposable hub, the Dev tickets type, one runner for every bot, and a fake GitHub.
- `bots.py`: simulated bots by role (Builder, reviewer, QA, Head of Engineering). A bot's `style` sets how its model
  behaves: asks for changes, fails, garbles its reply, goes silent, crashes, can't test, goes off script. Turn
  lengths and token counts are a real team's weekly averages.
- `sim.py`: the loop, what it measures (turns, noise turns, turns on stale notices, cost, queue peaks, tickets at
  work per builder) and the invariants it watches on every tick.
- `scenarios.py`: board situations seen on a real team, each with its checks. A check that names a ticket or a
  feature is a known gap: it fails until that work lands, then guards it.

`SIM_TRACE=1` prints every turn: time, bot, what woke it, whether the notice was already stale (`*`), and what the
bot did. The seed makes each run repeat exactly.

The simulation is not part of the test suite. Run it before and after a change to the wake rules, the queue, the
review gate, the Dev steps or usage limits, and compare.
