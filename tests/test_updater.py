"""Tests for Rotor's autonomous git updater."""

from __future__ import annotations

import logging
from pathlib import Path

import rotor.updater as updater
from rotor.updater import (
    DailyGitUpdater,
    GitCommandResult,
    GitUpdateResult,
    pull_latest,
)


def test_pull_latest_skips_non_git_worktree(tmp_path):
    calls: list[list[str]] = []

    def fake_git(_repo: Path, args: list[str], _timeout: float) -> GitCommandResult:
        calls.append(args)
        return GitCommandResult(returncode=1, stderr="not a git repository")

    result = pull_latest(repo_path=tmp_path, git_runner=fake_git)

    assert result.status == "skipped"
    assert "not a git worktree" in result.message
    assert calls == [["rev-parse", "--is-inside-work-tree"]]


def test_pull_latest_skips_dirty_worktree(tmp_path):
    calls: list[list[str]] = []
    responses = iter([
        GitCommandResult(returncode=0, stdout="true\n"),
        GitCommandResult(returncode=0, stdout=f"{tmp_path}\n"),
        GitCommandResult(returncode=0, stdout=" M rotor/mm/vl_runner.py\n"),
    ])

    def fake_git(_repo: Path, args: list[str], _timeout: float) -> GitCommandResult:
        calls.append(args)
        return next(responses)

    result = pull_latest(repo_path=tmp_path, git_runner=fake_git)

    assert result.status == "skipped"
    assert "local changes" in result.message
    assert ["pull", "--ff-only"] not in calls


def test_pull_latest_reports_fast_forward_update(tmp_path):
    before = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    after = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    calls: list[list[str]] = []
    responses = iter([
        GitCommandResult(returncode=0, stdout="true\n"),
        GitCommandResult(returncode=0, stdout=f"{tmp_path}\n"),
        GitCommandResult(returncode=0, stdout=""),
        GitCommandResult(returncode=0, stdout="main\n"),
        GitCommandResult(returncode=0, stdout=f"{before}\n"),
        GitCommandResult(returncode=0, stdout="Fast-forward\n"),
        GitCommandResult(returncode=0, stdout=f"{after}\n"),
    ])

    def fake_git(_repo: Path, args: list[str], _timeout: float) -> GitCommandResult:
        calls.append(args)
        return next(responses)

    result = pull_latest(
        repo_path=tmp_path,
        remote="origin",
        branch="main",
        git_runner=fake_git,
    )

    assert result.status == "updated"
    assert result.updated is True
    assert result.before == before
    assert result.after == after
    assert ["pull", "--ff-only", "origin", "main"] in calls


def test_pull_latest_reports_unchanged_when_head_does_not_move(tmp_path):
    head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    responses = iter([
        GitCommandResult(returncode=0, stdout="true\n"),
        GitCommandResult(returncode=0, stdout=f"{tmp_path}\n"),
        GitCommandResult(returncode=0, stdout=""),
        GitCommandResult(returncode=0, stdout="main\n"),
        GitCommandResult(returncode=0, stdout=f"{head}\n"),
        GitCommandResult(returncode=0, stdout="Already up to date.\n"),
        GitCommandResult(returncode=0, stdout=f"{head}\n"),
    ])

    def fake_git(_repo: Path, _args: list[str], _timeout: float) -> GitCommandResult:
        return next(responses)

    result = pull_latest(repo_path=tmp_path, git_runner=fake_git)

    assert result.status == "unchanged"
    assert result.updated is False
    assert result.before == head
    assert result.after == head


def test_daily_git_updater_runs_only_when_due(tmp_path):
    calls: list[dict] = []

    def fake_puller(**kwargs) -> GitUpdateResult:
        calls.append(kwargs)
        return GitUpdateResult(status="unchanged", message="already up to date")

    updater = DailyGitUpdater(
        repo_path=tmp_path,
        interval_seconds=10,
        remote="origin",
        branch="main",
        puller=fake_puller,
    )
    log = logging.getLogger("tests.updater")

    assert updater.run_if_due(log, now=100.0).status == "unchanged"
    assert updater.run_if_due(log, now=105.0) is None
    assert updater.run_if_due(log, now=111.0).status == "unchanged"
    assert len(calls) == 2
    assert calls[0]["repo_path"] == tmp_path
    assert calls[0]["remote"] == "origin"
    assert calls[0]["branch"] == "main"


def test_daily_git_updater_contains_puller_exceptions(tmp_path):
    def broken_puller(**_kwargs) -> GitUpdateResult:
        raise RuntimeError("network unavailable")

    updater = DailyGitUpdater(repo_path=tmp_path, puller=broken_puller)

    result = updater.run_if_due(logging.getLogger("tests.updater"), now=100.0)

    assert result is not None
    assert result.status == "failed"
    assert "network unavailable" in result.message


def test_restart_current_process_reexecs_same_command(monkeypatch):
    captured = {}

    def fake_execv(path, args):
        captured["path"] = path
        captured["args"] = args
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(updater.os, "execv", fake_execv)
    monkeypatch.setattr(updater.sys, "executable", "/venv/bin/python")
    monkeypatch.setattr(updater.sys, "argv", ["rotor", "mm", "vl", "--auto-update"])

    try:
        updater.restart_current_process()
    except RuntimeError as exc:
        assert str(exc) == "exec intercepted"

    assert captured == {
        "path": "/venv/bin/python",
        "args": ["/venv/bin/python", "rotor", "mm", "vl", "--auto-update"],
    }
