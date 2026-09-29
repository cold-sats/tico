"""Opt-in telemetry with a small, explicit wire contract and no ambient SDK state."""

import hashlib
import hmac
import json
import re
from pathlib import Path

from .config import ROOT

ENVIRONMENTS = frozenset({"development", "staging", "production", "test"})
POSTHOG_HOSTS = frozenset({"https://us.i.posthog.com", "https://eu.i.posthog.com"})
SOURCE_FILES = frozenset(p.relative_to(ROOT).as_posix() for p in (ROOT / "backend").glob("*.py"))


def public_dsn(value):
    """Only public Sentry ingestion DSNs; never expose legacy password credentials."""
    if isinstance(value, str) and re.fullmatch(
        r"https://[a-fA-F0-9]+@(?:[a-z0-9-]+\.)*ingest(?:\.[a-z]{2})?\.sentry\.io/[0-9]+", value
    ):
        return value
    return ""


def release(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value) else ""


def browser_config(settings, actor):
    if (settings.observability_environment not in ENVIRONMENTS
            or len(settings.observability_id_secret) < 32):
        return {}
    host = settings.posthog_host.rstrip("/")
    key = settings.posthog_key
    if host not in POSTHOG_HOSTS or not re.fullmatch(r"phc_[A-Za-z0-9_-]+", key):
        key, host = "", ""
    dsn = public_dsn(settings.sentry_dsn)
    if not key and not dsn:
        return {}
    distinct_id = "tico:" + hmac.new(settings.observability_id_secret.encode(), actor.encode(),
                                     hashlib.sha256).hexdigest()
    return {"app": "tico", "environment": settings.observability_environment,
            "distinct_id": distinct_id, "posthog_key": key, "posthog_host": host,
            "sentry_dsn": dsn, "release": release(settings.release_id)}


def staff_display_name(c, who):
    """Only admitted staff metadata; normalized ID-title names lack provenance."""
    if who.role not in ("human", "owner") or not who.actor.startswith("human:"):
        return ""
    pid = who.actor[len("human:"):]
    human = c.execute("SELECT email FROM humans WHERE id=?", (pid,)).fetchone()
    if not human:
        return ""

    def bounded(value):
        if not isinstance(value, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            return ""
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return ""
        value = value.strip()
        return value if 0 < len(value) <= 254 else ""

    row = c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()
    if row:
        try:
            roster = json.loads(row[0])
        except (ValueError, TypeError):
            roster = {}
        people = roster.get("people", []) if isinstance(roster, dict) else []
        people = people if isinstance(people, list) else []
        matches = [p for p in people if isinstance(p, dict) and p.get("id") == pid]
        if len(matches) == 1:
            name = bounded(matches[0].get("name"))
            # Initial import stores P.load(roster), which fills missing names with
            # pid.title(). Even a real name equal to that fallback is ambiguous.
            if name and name.casefold() != pid.title().casefold():
                return name
    email = bounded(who.email)
    if (email and email == who.email and email.lower() == str(human["email"] or "").lower()
            and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
        return email
    return ""


def sanitize_event(event, hint=None):
    """Rebuild rather than redact: SDK-added context never crosses this boundary."""
    tags = event.get("tags", {})
    source = tags.get("source")
    if source not in {"request", "scheduler"}:
        return None
    clean = {"level": "error", "platform": "python", "tags": {"app": "tico", "source": source}}
    if tags.get("status") in {str(n) for n in range(500, 600)}:
        clean["tags"]["status"] = tags["status"]
    if event.get("environment") in ENVIRONMENTS:
        clean["environment"] = event["environment"]
    if release(event.get("release")):
        clean["release"] = release(event["release"])
    frames = []
    for value in event.get("exception", {}).get("values", []):
        for frame in value.get("stacktrace", {}).get("frames", []):
            if (frame.get("filename") in SOURCE_FILES and type(frame.get("lineno")) is int
                    and 0 < frame["lineno"] < 1_000_000):
                frames.append({"filename": frame["filename"], "lineno": frame["lineno"], "in_app": True})
    clean["exception"] = {"values": [{"type": "SchedulerError" if source == "scheduler" else "RequestError",
                                        "stacktrace": {"frames": frames[-50:]}}]}
    # Preserve only the SDK-generated hexadecimal event identifier.
    if isinstance(event.get("event_id"), str) and re.fullmatch(r"[a-f0-9]{32}", event["event_id"]):
        clean["event_id"] = event["event_id"]
    return clean


class Observability:
    def __init__(self, settings):
        self.settings = settings
        self.client = None

    def start(self):
        dsn = public_dsn(self.settings.sentry_server_dsn)
        if not dsn or self.settings.observability_environment not in ENVIRONMENTS:
            return
        try:
            from sentry_sdk import Client
            self.client = Client(
                dsn=dsn, environment=self.settings.observability_environment,
                release=release(self.settings.release_id) or None,
                default_integrations=False, auto_enabling_integrations=False,
                send_default_pii=False, include_local_variables=False, include_source_context=False,
                max_breadcrumbs=0, traces_sample_rate=0, profiles_sample_rate=0,
                auto_session_tracking=False, send_client_reports=False,
                enable_logs=False, enable_metrics=False, server_name="", before_send=sanitize_event,
            )
        except Exception:
            self.client = None

    def capture(self, source, exc=None, status=None):
        if self.client is None:
            return
        try:
            frames = []
            tb = exc.__traceback__ if exc is not None else None
            while tb:
                try:
                    filename = Path(tb.tb_frame.f_code.co_filename).resolve().relative_to(ROOT).as_posix()
                except ValueError:
                    filename = ""
                if filename in SOURCE_FILES:
                    frames.append({"filename": filename, "lineno": tb.tb_lineno})
                tb = tb.tb_next
            event = {"tags": {"source": source, "status": str(status)},
                     "environment": self.settings.observability_environment,
                     "release": release(self.settings.release_id),
                     "exception": {"values": [{"stacktrace": {"frames": frames}}]}}
            # Sanitize before handing anything to the SDK, and again at its final hook.
            clean = sanitize_event(event)
            if clean:
                self.client.capture_event(clean)
        except Exception:
            pass

    def close(self):
        client, self.client = self.client, None
        if client:
            try:
                client.close(timeout=2)
            except Exception:
                pass
