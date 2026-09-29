"""Print one version's section of CHANGELOG.md, the body of its GitHub release."""
import re
import sys
from pathlib import Path


def section(text, version):
    """The lines under `## [version]` (or `## version`) up to the next version heading; empty when absent."""
    lines, out, on = text.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            if on:
                break
            on = re.match(r"## \[?" + re.escape(version.lstrip("v")) + r"\b", line) is not None
            continue
        if on and not re.match(r"\[[^\]]+\]: ", line):
            out.append(line)
    return "\n".join(out).strip()


if __name__ == "__main__":
    notes = section(Path(sys.argv[2] if len(sys.argv) > 2 else "CHANGELOG.md").read_text(), sys.argv[1])
    if not notes:
        sys.exit("CHANGELOG.md has no notes for " + sys.argv[1])
    print(notes)
