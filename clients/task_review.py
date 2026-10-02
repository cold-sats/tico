"""Shared CLI question shorthand and attachment payloads (stdlib only)."""
import base64
import json
from pathlib import Path


def ask_from_args(args):
    if getattr(args, "ask", None):
        return json.loads(Path(args.ask).read_text())
    if getattr(args, "choices", None) is not None:
        labels = [s.strip() for s in args.choices.split(",")]
        if not 1 <= len(labels) <= 6 or any(not s or len(s) > 60 for s in labels) or len(set(labels)) != len(labels):
            raise ValueError("Choices are one to six unique labels, each at most 60 characters")
        return {"questions": [{"id": "verdict", "header": "Review", "question": "What do you think?",
                               "options": [{"label": s} for s in labels], "multi": False, "other": True}], "who": None}
    return None


def attachment(path, name=None):
    path = Path(path)
    data = path.read_bytes()
    body = {"name": name or path.name}
    try:
        body["text"] = data.decode("utf-8")
    except UnicodeDecodeError:
        body["content_base64"] = base64.b64encode(data).decode("ascii")
    return body


ASK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["questions"], "properties": {
    "who": {"type": ["string", "null"], "description": "Person or bot slug highlighted in Needs you; defaults to the requester"},
    "questions": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "header", "question"], "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 40},
            "header": {"type": "string", "maxLength": 30},
            "question": {"type": "string", "minLength": 1, "maxLength": 300},
            "multi": {"type": "boolean", "default": False}, "other": {"type": "boolean", "default": True},
            "options": {"type": "array", "maxItems": 6, "items": {
                "type": "object", "additionalProperties": False, "required": ["label"], "properties": {
                    "label": {"type": "string", "minLength": 1, "maxLength": 60},
                    "description": {"type": "string", "maxLength": 200},
                    "file": {"type": "string", "pattern": "^[^@]+@[1-9][0-9]*$"}}}}}}}}}
