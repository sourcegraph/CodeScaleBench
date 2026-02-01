"""Generate per-task LLM judge context files.

For each task in each run, generates a JSON file containing everything an LLM
judge needs to evaluate quality: task instructions, agent output, ground truth,
tool usage summary, and run metadata.

Stdlib only — no external dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

from .discovery import discover_runs, _extract_task_id, _is_batch_dir, _is_task_dir
from .extractors import (
    extract_tool_usage_from_trajectory,
    extract_tool_usage_from_transcript,
)


def _read_text_file(path: Path) -> Optional[str]:
    """Read a text file, returning None if missing or unreadable."""
    if not path.is_file():
        return None
    try:
        return path.read_text()
    except OSError:
        return None


def _read_instruction(benchmarks_dir: Path, benchmark: str, task_id: str) -> Optional[str]:
    """Locate and read instruction.md for a task from the benchmarks directory.

    Mapping:
        locobench -> benchmarks/locobench_agent/tasks/<task_id>/instruction.md
        bigcode   -> benchmarks/big_code_mcp/<task_id>/instruction.md
        k8s_docs  -> benchmarks/kubernetes_docs/<task_id>/instruction.md
        swebenchpro -> None (instructions come from Harbor dataset, not local)
    """
    if benchmark == "locobench":
        p = benchmarks_dir / "locobench_agent" / "tasks" / task_id / "instruction.md"
    elif benchmark == "bigcode":
        p = benchmarks_dir / "big_code_mcp" / task_id / "instruction.md"
    elif benchmark == "k8s_docs":
        p = benchmarks_dir / "kubernetes_docs" / task_id / "instruction.md"
    else:
        return None

    return _read_text_file(p)


def _read_ground_truth(benchmarks_dir: Path, benchmark: str, task_id: str) -> Optional[str]:
    """Read ground truth files for a task, concatenated into a single string.

    Looks in ground_truth/ directory. Returns None if not found.
    """
    if benchmark == "locobench":
        gt_dir = benchmarks_dir / "locobench_agent" / "tasks" / task_id / "solution"
    elif benchmark == "bigcode":
        gt_dir = benchmarks_dir / "big_code_mcp" / task_id / "solution"
    elif benchmark == "k8s_docs":
        gt_dir = benchmarks_dir / "kubernetes_docs" / task_id / "ground_truth"
    else:
        return None

    if not gt_dir.is_dir():
        return None

    parts = []
    for f in sorted(gt_dir.iterdir()):
        if f.is_file():
            text = _read_text_file(f)
            if text:
                parts.append(f"--- {f.name} ---\n{text}")
    return "\n\n".join(parts) if parts else None


def _extract_transcript_summary(transcript_path: Path, head: int = 200, tail: int = 100) -> Optional[str]:
    """Extract first `head` + last `tail` lines of the transcript as a summary."""
    if not transcript_path.is_file():
        return None
    try:
        lines = transcript_path.read_text().splitlines()
    except OSError:
        return None

    if not lines:
        return None

    total = len(lines)
    if total <= head + tail:
        return "\n".join(lines)

    summary_lines = lines[:head]
    summary_lines.append(f"\n... [{total - head - tail} lines omitted] ...\n")
    summary_lines.extend(lines[-tail:])
    return "\n".join(summary_lines)


def _extract_agent_output(task_dir: Path) -> Optional[str]:
    """Extract agent output: solution.md if it exists, else last assistant text."""
    # Try solution.md first
    solution_path = task_dir / "agent" / "solution.md"
    text = _read_text_file(solution_path)
    if text:
        return text

    # Fallback: last assistant message text from transcript
    transcript_path = task_dir / "agent" / "claude-code.txt"
    if not transcript_path.is_file():
        return None

    try:
        lines = transcript_path.read_text().splitlines()
    except OSError:
        return None

    last_text = None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                last_text = block.get("text")
                if last_text:
                    return last_text
        break

    return last_text


def _extract_tool_usage_summary(task_dir: Path) -> Optional[dict]:
    """Extract tool usage summary: total calls, MCP calls, top 5 tools."""
    trajectory_path = task_dir / "agent" / "trajectory.json"
    transcript_path = task_dir / "agent" / "claude-code.txt"

    usage = extract_tool_usage_from_trajectory(trajectory_path)
    if usage.get("tool_calls_total") is None:
        usage = extract_tool_usage_from_transcript(transcript_path)

    if usage.get("tool_calls_total") is None:
        return None

    by_name = usage.get("tool_calls_by_name") or {}
    top5 = dict(Counter(by_name).most_common(5))

    return {
        "tool_calls_total": usage["tool_calls_total"],
        "tool_calls_mcp": usage["tool_calls_mcp"],
        "tool_calls_local": usage["tool_calls_local"],
        "mcp_ratio": usage["mcp_ratio"],
        "top_5_tools": top5,
    }


def _extract_code_changes(task_dir: Path) -> Optional[list[dict]]:
    """Extract code changes from trajectory or transcript Edit/Write tool calls.

    Returns a list of {file, action} dicts, or None if not available.
    """
    trajectory_path = task_dir / "agent" / "trajectory.json"
    transcript_path = task_dir / "agent" / "claude-code.txt"

    changes: list[dict] = []

    # Try trajectory first
    if trajectory_path.is_file():
        try:
            data = json.loads(trajectory_path.read_text())
            for step in data.get("steps") or []:
                for tc in step.get("tool_calls") or []:
                    name = tc.get("function_name", "")
                    if name in ("Edit", "Write"):
                        inp = tc.get("input") or {}
                        fp = inp.get("file_path") or inp.get("path", "")
                        if fp:
                            changes.append({"file": fp, "action": name.lower()})
        except (OSError, json.JSONDecodeError):
            pass

    # Fallback to transcript if no changes from trajectory
    if not changes and transcript_path.is_file():
        try:
            lines = transcript_path.read_text().splitlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                message = entry.get("message") or {}
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if name in ("Edit", "Write"):
                            inp = block.get("input") or {}
                            fp = inp.get("file_path") or inp.get("path", "")
                            if fp:
                                changes.append({"file": fp, "action": name.lower()})
        except OSError:
            pass

    if not changes:
        return None

    # Deduplicate by file, keeping unique entries
    seen = set()
    unique = []
    for c in changes:
        key = (c["file"], c["action"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


def _read_verifier_output(task_dir: Path) -> Optional[str]:
    """Read verifier output from test-stdout.txt or reward.txt."""
    test_stdout = task_dir / "verifier" / "test-stdout.txt"
    text = _read_text_file(test_stdout)
    if text:
        return text

    reward_txt = task_dir / "verifier" / "reward.txt"
    text = _read_text_file(reward_txt)
    if text:
        return f"reward: {text.strip()}"

    return None


def _find_task_dirs(runs_dir: Path) -> list[dict]:
    """Walk runs_dir and return metadata for each task directory found.

    Returns list of dicts with keys: task_dir, run_name, benchmark, config_name,
    model, timestamp.
    """
    import re
    from .discovery import _infer_benchmark, _extract_model_from_config, _extract_batch_timestamp

    results = []
    if not runs_dir.is_dir():
        return results

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        run_name = run_dir.name
        benchmark = _infer_benchmark(run_name)

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name

            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir() or not _is_batch_dir(batch_dir):
                    continue

                model = _extract_model_from_config(batch_dir)
                timestamp = _extract_batch_timestamp(batch_dir)

                for task_dir in sorted(batch_dir.iterdir()):
                    if not _is_task_dir(task_dir):
                        continue

                    # Get task_id from result.json if available
                    result_json = task_dir / "result.json"
                    task_id = None
                    reward = None
                    partial_score = None
                    if result_json.is_file():
                        try:
                            data = json.loads(result_json.read_text())
                            task_id = data.get("task_name")
                            vr = (data.get("verifier_result") or {}).get("rewards") or {}
                            if "reward" in vr:
                                try:
                                    reward = float(vr["reward"])
                                except (TypeError, ValueError):
                                    pass
                        except (OSError, json.JSONDecodeError):
                            pass

                    if not task_id:
                        task_id = _extract_task_id(task_dir.name)

                    results.append({
                        "task_dir": task_dir,
                        "task_id": task_id,
                        "run_name": run_name,
                        "benchmark": benchmark,
                        "config_name": config_name,
                        "model": model,
                        "timestamp": timestamp,
                        "reward": reward,
                        "partial_score": partial_score,
                    })

    return results


def generate_judge_contexts(
    runs_dir: str | Path,
    benchmarks_dir: str | Path,
    output_dir: str | Path,
) -> list[dict]:
    """Generate per-task LLM judge context JSON files.

    Args:
        runs_dir: Path to Harbor runs/official/ directory.
        benchmarks_dir: Path to benchmarks/ directory with task definitions.
        output_dir: Where to write judge context files.

    Returns:
        List of index entries (task_id, benchmark, config, path).
    """
    runs_dir = Path(runs_dir)
    benchmarks_dir = Path(benchmarks_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task_entries = _find_task_dirs(runs_dir)

    # Deduplicate: keep latest per (benchmark, config, task_id)
    deduped: dict[tuple[str, str, str], dict] = {}
    for entry in task_entries:
        key = (entry["benchmark"], entry["config_name"], entry["task_id"])
        deduped[key] = entry  # later batches overwrite earlier

    index = []
    for (benchmark, config_name, task_id), entry in sorted(deduped.items()):
        task_dir = entry["task_dir"]

        # Read task instructions from benchmarks
        instructions = _read_instruction(benchmarks_dir, benchmark, task_id)

        # Read ground truth
        ground_truth = _read_ground_truth(benchmarks_dir, benchmark, task_id)

        # Extract transcript summary
        transcript_path = task_dir / "agent" / "claude-code.txt"
        transcript_summary = _extract_transcript_summary(transcript_path)

        # Extract agent output
        agent_output = _extract_agent_output(task_dir)

        # Extract tool usage summary
        tool_usage = _extract_tool_usage_summary(task_dir)

        # Extract code changes
        code_changes = _extract_code_changes(task_dir)

        # Read verifier output
        verifier_output = _read_verifier_output(task_dir)

        # SWE-bench partial score
        partial_score = entry.get("partial_score")
        if "swebench" in benchmark.lower():
            from .extractors import extract_swebench_partial_score
            test_stdout = task_dir / "verifier" / "test-stdout.txt"
            partial_score = extract_swebench_partial_score(test_stdout)

        # Build context
        context = {
            "task_id": task_id,
            "benchmark": benchmark,
            "config_name": config_name,
            "model": entry["model"],
            "reward": entry["reward"],
            "partial_score": partial_score,
            "task_instructions": instructions,
            "agent_transcript_summary": transcript_summary,
            "agent_output": agent_output,
            "ground_truth": ground_truth,
            "tool_usage_summary": tool_usage,
            "code_changes": code_changes,
            "verifier_output": verifier_output,
            "run_metadata": {
                "model": entry["model"],
                "config_name": config_name,
                "benchmark": benchmark,
                "timestamp": entry["timestamp"],
                "run_name": entry["run_name"],
            },
        }

        # Write context file
        ctx_dir = output_dir / benchmark / config_name
        ctx_dir.mkdir(parents=True, exist_ok=True)
        ctx_path = ctx_dir / f"{task_id}_judge_context.json"
        ctx_path.write_text(json.dumps(context, indent=2) + "\n")

        index.append({
            "task_id": task_id,
            "benchmark": benchmark,
            "config": config_name,
            "path": str(ctx_path.relative_to(output_dir)),
        })

    # Write index file
    index_path = output_dir / "judge_contexts_index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n")

    return index


def main() -> None:
    """CLI entry point for generating judge context files."""
    parser = argparse.ArgumentParser(
        description="Generate per-task LLM judge context files for evaluation.",
    )
    parser.add_argument(
        "--runs-dir",
        default=str(Path.home() / "evals/custom_agents/agents/claudecode/runs/official"),
        help="Path to Harbor runs/official/ directory (default: ~/evals/.../runs/official/)",
    )
    parser.add_argument(
        "--benchmarks-dir",
        default="./benchmarks",
        help="Path to benchmarks/ directory with task definitions (default: ./benchmarks/)",
    )
    parser.add_argument(
        "--output-dir",
        default="./judge_contexts",
        help="Directory to write judge context JSON files (default: ./judge_contexts/)",
    )

    args = parser.parse_args()
    runs_dir = Path(args.runs_dir)
    benchmarks_dir = Path(args.benchmarks_dir)
    output_dir = Path(args.output_dir)

    if not runs_dir.is_dir():
        print(f"Error: runs directory not found: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning runs: {runs_dir}")
    print(f"Benchmarks:    {benchmarks_dir}")
    print(f"Output:        {output_dir}")
    print()

    index = generate_judge_contexts(runs_dir, benchmarks_dir, output_dir)

    # Print summary
    benchmarks = sorted({e["benchmark"] for e in index})
    configs = sorted({e["config"] for e in index})
    print(f"Generated {len(index)} judge context files")
    print(f"Benchmarks: {', '.join(benchmarks)}")
    print(f"Configs:    {', '.join(configs)}")
    print(f"Index:      {output_dir / 'judge_contexts_index.json'}")


if __name__ == "__main__":
    main()
