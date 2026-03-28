"""Shared infrastructure for autonomous research loops."""
from .checkpoint import capture_code_state, restore_code_state, write_snapshot, safe_revert, resolve_snapshot
from .prompt_editor import list_assets, read_asset, edit_asset, diff_text, edit_history, resolve_asset
from .metrics import extract_metric, report_summary, metric_trend, trend_direction, log_result
from .git_utils import git_command, git_status, git_head, git_branch, git_commit, git_reset_hard, git_diff_stat, commit_claude_changes
