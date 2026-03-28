"""Tests for checkpoint, snapshot, and restore."""
import json
import subprocess
import tempfile
from pathlib import Path

from harness_core.checkpoint import (
    capture_code_state,
    restore_code_state,
    write_snapshot,
    safe_revert,
    resolve_snapshot,
)


def _init_temp_repo() -> Path:
    """Create a temp git repo with one commit."""
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, check=True, capture_output=True)
    (d / "file.txt").write_text("initial content")
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=d, check=True, capture_output=True)
    return d


def _setup_dirs(base: Path) -> tuple[Path, Path]:
    """Create snapshots and history dirs, return (snapshots_dir, history_path)."""
    snapshots_dir = base / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    history_path = base / "history.jsonl"
    return snapshots_dir, history_path


def test_capture_code_state_clean():
    repo = _init_temp_repo()
    snap_dir = Path(tempfile.mkdtemp()) / "snap"
    snap_dir.mkdir()
    result = capture_code_state(repo, snap_dir)
    assert result["head"] is not None
    assert len(result["head"]) == 40
    assert result["tracked_patch_bytes"] == 0
    assert result["untracked_file_count"] == 0
    assert (snap_dir / "code-state" / "tracked.patch").exists()
    assert (snap_dir / "code-state" / "untracked.tar.gz").exists()


def test_capture_code_state_dirty():
    repo = _init_temp_repo()
    (repo / "file.txt").write_text("modified content")
    (repo / "untracked.txt").write_text("new file")
    snap_dir = Path(tempfile.mkdtemp()) / "snap"
    snap_dir.mkdir()
    result = capture_code_state(repo, snap_dir)
    assert result["tracked_patch_bytes"] > 0
    assert result["untracked_file_count"] == 1


def test_capture_and_restore_roundtrip():
    repo = _init_temp_repo()
    # Make modifications
    (repo / "file.txt").write_text("modified content")
    (repo / "untracked.txt").write_text("new file")

    snap_dir = Path(tempfile.mkdtemp()) / "snap"
    snap_dir.mkdir()
    code_state = capture_code_state(repo, snap_dir)

    # Write a snapshot.json so restore can verify HEAD
    snapshot_json = snap_dir / "snapshot.json"
    snapshot_json.write_text(json.dumps({"code_state": code_state}))

    # Reset to clean
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo, check=True, capture_output=True)
    assert (repo / "file.txt").read_text() == "initial content"
    assert not (repo / "untracked.txt").exists()

    # Restore
    result = restore_code_state(repo, snap_dir)
    assert result["tracked_applied"] is True
    assert result["untracked_extracted"] is True
    assert (repo / "file.txt").read_text() == "modified content"
    assert (repo / "untracked.txt").read_text() == "new file"


def test_write_snapshot():
    repo = _init_temp_repo()
    base = Path(tempfile.mkdtemp())
    snapshots_dir, history_path = _setup_dirs(base)

    # Create a report file
    report = base / "report.json"
    report.write_text(json.dumps({"failed": 5, "total": 20}))

    snap_dir = write_snapshot(
        repo_path=repo,
        snapshots_dir=snapshots_dir,
        history_path=history_path,
        report_paths=[report],
        prompt_asset_paths={},
        label="test-snap",
        extra_data={"primary_metric": 5},
    )

    assert snap_dir.exists()
    assert "test-snap" in snap_dir.name
    assert (snap_dir / "snapshot.json").exists()
    assert (snap_dir / "artifacts" / "report.json").exists()
    assert (snap_dir / "code-state" / "tracked.patch").exists()

    # Check history was appended
    lines = history_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["label"] == "test-snap"
    assert entry["primary_metric"] == 5


def test_safe_revert_full():
    repo = _init_temp_repo()
    base = Path(tempfile.mkdtemp())
    snapshots_dir, history_path = _setup_dirs(base)

    # Make a modification
    (repo / "src" / "main.py").write_text("print('modified')")

    snap_dir = safe_revert(
        repo_path=repo,
        snapshots_dir=snapshots_dir,
        history_path=history_path,
        report_paths=[],
        prompt_asset_paths={},
        label="revert-test",
        full=True,
    )

    assert snap_dir.exists()
    # After full revert, file should be back to original
    assert (repo / "src" / "main.py").read_text() == "print('hello')"


def test_safe_revert_partial():
    repo = _init_temp_repo()
    base = Path(tempfile.mkdtemp())
    snapshots_dir, history_path = _setup_dirs(base)

    # Modify files in src/ and the root
    (repo / "src" / "main.py").write_text("print('modified')")
    (repo / "file.txt").write_text("root modified")

    snap_dir = safe_revert(
        repo_path=repo,
        snapshots_dir=snapshots_dir,
        history_path=history_path,
        report_paths=[],
        prompt_asset_paths={},
        revert_paths=("src/",),
    )

    assert snap_dir.exists()
    # src/ should be reverted
    assert (repo / "src" / "main.py").read_text() == "print('hello')"
    # root file should still be modified (not in revert_paths)
    assert (repo / "file.txt").read_text() == "root modified"


def test_resolve_snapshot_by_prefix():
    base = Path(tempfile.mkdtemp())
    snapshots_dir = base / "snapshots"
    snapshots_dir.mkdir()
    history_path = base / "history.jsonl"

    # Create a snapshot dir with a known prefix
    snap = snapshots_dir / "20240101T120000000000Z-test"
    snap.mkdir()

    resolved = resolve_snapshot(snapshots_dir, history_path, "20240101T12")
    assert resolved == snap


def test_resolve_snapshot_best():
    base = Path(tempfile.mkdtemp())
    snapshots_dir = base / "snapshots"
    snapshots_dir.mkdir()
    history_path = base / "history.jsonl"

    # Create two snapshot dirs
    snap_a = snapshots_dir / "snap-a"
    snap_a.mkdir()
    snap_b = snapshots_dir / "snap-b"
    snap_b.mkdir()

    # Write history with metrics
    with history_path.open("w") as f:
        f.write(json.dumps({"primary_metric": 10, "path": str(snap_a)}) + "\n")
        f.write(json.dumps({"primary_metric": 5, "path": str(snap_b)}) + "\n")

    # Best with minimize should pick snap_b (metric=5)
    resolved = resolve_snapshot(snapshots_dir, history_path, "best", direction="minimize")
    assert resolved == snap_b

    # Best with maximize should pick snap_a (metric=10)
    resolved = resolve_snapshot(snapshots_dir, history_path, "best", direction="maximize")
    assert resolved == snap_a


def test_resolve_snapshot_absolute_path():
    base = Path(tempfile.mkdtemp())
    snapshots_dir = base / "snapshots"
    snapshots_dir.mkdir()
    history_path = base / "history.jsonl"

    target = base / "some-snapshot"
    target.mkdir()

    resolved = resolve_snapshot(snapshots_dir, history_path, str(target))
    assert resolved == target
