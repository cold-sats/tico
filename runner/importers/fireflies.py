"""Fireflies.ai through its GraphQL API (https://docs.fireflies.ai). One API key per person.

The key stays in secrets/fireflies.env on this computer. `mine: true` keeps each key to its own
holder's transcripts, so the meeting is filed for the person who made the key.
"""

import hashlib
from datetime import timedelta

from .base import (Importer, Item, ProviderError, Scope, email_of, https_url, moment, people, text,
                   turns_of)

ENDPOINT = "https://api.fireflies.ai/graphql"
PAGE = 25          # the API allows 50; details are fetched one by one, so keep a page small
PAGES = 40

LIST = """query Meetings($from: DateTime, $to: DateTime, $limit: Int, $skip: Int) {
  transcripts(mine: true, fromDate: $from, toDate: $to, limit: $limit, skip: $skip) {
    id title date duration
  }
}"""
DETAIL = """query Meeting($id: String!) {
  transcript(id: $id) {
    id title date duration organizer_email participants transcript_url audio_url meeting_link
    meeting_attendees { displayName email name }
    summary { overview short_summary action_items shorthand_bullet }
    sentences { speaker_name text start_time end_time }
  }
}"""
WHO = "query { user { email name } }"


class Fireflies(Importer):
    source = "fireflies"
    name = "Fireflies"
    prefix = "FIREFLIES"
    secret_file = "fireflies.env"
    required = ("FIREFLIES_API_KEY",)
    interval = 900          # free plans allow 50 calls a day, Pro 500, Business 60 a minute
    pace = 1.1

    def graphql(self, key, query, variables=None):
        answer = self.send("POST", ENDPOINT, headers={"Authorization": "Bearer " + key},
                           body={"query": query, "variables": variables or {}})
        if not isinstance(answer, dict):
            raise ProviderError("bad_response", "Fireflies returned an unreadable response")
        errors = answer.get("errors")
        if errors:
            codes = {str((e.get("extensions") or {}).get("code") or e.get("code") or "")
                     for e in errors if isinstance(e, dict)}
            if codes & {"auth_failed", "invalid_api_key"}:
                raise ProviderError("auth_failed", "Fireflies refused the API key")
            if "too_many_requests" in codes:
                raise ProviderError("rate_limited", "Fireflies rate limit reached; retrying later")
            if "require_elevated_privilege" in codes:
                raise ProviderError("forbidden", "Fireflies denied access to that transcript")
            raise ProviderError("provider_error", "Fireflies reported an error")
        data = answer.get("data")
        if not isinstance(data, dict):
            raise ProviderError("bad_response", "Fireflies returned no data")
        return data

    def scopes(self):
        keys = [k.strip() for k in self.env()["FIREFLIES_API_KEY"].split(",") if k.strip()]
        out = []
        for key in keys[:50]:
            who = (self.graphql(key, WHO).get("user") or {})
            email = email_of(who.get("email"))
            if not email:
                raise ProviderError("bad_response", "Fireflies did not say whose key this is")
            # The cursor is named by a fingerprint, never by the key.
            out.append(Scope(hashlib.sha256(key.encode()).hexdigest()[:10], email, {"key": key, "email": email}))
        return out

    def fetch(self, scope, since, until):
        key, skip, listed = scope.data["key"], 0, []
        for _ in range(PAGES):
            rows = self.graphql(key, LIST, {
                "from": since.isoformat().replace("+00:00", "Z"), "to": until.isoformat().replace("+00:00", "Z"),
                "limit": PAGE, "skip": skip}).get("transcripts")
            if not isinstance(rows, list):
                raise ProviderError("bad_response", "Fireflies returned no transcript list")
            listed.extend(r for r in rows if isinstance(r, dict) and r.get("id"))
            if len(rows) < PAGE:
                break
            skip += len(rows)
        else:
            raise ProviderError("provider_error", "Fireflies returned more transcripts than one pass reads; use a shorter --backfill-days")
        for row in sorted(listed, key=lambda r: (r.get("date") or 0, str(r["id"]))):
            started = moment(row.get("date"), since)
            ident = str(row["id"])
            revision = "%s|%s|%s" % (row.get("date"), row.get("duration"), row.get("title"))
            if self.known(scope, ident, revision):
                continue
            item = self.item(scope, ident, started, revision)
            if item:
                yield item

    def item(self, scope, ident, started, revision):
        detail = self.graphql(scope.data["key"], DETAIL, {"id": ident}).get("transcript")
        if not isinstance(detail, dict):
            raise ProviderError("bad_response", "Fireflies returned no transcript")
        sentences = detail.get("sentences")
        rows = [(s.get("speaker_name"), round(float(s.get("start_time") or 0) * 1000),
                 round(float(s.get("end_time") or 0) * 1000), s.get("text"))
                for s in sentences or [] if isinstance(s, dict)]
        turns = turns_of(rows)
        if not turns:
            # Still being transcribed, or a silent recording: look again while it is young.
            self.hold_at(started)
            return None
        summary = detail.get("summary") if isinstance(detail.get("summary"), dict) else {}
        notes = self.notes(summary)
        attendees = [(a.get("displayName") or a.get("name") or "", a.get("email"))
                     for a in detail.get("meeting_attendees") or [] if isinstance(a, dict)]
        who = people(*attendees, *(detail.get("participants") or []), scope.data["email"])
        last = turns[-1]["end_ms"] / 1000
        minutes = detail.get("duration")
        body = {"title": text(detail.get("title"), 300) or "Fireflies meeting", "started_at": started.isoformat(),
                "participants": who, "transcript": turns, "notes": notes,
                "media_url": https_url(detail.get("transcript_url")),
                "context": {k: v for k, v in {"meeting_url": https_url(detail.get("meeting_link")),
                                              "audio_url": https_url(detail.get("audio_url")),
                                              "fireflies_organizer": email_of(detail.get("organizer_email"))}.items() if v}}
        if isinstance(minutes, (int, float)) and last <= minutes * 60 <= last + 7200:
            body["duration_seconds"] = minutes * 60      # the schema says minutes; distrust anything implausible
        return Item(ident, scope.data["email"], body, started, revision)

    @staticmethod
    def notes(summary):
        parts = []
        if text(summary.get("overview") or summary.get("short_summary"), 200_000):
            parts.append(str(summary.get("overview") or summary.get("short_summary")).strip())
        for title, key in (("Action items", "action_items"), ("Outline", "shorthand_bullet")):
            value = summary.get(key)
            if isinstance(value, list):
                value = "\n".join("- " + text(v, 1000) for v in value if text(v))
            if text(value):
                parts.append("## " + title + "\n" + str(value).strip())
        return "\n\n".join(parts)[:200_000]
