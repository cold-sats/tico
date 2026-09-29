"""SQLite migration for durable meeting sources."""
MEETING_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
 recorded_by TEXT, uploaded_by TEXT, metadata_json TEXT NOT NULL,
 transcript_original TEXT NOT NULL DEFAULT '', transcript_readable TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL DEFAULT '',
 created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meeting_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
 content_hash TEXT NOT NULL, metadata_json TEXT NOT NULL, transcript_original TEXT NOT NULL,
 transcript_readable TEXT NOT NULL, notes TEXT NOT NULL, created TEXT NOT NULL,
 UNIQUE(meeting_id, content_hash)
);
CREATE TABLE IF NOT EXISTS meeting_deliveries (
 meeting_id TEXT PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
 requested_by TEXT NOT NULL, sender_name TEXT NOT NULL, destination TEXT NOT NULL,
 instructions TEXT NOT NULL, attachments_json TEXT NOT NULL DEFAULT '[]',
 status TEXT NOT NULL DEFAULT 'pending', task_id TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 requested_at TEXT NOT NULL, delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS task_delegations (
 task_id TEXT NOT NULL REFERENCES tasks(id), delegate TEXT NOT NULL, requested_by TEXT NOT NULL,
 message_id TEXT PRIMARY KEY REFERENCES messages(id), expires TEXT NOT NULL
);
"""

# The three sections a meeting fills up, plus the two read-only context lists
# Items live beside
# the meeting rather than inside its notes so they can be edited and pushed for as long as the
# meeting exists. `decision` and `question` rows are context and are never pushed.
MEETING_ITEMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS meeting_items (
 id TEXT PRIMARY KEY,
 meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
 section TEXT NOT NULL CHECK (section IN ('doc','task','feature','decision','question')),  -- the last two: legacy rows, never listed
 text TEXT NOT NULL,
 detail_json TEXT NOT NULL DEFAULT '{}',
 quote TEXT NOT NULL DEFAULT '',
 at_ms INTEGER,
 status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','pushed','dismissed')),
 created_by TEXT NOT NULL,
 updated_by TEXT,
 pushed_at TEXT,
 result_ref TEXT,
 created TEXT NOT NULL,
 updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS meeting_items_meeting ON meeting_items(meeting_id, section, created);
"""

# What the brain has already thought about one meeting (`backend/meeting_brain.py`). It lives in a
# table rather than in memory so the cadence survives a restart and `hub sql` can answer "is the
# brain keeping up?". `last_turn_index` is how far into `meta.turns` the last think read;
# `final_at` is the one think that runs right after Stop; `error_at` backs a failing meeting off.
MEETING_BRAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS meeting_brain (
 meeting_id TEXT PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
 last_think_at TEXT,
 last_turn_index INTEGER NOT NULL DEFAULT 0,
 runs INTEGER NOT NULL DEFAULT 0,
 last_error TEXT,
 error_at TEXT,
 final_at TEXT,
 updated TEXT NOT NULL
);
"""

# What people say about a meeting, beside it. Anyone who can open the meeting can read the thread
# and add to it (the recorder's own `note` on the record stays theirs); a comment is never edited,
# only added, so the thread reads as it happened. Visible exactly where its meeting is.
MEETING_COMMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS meeting_comments (
 id TEXT PRIMARY KEY,
 meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
 author TEXT NOT NULL,
 text TEXT NOT NULL,
 at_ms INTEGER,
 created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS meeting_comments_meeting ON meeting_comments(meeting_id, created);
"""

# An outside activity may point at a recording already captured in Tico. Keep each transcript
# revision independently: a provider correction must not silently rewrite a person's sent work.
RECORDING_SOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS recording_source_refs (
 source TEXT NOT NULL, resource_type TEXT NOT NULL, external_id TEXT NOT NULL,
 meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
 created TEXT NOT NULL,
 PRIMARY KEY(source,resource_type,external_id)
);
CREATE INDEX IF NOT EXISTS recording_source_meeting ON recording_source_refs(meeting_id);
CREATE TABLE IF NOT EXISTS recording_transcripts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
 source TEXT NOT NULL, resource_type TEXT NOT NULL, external_id TEXT NOT NULL,
 transcript_index INTEGER NOT NULL DEFAULT 0,
 content_hash TEXT NOT NULL, source_updated_at TEXT NOT NULL,
 turns_json TEXT NOT NULL, transcript_text TEXT NOT NULL, summary_text TEXT NOT NULL DEFAULT '',
 imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS recording_transcripts_meeting ON recording_transcripts(meeting_id,id DESC);
"""
