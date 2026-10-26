"""Run the factory simulation: `python -m evals.factory.run [scenario ...] [--seed N] [-j N]`.

Each scenario drives the real server with simulated bots on a fake clock, then prints what happened and which of
its checks passed. A failed check that names a Dev ticket is a known gap that ticket fixes. Scenarios run in
parallel, one process each (each has its own server, database and clock)."""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context


def one(name, seed, explain):
    """Run one scenario in this process: (name, seconds, summary, check results, explain lines, trace)."""
    from .scenarios import SCENARIOS
    from .sim import Run
    scenario = next(s for s in SCENARIOS if s.name == name)
    started = time.perf_counter()
    run = Run(scenario, seed).go()
    results = []
    for check, ticket, fn in scenario.checks:
        ok, detail = fn(run)
        results.append({"check": check, "ok": ok, "ticket": ticket, "detail": detail})
    return {"scenario": name, "about": scenario.about, "seconds": round(time.perf_counter() - started, 1),
            "summary": run.summary(), "checks": results, "explain": run.explain() if explain else []}


def render(r):
    lines = [f"\n== {r['scenario']} ({r['seconds']:.0f}s): {r['about']}",
             "   " + ", ".join(f"{k} {v}" for k, v in r["summary"].items())]
    for c in r["checks"]:
        gap = f" [{c['ticket']}]" if c["ticket"] and not c["ok"] else ""
        lines.append(f"   {'PASS' if c['ok'] else 'FAIL'} {c['check']}{gap}" + (f": {c['detail']}" if c["detail"] else ""))
    lines += ["     " + line for line in r["explain"]]
    return "\n".join(lines)


def main(argv=None):
    from .scenarios import SCENARIOS
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="scenarios to run (default: all)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4, help="scenarios at once (1: in order)")
    parser.add_argument("--json", action="store_true", help="print one JSON object per scenario")
    parser.add_argument("--explain", action="store_true", help="say where each unfinished ticket stands")
    args = parser.parse_args(argv)
    unknown = set(args.names) - {s.name for s in SCENARIOS}
    if unknown:
        parser.error("unknown scenario: " + ", ".join(sorted(unknown)))
    names = [s.name for s in SCENARIOS if not args.names or s.name in args.names]
    started = time.perf_counter()
    results = []
    if args.jobs <= 1 or len(names) == 1:
        for name in names:
            results.append(one(name, args.seed, args.explain))
            print(json.dumps(results[-1], default=str) if args.json else render(results[-1]), flush=True)
    else:
        # A fresh interpreter per scenario: the fake clock and the server's module state are per process.
        with ProcessPoolExecutor(min(args.jobs, len(names)), mp_context=get_context("spawn")) as pool:
            futures = [pool.submit(one, name, args.seed, args.explain) for name in names]
            for future in as_completed(futures):
                results.append(future.result())
                print(json.dumps(results[-1], default=str) if args.json else render(results[-1]), flush=True)
    failed = sum(not c["ok"] for r in results for c in r["checks"])
    if not args.json:
        print(f"\n{len(results)} scenarios in {time.perf_counter() - started:.0f}s; "
              f"{sum(all(c['ok'] for c in r['checks']) for r in results)} passed, {failed} failed checks")
        for r in sorted(results, key=lambda r: names.index(r["scenario"])):
            bad = [c for c in r["checks"] if not c["ok"]]
            print(f"   {'PASS' if not bad else 'FAIL'} {r['scenario']:24}"
                  + "; ".join(f"{c['check']} [{c['ticket'] or '-'}]" for c in bad))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
