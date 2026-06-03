import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Finding:
    severity: str
    file: str
    line: int
    image: str
    message: str


@dataclass
class RuleResult:
    rule: str
    passed: bool = True
    findings: list[Finding] = field(default_factory=list)


def get_tracked_files(repo_root: Path) -> Optional[set[Path]]:
    """Return git-tracked files as resolved Paths, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        files = set()
        for rel in result.stdout.split("\0"):
            if rel:
                files.add((repo_root / rel).resolve())
        return files
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
