"""Git utility functions for managing target repos."""
import subprocess
from pathlib import Path


def git_command(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the given repo."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )


def git_status(repo_path: Path) -> dict:
    """Get branch, HEAD, and working tree status."""
    branch = git_command(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    head = git_command(repo_path, "rev-parse", "HEAD")
    status = git_command(repo_path, "status", "--short")
    return {
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "status_lines": [l for l in status.stdout.splitlines() if l],
    }


def git_head(repo_path: Path) -> str | None:
    r = git_command(repo_path, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def git_branch(repo_path: Path) -> str | None:
    r = git_command(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def git_commit(repo_path: Path, message: str, paths: list[str] | None = None) -> bool:
    """Stage specified paths (or all) and commit. Returns True if commit created."""
    if paths:
        for p in paths:
            subprocess.run(["git", "add", p], cwd=repo_path, check=False, capture_output=True)
    else:
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=False, capture_output=True)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path, check=False, capture_output=True, text=True,
    )
    return result.returncode == 0


def git_reset_hard(repo_path: Path, ref: str = "HEAD~1") -> bool:
    """Reset repo to ref. Used for autoresearch discard."""
    result = subprocess.run(
        ["git", "reset", "--hard", ref],
        cwd=repo_path, check=False, capture_output=True, text=True,
    )
    return result.returncode == 0


def git_diff_stat(repo_path: Path) -> str:
    """Return short diff stat."""
    r = git_command(repo_path, "diff", "--stat")
    return r.stdout.strip()


def commit_claude_changes(repo_path: Path) -> bool:
    """Commit .claude/ changes so they survive reverts."""
    result = subprocess.run(
        ["git", "diff", "--name-only", ".claude/"],
        cwd=repo_path, capture_output=True, text=True,
    )
    changed = [f for f in result.stdout.strip().splitlines() if f]
    if not changed:
        return False
    subprocess.run(["git", "add", ".claude/"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Auto-commit .claude/ prompt edits before revert"],
        cwd=repo_path, check=True, capture_output=True,
    )
    return True
