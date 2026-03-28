"""Tests for git utility functions."""
import subprocess
import tempfile
from pathlib import Path

from harness_core.git_utils import git_status, git_head, git_branch, git_commit, git_reset_hard, git_diff_stat


def _init_temp_repo() -> Path:
    """Create a temp git repo with one commit."""
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, check=True, capture_output=True)
    (d / "file.txt").write_text("initial")
    subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=d, check=True, capture_output=True)
    return d


def test_git_status():
    repo = _init_temp_repo()
    s = git_status(repo)
    assert s["branch"] is not None
    assert s["head"] is not None
    assert isinstance(s["status_lines"], list)


def test_git_head():
    repo = _init_temp_repo()
    head = git_head(repo)
    assert head is not None
    assert len(head) == 40  # full SHA


def test_git_branch():
    repo = _init_temp_repo()
    branch = git_branch(repo)
    assert branch in ("main", "master")


def test_git_commit():
    repo = _init_temp_repo()
    (repo / "new.txt").write_text("new")
    ok = git_commit(repo, "add new file", paths=["new.txt"])
    assert ok
    s = git_status(repo)
    assert len(s["status_lines"]) == 0


def test_git_reset_hard():
    repo = _init_temp_repo()
    head_before = git_head(repo)
    (repo / "another.txt").write_text("another")
    git_commit(repo, "another commit")
    head_after = git_head(repo)
    assert head_before != head_after
    git_reset_hard(repo, "HEAD~1")
    assert git_head(repo) == head_before
    assert not (repo / "another.txt").exists()


def test_git_diff_stat_clean():
    repo = _init_temp_repo()
    stat = git_diff_stat(repo)
    assert stat == ""


def test_git_diff_stat_dirty():
    repo = _init_temp_repo()
    (repo / "file.txt").write_text("changed")
    stat = git_diff_stat(repo)
    assert "file.txt" in stat
