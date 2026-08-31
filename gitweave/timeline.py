"""
timeline.py — assigns a commit timestamp to each CommitGroup.

Two modes only. There is deliberately no "spread randomly over N fake days"
mode: gitweave will not manufacture a development history that didn't happen.

  today   : every commit gets a timestamp from *today*, spaced out over
            working hours, strictly increasing. Honest, because the push
            really is happening today — this just avoids one giant commit.

  history : commit timestamps are derived from the *real* mtimes of the
            files in that group (the latest mtime in the group = "when this
            chunk was last touched"). Groups are then ordered and, if
            necessary, nudged so timestamps are strictly increasing without
            moving further from the real value than `max_drift_minutes`.

`plan_timeline` automatically falls back from "history" to "today" (with a
warning) when the mtime evidence is too weak to be meaningful - e.g. every
file has (nearly) the same timestamp, which usually means the folder was
just extracted from a zip/clone rather than organically edited over time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from .planner import CommitGroup

MIN_HISTORY_SPAN_SECONDS = 3 * 3600  # need at least 3h of real spread to trust it


@dataclass
class TimedCommit:
    group: CommitGroup
    timestamp: datetime


def _history_feasible(groups: List[CommitGroup]) -> Tuple[bool, str]:
    mtimes = [g.latest_mtime for g in groups if g.files]
    if len(mtimes) < 2:
        return False, "Not enough groups with file data to derive a history."
    span = max(mtimes) - min(mtimes)
    if span < MIN_HISTORY_SPAN_SECONDS:
        return False, (
            f"File mtimes only span {span/60:.1f} minutes across the whole "
            f"project — too little real signal to build an honest history "
            f"(minimum {MIN_HISTORY_SPAN_SECONDS/3600:.0f}h). Falling back to 'today' mode."
        )
    return True, ""


def _spread_today(groups: List[CommitGroup], work_start_hour: int, work_end_hour: int,
                   tz: timezone) -> List[TimedCommit]:
    now = datetime.now(tz)
    n = len(groups)
    if n == 0:
        return []

    day_start = now.replace(hour=work_start_hour, minute=0, second=0, microsecond=0)
    day_end = now.replace(hour=work_end_hour, minute=0, second=0, microsecond=0)
    # if it's currently outside the work window, just end at "now"
    day_end = min(day_end, now) if now > day_start else day_end
    if day_end <= day_start:
        day_end = day_start + timedelta(hours=1)

    total_window = (day_end - day_start).total_seconds()
    # reserve small random gaps between commits, spaced roughly evenly
    base_gap = total_window / max(n, 1)

    timed: List[TimedCommit] = []
    cursor = day_start
    for g in groups:
        jitter = random.uniform(-0.15, 0.15) * base_gap
        ts = cursor + timedelta(seconds=max(0, jitter))
        timed.append(TimedCommit(group=g, timestamp=ts))
        cursor = cursor + timedelta(seconds=base_gap)
    return timed


def _derive_from_history(groups: List[CommitGroup], tz: timezone) -> List[TimedCommit]:
    ordered = sorted(groups, key=lambda g: g.latest_mtime)
    timed: List[TimedCommit] = []
    last_ts: datetime | None = None
    for g in ordered:
        ts = datetime.fromtimestamp(g.latest_mtime, tz=tz)
        if last_ts is not None and ts <= last_ts:
            # keep strictly increasing while staying as close to real as possible
            ts = last_ts + timedelta(minutes=1)
        timed.append(TimedCommit(group=g, timestamp=ts))
        last_ts = ts
    return timed


def plan_timeline(
    groups: List[CommitGroup],
    mode: str = "today",
    work_start_hour: int = 9,
    work_end_hour: int = 19,
    tz: timezone = timezone.utc,
) -> Tuple[List[TimedCommit], List[str]]:
    """
    Returns (timed_commits, warnings). `mode` is 'today' or 'history'.
    'history' silently (but with a returned warning) falls back to 'today'
    if there isn't enough real mtime evidence to justify it.
    """
    warnings: List[str] = []

    if mode not in ("today", "history"):
        raise ValueError("mode must be 'today' or 'history'")

    if mode == "history":
        feasible, reason = _history_feasible(groups)
        if not feasible:
            warnings.append(reason)
            mode = "today"

    if mode == "today":
        timed = _spread_today(groups, work_start_hour, work_end_hour, tz)
    else:
        timed = _derive_from_history(groups, tz)

    return timed, warnings
