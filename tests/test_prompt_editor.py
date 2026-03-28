"""Tests for prompt editor."""
import json
import subprocess
import tempfile
from pathlib import Path

from harness_core.prompt_editor import (
    build_asset_kinds,
    resolve_asset,
    list_assets,
    read_asset,
    edit_asset,
    diff_text,
    edit_history,
)


def _init_temp_repo_with_assets(
    skill_name: str = "test-skill",
    agent_names: list[str] | None = None,
) -> tuple[Path, Path]:
    """Create a temp git repo with .claude/ assets. Returns (repo_path, claude_dir)."""
    if agent_names is None:
        agent_names = ["test-agent"]
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, check=True, capture_output=True)

    claude_dir = d / ".claude"
    skill_dir = claude_dir / "skills" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Test Skill\n\nDo the thing.\n")

    agents_dir = claude_dir / "agents"
    agents_dir.mkdir(parents=True)
    for agent_name in agent_names:
        (agents_dir / f"{agent_name}.md").write_text(f"# {agent_name}\n\nAgent instructions.\n")

    rules_dir = claude_dir / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "test-rule.md").write_text("# Test Rule\n\nDon't do bad things.\n")

    subprocess.run(["git", "add", "-A"], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=d, check=True, capture_output=True)
    return d, claude_dir


def test_build_asset_kinds():
    kinds = build_asset_kinds("my-skill", ["analyzer", "fixer"])
    assert kinds["skill"] == "skills/my-skill/SKILL.md"
    assert kinds["analyzer"] == "agents/analyzer.md"
    assert kinds["fixer"] == "agents/fixer.md"
    assert len(kinds) == 3


def test_resolve_asset_skill():
    repo, claude_dir = _init_temp_repo_with_assets()
    p = resolve_asset(claude_dir, "test-skill", ["test-agent"], "skill")
    assert p == claude_dir / "skills" / "test-skill" / "SKILL.md"
    assert p.exists()


def test_resolve_asset_agent():
    repo, claude_dir = _init_temp_repo_with_assets()
    p = resolve_asset(claude_dir, "test-skill", ["test-agent"], "test-agent")
    assert p == claude_dir / "agents" / "test-agent.md"
    assert p.exists()


def test_resolve_asset_relative_path():
    repo, claude_dir = _init_temp_repo_with_assets()
    p = resolve_asset(claude_dir, "test-skill", ["test-agent"], "rules/test-rule.md")
    assert p.exists()
    assert p == claude_dir / "rules" / "test-rule.md"


def test_resolve_asset_unknown():
    repo, claude_dir = _init_temp_repo_with_assets()
    try:
        resolve_asset(claude_dir, "test-skill", ["test-agent"], "nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown asset" in str(e)


def test_list_assets():
    repo, claude_dir = _init_temp_repo_with_assets()
    assets = list_assets(claude_dir, "test-skill", ["test-agent"])
    names = [a["name"] for a in assets]
    assert "skill" in names
    assert "test-agent" in names
    assert "rules/test-rule.md" in names
    # All should exist
    for a in assets:
        assert a["exists"] is True
        assert "sha1" in a
        assert "size_bytes" in a


def test_read_asset():
    repo, claude_dir = _init_temp_repo_with_assets()
    content = read_asset(claude_dir, "test-skill", ["test-agent"], "skill")
    assert "# Test Skill" in content


def test_read_asset_missing():
    repo, claude_dir = _init_temp_repo_with_assets()
    # Remove the skill file
    skill_path = claude_dir / "skills" / "test-skill" / "SKILL.md"
    skill_path.unlink()
    try:
        read_asset(claude_dir, "test-skill", ["test-agent"], "skill")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_diff_text():
    old = "line1\nline2\nline3\n"
    new = "line1\nline2 modified\nline3\n"
    d = diff_text(old, new, label="test.md")
    assert "a/test.md" in d
    assert "b/test.md" in d
    assert "-line2" in d
    assert "+line2 modified" in d


def test_diff_text_no_change():
    text = "same content\n"
    d = diff_text(text, text, label="test.md")
    assert d == ""


def test_edit_asset():
    repo, claude_dir = _init_temp_repo_with_assets()
    log_dir = Path(tempfile.mkdtemp())

    result = edit_asset(
        claude_dir=claude_dir,
        repo_path=repo,
        skill_name="test-skill",
        agent_names=["test-agent"],
        name="skill",
        new_content="# Updated Skill\n\nNew instructions.\n",
        log_dir=log_dir,
    )

    assert result["changed"] is True
    assert result["old_sha1"] != result["new_sha1"]
    assert "diff" in result

    # Verify file was written
    skill_path = claude_dir / "skills" / "test-skill" / "SKILL.md"
    assert "Updated Skill" in skill_path.read_text()

    # Verify edit log was created
    edit_log = log_dir / "prompt-edits.jsonl"
    assert edit_log.exists()
    entries = [json.loads(line) for line in edit_log.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["name"] == "skill"


def test_edit_asset_no_change():
    repo, claude_dir = _init_temp_repo_with_assets()
    original = read_asset(claude_dir, "test-skill", ["test-agent"], "skill")

    result = edit_asset(
        claude_dir=claude_dir,
        repo_path=repo,
        skill_name="test-skill",
        agent_names=["test-agent"],
        name="skill",
        new_content=original,
    )

    assert result["changed"] is False


def test_edit_asset_auto_commits():
    repo, claude_dir = _init_temp_repo_with_assets()
    log_dir = Path(tempfile.mkdtemp())

    edit_asset(
        claude_dir=claude_dir,
        repo_path=repo,
        skill_name="test-skill",
        agent_names=["test-agent"],
        name="skill",
        new_content="# Changed\n",
        log_dir=log_dir,
    )

    # Check that git log shows the auto-commit
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo, capture_output=True, text=True,
    )
    assert "prompt-edit: update skill" in result.stdout


def test_edit_history():
    d = Path(tempfile.mkdtemp())
    log_file = d / "prompt-edits.jsonl"

    # No log file yet
    assert edit_history(d) == []

    # Write some entries
    with log_file.open("w") as f:
        f.write(json.dumps({"name": "skill", "timestamp": "2024-01-01"}) + "\n")
        f.write(json.dumps({"name": "agent", "timestamp": "2024-01-02"}) + "\n")

    history = edit_history(d)
    assert len(history) == 2
    assert history[0]["name"] == "skill"


def test_edit_history_limit():
    d = Path(tempfile.mkdtemp())
    log_file = d / "prompt-edits.jsonl"
    with log_file.open("w") as f:
        for i in range(10):
            f.write(json.dumps({"name": f"edit-{i}"}) + "\n")

    history = edit_history(d, limit=3)
    assert len(history) == 3
    assert history[0]["name"] == "edit-7"
