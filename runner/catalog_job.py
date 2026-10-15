"""Built-in bots from the catalog, for the Rust runner (runner-rs/src/product_files.rs), which ships no templates:
`python -m runner --config <path> catalog` reads one JSON request on stdin and prints one JSON answer on stdout.

    {"bots": [{"bot": "botops", "entry": {...assignment row...}, "path": "...", "action": "bootstrap" | "refresh"}]}

`bootstrap` sets a bot without a repository up from its template (Runner.bootstrap: never over history GitHub holds);
`refresh` brings a built-in bot's product files up to this release (Runner.refresh_from_template). The answer is
{bot: {"materialized", "problem"}} or {bot: {"changed": [...]}}. Log lines go to stderr."""

import contextlib
import json
import sys
from pathlib import Path

from .service import Runner


def handle(config, client, request):
    service = Runner.__new__(Runner)     # as `doctor`: no outbox, threads or loop, just the methods
    service.config = config
    service.client = client
    items = [item for item in request.get("bots") or [] if isinstance(item, dict) and item.get("bot")]
    service.assignments_seen = [item.get("entry") or {} for item in items]
    answer = {}
    for item in items:
        bot, entry, path = str(item["bot"]), item.get("entry") or {}, Path(str(item.get("path") or ""))
        if item.get("action") == "bootstrap":
            note, problem = service.bootstrap(bot, entry.get("config"), path, entry)
            answer[bot] = {"materialized": note, "problem": problem}
        else:
            answer[bot] = {"changed": service.refresh_from_template(bot, entry.get("config"), path)}
    return answer


def main(config, client, stdin=None, stdout=None):
    request = json.loads((stdin or sys.stdin).read() or "{}")
    with contextlib.redirect_stdout(sys.stderr):
        answer = handle(config, client, request)
    print(json.dumps(answer), file=stdout or sys.stdout, flush=True)
