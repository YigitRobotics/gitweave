"""
cli.py — command-line interface for gitweave.

Subcommands:
  run       Simple one-shot: plan, preview, ask for confirmation, then
            commit (and optionally push). No plan.json needed. Use this
            for everyday use.

  analyze   Scan a project and print a report (file counts, mtime spread,
            feasibility of 'history' mode). Read-only, no git side effects.

  plan      Build a commit plan (grouping + timestamps) and save it to JSON
            for inspection or hand-editing before touching git at all.

  apply     Execute a saved plan (or build + execute in one step) against a
            real git repo. Dry-run unless --execute is passed. Use this
            (with `plan`) when you want to review/edit the plan file first.

Examples:
  gitweave run ./my-project                      # simplest everyday use
  gitweave run ./my-project --push -y             # no prompt, push after
  gitweave analyze ./my-project
  gitweave plan ./my-project --mode history --out plan.json
  gitweave apply ./my-project --plan plan.json --execute --push
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import timezone
from pathlib import Path

from .scan import scan_repo, FileInfo
from .planner import plan_commits, CommitGroup
from .timeline import plan_timeline, TimedCommit
from .gitops import apply_plan, ensure_repo, check_clean_baseline, GitOpsError
from .report import build_report, readme_disclosure_snippet


def _files_from_plan_json(obj: dict) -> list[CommitGroup]:
    groups = []
    for g in obj["groups"]:
        files = [FileInfo(**f) for f in g["files"]]
        groups.append(CommitGroup(key=g["key"], message=g["message"], files=files,
                                   order_rank=g.get("order_rank", 5)))
    return groups


def _plan_to_json(groups: list[CommitGroup], timed: list[TimedCommit] | None) -> dict:
    def file_dict(f: FileInfo) -> dict:
        return {
            "path": f.path, "size": f.size, "mtime": f.mtime,
            "lines": f.lines, "file_hash": f.file_hash, "is_binary": f.is_binary,
        }

    ts_by_key = {tc.group.key: tc.timestamp.isoformat() for tc in (timed or [])}
    return {
        "groups": [
            {
                "key": g.key,
                "message": g.message,
                "order_rank": g.order_rank,
                "timestamp": ts_by_key.get(g.key),
                "files": [file_dict(f) for f in g.files],
            }
            for g in groups
        ]
    }


def _git_config_default(key: str) -> str | None:
    try:
        result = subprocess.run(["git", "config", "--get", key],
                                 capture_output=True, text=True)
        value = result.stdout.strip()
        return value or None
    except FileNotFoundError:
        return None


def _resolve_author(args: argparse.Namespace) -> tuple[str, str]:
    name = args.author_name or _git_config_default("user.name")
    email = args.author_email or _git_config_default("user.email")
    if not name or not email:
        print("error: --author-name/--author-email not given and not found in "
              "`git config user.name` / `user.email`. Set them with:\n"
              "  git config --global user.name \"Your Name\"\n"
              "  git config --global user.email \"you@example.com\"\n"
              "or pass --author-name/--author-email directly.", file=sys.stderr)
        sys.exit(1)
    return name, email


def cmd_analyze(args: argparse.Namespace) -> int:
    files = scan_repo(args.path)
    print(build_report(files))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    files = scan_repo(args.path)
    if not files:
        print("No files found.", file=sys.stderr)
        return 1

    groups = plan_commits(files, max_files_per_commit=args.max_files)
    timed, warnings = plan_timeline(
        groups, mode=args.mode,
        work_start_hour=args.work_start, work_end_hour=args.work_end,
        tz=timezone.utc,
    )
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    plan_obj = _plan_to_json(groups, timed)
    out_path = Path(args.out)
    out_path.write_text(json.dumps(plan_obj, indent=2), encoding="utf-8")
    print(f"Plan written to {out_path} ({len(groups)} commits).")

    print("\nPlanned commits:")
    for tc in timed:
        print(f"  [{tc.timestamp.isoformat()}] {tc.group.message}  "
              f"({len(tc.group.files)} files)")

    if not args.no_readme_snippet:
        print("\nSuggested README disclosure snippet:\n")
        print(readme_disclosure_snippet(args.mode if not warnings else "today"))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    repo = Path(args.path).resolve()
    ensure_repo(repo)
    if not args.force:
        try:
            check_clean_baseline(repo)
        except GitOpsError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    if args.plan:
        plan_obj = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        groups = _files_from_plan_json(plan_obj)
        from datetime import datetime
        timed = []
        for g, gj in zip(groups, plan_obj["groups"]):
            ts = datetime.fromisoformat(gj["timestamp"])
            timed.append(TimedCommit(group=g, timestamp=ts))
        warnings = []
    else:
        files = scan_repo(args.path)
        groups = plan_commits(files, max_files_per_commit=args.max_files)
        timed, warnings = plan_timeline(
            groups, mode=args.mode,
            work_start_hour=args.work_start, work_end_hour=args.work_end,
            tz=timezone.utc,
        )
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)

    if not args.execute:
        print("DRY RUN (pass --execute to actually create commits):\n")

    author_name, author_email = _resolve_author(args)
    results = apply_plan(
        repo, timed,
        author_name=author_name, author_email=author_email,
        execute=args.execute, push=args.push, remote=args.remote, branch=args.branch,
    )

    for r in results:
        tag = "  (already committed, skipped)" if getattr(r, "skipped", False) else ""
        print(f"  [{r.date_iso}] {r.sha[:10]}  {r.message}  ({r.file_count} files){tag}")

    if not args.execute and not args.push:
        print("\nNo changes were made. Re-run with --execute to apply this plan.")
    elif not args.execute and args.push:
        print("\nNo commits were created (dry-run); pushed existing commits in the repo.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """One-shot: analyze + plan + preview + (optionally) execute + (optionally) push.

    No plan.json needed. Meant as the simple, everyday entry point; use
    `plan` + `apply` separately if you need to inspect or hand-edit the plan.
    """
    repo = Path(args.path).resolve()
    ensure_repo(repo)
    if not args.force:
        try:
            check_clean_baseline(repo)
        except GitOpsError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    files = scan_repo(args.path)
    if not files:
        print("No files found.", file=sys.stderr)
        return 1

    groups = plan_commits(files, max_files_per_commit=args.max_files)
    timed, warnings = plan_timeline(
        groups, mode=args.mode,
        work_start_hour=args.work_start, work_end_hour=args.work_end,
        tz=timezone.utc,
    )
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    print(f"Planned {len(timed)} commits:\n")
    for tc in timed:
        print(f"  [{tc.timestamp.isoformat()}] {tc.group.message}  "
              f"({len(tc.group.files)} files)")

    if not args.yes:
        answer = input("\nCreate these commits now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted, nothing was changed.")
            return 0

    author_name, author_email = _resolve_author(args)
    results = apply_plan(
        repo, timed,
        author_name=author_name, author_email=author_email,
        execute=True, push=args.push, remote=args.remote, branch=args.branch,
    )
    print()
    for r in results:
        tag = "  (already committed, skipped)" if getattr(r, "skipped", False) else ""
        print(f"  [{r.date_iso}] {r.sha[:10]}  {r.message}  ({r.file_count} files){tag}")
    if args.push:
        print("\nPushed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gitweave", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Scan and report on a project (read-only)")
    p_analyze.add_argument("path")
    p_analyze.set_defaults(func=cmd_analyze)

    p_plan = sub.add_parser("plan", help="Build a commit plan and save it as JSON")
    p_plan.add_argument("path")
    p_plan.add_argument("--mode", choices=["today", "history"], default="today")
    p_plan.add_argument("--out", default="gitweave-plan.json")
    p_plan.add_argument("--max-files", type=int, default=25,
                         help="max files per commit before splitting a directory")
    p_plan.add_argument("--work-start", type=int, default=9)
    p_plan.add_argument("--work-end", type=int, default=19)
    p_plan.add_argument("--no-readme-snippet", action="store_true")
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="Execute a plan against a real git repo")
    p_apply.add_argument("path")
    p_apply.add_argument("--plan", help="Path to a plan JSON from `gitweave plan`. "
                                         "If omitted, builds a plan on the fly.")
    p_apply.add_argument("--mode", choices=["today", "history"], default="today")
    p_apply.add_argument("--max-files", type=int, default=25)
    p_apply.add_argument("--work-start", type=int, default=9)
    p_apply.add_argument("--work-end", type=int, default=19)
    p_apply.add_argument("--author-name", default=None,
                          help="defaults to `git config user.name` if not given")
    p_apply.add_argument("--author-email", default=None,
                          help="defaults to `git config user.email` if not given")
    p_apply.add_argument("--execute", action="store_true",
                          help="Actually create commits (default: dry-run preview only)")
    p_apply.add_argument("--push", action="store_true")
    p_apply.add_argument("--remote", default="origin")
    p_apply.add_argument("--branch", default=None)
    p_apply.add_argument("--force", action="store_true",
                          help="Proceed even if repo has staged/tracked changes")
    p_apply.set_defaults(func=cmd_apply)

    p_run = sub.add_parser(
        "run", help="Simple one-shot: plan, preview, and (with confirmation) commit + push")
    p_run.add_argument("path")
    p_run.add_argument("--mode", choices=["today", "history"], default="today")
    p_run.add_argument("--max-files", type=int, default=25)
    p_run.add_argument("--work-start", type=int, default=9)
    p_run.add_argument("--work-end", type=int, default=19)
    p_run.add_argument("--author-name", default=None,
                        help="defaults to `git config user.name` if not given")
    p_run.add_argument("--author-email", default=None,
                        help="defaults to `git config user.email` if not given")
    p_run.add_argument("--push", action="store_true")
    p_run.add_argument("--remote", default="origin")
    p_run.add_argument("--branch", default=None)
    p_run.add_argument("--force", action="store_true")
    p_run.add_argument("-y", "--yes", action="store_true",
                        help="skip the confirmation prompt")
    p_run.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
