import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gitweave.scan import scan_repo
from gitweave.planner import plan_commits
from gitweave.timeline import plan_timeline
from gitweave.gitops import apply_plan, ensure_repo


def make_fake_project(tmp_path: Path) -> Path:
    proj = tmp_path / "demo"
    (proj / "src" / "core").mkdir(parents=True)
    (proj / "src" / "api").mkdir(parents=True)
    (proj / "tests").mkdir(parents=True)

    (proj / "package.json").write_text('{"name": "demo"}')
    (proj / "README.md").write_text("# Demo project\n")
    (proj / "src" / "core" / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    time.sleep(0.05)
    (proj / "src" / "api" / "server.py").write_text("def handler():\n    return 'ok'\n")
    time.sleep(0.05)
    (proj / "tests" / "test_utils.py").write_text("def test_add():\n    assert True\n")

    subprocess.run(["git", "init"], cwd=proj, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=proj, check=True)
    return proj


def test_scan_finds_all_files(tmp_path):
    proj = make_fake_project(tmp_path)
    files = scan_repo(proj)
    paths = {f.path for f in files}
    assert "package.json" in paths
    assert "README.md" in paths
    assert "src/core/utils.py" in paths
    assert "src/api/server.py" in paths
    assert "tests/test_utils.py" in paths
    assert not any(p.startswith(".git/") for p in paths)


def test_plan_groups_scaffold_and_docs_at_edges(tmp_path):
    proj = make_fake_project(tmp_path)
    files = scan_repo(proj)
    groups = plan_commits(files)
    assert groups[0].key == "(scaffold)"
    assert groups[-1].key == "(docs)"
    keys = [g.key for g in groups]
    assert "src/core" in keys or any(k.startswith("src") for k in keys)


def test_timeline_today_mode_is_monotonic_and_today(tmp_path):
    proj = make_fake_project(tmp_path)
    files = scan_repo(proj)
    groups = plan_commits(files)
    timed, warnings = plan_timeline(groups, mode="today")
    assert len(timed) == len(groups)
    timestamps = [tc.timestamp for tc in timed]
    assert timestamps == sorted(timestamps)


def test_timeline_history_falls_back_when_no_spread(tmp_path):
    proj = make_fake_project(tmp_path)  # all files created within ~0.1s
    files = scan_repo(proj)
    groups = plan_commits(files)
    timed, warnings = plan_timeline(groups, mode="history")
    assert warnings, "expected a fallback warning when mtime spread is too small"


def test_apply_dry_run_makes_no_commits(tmp_path):
    proj = make_fake_project(tmp_path)
    files = scan_repo(proj)
    groups = plan_commits(files)
    timed, _ = plan_timeline(groups, mode="today")

    results = apply_plan(proj, timed, author_name="Tester", author_email="t@example.com",
                          execute=False)
    assert all(r.sha == "(dry-run)" for r in results)
    log = subprocess.run(["git", "log", "--oneline"], cwd=proj, capture_output=True, text=True)
    assert log.stdout.strip() == ""


def test_apply_execute_creates_expected_commits(tmp_path):
    proj = make_fake_project(tmp_path)
    files = scan_repo(proj)
    groups = plan_commits(files)
    timed, _ = plan_timeline(groups, mode="today")

    results = apply_plan(proj, timed, author_name="Tester", author_email="t@example.com",
                          execute=True)
    assert all(r.sha != "(dry-run)" for r in results)

    log = subprocess.run(["git", "log", "--format=%s"], cwd=proj, capture_output=True, text=True)
    subjects = log.stdout.strip().splitlines()
    assert len(subjects) == len(groups)
    assert "chore: project scaffolding" in subjects

    status = subprocess.run(["git", "status", "--porcelain"], cwd=proj,
                             capture_output=True, text=True)
    assert status.stdout.strip() == "", "all files should now be committed"


def test_apply_sets_honest_author_dates(tmp_path):
    proj = make_fake_project(tmp_path)
    files = scan_repo(proj)
    groups = plan_commits(files)
    timed, _ = plan_timeline(groups, mode="today")
    apply_plan(proj, timed, author_name="Tester", author_email="t@example.com", execute=True)

    log = subprocess.run(["git", "log", "--format=%aI"], cwd=proj, capture_output=True, text=True)
    dates = log.stdout.strip().splitlines()
    assert len(dates) == len(groups)
    # strictly increasing when read oldest->newest (git log is newest-first)
    assert dates == sorted(dates, reverse=True)
