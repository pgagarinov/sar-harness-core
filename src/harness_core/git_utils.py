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


def git_fetch(repo_path: Path, remote_path: Path, refspec: str = "main") -> str | None:
    """Fetch from another local repo. Returns FETCH_HEAD hash or None on failure."""
    result = subprocess.run(
        ["git", "fetch", str(remote_path), refspec],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    head = subprocess.run(
        ["git", "rev-parse", "FETCH_HEAD"],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    return head.stdout.strip() if head.returncode == 0 else None


def git_cherry_pick(repo_path: Path, *commits: str) -> dict:
    """Cherry-pick commits. Returns {applied: list[str], conflicts: list[str]}."""
    applied: list[str] = []
    conflicts: list[str] = []
    for commit in commits:
        result = subprocess.run(
            ["git", "cherry-pick", commit],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            applied.append(commit)
        else:
            conflicts.append(commit)
            # Abort the failed cherry-pick to leave repo in clean state
            subprocess.run(
                ["git", "cherry-pick", "--abort"],
                cwd=repo_path,
                check=False,
                capture_output=True,
            )
    return {"applied": applied, "conflicts": conflicts}


def git_log_range(
    repo_path: Path, base: str, head: str = "HEAD"
) -> list[dict[str, str]]:
    """List commits between base..head. Returns [{hash, message}, ...]."""
    result = subprocess.run(
        ["git", "log", "--oneline", f"{base}..{head}"],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    commits = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split(" ", 1)
        commits.append({
            "hash": parts[0],
            "message": parts[1] if len(parts) > 1 else "",
        })
    return commits


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
