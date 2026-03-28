"""Checkpoint, snapshot, and restore for autonomous research loops.

Captures the working tree state (tracked modifications as a binary patch,
untracked files as a tar.gz), report files, and prompt assets into a
timestamped snapshot directory.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _git_command(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )


def capture_code_state(repo_path: Path, snapshot_dir: Path) -> dict[str, Any]:
    """Capture the repo's working tree state as a patch + untracked archive.

    Creates a code-state/ directory inside snapshot_dir containing:
    - tracked.patch: binary diff of all tracked modifications against HEAD
    - untracked.tar.gz: archive of all untracked (non-ignored) files
    """
    code_state_dir = snapshot_dir / "code-state"
    code_state_dir.mkdir(parents=True, exist_ok=True)

    head = _git_command(repo_path, "rev-parse", "HEAD")
    branch = _git_command(repo_path, "rev-parse", "--abbrev-ref", "HEAD")

    # Capture tracked modifications as a binary patch
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=repo_path,
        check=False,
        capture_output=True,
    )
    patch_path = code_state_dir / "tracked.patch"
    patch_path.write_bytes(diff.stdout)

    # Capture untracked files as a tar.gz
    untracked = _git_command(repo_path, "ls-files", "--others", "--exclude-standard")
    untracked_files = [f for f in untracked.stdout.splitlines() if f.strip()]
    untracked_archive = code_state_dir / "untracked.tar.gz"
    if untracked_files:
        subprocess.run(
            ["tar", "czf", str(untracked_archive), *untracked_files],
            cwd=repo_path,
            check=False,
            capture_output=True,
        )
    else:
        # Create empty archive
        subprocess.run(
            ["tar", "czf", str(untracked_archive), "--files-from", "/dev/null"],
            check=False,
            capture_output=True,
        )

    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "tracked_patch_bytes": len(diff.stdout),
        "untracked_file_count": len(untracked_files),
        "untracked_archive_bytes": (
            untracked_archive.stat().st_size if untracked_archive.exists() else 0
        ),
    }


def restore_code_state(repo_path: Path, snapshot_dir: Path) -> dict[str, Any]:
    """Restore the repo to the state captured in a snapshot.

    The snapshot_dir must contain a code-state/ subdirectory with
    tracked.patch and untracked.tar.gz as created by capture_code_state.
    """
    code_state_dir = snapshot_dir / "code-state"
    patch_path = code_state_dir / "tracked.patch"
    untracked_archive = code_state_dir / "untracked.tar.gz"

    if not code_state_dir.exists():
        raise FileNotFoundError(f"No code-state in snapshot: {snapshot_dir}")

    # Read snapshot metadata to verify HEAD matches
    snapshot_json = snapshot_dir / "snapshot.json"
    if snapshot_json.exists():
        snap = json.loads(snapshot_json.read_text(encoding="utf-8"))
        snap_head = snap.get("code_state", {}).get("head")
        current_head = _git_command(repo_path, "rev-parse", "HEAD").stdout.strip()
        if snap_head and snap_head != current_head:
            raise ValueError(
                f"HEAD mismatch: snapshot was taken at {snap_head[:12]}, "
                f"current is {current_head[:12]}. The patch may not apply cleanly."
            )

    # Reset working tree
    subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clean", "-fd"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    applied: dict[str, Any] = {"tracked_applied": False, "untracked_extracted": False}

    # Apply tracked patch
    if patch_path.exists() and patch_path.stat().st_size > 0:
        result = subprocess.run(
            ["git", "apply", "--binary", str(patch_path)],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        applied["tracked_applied"] = result.returncode == 0
        if result.returncode != 0:
            applied["tracked_error"] = result.stderr.strip()

    # Extract untracked files
    if untracked_archive.exists() and untracked_archive.stat().st_size > 0:
        result = subprocess.run(
            ["tar", "xzf", str(untracked_archive)],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        applied["untracked_extracted"] = result.returncode == 0

    # Verify
    status = _git_command(repo_path, "status", "--short")
    applied["status_lines"] = len(
        [line for line in status.stdout.splitlines() if line.strip()]
    )
    return applied


def write_snapshot(
    repo_path: Path,
    snapshots_dir: Path,
    history_path: Path,
    report_paths: list[Path],
    prompt_asset_paths: dict[str, Path],
    label: str | None = None,
    extra_data: dict[str, Any] | None = None,
) -> Path:
    """Write a full snapshot: code-state, reports, prompt assets, history entry.

    Args:
        repo_path: Path to the git repo being supervised.
        snapshots_dir: Directory to store snapshot subdirectories.
        history_path: Path to the JSONL history file.
        report_paths: Paths to JSON report files to copy into the snapshot.
        prompt_asset_paths: Mapping of asset name -> absolute path for prompt
            assets (skill, agents) to copy into the snapshot.
        label: Optional label suffix for the snapshot directory name.
        extra_data: Optional extra data to merge into the snapshot JSON.

    Returns:
        Path to the created snapshot directory.
    """
    snapshot_id = _snapshot_id()
    suffix = f"-{label}" if label else ""
    snapshot_dir = snapshots_dir / f"{snapshot_id}{suffix}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Copy report files
    copied_files: list[str] = []
    for report_path in report_paths:
        if _copy_if_exists(report_path, snapshot_dir / "artifacts" / report_path.name):
            copied_files.append(report_path.name)

    # Copy prompt assets
    for asset_name, asset_path in prompt_asset_paths.items():
        _copy_if_exists(
            asset_path,
            snapshot_dir / "prompt-assets" / f"{asset_name}.md",
        )

    # Capture code state
    code_state = capture_code_state(repo_path, snapshot_dir)

    payload: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_state": code_state,
        "copied_files": copied_files,
    }
    if extra_data:
        payload.update(extra_data)

    snapshot_json = snapshot_dir / "snapshot.json"
    snapshot_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Append history entry
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_entry = {
        "snapshot_id": snapshot_id,
        "label": label,
        "path": str(snapshot_dir),
        "created_at": payload["created_at"],
        "primary_metric": (extra_data or {}).get("primary_metric"),
    }
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(history_entry) + "\n")

    return snapshot_dir


DEFAULT_REVERT_PATHS = ("src/", "tests/", "lib/")


def safe_revert(
    repo_path: Path,
    snapshots_dir: Path,
    history_path: Path,
    report_paths: list[Path],
    prompt_asset_paths: dict[str, Path],
    label: str | None = None,
    revert_paths: tuple[str, ...] | None = None,
    full: bool = False,
) -> Path:
    """Checkpoint current state, then revert production code.

    First commits any .claude/ changes so they survive the revert, then
    writes a snapshot checkpoint, then reverts the specified paths (or the
    full working tree if full=True).

    Args:
        repo_path: Path to the git repo being supervised.
        snapshots_dir: Directory to store snapshot subdirectories.
        history_path: Path to the JSONL history file.
        report_paths: Paths to JSON report files to copy into the snapshot.
        prompt_asset_paths: Mapping of asset name -> absolute path for prompt assets.
        label: Optional label for the checkpoint snapshot.
        revert_paths: Tuple of path prefixes to revert. Defaults to DEFAULT_REVERT_PATHS.
        full: If True, revert the entire working tree.

    Returns:
        Path to the pre-revert checkpoint snapshot directory.
    """
    if revert_paths is None:
        revert_paths = DEFAULT_REVERT_PATHS

    # Commit .claude/ changes first so they survive the revert
    from .git_utils import commit_claude_changes

    commit_claude_changes(repo_path)

    snapshot_dir = write_snapshot(
        repo_path=repo_path,
        snapshots_dir=snapshots_dir,
        history_path=history_path,
        report_paths=report_paths,
        prompt_asset_paths=prompt_asset_paths,
        label=label or "pre-revert",
    )

    if full:
        subprocess.run(
            ["git", "checkout", "--", "."],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    else:
        for rp in revert_paths:
            subprocess.run(
                ["git", "checkout", "--", rp],
                cwd=repo_path,
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["git", "clean", "-fd", "--", rp],
                cwd=repo_path,
                check=False,
                capture_output=True,
            )

    return snapshot_dir


def resolve_snapshot(
    snapshots_dir: Path,
    history_path: Path,
    identifier: str,
    direction: str = "minimize",
) -> Path:
    """Resolve a snapshot identifier to a directory path.

    Accepts: full path, snapshot ID prefix, or 'best' (best primary_metric).

    Args:
        snapshots_dir: Directory containing snapshot subdirectories.
        history_path: Path to the JSONL history file.
        identifier: Snapshot identifier -- full path, ID prefix, or 'best'.
        direction: 'minimize' or 'maximize' for resolving 'best'.

    Returns:
        Path to the resolved snapshot directory.
    """
    if identifier == "best":
        if not history_path.exists():
            raise FileNotFoundError("No history.jsonl -- no snapshots to search")
        best_path = None
        best_value = float("inf") if direction == "minimize" else float("-inf")
        for line in history_path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            value = entry.get("primary_metric")
            if value is not None:
                is_better = (
                    (direction == "minimize" and value < best_value)
                    or (direction == "maximize" and value > best_value)
                )
                if is_better:
                    best_value = value
                    best_path = entry.get("path")
        if best_path is None:
            raise FileNotFoundError("No snapshots with primary_metric data found")
        p = Path(best_path)
        if not p.exists():
            raise FileNotFoundError(f"Best snapshot dir no longer exists: {p}")
        return p

    # Try as absolute path
    p = Path(identifier)
    if p.is_absolute() and p.exists():
        return p

    # Try as snapshot ID prefix
    if snapshots_dir.exists():
        matches = sorted(snapshots_dir.glob(f"{identifier}*"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous prefix '{identifier}' matches {len(matches)} snapshots: "
                + ", ".join(m.name for m in matches[:5])
            )

    raise FileNotFoundError(f"No snapshot found for '{identifier}'")
