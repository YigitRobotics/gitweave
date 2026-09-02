"""
gitops.py — executes a commit plan against a real git repository.

Safety notes:
  - Dry-run by default. Callers must pass execute=True to actually touch git.
  - Refuses to run on a repo with uncommitted changes it didn't create
    (checked via `git status --porcelain` before starting) unless --force.
  - Sets both GIT_AUTHOR_DATE and GIT_COMMITTER_DATE so `git log` shows a
    consistent, honest date for each commit.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .timeline import TimedCommit


class GitOpsError(RuntimeError):
    pass


@dataclass
class CommitResult:
    key: str
    message: str
    sha: str
    date_iso: str
    file_count: int
    skipped: bool = False


def _run_git(repo: Path, args: List[str], env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, env=full_env
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "(no output from git)"
        raise GitOpsError(f"git {' '.join(args)} failed: {detail}")
    return result


def ensure_repo(repo: Path) -> None:
    if not (repo / ".git").exists():
        raise GitOpsError(
            f"{repo} is not a git repository yet. Run `git init` first "
            f"(gitweave organizes commits, it doesn't create the repo)."
        )


def check_clean_baseline(repo: Path) -> None:
    """Refuse to run if there's already a mix of staged/unstaged changes that
    aren't part of what gitweave is about to organize would be ambiguous.
    In practice gitweave expects an empty repo (just `git init`) with all
    project files present but untracked."""
    result = _run_git(repo, ["status", "--porcelain"])
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    non_untracked = [l for l in lines if not l.startswith("??")]
    if non_untracked:
        raise GitOpsError(
            "Repo has staged or tracked changes already (not just untracked "
            "files). Commit or stash those first, or use --force to proceed anyway."
        )


def apply_plan(
    repo: Path,
    timed_commits: List[TimedCommit],
    author_name: str,
    author_email: str,
    execute: bool = False,
    push: bool = False,
    remote: str = "origin",
    branch: str | None = None,
) -> List[CommitResult]:
    ensure_repo(repo)
    results: List[CommitResult] = []

    for tc in timed_commits:
        iso = tc.timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
        rel_paths = [f.path for f in tc.group.files]

        if not execute:
            results.append(CommitResult(
                key=tc.group.key, message=tc.group.message, sha="(dry-run)",
                date_iso=iso, file_count=len(rel_paths),
            ))
            continue

        _run_git(repo, ["add", "--", *rel_paths])

        # If this group is already committed (e.g. gitweave was already run
        # once with this same plan), there will be nothing staged. Skip the
        # commit instead of letting `git commit` fail with a confusing,
        # empty-looking error.
        staged = _run_git(repo, ["diff", "--cached", "--name-only"]).stdout.strip()
        if not staged:
            sha = _run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
            results.append(CommitResult(
                key=tc.group.key, message=tc.group.message, sha=sha,
                date_iso=iso, file_count=len(rel_paths), skipped=True,
            ))
            continue

        env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
            "GIT_AUTHOR_DATE": iso,
            "GIT_COMMITTER_DATE": iso,
        }
        _run_git(repo, ["commit", "-m", tc.group.message, "--no-verify"], env=env)
        sha = _run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()

        results.append(CommitResult(
            key=tc.group.key, message=tc.group.message, sha=sha,
            date_iso=iso, file_count=len(rel_paths),
        ))

    # Push is independent of execute: this lets you run `apply --plan ...`
    # a second time with just --push to publish commits that were already
    # created by an earlier --execute run, without needing to redo them.
    if push:
        # -u/--set-upstream so this works whether or not the branch already
        # has a tracking upstream configured (first push to a fresh repo
        # otherwise fails with "has no upstream branch").
        current_branch = branch or _run_git(repo, ["branch", "--show-current"]).stdout.strip()
        push_args = ["push", "--set-upstream", remote, current_branch]
        _run_git(repo, push_args)

    return results
