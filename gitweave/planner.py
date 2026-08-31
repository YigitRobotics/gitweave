"""
planner.py — turns a flat list of FileInfo into an ordered list of CommitGroup
objects: logical, reviewable chunks (roughly "what a careful dev would have
committed as they built the feature"), not a random shuffle.

Heuristic used (deterministic, no AI/model call needed):

  1. Root-level config / scaffolding files (package.json, requirements.txt,
     Dockerfile, .gitignore, pyproject.toml, go.mod, etc.) -> first commit,
     "chore: project scaffolding".

  2. Remaining files are grouped by their top-level (or second-level for
     monorepo-style src/<module>) directory. Each directory becomes one
     commit, e.g. "feat: add auth module".

  3. Directories are ordered by a rough dependency heuristic: shared/util/lib
     /core-style folders first, then application/feature code, then
     tests, then docs, then everything else. Within that, alphabetical.

  4. Root-level README / docs are pushed to the end ("docs: add README").

This is intentionally simple and transparent — the point is a sensible,
explainable order, not a perfect model of how the code was actually written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import List

from .scan import FileInfo

SCAFFOLD_NAMES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "Pipfile", "Pipfile.lock", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".gitignore", ".dockerignore", ".editorconfig", ".gitattributes",
    "tsconfig.json", "babel.config.js", ".eslintrc", ".eslintrc.json",
    "Makefile", "CMakeLists.txt", "Gemfile", "Gemfile.lock",
}

DOC_NAMES_RE = re.compile(r"(?i)^(README|CHANGELOG|LICENSE|CONTRIBUTING)")

PRIORITY_DIR_HINTS = [
    (0, re.compile(r"(?i)^(shared|common|core|lib|libs|utils?|helpers?|types|models|schema)")),
    (1, re.compile(r"(?i)^(config|configs|settings)")),
    (2, re.compile(r"(?i)^(services?|api|server|backend)")),
    (3, re.compile(r"(?i)^(components?|views?|pages?|ui|frontend|client|app)")),
    (4, re.compile(r"(?i)^(routes?|controllers?)")),
    (8, re.compile(r"(?i)^(tests?|__tests__|spec)")),
    (9, re.compile(r"(?i)^(docs?|examples?)")),
]


@dataclass
class CommitGroup:
    key: str                       # short identifier, e.g. "src/auth"
    message: str                   # commit message
    files: List[FileInfo] = field(default_factory=list)
    order_rank: int = 5            # lower = earlier

    @property
    def total_lines(self) -> int:
        return sum(f.lines for f in self.files)

    @property
    def latest_mtime(self) -> float:
        return max((f.mtime for f in self.files), default=0.0)

    @property
    def earliest_mtime(self) -> float:
        return min((f.mtime for f in self.files), default=0.0)


def _top_component(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if parts else path


def _rank_for_dir(dirname: str) -> int:
    for rank, pattern in PRIORITY_DIR_HINTS:
        if pattern.match(dirname):
            return rank
    return 5


def _commit_message_for(dirname: str, files: List[FileInfo]) -> str:
    if dirname in ("(root)",):
        return "chore: project scaffolding"
    verb = "feat"
    lowered = dirname.lower()
    if any(k in lowered for k in ("test", "spec")):
        verb = "test"
    elif any(k in lowered for k in ("doc", "example")):
        verb = "docs"
    elif any(k in lowered for k in ("config", "setting")):
        verb = "chore"
    return f"{verb}: add {dirname} ({len(files)} file{'s' if len(files) != 1 else ''})"


def plan_commits(files: List[FileInfo], max_files_per_commit: int = 25) -> List[CommitGroup]:
    """Group files into ordered CommitGroup chunks."""
    scaffold: List[FileInfo] = []
    docs: List[FileInfo] = []
    by_dir: dict[str, List[FileInfo]] = {}

    for f in files:
        base = PurePosixPath(f.path).name
        top = _top_component(f.path)
        if PurePosixPath(f.path).parent == PurePosixPath("."):
            if base in SCAFFOLD_NAMES:
                scaffold.append(f)
                continue
            if DOC_NAMES_RE.match(base):
                docs.append(f)
                continue
            # loose root file with no directory - group under "(root)"
            by_dir.setdefault("(root)", []).append(f)
            continue
        by_dir.setdefault(top, []).append(f)

    groups: List[CommitGroup] = []

    if scaffold:
        groups.append(CommitGroup(key="(scaffold)", message="chore: project scaffolding",
                                   files=scaffold, order_rank=-1))

    for dirname, dir_files in by_dir.items():
        rank = _rank_for_dir(dirname) if dirname != "(root)" else 0
        # split large directories into multiple commits so a single commit
        # never dumps hundreds of files at once
        for i in range(0, len(dir_files), max_files_per_commit):
            chunk = dir_files[i:i + max_files_per_commit]
            suffix = "" if i == 0 else f" (part {i // max_files_per_commit + 1})"
            groups.append(CommitGroup(
                key=f"{dirname}{suffix}",
                message=_commit_message_for(dirname, chunk) + suffix,
                files=chunk,
                order_rank=rank,
            ))

    if docs:
        groups.append(CommitGroup(key="(docs)", message="docs: add README / project docs",
                                   files=docs, order_rank=10))

    groups.sort(key=lambda g: (g.order_rank, g.key))
    return groups
