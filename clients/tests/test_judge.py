"""The judging primitive (`clients/judge.py`): the contract, the two transports, the sets.

No network. The direct transport is exercised through its `opener` seam with a fake HTTP
response; the hub transport through a fake client. The question sets in `questions/` are
loaded for real, because a set that does not load is a broken release.
"""
import io
import json
import unittest
import urllib.error
from pathlib import Path

from clients import judge as J

ROOT = Path(__file__).resolve().parents[2]

QUESTIONS = {
    "bucket": {"type": "choice", "instructions": "Where does it go?",
               "criteria": {"archive": "noise", "reply": "answer it"}},
    "urgency": {"type": "score", "instructions": "How soon?", "criteria": ["never", "today"]},
    "is_ask": {"type": "noul", "instructions": "Is someone asking for something?"},
}
ANSWERS = {
    "bucket": {"type": "choice", "choice": "reply", "confidence": 0.8, "probabilities": {"archive": 0.2, "reply": 0.8}},
    "urgency": {"type": "score", "score": 0.7, "confidence": 0.6, "probabilities": {"0": 0.3, "1": 0.7}},
    "is_ask": {"type": "noul", "noul": 0.9},
}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status, body=b"{}"):
    return urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", status, "err", {}, io.BytesIO(body))


class Contract(unittest.TestCase):
    def test_the_shape_is_refused_before_the_network(self):
        with self.assertRaises(J.JudgeError) as caught:
            J.validate({}, {})
        self.assertEqual(caught.exception.code, "invalid")
        bad = [
            {"q": {"type": "guess", "instructions": "x"}},
            {"q": {"type": "choice", "instructions": "x", "criteria": {"only": "one"}}},
            {"q": {"type": "score", "instructions": "x", "criteria": ["one"]}},
            {"q": {"type": "noul", "instructions": ""}},
            {"q": {"type": "noul", "instructions": "x", "extra": 1}},
            {"q": {"type": "noul", "instructions": "x", "criteria": ["not", "a", "map"]}},
            {"q": {"type": "noul", "instructions": "x", "criteria": {"yes": "y", "no": "n"}}},
            {"q": {"type": "noul", "instructions": {}}},
            {"q": {"type": "noul", "instructions": 42}},
            {"q": {"type": "choice", "instructions": "x", "criteria": {"a": 1, "b": "two"}}},
            {"q": {"type": "score", "instructions": "x", "criteria": ["low", 2]}},
        ]
        for questions in bad:
            with self.assertRaises(J.JudgeError, msg=questions):
                J.validate({"a": 1}, questions)
        with self.assertRaises(J.JudgeError):
            J.validate("x" * (J.MAX_STATE_CHARS + 1), QUESTIONS)
        with self.assertRaises(J.JudgeError):
            J.validate({}, QUESTIONS, label="l" * (J.MAX_LABEL + 1))
        J.validate({"subject": "hi"}, QUESTIONS, label="mail-triage@1")

    def test_answers_are_checked_against_the_questions(self):
        J.check_answers(ANSWERS, QUESTIONS)
        with self.assertRaises(J.JudgeError):
            J.check_answers({**ANSWERS, "bucket": {"choice": "elsewhere"}}, QUESTIONS)
        with self.assertRaises(J.JudgeError):
            J.check_answers({k: v for k, v in ANSWERS.items() if k != "is_ask"}, QUESTIONS)
        for bad in (
            {"noul": 1.5}, {"noul": float("nan")}, {"noul": True},
        ):
            with self.assertRaises(J.JudgeError):
                J.check_answers({**ANSWERS, "is_ask": bad}, QUESTIONS)
        for bad in ({"score": -1, "confidence": 0.9},
                    {"score": 0.5, "confidence": 1.5}):
            with self.assertRaises(J.JudgeError):
                J.check_answers({**ANSWERS, "urgency": bad}, QUESTIONS)
        with self.assertRaises(J.JudgeError):
            J.check_answers({**ANSWERS, "bucket": {"choice": "reply"}}, QUESTIONS)

class ProviderJudge(unittest.TestCase):
    """With no TypeSafe key the judge asks the company's own provider, in that provider's dialect."""

    REPLY = {"bucket": {"probabilities": {"archive": 1, "reply": 3}},
             "urgency": {"probabilities": [0.25, 0.75]}, "is_ask": {"noul": 0.9}}

    def engine(self, provider, wrap):
        seen = []

        def opener(request, timeout):
            seen.append(request)
            return Response(json.dumps(wrap(json.dumps(self.REPLY))).encode())
        return J.llm(provider, "key", "some-model", opener=opener), seen

    def test_each_provider_dialect_is_read_into_the_same_answers(self):
        dialects = {
            "anthropic": lambda text: {"content": [{"type": "text", "text": text}]},
            "openai": lambda text: {"choices": [{"message": {"content": text}}]},
            "google": lambda text: {"candidates": [{"content": {"parts": [{"text": text}]}}]},
        }
        for provider, wrap in dialects.items():
            engine, seen = self.engine(provider, wrap)
            result = engine({"subject": "hi"}, QUESTIONS)
            self.assertEqual(result["answers"]["bucket"]["choice"], "reply", provider)
            self.assertAlmostEqual(result["answers"]["bucket"]["confidence"], 0.75)
            self.assertAlmostEqual(result["answers"]["urgency"]["score"], 0.75)
            self.assertEqual(result["answers"]["is_ask"]["noul"], 0.9)
            self.assertEqual(engine.model, "some-model")
            self.assertTrue(any(value.endswith("key") for value in seen[0].headers.values()), provider)

    def test_an_answer_that_is_not_json_or_misses_a_question_is_a_shape_error(self):
        engine, _ = self.engine("openai", lambda text: {"choices": [{"message": {"content": "sorry"}}]})
        with self.assertRaises(J.JudgeError) as caught:
            engine({}, QUESTIONS)
        self.assertEqual(caught.exception.code, "shape")

    def test_it_needs_a_key_and_a_model(self):
        with self.assertRaises(J.JudgeError):
            J.llm("openai", "", "m")


class Sets(unittest.TestCase):
    def test_every_shipped_set_loads_and_is_listed(self):
        listed = {s["id"]: s for s in J.list_sets()}
        self.assertFalse([s for s in listed.values() if "error" in s], listed)
        shipped = {"mail-triage", "mail-draft-gate", "covered", "slack-route",
                   "listening-card", "listening-item", "reply-intent"}
        for name in shipped:
            chosen = J.load_set(name)
            self.assertEqual(chosen["label"], f"{name}@{chosen['version']}")
            self.assertIn(name, listed)
        self.assertEqual(set(listed) - shipped, set(), "a new set needs its README line and a caller")

if __name__ == "__main__":
    unittest.main()
