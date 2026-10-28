# Redesign scenarios

PLAN §7 scenarios for the redesign, written before the code. Each check is a real API call against the factory's
in-process hub on a fake clock (`evals/factory/world.py`). Nothing is stubbed: a check the product cannot pass yet
fails as `not built yet: <wave>`, and a check the CONTRACT cannot back fails as untestable.

Run from the repo root:

    python -m evals.redesign.run                  # all named scenarios
    python -m evals.redesign.run 1 6 perm-audit   # by number or name
    python -m evals.redesign.run 13 --explain     # also print each API call the scenario made
    python -m evals.redesign.run matrix --seed 1  # all-pairs matrix; prints the seed and combination count

Files
- `harness.py`: the org (Chris, Engineering Lead, two builders, Release Manager), the API calls, `Unmet`, `BUILT`.
- `cases/`: caps (1-10), spend (11-15), inboxes (16-21), engine (22-31), permissions (32-35), setting (45).
- `matrix.py`: the seeded all-pairs plan and its skip rules (no server). `cases/matrix.py` builds and reads each row.
- `fakes.py`: the judge replay, Slack and Gmail fakes, the incoming-webhook helpers, the outgoing receiver.
- `run.py`: prints PASS or FAIL per check; exits 1 on any FAIL.

Judge and recordings
- `ReplayJudge` answers from `recordings/<hash>.json`, else from a scripted answer, else `MissingRecording`.
- `RECORD=1` (the recorder) raises `NotImplementedError("record: not built")`.
- `REDESIGN_LIVE=1` turns on the live sample: 5% of recorded calls, at most 10 a run. Off by default.
  `go_live` raises `NotImplementedError("live: not built")`.

Status
- `BUILT` (harness.py): a wave is added there when its PR merges. Its failures then print the real reason.
- Holds today: a check that passes on main now. It must keep passing. The matrix's plan checks are of this kind.
- CONTRACT gap: a check with no route or read shape named yet. Fails as untestable until the CONTRACT names one.
- Matrix inputs with no named route (email, Slack, listening, event) are untestable until the CONTRACT names one.

Adding a scenario: a `Scenario` in a case module, steps that call `org.step`, and checks that return `(ok, detail)`.
