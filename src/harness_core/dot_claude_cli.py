"""Unified CLI for managing .claude/ files in any repo.

Every repo uses this same CLI — only the --repo path differs.
Skill and agent names are auto-discovered from the repo's .claude/ directory.

Usage:
    python -m harness_core.dot_claude_cli --repo ../sar-rag-target list
    python -m harness_core.dot_claude_cli --repo . read skill
    echo "content" | python -m harness_core.dot_claude_cli --repo . edit skill
    python -m harness_core.dot_claude_cli --repo . delete rules/old-rule.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness_core.prompt_editor import (
    delete_asset,
    diff_text,
    edit_asset,
    list_assets,
    read_asset,
    sed_asset,
)


def _discover_skill_name(claude_dir: Path) -> str:
    """Find the skill name from .claude/skills/<name>/SKILL.md."""
    skills_dir = claude_dir / "skills"
    if skills_dir.is_dir():
        for child in skills_dir.iterdir():
            if child.is_dir() and (child / "SKILL.md").exists():
                return child.name
    return "start"


def _discover_agent_names(claude_dir: Path) -> list[str]:
    """Find agent names from .claude/agents/<name>.md."""
    agents_dir = claude_dir / "agents"
    if agents_dir.is_dir():
        return sorted(p.stem for p in agents_dir.glob("*.md"))
    return []


def _resolve_repo(repo_arg: str) -> Path:
    """Resolve repo path from argument, alias, or env var.

    Supports aliases so pixi tasks don't need shell-specific syntax:
      --repo target     → $SAR_TARGET_PATH or ../sar-rag-target
      --repo researcher → $RESEARCH_LOOP_REPO or ../sar-research-loop
      --repo supervisor → $SUPERVISOR_REPO or ../sar-supervisor
      --repo .          → current directory
      --repo /abs/path  → literal path
    """
    import os
    aliases: dict[str, str] = {
        "target": "SAR_TARGET_PATH",
        "researcher": "RESEARCH_LOOP_REPO",
        "supervisor": "SUPERVISOR_REPO",
    }
    if repo_arg in aliases:
        env_var = aliases[repo_arg]
        val = os.environ.get(env_var, "")
        if not val:
            raise RuntimeError(f"{env_var} env var is not set. Required for --repo {repo_arg}.")
        return Path(val).resolve()
    return Path(repo_arg).resolve()


def _cmd_list(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.repo)
    claude_dir = repo / ".claude"
    assets = list_assets(claude_dir, _discover_skill_name(claude_dir), _discover_agent_names(claude_dir))
    if args.json:
        print(json.dumps(assets, indent=2))
        return 0
    for a in assets:
        status = f"{a['lines']}L {a['sha1'][:8]}" if a["exists"] else "MISSING"
        print(f"  {a['name']:30s} {status}")
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.repo)
    claude_dir = repo / ".claude"
    content = read_asset(claude_dir, _discover_skill_name(claude_dir), _discover_agent_names(claude_dir), args.name)
    print(content, end="")
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.repo)
    claude_dir = repo / ".claude"
    skill_name = _discover_skill_name(claude_dir)
    agent_names = _discover_agent_names(claude_dir)

    if args.sed:
        record = sed_asset(
            claude_dir=claude_dir, repo_path=repo,
            skill_name=skill_name, agent_names=agent_names,
            name=args.name, pattern=args.sed,
        )
    else:
        content = sys.stdin.read()
        if not content:
            print("error: no content on stdin", file=sys.stderr)
            return 1
        record = edit_asset(
            claude_dir=claude_dir, repo_path=repo,
            skill_name=skill_name, agent_names=agent_names,
            name=args.name, new_content=content,
        )
    if not record["changed"]:
        print(f"{args.name}: no changes")
        return 0
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"{args.name}: changed ({record['old_lines']}L -> {record['new_lines']}L)")
        if record.get("diff"):
            print(record["diff"], end="")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.repo)
    claude_dir = repo / ".claude"
    skill_name = _discover_skill_name(claude_dir)
    agent_names = _discover_agent_names(claude_dir)
    content = read_asset(claude_dir, skill_name, agent_names, args.name)
    new_content = sys.stdin.read()
    if not new_content:
        print("error: no content on stdin", file=sys.stderr)
        return 1
    diff = diff_text(content, new_content, label=args.name)
    if diff:
        print(diff, end="")
    else:
        print("no differences")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.repo)
    claude_dir = repo / ".claude"
    try:
        record = delete_asset(claude_dir=claude_dir, repo_path=repo, name=args.path)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"deleted: {record['name']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dot-claude", description="Manage .claude/ files in any repo")
    parser.add_argument("--repo", default=".", help="Repo path (default: current directory)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_p = subparsers.add_parser("list", help="List all .claude/ assets")
    list_p.add_argument("--json", action="store_true")
    list_p.set_defaults(func=_cmd_list)

    read_p = subparsers.add_parser("read", help="Read an asset")
    read_p.add_argument("name", help="Asset name or path relative to .claude/")
    read_p.set_defaults(func=_cmd_read)

    edit_p = subparsers.add_parser("edit", help="Edit an asset (content from stdin or --sed)")
    edit_p.add_argument("name", help="Asset name to edit")
    edit_p.add_argument("--json", action="store_true")
    edit_p.add_argument("--sed", default=None, help="sed substitution: s/pattern/replacement/[g]")
    edit_p.set_defaults(func=_cmd_edit)

    diff_p = subparsers.add_parser("diff", help="Diff an asset against stdin")
    diff_p.add_argument("name", help="Asset name to diff")
    diff_p.set_defaults(func=_cmd_diff)

    delete_p = subparsers.add_parser("delete", help="Delete an asset")
    delete_p.add_argument("path", help="Path relative to .claude/")
    delete_p.set_defaults(func=_cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
