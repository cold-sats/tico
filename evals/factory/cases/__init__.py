"""Scenarios kept one per file: each module's `SCENARIOS` list joins scenarios.SCENARIOS, after the built-in ones,
in file-name order. A case module imports what it needs from evals.factory.scenarios (Scenario, standard, tickets,
the checks) and adds its own setup and checks beside them."""
