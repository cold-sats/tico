"""Scenarios kept one per file: each module's `SCENARIOS` list joins scenarios.SCENARIOS, after the built-in ones.
A case module imports what it needs from evals.factory.scenarios (Scenario, standard, tickets, the checks) and adds
its own setup and checks beside them; add one import line below for it. The imports are literal so the PR checks'
dependency map (scripts/pr_checks.py) sees exactly which files the sim runs."""
SCENARIOS = []
# One line per case, in name order:  from .<name> import SCENARIOS as _<name>; SCENARIOS += _<name>
from .qa_waiver_head import SCENARIOS as _qa_waiver_head; SCENARIOS += _qa_waiver_head
