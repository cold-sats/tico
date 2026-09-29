#!/usr/bin/env python3
"""Publish desktop app bundles: upload them to `releases/app/<version>/` in the storage bucket
and rewrite `releases/app/latest.json`, the manifest the app's updater and the hub's download
routes read (backend/downloads.py).

    app_release.py --version 2.1.0 --bucket <bucket> --base https://runner.acme.example DIR [DIR...]

Each DIR is scanned for what `tauri build` produced on one OS:
  *.app.tar.gz (+ .sig)   macOS update archive         -> platforms darwin-aarch64 / darwin-x86_64
  *.dmg                   macOS installer              -> installers.mac
  *-setup.exe (+ .sig)    Windows installer            -> platforms windows-x86_64, installers.windows
  *.AppImage (+ .sig)     Linux                        -> platforms linux-x86_64, installers.linux
  *.deb                   uploaded beside the AppImage -> installers.linux_deb
A platform that is not in any DIR keeps its entry from the manifest already published, so one
OS can be released on its own. `--dry-run` prints the manifest and uploads nothing.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "releases/app/"


def classify(directory):
    found = {"platforms": {}, "installers": {}, "files": []}
    for path in sorted(Path(directory).rglob("*")):
        if not path.is_file() or path.suffix == ".sig":
            continue
        name = path.name
        sig = path.with_name(name + ".sig")
        signature = sig.read_text().strip() if sig.exists() else None
        entry = {"file": name, "bytes": path.stat().st_size}
        if name.endswith(".app.tar.gz"):
            for target in ("darwin-aarch64", "darwin-x86_64"):
                if "universal" in name or target.split("-")[1] in name or "aarch64" not in name and "x86_64" not in name:
                    found["platforms"][target] = {**entry, "signature": signature}
        elif name.endswith(".dmg"):
            found["installers"]["mac"] = entry
        elif name.endswith("-setup.exe"):
            found["platforms"]["windows-x86_64"] = {**entry, "signature": signature}
            found["installers"]["windows"] = entry
        elif name.endswith(".msi"):
            found["installers"].setdefault("windows", entry)
        elif name.endswith(".AppImage"):
            found["platforms"]["linux-x86_64"] = {**entry, "signature": signature}
            found["installers"]["linux"] = entry
        elif name.endswith(".deb"):
            found["installers"]["linux_deb"] = entry
        else:
            continue
        found["files"].append(path)
        if signature is not None:
            found["files"].append(sig)
    return found


def manifest(version, base, scans, previous, notes="", signed=False, notarized=False):
    platforms = dict((previous or {}).get("platforms") or {})
    installers = dict((previous or {}).get("installers") or {})
    for scan in scans:
        for target, entry in scan["platforms"].items():
            if not entry.get("signature"):
                raise SystemExit(f"{entry['file']} has no .sig beside it; build with TAURI_SIGNING_PRIVATE_KEY set")
            platforms[target] = {"signature": entry["signature"], "url": f"{base}/download/file/{version}/{entry['file']}"}
        for os_name, entry in scan["installers"].items():
            installers[os_name] = {"file": entry["file"], "bytes": entry["bytes"],
                                   "signed": signed, "notarized": notarized and os_name == "mac"}
    return {"version": version, "notes": notes, "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "platforms": platforms, "installers": installers}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dirs", nargs="+")
    parser.add_argument("--version", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--base", required=True, help="the hub URL the app reaches without a browser session")
    parser.add_argument("--notes", default="")
    parser.add_argument("--signed", action="store_true")
    parser.add_argument("--notarized", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    scans = [classify(d) for d in args.dirs]
    if not any(s["files"] for s in scans):
        raise SystemExit("no bundles found in " + ", ".join(args.dirs))
    previous = None
    s3 = None
    if not args.dry_run:
        import boto3
        s3 = boto3.client("s3")
        try:
            previous = json.loads(s3.get_object(Bucket=args.bucket, Key=PREFIX + "latest.json")["Body"].read())
        except Exception:
            previous = None
    value = manifest(args.version, args.base.rstrip("/"), scans, previous, args.notes, args.signed, args.notarized)
    print(json.dumps(value, indent=2))
    if args.dry_run:
        return 0
    for scan in scans:
        for path in scan["files"]:
            key = f"{PREFIX}{args.version}/{path.name}"
            print("upload", key, file=sys.stderr)
            s3.upload_file(str(path), args.bucket, key)
    s3.put_object(Bucket=args.bucket, Key=PREFIX + "latest.json", Body=json.dumps(value).encode(),
                  ContentType="application/json", CacheControl="no-cache")
    print("published", args.version, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
