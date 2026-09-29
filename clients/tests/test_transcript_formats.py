"""Every import format lands as the same segment list (clients/transcript_formats.py)."""
import json
import unittest

from clients import transcript_formats as TF

VTT = """WEBVTT

NOTE made by a call recorder

1
00:00:05.000 --> 00:00:08.500
<v Ana>Let's raise the annual plan.</v>

2
00:01:10.250 --> 00:01:12.000
Ben: Ten percent, then.
Sounds fine.
"""

SRT = """1
00:00:05,000 --> 00:00:08,500
Ana: Let's raise the annual plan.

2
00:01:10,250 --> 00:01:12,000
Ten percent, then.
"""


class Formats(unittest.TestCase):
    def test_plain_text_takes_times_and_speakers_from_each_line(self):
        got = TF.parse("[00:05] Ana: Let's raise it.\n[1:01:10] Ben: Ten percent.\n\nNo speaker line\nhttps://x.example/a: not a name")
        self.assertEqual([(s["speaker"], s["start_ms"]) for s in got],
                         [("Ana", 5000), ("Ben", 3670000), ("", 3670000), ("", 3670000)])
        self.assertEqual(got[3]["text"], "https://x.example/a: not a name")

    def test_vtt_reads_voice_tags_prefixes_and_multiline_cues(self):
        got = TF.parse(VTT)
        self.assertEqual(got, [
            {"speaker": "Ana", "start_ms": 5000, "end_ms": 8500, "text": "Let's raise the annual plan."},
            {"speaker": "Ben", "start_ms": 70250, "end_ms": 72000, "text": "Ten percent, then. Sounds fine."}])

    def test_srt_uses_commas_and_an_optional_prefix(self):
        got = TF.parse(SRT)
        self.assertEqual([(s["speaker"], s["start_ms"], s["end_ms"]) for s in got],
                         [("Ana", 5000, 8500), ("", 70250, 72000)])

    def test_json_segments_in_seconds_or_milliseconds_or_clock_strings(self):
        rows = [{"speaker": "Ana", "start": 5, "end": 8.5, "text": "Hello."},
                {"speaker_name": "Ben", "start_ms": 9000, "end_ms": 10000, "text": "Hi."},
                {"speaker": {"name": "Dana"}, "start": "1:02", "text": "Bye."},
                {"speaker": "Nobody", "start": 1, "text": "  "}]
        for data in (rows, json.dumps(rows), {"segments": rows}, json.dumps({"utterances": rows})):
            got = TF.parse(data)
            self.assertEqual([(s["speaker"], s["start_ms"], s["end_ms"]) for s in got],
                             [("Ana", 5000, 8500), ("Ben", 9000, 10000), ("Dana", 62000, 62000)])

    def test_auto_detects_and_an_explicit_format_wins(self):
        self.assertEqual({TF.detect(VTT), TF.detect(SRT), TF.detect('[{"text": "x"}]'), TF.detect("Ana: hi")},
                         {"vtt", "srt", "json", "text"})
        self.assertEqual(TF.parse("[not json] but text", "text")[0]["text"], "[not json] but text")
        self.assertEqual(TF.parse("﻿Ana: hi")[0]["speaker"], "Ana")

    def test_a_transcript_with_nothing_in_it_or_a_bad_shape_is_refused(self):
        for data, fmt in (("", "auto"), ("  \n\n", "text"), ("[]", "auto"), ("{}", "json"), ("[1, 2]", "json"),
                          ('[{"start": -1, "text": "x"}]', "json"), ('[{"start": "soon", "text": "x"}]', "json"),
                          ("1\nno time here\n", "srt"), ("[{oops", "json"), ("x", "docx")):
            with self.assertRaises(TF.TranscriptFormatError, msg=repr(data)):
                TF.parse(data, fmt)

    def test_end_never_precedes_start_and_duration_is_the_last_end(self):
        got = TF.parse([{"start": 10, "end": 4, "text": "Backwards."}, {"start": 12, "text": "Open ended."}])
        self.assertEqual([(s["start_ms"], s["end_ms"]) for s in got], [(10000, 10000), (12000, 12000)])
        self.assertEqual(TF.duration_ms(got), 12000)


if __name__ == "__main__":
    unittest.main()
