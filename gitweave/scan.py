"""
scan.py — collects per-file facts (size, mtime, line count, hash, binary flag)
using the compiled `fastscan` C binary when available, falling back to a pure
Python implementation otherwise (slower, but keeps the tool usable anywhere).
"""

from __future__ import annotations

import json
import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env",
    "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".idea", ".vscode", ".next", "target", ".gradle", "vendor",
}

_HERE = Path(__file__).resolve().parent
_BINARY_CANDIDATES = [
    _HERE.parent / "src" / "fastscan",
    _HERE.parent / "bin" / "fastscan",
    shutil.which("gitweave-fastscan") or "",
]


@dataclass
class FileInfo:
    path: str          # relative to scan root, POSIX-style
    size: int
    mtime: float
    lines: int
    file_hash: str
    is_binary: bool


def _find_binary() -> str | None:
    for candidate in _BINARY_CANDIDATES:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _scan_with_binary(binary: str, root: Path, ignore_dirs: set[str]) -> List[FileInfo]:
    args = [binary, str(root), *sorted(ignore_dirs)]
    proc = subprocess.run(args, capture_output=True, text=True, check=True)
    results: List[FileInfo] = []
    root_str = str(root)
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        abs_path = obj["path"]
        # fastscan prints paths as "<root>/<...>"; normalize to relative POSIX paths
        rel = os.path.relpath(abs_path, root_str)
        rel = rel.replace(os.sep, "/")
        results.append(FileInfo(
            path=rel,
            size=obj["size"],
            mtime=float(obj["mtime"]),
            lines=obj["lines"],
            file_hash=obj["hash"],
            is_binary=obj["binary"],
        ))
    return results


def _scan_pure_python(root: Path, ignore_dirs: set[str]) -> List[FileInfo]:
    results: List[FileInfo] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for fname in filenames:
            full = Path(dirpath) / fname
            try:
                st = full.stat()
                data = full.read_bytes()
            except (OSError, PermissionError):
                continue
            is_binary = b"\x00" in data[:8192]
            lines = data.count(b"\n")
            # simple FNV-1a 64-bit to match the C implementation's algorithm
            h = 1469598103934665603
            for b in data:
                h ^= b
                h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
            rel = str(full.relative_to(root)).replace(os.sep, "/")
            results.append(FileInfo(
                path=rel,
                size=st.st_size,
                mtime=st.st_mtime,
                lines=lines,
                file_hash=f"{h:016x}",
                is_binary=is_binary,
            ))
    return results


def scan_repo(root: str | Path, extra_ignore: set[str] | None = None) -> List[FileInfo]:
    """Scan `root` and return per-file facts. Uses the C binary if present."""
    root = Path(root).resolve()
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    if extra_ignore:
        ignore_dirs |= extra_ignore

    binary = _find_binary()
    if binary:
        try:
            return _scan_with_binary(binary, root, ignore_dirs)
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
            pass  # fall through to pure python
    return _scan_pure_python(root, ignore_dirs)
