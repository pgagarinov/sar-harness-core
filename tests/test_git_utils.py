"""Tests for git utility functions."""
import subprocess
import tempfile
from pathlib import Path

from harness_core.git_utils import (
    git_status, git_head, git_branch, git_commit, git_reset_hard, git_diff_stat,
    git_fetch, git_cherry_pick, git_log_range,
)


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


def test_git_fetch_from_local_clone():
    """Fetch from a local clone, verify FETCH_HEAD points to the clone's HEAD."""
    repo_a = _init_temp_repo()
    # Clone A → B
    repo_b = Path(tempfile.mkdtemp())
    subprocess.run(["git", "clone", "--local", str(repo_a), str(repo_b)], check=True, capture_output=True)
    # Commit in B
    (repo_b / "new.txt").write_text("from B")
    subprocess.run(["git", "add", "-A"], cwd=repo_b, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo_b, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_b, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "B commit"], cwd=repo_b, check=True, capture_output=True)
    b_head = git_head(repo_b)
    # Fetch B into A
    fetch_head = git_fetch(repo_a, repo_b, "main")
    assert fetch_head is not None
    assert fetch_head == b_head


def test_git_cherry_pick_clean():
    """Cherry-pick a non-conflicting commit."""
    repo = _init_temp_repo()
    head_before = git_head(repo)
    # Create a branch with a commit
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True)
    (repo / "feature.txt").write_text("feature")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feature commit"], cwd=repo, check=True, capture_output=True)
    feature_head = git_head(repo)
    # Back to main
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    assert git_head(repo) == head_before
    # Cherry-pick the feature commit
    result = git_cherry_pick(repo, feature_head)
    assert feature_head in result["applied"]
    assert len(result["conflicts"]) == 0
    assert (repo / "feature.txt").exists()


def test_git_cherry_pick_conflict():
    """Cherry-pick a conflicting commit → detected and aborted."""
    repo = _init_temp_repo()
    # Create conflicting changes on two branches
    subprocess.run(["git", "checkout", "-b", "branch-a"], cwd=repo, check=True, capture_output=True)
    (repo / "file.txt").write_text("version A")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "A change"], cwd=repo, check=True, capture_output=True)
    a_head = git_head(repo)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "file.txt").write_text("version main")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=repo, check=True, capture_output=True)
    # Cherry-pick A onto main → conflict
    result = git_cherry_pick(repo, a_head)
    assert a_head in result["conflicts"]
    assert len(result["applied"]) == 0
    # Repo should be clean after abort
    s = git_status(repo)
    assert len(s["status_lines"]) == 0


def test_git_log_range():
    """List commits between two refs."""
    repo = _init_temp_repo()
    base = git_head(repo)
    for i in range(3):
        (repo / f"f{i}.txt").write_text(f"content {i}")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=repo, check=True, capture_output=True)
    commits = git_log_range(repo, base, "HEAD")
    assert len(commits) == 3
    assert all("hash" in c and "message" in c for c in commits)
