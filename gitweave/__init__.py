"""
gitweave — turn a finished project into a well-organized, honest commit history.

gitweave does NOT fabricate a development timeline. It only supports two modes:

  today   - all commits are timestamped now (today), just split into
            logical, reviewable chunks instead of one giant commit.

  history - commit timestamps are derived from real evidence on disk
            (file modification times), so the git history reflects when
            the code actually last changed, not an invented story.

If "history" mode doesn't have enough real signal to work with (e.g. every
file has the same mtime because the folder was just copied/zipped), gitweave
refuses to guess and automatically falls back to "today" mode with a warning.
"""

__version__ = "0.1.0"
