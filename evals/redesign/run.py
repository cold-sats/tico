"""Run the redesign scenarios: python -m evals.redesign.run [names or numbers] [--explain].

Each check prints PASS, or FAIL with the PLAN §6 wave it waits on ("not built yet: wave 2 · budgets"). A wave listed in
harness.BUILT prints the real reason instead. A check the CONTRACT cannot back prints as untestable. Exit 1 on any FAIL."""
import argparse
import sys
import time

from .cases import SCENARIOS
from .harness import BUILT, GAP, run_scenario


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="scenario names or numbers (default: all)")
    parser.add_argument("--explain", action="store_true", help="also print each API call a scenario made")
    args = parser.parse_args(argv)
    known = {s.name for s in SCENARIOS} | {str(s.num) for s in SCENARIOS}
    unknown = [n for n in args.names if n not in known]
    if unknown:
        parser.error("unknown scenario: " + ", ".join(unknown))
    chosen = [s for s in SCENARIOS if not args.names or s.name in args.names or str(s.num) in args.names]
    passed = failed = 0
    started = time.perf_counter()
    for scenario in chosen:
        results, log, seconds = run_scenario(scenario)
        print(f"{scenario.num:>2} {scenario.name} ({seconds:.1f}s)")
        if args.explain:
            print("\n".join("     " + line for line in log))
        for result in results:
            if result.ok:
                passed += 1
                print(f"   PASS {result.label}")
                continue
            failed += 1
            if result.wave == GAP:
                why = f"untestable as written: {result.text}"
            elif result.wave in BUILT:
                why = result.text
            else:
                why = f"not built yet: {result.wave} ({result.text})"
            print(f"   FAIL {result.label}: {why}")
    print(f"\n{passed} passed, {failed} failed, {time.perf_counter() - started:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
