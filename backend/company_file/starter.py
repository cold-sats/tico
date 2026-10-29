"""A normalized starter plan shared by setup, Hosted and the installed app.

Transport contains plan data only, never chat, browser state or authority. The
compressed value travels beside the install's secrets, not in command arguments.
"""
import base64
import binascii
import gzip
import json
import sys
import zlib

from . import draft as D
from .keys import scrub_all
from .yamlfile import from_yaml, to_yaml

MAX_BYTES = 524288          # a 300-seat plan, normalized, with room (about 320 KB at 300 bots and 325 goals, every text at full length)
# A packed plan HQ carries to the server as a file (the hosted plan bucket): gzip+base64 of MAX_BYTES is about 700 KB.
MAX_PACKED = 1048576
# A packed plan carried in TICO_COMPANY_FILE_B64 (self-install, and AWS without --plan-bucket): Parameter Store's 8 KB
# with the install settings, and far below Linux's 128 KB limit on one environment string.
ENV_PACKED = 7168
# The in-app path for a plan setup cannot carry: ui/app/welcome.js onbCompanyFileHTML (keep the labels in step).
IMPORT_IN_APP = ("Run setup again without --company-file; then, on the first Welcome step in Tico, under \"Already chose "
                 "your team?\", choose the file in \"Company YAML file\" and click \"Use this team\".")


def load(source):
    if isinstance(source, str):
        import yaml
        draft = from_yaml(source)
        document = yaml.safe_load(source)
    elif isinstance(source, dict):
        document = source
        draft = D.check(scrub_all({k: v for k, v in source.items() if k != "models"})[0])
    else:
        raise D.DraftError("the starter plan must be a company file")
    if any(b["existing"] for b in draft["bots"]):
        raise D.DraftError("Connect existing agents in Tico after importing the starter team")
    # A coworker comes along only as the person who holds a seat; they join the team in Tico, never by import.
    holders = {b.get("person") for b in draft["bots"]}
    if any(not p["owner"] and p["id"] not in holders for p in draft["people"]):
        raise D.DraftError("This import supports the owner, AI employees and the people who hold seats; add other coworkers in Tico first")
    if draft["rules"]["mode"] != "defaults":
        raise D.DraftError("Review custom rules in Tico; this starter import uses the default rules")
    # Match the app's setup fields before a cloud installer creates anything.
    if (not draft["company"]["name"].strip() or len(draft["company"]["name"]) > 100
            or len(draft["company"]["about"]) > 2000
            or any(len(person["name"]) > 100 for person in draft["people"])):
        raise D.DraftError("Use a company/owner name up to 100 characters and a company description up to 2000 characters")
    saved = D.plan_of(draft)
    if "models" in document:
        models = document["models"]
        if not isinstance(models, dict) or models.get("source") not in ("gateway", "own"):
            raise D.DraftError("the company file's model choices are not supported")
        saved["models"] = scrub_all(models)[0]
    try:
        raw = canonical(saved)
    except (ValueError, TypeError, RecursionError):
        raise D.DraftError("the company file contains unsupported values") from None
    if len(raw.encode()) > MAX_BYTES:
        raise D.DraftError("the company file is too large")
    return saved


def canonical(saved):
    return json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def file_text(source):
    """A scrubbed company file for a provisioning worker's private local file."""
    saved = load(source)
    text = to_yaml(D.plan_of(saved))
    if "models" in saved:
        text += "models: " + canonical(saved["models"]) + "\n"
    return text


TOO_LARGE = f"This company file is too large for automatic setup. {IMPORT_IN_APP}"


def pack(source, limit=ENV_PACKED):
    data = base64.b64encode(gzip.compress(canonical(load(source)).encode(), mtime=0)).decode("ascii")
    if len(data) > limit:
        raise D.DraftError(TOO_LARGE)
    return data


def unpack(data):
    try:
        if not isinstance(data, str) or len(data) > MAX_PACKED:
            raise ValueError()
        compressed = base64.b64decode(data, validate=True)
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = decoder.decompress(compressed, MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError()
        return load(json.loads(raw))
    except (ValueError, TypeError, binascii.Error, zlib.error, RecursionError):
        raise D.DraftError("the saved starter plan is invalid or too large; provide the company file again") from None


def main(argv):
    """`python -m backend.company_file.starter pack < tico.company.yaml`: the packed plan, on one line. scripts/install.sh
    runs it in the server image, so an installer packs a file with the code that reads it and needs no Python of its own.
    A file Tico cannot import gives its reason on stderr and exit 2; nothing is printed on stdout then."""
    if argv != ["pack"]:
        print("usage: python -m backend.company_file.starter pack < tico.company.yaml", file=sys.stderr)
        return 2
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        print("the company file is too large", file=sys.stderr)
        return 2
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        print("Cannot read --company-file; use a readable UTF-8 company YAML file", file=sys.stderr)
        return 2
    try:
        packed = pack(text, MAX_PACKED)
    except D.DraftError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(packed)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
