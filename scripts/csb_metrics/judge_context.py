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

from .discovery import (
    _extract_task_id,
    _is_batch_dir,
    _is_task_dir,
    resolve_task_transcript_path,
)
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
        locobench -> benchmarks/ccb_locobench/tasks/<task_id>/instruction.md
        bigcode   -> benchmarks/ccb_largerepo/<task_id>/instruction.md
        k8s_docs  -> benchmarks/ccb_k8sdocs/<task_id>/instruction.md
        swebenchpro -> None (instructions come from Harbor dataset, not local)
    """
    if benchmark == "locobench":
        p = benchmarks_dir / "ccb_locobench" / "tasks" / task_id / "instruction.md"
    elif benchmark == "bigcode":
        p = benchmarks_dir / "ccb_largerepo" / task_id / "instruction.md"
    elif benchmark == "k8s_docs":
        p = benchmarks_dir / "ccb_k8sdocs" / task_id / "instruction.md"
    else:
        return None

    return _read_text_file(p)


def _read_ground_truth(benchmarks_dir: Path, benchmark: str, task_id: str) -> Optional[str]:
    """Read ground truth files for a task, concatenated into a single string.

    Looks in ground_truth/ directory. Returns None if not found.
    """
    if benchmark == "locobench":
        gt_dir = benchmarks_dir / "ccb_locobench" / "tasks" / task_id / "solution"
    elif benchmark == "bigcode":
        gt_dir = benchmarks_dir / "ccb_largerepo" / task_id / "solution"
    elif benchmark == "k8s_docs":
        gt_dir = benchmarks_dir / "ccb_k8sdocs" / task_id / "ground_truth"
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
    transcript_path = resolve_task_transcript_path(task_dir)
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
    transcript_path = resolve_task_transcript_path(task_dir)

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
    transcript_path = resolve_task_transcript_path(task_dir)

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


def _locobench_dimensions(
    task_dir: Path,
    ir_metrics_path: Optional[Path] = None,
    benchmarks_dir: Optional[Path] = None,
    task_id: Optional[str] = None,
) -> dict:
    """Return LoCoBench-inspired evaluation dimensions for ccb_largerepo tasks.

    Dimensions:
        ACS — Architectural Coherence Score: Does the agent understand the
              system's high-level architecture and locate the right modules?
        DTA — Dependency Traversal Accuracy: Can the agent trace dependency
              chains across files and packages?
        CFRD — Cross-File Reasoning Depth: How deeply does the agent reason
               about relationships spanning multiple source files?

    Each dimension is a rubric dict with keys:
        dimension, definition, scoring_scale, observable_evidence

    The function enriches evidence lists with data from ir_metrics.json (run
    output) and tests/ground_truth.json (benchmark source) when available.
    """
    # Attempt to read IR metrics from the task run directory
    ir_data: dict = {}
    if ir_metrics_path and ir_metrics_path.is_file():
        try:
            ir_data = json.loads(ir_metrics_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass

    # Attempt to read ground truth from the benchmarks directory
    gt_data: dict = {}
    if benchmarks_dir and task_id:
        gt_path = benchmarks_dir / "ccb_largerepo" / task_id / "tests" / "ground_truth.json"
        if gt_path.is_file():
            try:
                gt_data = json.loads(gt_path.read_text())
            except (OSError, json.JSONDecodeError):
                pass

    # Build evidence from IR metrics
    ir_evidence: list[str] = []
    for key in ("precision", "recall", "f1", "dependency_accuracy"):
        if key in ir_data:
            ir_evidence.append(f"{key}={ir_data[key]}")

    # Build evidence from ground truth
    gt_evidence: list[str] = []
    gt_files = gt_data.get("files") or []
    gt_dep_chain = gt_data.get("dependency_chain") or []
    if gt_files:
        gt_evidence.append(f"ground_truth_file_count={len(gt_files)}")
    if gt_dep_chain:
        gt_evidence.append(f"dependency_chain_length={len(gt_dep_chain)}")

    return {
        "architectural_coherence_score": {
            "dimension": "ACS",
            "definition": (
                "Measures whether the agent identifies the correct architectural "
                "modules and understands how they fit together in the system's "
                "overall design. A score of 5 means every relevant subsystem was "
                "identified and correctly described."
            ),
            "scoring_scale": "1-5",
            "observable_evidence": [
                "Agent references correct top-level packages/modules",
                "Agent identifies the right entry points for the task",
                "Agent's file list overlaps with ground truth files",
                *ir_evidence,
                *gt_evidence,
            ],
        },
        "dependency_traversal_accuracy": {
            "dimension": "DTA",
            "definition": (
                "Measures whether the agent correctly traces dependency chains "
                "across files — from API surface through internal layers to the "
                "implementation leaf. A score of 5 means the full dependency "
                "chain was traversed in the correct order."
            ),
            "scoring_scale": "1-5",
            "observable_evidence": [
                "Agent follows import/include chains accurately",
                "Agent identifies transitive dependencies, not just direct ones",
                "Agent's dependency ordering matches ground truth chain",
                *(
                    [f"ground_truth_dependency_chain={gt_dep_chain}"]
                    if gt_dep_chain
                    else []
                ),
                *(
                    [f"dependency_accuracy={ir_data['dependency_accuracy']}"]
                    if "dependency_accuracy" in ir_data
                    else []
                ),
            ],
        },
        "cross_file_reasoning_depth": {
            "dimension": "CFRD",
            "definition": (
                "Measures how deeply the agent reasons about relationships that "
                "span multiple source files — type hierarchies, shared state, "
                "callback registration, and cross-module contracts. A score of 5 "
                "means the agent demonstrates deep multi-file reasoning."
            ),
            "scoring_scale": "1-5",
            "observable_evidence": [
                "Agent explains cross-file type relationships",
                "Agent identifies shared state or callback patterns",
                "Agent traces data flow across module boundaries",
                *(
                    [f"files_examined_count={ir_data['agent_file_count']}"]
                    if "agent_file_count" in ir_data
                    else []
                ),
                *(
                    [f"file_recall={ir_data['recall']}"]
                    if "recall" in ir_data
                    else []
                ),
                *(
                    [f"file_precision={ir_data['precision']}"]
                    if "precision" in ir_data
                    else []
                ),
            ],
        },
    }


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
    selected_tasks_path: Optional[str | Path] = None,
) -> list[dict]:
    """Generate per-task LLM judge context JSON files.

    Args:
        runs_dir: Path to Harbor runs/official/ directory.
        benchmarks_dir: Path to benchmarks/ directory with task definitions.
        output_dir: Where to write judge context files.
        selected_tasks_path: Optional path to selected_benchmark_tasks.json.
            If provided, only generates contexts for canonical tasks and
            includes SDLC phase / MCP score metadata in each context.

    Returns:
        List of index entries (task_id, benchmark, config, path).
    """
    runs_dir = Path(runs_dir)
    benchmarks_dir = Path(benchmarks_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load task selection metadata if provided
    task_index: dict[str, dict] = {}
    if selected_tasks_path:
        sel_path = Path(selected_tasks_path)
        if sel_path.is_file():
            from .task_selection import load_selected_tasks, build_task_index
            selection = load_selected_tasks(sel_path)
            task_index = build_task_index(selection)

    task_entries = _find_task_dirs(runs_dir)

    # Deduplicate: keep latest per (benchmark, config, task_id)
    deduped: dict[tuple[str, str, str], dict] = {}
    for entry in task_entries:
        key = (entry["benchmark"], entry["config_name"], entry["task_id"])
        deduped[key] = entry  # later batches overwrite earlier

    index = []
    for (benchmark, config_name, task_id), entry in sorted(deduped.items()):
        # If task selection is loaded, skip tasks not in the canonical set
        if task_index and task_id not in task_index:
            continue

        task_dir = entry["task_dir"]

        # Read task instructions from benchmarks
        instructions = _read_instruction(benchmarks_dir, benchmark, task_id)

        # Read ground truth
        ground_truth = _read_ground_truth(benchmarks_dir, benchmark, task_id)

        # Extract transcript summary
        transcript_path = resolve_task_transcript_path(task_dir)
        transcript_summary = _extract_transcript_summary(transcript_path)

        # Extract agent output
        agent_output = _extract_agent_output(task_dir)

        # Extract tool usage summary
        tool_usage = _extract_tool_usage_summary(task_dir)

        # Extract code changes
        code_changes = _extract_code_changes(task_dir)

        # Read verifier output
        verifier_output = _read_verifier_output(task_dir)

        # LoCoBench dimensions for bigcode (ccb_largerepo) tasks
        locobench_dims = None
        if benchmark == "bigcode":
            ir_metrics_path = task_dir / "verifier" / "ir_metrics.json"
            locobench_dims = _locobench_dimensions(
                task_dir,
                ir_metrics_path=ir_metrics_path,
                benchmarks_dir=benchmarks_dir,
                task_id=task_id,
            )

        # SWE-bench partial score
        partial_score = entry.get("partial_score")
        if "swebench" in benchmark.lower():
            from .extractors import extract_swebench_partial_score
            test_stdout = task_dir / "verifier" / "test-stdout.txt"
            partial_score = extract_swebench_partial_score(test_stdout)

        # Build selection metadata if available
        selection_meta = {}
        if task_id in task_index:
            sel = task_index[task_id]
            selection_meta = {
                "sdlc_phase": sel.get("sdlc_phase"),
                "language": sel.get("language"),
                "category": sel.get("category"),
                "difficulty": sel.get("difficulty"),
                "mcp_benefit_score": sel.get("mcp_benefit_score"),
                "mcp_breakdown": sel.get("mcp_breakdown"),
                "selection_rationale": sel.get("selection_rationale"),
            }

        # Build context
        context = {
            "task_id": task_id,
            "benchmark": benchmark,
            "config_name": config_name,
            "model": entry["model"],
            "reward": entry["reward"],
            "partial_score": partial_score,
            "task_selection_metadata": selection_meta or None,
            "task_instructions": instructions,
            "agent_transcript_summary": transcript_summary,
            "agent_output": agent_output,
            "ground_truth": ground_truth,
            "tool_usage_summary": tool_usage,
            "code_changes": code_changes,
            "verifier_output": verifier_output,
            "locobench_dimensions": locobench_dims,
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
        default=str(Path(__file__).resolve().parent.parent.parent / "runs" / "official"),
        help="Path to Harbor runs/official/ directory (default: <project>/runs/official/)",
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
    parser.add_argument(
        "--selected-tasks",
        default="./configs/selected_benchmark_tasks.json",
        help="Path to selected_benchmark_tasks.json for filtering and metadata "
             "(default: ./configs/selected_benchmark_tasks.json). Set to empty string to disable.",
    )

    args = parser.parse_args()
    runs_dir = Path(args.runs_dir)
    benchmarks_dir = Path(args.benchmarks_dir)
    output_dir = Path(args.output_dir)
    selected = args.selected_tasks if args.selected_tasks else None

    if not runs_dir.is_dir():
        print(f"Error: runs directory not found: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning runs: {runs_dir}")
    print(f"Benchmarks:    {benchmarks_dir}")
    print(f"Output:        {output_dir}")
    if selected:
        print(f"Task selection: {selected}")
    print()

    index = generate_judge_contexts(runs_dir, benchmarks_dir, output_dir, selected)

    # Print summary
    benchmarks = sorted({e["benchmark"] for e in index})
    configs = sorted({e["config"] for e in index})
    print(f"Generated {len(index)} judge context files")
    print(f"Benchmarks: {', '.join(benchmarks)}")
    print(f"Configs:    {', '.join(configs)}")
    print(f"Index:      {output_dir / 'judge_contexts_index.json'}")


if __name__ == "__main__":
    main()
