"""Daily git updater for autonomous Rotor deployments."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_UPDATE_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class GitCommandResult:
    """Small subprocess result shape used by the updater."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class GitUpdateResult:
    """Outcome of one git update attempt."""

    status: str
    message: str
    before: str | None = None
    after: str | None = None
    output: str = ""

    @property
    def updated(self) -> bool:
        """Return true when the update advanced HEAD."""
        return self.status == "updated"


GitRunner = Callable[[Path, list[str], float], GitCommandResult]
Puller = Callable[..., GitUpdateResult]


class DailyGitUpdater:
    """Run a safe git update at most once per configured interval."""

    def __init__(
        self,
        *,
        repo_path: str | Path | None = None,
        interval_seconds: float = DEFAULT_UPDATE_INTERVAL_SECONDS,
        remote: str | None = None,
        branch: str | None = None,
        puller: Puller | None = None,
    ) -> None:
        """Store updater settings for later ticks."""
        self.repo_path = Path(repo_path) if repo_path is not None else default_repo_root()
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.remote = remote
        self.branch = branch
        self._puller = pull_latest if puller is None else puller
        self._next_check_at = 0.0

    def run_if_due(
        self,
        log: logging.Logger,
        *,
        now: float | None = None,
    ) -> GitUpdateResult | None:
        """Pull the latest code when the daily interval has elapsed."""
        current = time.time() if now is None else now
        if current < self._next_check_at:
            return None
        self._next_check_at = current + self.interval_seconds
        try:
            result = self._puller(
                repo_path=self.repo_path,
                remote=self.remote,
                branch=self.branch,
            )
        except Exception as exc:  # pragma: no cover - defensive guard.
            result = GitUpdateResult(status="failed", message=str(exc))
        log_update_result(log, result)
        return result


def default_repo_root() -> Path:
    """Return the source checkout root for an editable/source install."""
    return Path(__file__).resolve().parents[1]


def pull_latest(
    *,
    repo_path: str | Path | None = None,
    remote: str | None = None,
    branch: str | None = None,
    timeout_seconds: float = 120.0,
    git_runner: GitRunner | None = None,
) -> GitUpdateResult:
    """Run `git pull --ff-only` safely and report whether HEAD changed."""
    repo = Path(repo_path) if repo_path is not None else default_repo_root()
    run_git = _run_git if git_runner is None else git_runner
    inside = run_git(repo, ["rev-parse", "--is-inside-work-tree"], timeout_seconds)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitUpdateResult(
            status="skipped",
            message=f"{repo} is not a git worktree",
            output=_combined_output(inside),
        )

    top_level = run_git(repo, ["rev-parse", "--show-toplevel"], timeout_seconds)
    if top_level.returncode == 0 and top_level.stdout.strip():
        repo = Path(top_level.stdout.strip())

    dirty = run_git(repo, ["status", "--porcelain"], timeout_seconds)
    if dirty.returncode != 0:
        return GitUpdateResult(
            status="failed",
            message="could not inspect git worktree status",
            output=_combined_output(dirty),
        )
    if dirty.stdout.strip():
        return GitUpdateResult(
            status="skipped",
            message="worktree has local changes; skipping auto-update",
            output=dirty.stdout,
        )

    current_branch = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout_seconds)
    if current_branch.returncode != 0:
        return GitUpdateResult(
            status="failed",
            message="could not determine current git branch",
            output=_combined_output(current_branch),
        )
    if current_branch.stdout.strip() == "HEAD" and branch is None:
        return GitUpdateResult(
            status="skipped",
            message="checkout is detached; configure a branch before auto-update",
        )

    before_result = run_git(repo, ["rev-parse", "HEAD"], timeout_seconds)
    if before_result.returncode != 0:
        return GitUpdateResult(
            status="failed",
            message="could not determine current commit",
            output=_combined_output(before_result),
        )
    before = before_result.stdout.strip()

    pull_args = ["pull", "--ff-only"]
    if remote and branch:
        pull_args.extend([remote, branch])
    elif remote:
        pull_args.append(remote)
    elif branch:
        pull_args.extend(["origin", branch])
    pulled = run_git(repo, pull_args, timeout_seconds)
    if pulled.returncode != 0:
        return GitUpdateResult(
            status="failed",
            message="git pull --ff-only failed",
            before=before,
            output=_combined_output(pulled),
        )

    after_result = run_git(repo, ["rev-parse", "HEAD"], timeout_seconds)
    if after_result.returncode != 0:
        return GitUpdateResult(
            status="failed",
            message="could not determine updated commit",
            before=before,
            output=_combined_output(after_result),
        )
    after = after_result.stdout.strip()
    if after == before:
        return GitUpdateResult(
            status="unchanged",
            message="already up to date",
            before=before,
            after=after,
            output=_combined_output(pulled),
        )
    return GitUpdateResult(
        status="updated",
        message="pulled latest code; restarting process to use it",
        before=before,
        after=after,
        output=_combined_output(pulled),
    )


def log_update_result(log: logging.Logger, result: GitUpdateResult) -> None:
    """Log one update result at an appropriate severity."""
    if result.status == "failed":
        log.warning("auto-update failed: %s", result.message)
    elif result.status == "updated":
        log.warning(
            "auto-update pulled latest code %s..%s; restarting process",
            _short_sha(result.before),
            _short_sha(result.after),
        )
    elif result.status == "unchanged":
        log.debug("auto-update checked: already up to date")
    else:
        log.debug("auto-update skipped: %s", result.message)


def restart_current_process() -> None:
    """Replace this process with the same command so updated code is loaded."""
    os.execv(sys.executable, [sys.executable, *sys.argv])


def _run_git(repo: Path, args: list[str], timeout_seconds: float) -> GitCommandResult:
    """Run one git command without invoking a shell."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return GitCommandResult(returncode=127, stderr="git executable not found")
    except subprocess.TimeoutExpired:
        return GitCommandResult(returncode=124, stderr="git command timed out")
    return GitCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _combined_output(result: GitCommandResult, *, limit: int = 500) -> str:
    """Combine stdout/stderr and cap log-sized output."""
    text = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return text[-limit:]


def _short_sha(value: str | None) -> str:
    """Return a short commit identifier for logs."""
    return "-" if not value else value[:12]
