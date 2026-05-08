#!/usr/bin/env python3
"""Check that all container image references appear in CSV relatedImages."""

import re
import glob
import yaml
from pathlib import Path
from dataclasses import dataclass, field

IMAGE_REF_PATTERN = re.compile(
    r'(?:image:\s*|"image":\s*"|FROM\s+)'
    r'((?:[\w.\-]+(?:\.[\w.\-]+)+(?::\d+)?/)?[\w.\-]+/[\w.\-]+(?:[:@][\w.\-:]+)?)'
)

DIGEST_PATTERN = re.compile(r'@sha256:[a-f0-9]{64}')
TAG_PATTERN = re.compile(r':[\w][\w.\-]*$')


@dataclass
class Finding:
    severity: str  # blocker, warning, info
    file: str
    line: int
    image: str
    message: str


@dataclass
class RuleResult:
    rule: str = "csv-relatedimages-complete"
    passed: bool = True
    findings: list = field(default_factory=list)


def find_csv_files(repo_root: Path) -> list[Path]:
    """Find ClusterServiceVersion YAML files."""
    patterns = [
        "**/clusterserviceversion.yaml",
        "**/csv.yaml",
        "**/*.clusterserviceversion.yaml",
        "**/manifests/*.yaml",
    ]
    csvs = []
    for pattern in patterns:
        for p in repo_root.glob(pattern):
            try:
                content = p.read_text()
                if "relatedImages" in content or "ClusterServiceVersion" in content:
                    csvs.append(p)
            except (OSError, UnicodeDecodeError):
                continue
    return csvs


def extract_related_images(csv_path: Path) -> set[str]:
    """Extract image refs from CSV relatedImages section."""
    images = set()
    try:
        with open(csv_path) as f:
            docs = list(yaml.safe_load_all(f))
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            spec = doc.get("spec", {})
            for entry in spec.get("relatedImages", []):
                img = entry.get("image", "")
                if img:
                    images.add(normalize_image(img))
    except Exception:
        pass
    return images


def normalize_image(ref: str) -> str:
    """Normalize an image reference for comparison (strip tag/digest)."""
    ref = ref.strip().strip('"').strip("'")
    ref = DIGEST_PATTERN.sub("", ref)
    ref = TAG_PATTERN.sub("", ref)
    return ref


def scan_file_for_images(filepath: Path) -> list[tuple[int, str]]:
    """Scan a file for container image references, returning (line_number, image)."""
    results = []
    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return results

    for i, line in enumerate(lines, 1):
        for match in IMAGE_REF_PATTERN.finditer(line):
            img = match.group(1).strip().strip('"').strip("'")
            if "/" in img and not img.startswith("#"):
                results.append((i, img))
    return results


def scan_source_files(repo_root: Path) -> list[tuple[Path, int, str]]:
    """Scan all relevant source files for image references."""
    extensions = {".go", ".py", ".yaml", ".yml", ".json", ".toml", ".cfg"}
    skip_dirs = {".git", "vendor", "node_modules", "__pycache__", ".tox"}
    results = []

    for filepath in repo_root.rglob("*"):
        if any(d in filepath.parts for d in skip_dirs):
            continue
        if filepath.suffix not in extensions:
            continue
        for line_num, image in scan_file_for_images(filepath):
            results.append((filepath, line_num, image))

    return results


def run(repo_root: str) -> RuleResult:
    """Run the csv-relatedimages-complete rule."""
    root = Path(repo_root)
    result = RuleResult()

    csv_files = find_csv_files(root)
    if not csv_files:
        result.findings.append(Finding(
            severity="info",
            file="",
            line=0,
            image="",
            message="No ClusterServiceVersion found — skipping relatedImages check.",
        ))
        return result

    related_images = set()
    for csv_path in csv_files:
        related_images.update(extract_related_images(csv_path))

    if not related_images:
        result.findings.append(Finding(
            severity="warning",
            file=str(csv_files[0].relative_to(root)),
            line=0,
            image="",
            message="CSV found but relatedImages section is empty.",
        ))

    source_refs = scan_source_files(root)

    for filepath, line_num, image in source_refs:
        normalized = normalize_image(image)
        if normalized and normalized not in related_images:
            result.passed = False
            result.findings.append(Finding(
                severity="blocker",
                file=str(filepath.relative_to(root)),
                line=line_num,
                image=image,
                message=f"Image '{image}' not found in CSV relatedImages.",
            ))

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
