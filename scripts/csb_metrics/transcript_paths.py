"""Shared transcript path resolution for multi-harness artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# Ordered fallback list for transcript artifacts across harnesses.
TRANSCRIPT_CANDIDATE_RELATIVE_PATHS: tuple[str, ...] = (
    "agent/claude-code.txt",
    "agent/codex-code.txt",
    "agent/cursor-code.txt",
    "agent/gemini-code.txt",
    "agent/copilot-code.txt",
    "agent/openhands-code.txt",
    "agent/openhands.txt",
    "agent/transcript.jsonl",
    "agent/transcript.txt",
    "claude-code.txt",
    "codex-code.txt",
    "cursor-code.txt",
    "gemini-code.txt",
    "copilot-code.txt",
    "openhands-code.txt",
    "transcript.jsonl",
    "transcript.txt",
    "agent_output/claude-code.txt",
    "agent_output/codex-code.txt",
    "agent_output/cursor-code.txt",
    "agent_output/gemini-code.txt",
    "agent_output/copilot-code.txt",
    "agent_output/openhands-code.txt",
    "agent_output/transcript.jsonl",
    "agent_output/transcript.txt",
)


def resolve_task_transcript_path(task_dir: str | Path) -> Path:
    """Return the first existing transcript path for a task directory.

    If no candidate exists, returns the canonical default path
    `task_dir/agent/claude-code.txt`.
    """
    task_dir = Path(task_dir)
    for rel_path in TRANSCRIPT_CANDIDATE_RELATIVE_PATHS:
        candidate = task_dir / rel_path
        if candidate.is_file():
            return candidate
    return task_dir / "agent" / "claude-code.txt"


def infer_task_dir_from_transcript_path(path: str | Path) -> Optional[Path]:
    """Infer Harbor task directory from an expected transcript path."""
    path = Path(path)
    if path.is_dir():
        return path

    parent = path.parent
    if parent.name in {"agent", "agent_output"}:
        return parent.parent if parent.parent != parent else None
    return parent if parent.exists() else None
