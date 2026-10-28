# Redesign scenarios

PLAN §7 scenarios for the redesign, written before the code. Each check is a real API call against the factory's
in-process hub on a fake clock (`evals/factory/world.py`). Nothing is stubbed: a check the product cannot pass yet
fails as `not built yet: <wave>`, and a check the CONTRACT cannot back fails as untestable.

Run from the repo root:

    python -m evals.redesign.run                  # all scenarios
    python -m evals.redesign.run 1 6 perm-audit   # by number or name
    python -m evals.redesign.run 13 --explain     # also print each API call the scenario made

Files
- `harness.py`: the org (Chris, Engineering Lead, two builders, Release Manager), the API calls, `Unmet`, `BUILT`.
- `cases/caps.py` (1-10), `cases/spend.py` (11-15), `cases/permissions.py` (32-35), `cases/setting.py` (45).
- `run.py`: prints PASS or FAIL per check; exits 1 on any FAIL.

Status
- `BUILT` (harness.py): a wave is added there when its PR merges. Its failures then print the real reason.
- Holds today: a check that passes on main now. It must keep passing.
- CONTRACT gap: a check with no route or read shape named yet. Fails as untestable until the CONTRACT names one.

Adding a scenario: a `Scenario` in a case module, steps that call `org.step`, and checks that return `(ok, detail)`.
