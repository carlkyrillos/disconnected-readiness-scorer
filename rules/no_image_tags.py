#!/usr/bin/env python3
"""Enforce digest-only image references — reject mutable tags."""

import re
from pathlib import Path
from dataclasses import dataclass, field

IMAGE_REF_PATTERN = re.compile(
    r'((?:[\w.\-]+(?:\.[\w.\-]+)+(?::\d+)?/)?[\w.\-]+/[\w.\-]+)([:@][\w.\-:]+)'
)

PRODUCTION_DIRS = {"manifests", "deploy", "config", "bundle", "helm", "chart", "kustomize"}
TEST_DIRS = {"test", "tests", "e2e", "hack", "ci", "testdata"}


@dataclass
class Finding:
    severity: str
    file: str
    line: int
    image: str
    message: str


@dataclass
class RuleResult:
    rule: str = "no-image-tags"
    passed: bool = True
    findings: list = field(default_factory=list)


def is_test_file(filepath: Path) -> bool:
    return any(d in filepath.parts for d in TEST_DIRS)


def is_production_file(filepath: Path) -> bool:
    return any(d in filepath.parts for d in PRODUCTION_DIRS)


def scan_file(filepath: Path, root: Path) -> list[Finding]:
    findings = []
    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return findings

    for i, line in enumerate(lines, 1):
        if line.strip().startswith("#") or line.strip().startswith("//"):
            continue

        for match in IMAGE_REF_PATTERN.finditer(line):
            repo_part = match.group(1)
            ref_part = match.group(2)

            if "/" not in repo_part:
                continue
            if ref_part.startswith("@sha256:"):
                continue

            relative = str(filepath.relative_to(root))
            severity = "blocker" if is_production_file(filepath) else "warning"

            findings.append(Finding(
                severity=severity,
                file=relative,
                line=i,
                image=f"{repo_part}{ref_part}",
                message=f"Image uses tag '{ref_part}' instead of digest. "
                        f"Tags cannot be reliably mirrored.",
            ))

    return findings


def run(repo_root: str) -> RuleResult:
    root = Path(repo_root)
    result = RuleResult()
    skip_dirs = {".git", "vendor", "node_modules", "__pycache__"}
    extensions = {".go", ".py", ".yaml", ".yml", ".json", ".toml"}

    for filepath in root.rglob("*"):
        if any(d in filepath.parts for d in skip_dirs):
            continue
        if filepath.suffix not in extensions and filepath.name != "Dockerfile":
            continue

        for finding in scan_file(filepath, root):
            result.findings.append(finding)
            if finding.severity == "blocker":
                result.passed = False

    return result


if __name__ == "__main__":
    import sys
    import json

    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    r = run(repo)
    print(json.dumps({
        "rule": r.rule,
        "passed": r.passed,
        "findings": [
            {"severity": f.severity, "file": f.file, "line": f.line,
             "image": f.image, "message": f.message}
            for f in r.findings
        ],
    }, indent=2))
