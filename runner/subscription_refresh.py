"""Read allowance through the signed-in CLI, without a thread, turn or paid request."""
import math
import shutil
import threading
import time
from datetime import datetime, timezone

from clients.tico import APIError

from .hosts.codex import CLIENT_INFO, CodexHost, iso
from . import profiles

POLL_SECONDS = 15
TIMEOUT_SECONDS = 15


class QuotaHost(CodexHost):
    def _initialize(self):
        self.request('initialize', {'clientInfo': CLIENT_INFO}, timeout=TIMEOUT_SECONDS)
        self.notify('initialized', {})


def read_codex(profile, host_factory=QuotaHost, cancelled=None):
    executable = shutil.which('codex')
    if not executable:
        return {'state': 'unavailable'}
    env = profile.environment('codex')
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN'):
        env.pop(name, None)
    # Account-only app-server calls do not start threads or load thread MCP servers.
    host = host_factory(cmd=(executable, 'app-server'), env=env, config={})
    try:
        if cancelled and cancelled.is_set():
            return {'state': 'failed'}
        host.start()
        if cancelled and cancelled.is_set():
            return {'state': 'failed'}
        reply = host.request('account/rateLimits/read', timeout=TIMEOUT_SECONDS)
        buckets = reply.get('rateLimitsByLimitId')
        bucket = buckets.get('codex') if isinstance(buckets, dict) else reply.get('rateLimits')
        if not isinstance(bucket, dict) or bucket.get('limitId') not in (None, 'codex'):
            return {'state': 'unavailable'}
        windows = [w for w in (bucket.get('primary'), bucket.get('secondary'))
                   if isinstance(w, dict) and w.get('windowDurationMins') == 10080]
        if len(windows) != 1:
            return {'state': 'unavailable'}
        window = windows[0]
        percent, reset = window.get('usedPercent'), iso(window.get('resetsAt'))
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent) or not 0 <= percent <= 100:
            return {'state': 'failed'}
        now = datetime.now(timezone.utc)
        if reset is None or not 0 < (datetime.fromisoformat(reset) - now).total_seconds() <= 8 * 86400:
            return {'state': 'failed'}
        return {'state': 'succeeded', 'weekly': {'used_percent': percent, 'resets_at': reset,
                'reported_at': now.isoformat(), 'status': 'rejected' if percent >= 100 else None}}
    except Exception:
        # Provider errors can contain secrets/account details; only a fixed state travels back.
        return {'state': 'failed'}
    finally:
        host.stop()


class Refreshes:
    """One bounded worker per computer; retain completed reports for delivery retry."""
    def __init__(self, runner):
        self.runner = runner
        self.polled = -POLL_SECONDS
        self.thread = None
        self.result = None
        self.work = None
        self.lock = threading.Lock()
        self.cancelled = threading.Event()

    def busy(self):
        """A read under way or a result not yet delivered: followed on its own timer."""
        with self.lock:
            return self.result is not None or bool(self.thread and self.thread.is_alive())

    def poll(self, ask=None):
        """`ask`: whether to ask the server for work (the runner's event stream decides); None, on POLL_SECONDS."""
        if self.cancelled.is_set():
            return
        if ask is None:
            if time.monotonic() - self.polled < POLL_SECONDS:
                return
            ask = True
        self.polled = time.monotonic()
        with self.lock:
            result, work = self.result, self.work
        if result is not None:
            try:
                self.runner.client.post(f'runner-subscription-refreshes/{work["id"]}/report',
                                        {'profile': work['profile'], 'runtime': work['runtime'], **result})
            except APIError as exc:
                if exc.status not in (404, 409, 422):
                    raise
            with self.lock:
                self.result = self.work = None
        if self.thread and self.thread.is_alive() or not ask:
            return
        wanted = (self.runner.client.get('runner-subscription-refreshes') or {}).get('refreshes', [])
        if not wanted:
            return
        work = dict(wanted[0])
        entry = (self.runner.config.get('profiles') or {}).get(work.get('profile'))
        profile = profiles.Profile(work['profile'], entry['dir'], entry.get('share_operator')) if isinstance(entry, dict) and entry.get('dir') else None
        # Capture an isolated profile once. Never resolve the global/default profile here.
        self.work = work
        def run():
            try:
                result = read_codex(profile, cancelled=self.cancelled) if profile and work['runtime'] == 'codex' else {'state': 'unavailable'}
            except Exception:
                result = {'state': 'failed'}
            with self.lock:
                self.result = result
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancelled.set()
        if self.thread:
            # Both protocol requests are bounded; wait for the worker's finally to reap its process.
            self.thread.join(timeout=2 * TIMEOUT_SECONDS + 6)
