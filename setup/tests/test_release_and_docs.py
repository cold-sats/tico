"""The release workflow and the docs that describe the install: lint the workflow, and no dead internal links."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


@pytest.mark.skipif(not shutil.which("actionlint"), reason="actionlint not installed")
def test_workflows_pass_actionlint():
    # Every workflow's syntax and expressions; the shell inside run: blocks only for the release and docker workflows.
    r = subprocess.run(["actionlint", "-shellcheck=", *map(str, WORKFLOWS)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    strict = [str(ROOT / ".github/workflows" / n) for n in ("release.yml", "docker.yml")]
    r = subprocess.run(["actionlint", *strict], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_release_publishes_the_installer_its_bundle_and_checksums():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    doc = yaml.safe_load(text)
    assert doc[True]["push"]["tags"]  # YAML reads the key `on` as a boolean
    for asset in ("dist/install/install.sh", "tico-bundle-$GITHUB_REF_NAME.tar.gz", "dist/install/SHA256SUMS"):
        assert asset in text
    assert "build_install_bundle.py --version \"$GITHUB_REF_NAME\"" in text
    assert text.index("Wait for the images") < text.index("gh release create")  # never a release whose images are missing


def markdown_files():
    files = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md", ROOT / "CHANGELOG.md"]
    for d in ("docs", "infra", "setup", "connectors", "runner", "ui"):
        files += [p for p in (ROOT / d).rglob("*.md") if "node_modules" not in p.parts and "history" not in p.parts]
    return sorted(set(p for p in files if p.exists()))


def slug(heading: str) -> str:
    s = re.sub(r"[`*_]", "", heading.strip().lower())
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    out, seen, fenced = set(), {}, False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            fenced = not fenced
        out.update(re.findall(r'<a id="([^"]+)"></a>', line) if not fenced else [])   # an explicit anchor keeps an old link alive
        m = None if fenced else re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
    return out


LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")


def internal_links(path: Path):
    fenced = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if fenced:
            continue
        for target in LINK.findall(re.sub(r"`[^`]*`", "", line)):
            if not re.match(r"^([a-z]+:|#$|mailto:)", target) or target.startswith("#"):
                yield target


def test_no_dead_internal_links_in_the_docs():
    dead = []
    for md in markdown_files():
        for target in internal_links(md):
            file_part, _, frag = target.partition("#")
            dest = md if not file_part else (md.parent / file_part).resolve()
            if not dest.exists():
                dead.append(f"{md.relative_to(ROOT)}: {target} (no such file)")
            elif frag and dest.suffix == ".md" and frag not in anchors(dest):
                dead.append(f"{md.relative_to(ROOT)}: {target} (no such heading)")
    assert not dead, "\n".join(dead)

