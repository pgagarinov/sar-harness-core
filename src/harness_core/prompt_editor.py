"""Read, edit, and diff .claude prompt assets in a target repo.

All mutations go through this module so that every change is logged, diffed,
and optionally auto-committed.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def build_asset_kinds(skill_name: str, agent_names: list[str]) -> dict[str, str]:
    """Build asset name -> relative path mapping dynamically."""
    kinds: dict[str, str] = {"skill": f"skills/{skill_name}/SKILL.md"}
    for agent_name in agent_names:
        kinds[agent_name] = f"agents/{agent_name}.md"
    return kinds


def resolve_asset(
    claude_dir: Path, skill_name: str, agent_names: list[str], name: str
) -> Path:
    """Resolve an asset name to its absolute path under .claude/."""
    asset_kinds = build_asset_kinds(skill_name, agent_names)
    if name in asset_kinds:
        return claude_dir / asset_kinds[name]
    # Allow direct relative path under .claude/ (existing or new)
    candidate = claude_dir / name
    if candidate.exists() or "/" in name:
        return candidate
    raise ValueError(
        f"Unknown asset {name!r}. Known: {', '.join(sorted(asset_kinds))}. "
        f"Or pass a path relative to .claude/ (e.g., skills/my-skill/SKILL.md)"
    )


def list_assets(
    claude_dir: Path, skill_name: str, agent_names: list[str]
) -> list[dict[str, Any]]:
    """List all known prompt assets with metadata."""
    asset_kinds = build_asset_kinds(skill_name, agent_names)
    result = []
    for name, rel in asset_kinds.items():
        p = claude_dir / rel
        entry: dict[str, Any] = {"name": name, "path": str(p), "exists": p.exists()}
        if p.exists():
            text = p.read_text(encoding="utf-8")
            entry["size_bytes"] = len(text.encode())
            entry["sha1"] = _sha1(text)
            entry["lines"] = text.count("\n")
        result.append(entry)
    # Also list any rules
    rules_dir = claude_dir / "rules"
    if rules_dir.is_dir():
        for rule_file in sorted(rules_dir.glob("*.md")):
            text = rule_file.read_text(encoding="utf-8")
            result.append({
                "name": f"rules/{rule_file.name}",
                "path": str(rule_file),
                "exists": True,
                "size_bytes": len(text.encode()),
                "sha1": _sha1(text),
                "lines": text.count("\n"),
            })
    return result


def read_asset(
    claude_dir: Path, skill_name: str, agent_names: list[str], name: str
) -> str:
    """Read an asset's full contents."""
    p = resolve_asset(claude_dir, skill_name, agent_names, name)
    if not p.exists():
        raise FileNotFoundError(f"Asset {name!r} does not exist at {p}")
    return p.read_text(encoding="utf-8")


def diff_text(old: str, new: str, label: str = "asset") -> str:
    """Produce a unified diff between old and new text."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines, new_lines, fromfile=f"a/{label}", tofile=f"b/{label}"
        )
    )


def edit_asset(
    claude_dir: Path,
    repo_path: Path,
    skill_name: str,
    agent_names: list[str],
    name: str,
    new_content: str,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Write new content to an asset, returning a change record with diff."""
    p = resolve_asset(claude_dir, skill_name, agent_names, name)
    old_content = p.read_text(encoding="utf-8") if p.exists() else ""
    diff = diff_text(old_content, new_content, label=name)
    if not diff:
        return {"name": name, "path": str(p), "changed": False}

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_content, encoding="utf-8")

    record = {
        "name": name,
        "path": str(p),
        "changed": True,
        "old_sha1": _sha1(old_content),
        "new_sha1": _sha1(new_content),
        "old_lines": old_content.count("\n"),
        "new_lines": new_content.count("\n"),
        "diff": diff,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Append to edit log
    edit_log_dir = log_dir or (repo_path / ".supervisor")
    edit_log = edit_log_dir / "prompt-edits.jsonl"
    edit_log.parent.mkdir(parents=True, exist_ok=True)
    log_entry = {k: v for k, v in record.items() if k != "diff"}
    log_entry["diff_lines"] = diff.count("\n")
    with edit_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    # Auto-commit the .claude/ change so it survives reverts
    subprocess.run(
        ["git", "add", str(p)],
        cwd=repo_path,
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"prompt-edit: update {name}"],
        cwd=repo_path,
        check=False,
        capture_output=True,
    )

    return record


def sed_asset(
    claude_dir: Path,
    repo_path: Path,
    skill_name: str,
    agent_names: list[str],
    name: str,
    pattern: str,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Apply a sed-like substitution to an asset. Logged, diffed, auto-committed.

    Pattern format: s/search/replacement/[g]
    Uses Python re.sub internally.
    """
    import re as _re

    match = _re.match(r"s/((?:[^/\\]|\\.)*?)/((?:[^/\\]|\\.)*?)/(g?)$", pattern)
    if not match:
        raise ValueError(
            f"Invalid sed pattern: {pattern!r}. Expected: s/pattern/replacement/[g]"
        )

    search, replacement, flags = match.groups()
    count = 0 if flags == "g" else 1

    old_content = read_asset(claude_dir, skill_name, agent_names, name)
    new_content = _re.sub(search, replacement, old_content, count=count)

    return edit_asset(
        claude_dir, repo_path, skill_name, agent_names, name, new_content, log_dir
    )


def delete_asset(
    claude_dir: Path,
    repo_path: Path,
    name: str,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Delete an asset under .claude/, logged and auto-committed."""
    target = claude_dir / name
    if not target.exists():
        raise FileNotFoundError(f"Asset {name!r} does not exist at {target}")

    old_content = target.read_text(encoding="utf-8")
    target.unlink()

    record = {
        "name": name,
        "path": str(target),
        "action": "delete",
        "old_sha1": _sha1(old_content),
        "old_lines": old_content.count("\n"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Append to edit log
    edit_log_dir = log_dir or (repo_path / ".supervisor")
    edit_log = edit_log_dir / "prompt-edits.jsonl"
    edit_log.parent.mkdir(parents=True, exist_ok=True)
    with edit_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # Auto-commit
    subprocess.run(
        ["git", "add", str(target)],
        cwd=repo_path, check=False, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"prompt-edit: delete {name}"],
        cwd=repo_path, check=False, capture_output=True,
    )

    return record


def edit_history(state_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Read recent prompt edit history."""
    log_path = state_dir / "prompt-edits.jsonl"
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:]]
