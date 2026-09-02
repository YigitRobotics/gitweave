"""
report.py — human-readable analysis of a scan: file counts, size, language
mix (by extension), mtime spread, and whether 'history' mode is feasible.
Also generates the optional README disclosure snippet.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import List

from .scan import FileInfo
from .timeline import MIN_HISTORY_SPAN_SECONDS


def build_report(files: List[FileInfo]) -> str:
    if not files:
        return "No files found to analyze."

    total_files = len(files)
    total_lines = sum(f.lines for f in files if not f.is_binary)
    total_bytes = sum(f.size for f in files)
    binary_count = sum(1 for f in files if f.is_binary)

    ext_counter: Counter[str] = Counter()
    for f in files:
        ext = PurePosixPath(f.path).suffix.lower() or "(no ext)"
        ext_counter[ext] += 1
    top_exts = ext_counter.most_common(8)

    mtimes = [f.mtime for f in files]
    span_seconds = max(mtimes) - min(mtimes)
    earliest = datetime.fromtimestamp(min(mtimes), tz=timezone.utc)
    latest = datetime.fromtimestamp(max(mtimes), tz=timezone.utc)
    history_ok = span_seconds >= MIN_HISTORY_SPAN_SECONDS

    lines_out = []
    lines_out.append("gitweave analysis")
    lines_out.append("=" * 40)
    lines_out.append(f"Files scanned:        {total_files}")
    lines_out.append(f"  binary files:        {binary_count}")
    lines_out.append(f"Total size:            {total_bytes / 1024:.1f} KB")
    lines_out.append(f"Total lines (text):    {total_lines}")
    lines_out.append("")
    lines_out.append("Top file types:")
    for ext, count in top_exts:
        lines_out.append(f"  {ext:<12} {count}")
    lines_out.append("")
    lines_out.append("Modification time spread:")
    lines_out.append(f"  earliest mtime: {earliest.isoformat()}")
    lines_out.append(f"  latest mtime:   {latest.isoformat()}")
    lines_out.append(f"  span:           {span_seconds/3600:.2f} hours")
    lines_out.append("")
    if history_ok:
        lines_out.append(
            "'history' mode is FEASIBLE: real mtimes span enough time to "
            "derive an honest, evidence-based commit timeline."
        )
    else:
        lines_out.append(
            "'history' mode is NOT feasible: mtimes are too tightly clustered "
            "(likely copied/extracted together). gitweave will fall back to "
            "'today' mode automatically if you request 'history'."
        )
    return "\n".join(lines_out)


def readme_disclosure_snippet(mode: str) -> str:
    if mode == "today":
        return (
            "## Development notes\n\n"
            "This project was developed locally before being pushed to GitHub. "
            "The commit history was organized into logical chunks at push time "
            "rather than reflecting the exact original editing session.\n"
        )
    return (
        "## Development notes\n\n"
        "Commit timestamps in this repository were derived from the actual "
        "last-modified times of the source files, reconstructed from local "
        "history at push time.\n"
    )
