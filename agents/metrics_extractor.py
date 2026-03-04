"""
Metrics Extractor for Claude Code Agent Trials.

Parses claude-code.txt (JSON lines) and result.json to extract:
- Cost & Token Usage
- Time & Performance
- Tool Usage (including MCP tools)
- Code Changes
- Task Completion status
"""

import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class TimingMetrics:
    wall_clock_seconds: float = 0.0
    agent_execution_seconds: float = 0.0
    agent_setup_seconds: float = 0.0
    environment_setup_seconds: float = 0.0
    verifier_seconds: float = 0.0


@dataclass
class CostMetrics:
    total_usd: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cached_read: int = 0
    tokens_cached_creation: int = 0
    tokens_total: int = 0


@dataclass
class ToolMetrics:
    all_tools_called: dict = field(default_factory=dict)
    mcp_tools_used: bool = False
    mcp_tools_list: list = field(default_factory=list)
    mcp_servers: list = field(default_factory=list)
    permission_denials: list = field(default_factory=list)


@dataclass
class CodeChangeMetrics:
    files_modified: list = field(default_factory=list)
    files_created: list = field(default_factory=list)
    files_explored: list = field(default_factory=list)
    total_files_touched: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0


@dataclass
class TrialMetrics:
    trial_id: str = ""
    agent: str = ""
    agent_import_path: str = ""
    dataset: str = ""
    task_id: str = ""
    model: str = ""
    timestamp: str = ""
    
    reward_score: float = 0.0
    status: str = "unknown"  # passed, failed, error, timeout
    
    timing: TimingMetrics = field(default_factory=TimingMetrics)
    cost: CostMetrics = field(default_factory=CostMetrics)
    tools: ToolMetrics = field(default_factory=ToolMetrics)
    code_changes: CodeChangeMetrics = field(default_factory=CodeChangeMetrics)
    
    steps_to_completion: int = 0
    final_summary: str = ""
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "trial_id": self.trial_id,
            "agent": self.agent,
            "agent_import_path": self.agent_import_path,
            "dataset": self.dataset,
            "task_id": self.task_id,
            "model": self.model,
            "timestamp": self.timestamp,
            "reward_score": self.reward_score,
            "status": self.status,
            "timing": asdict(self.timing),
            "cost": asdict(self.cost),
            "tools": asdict(self.tools),
            "code_changes": asdict(self.code_changes),
            "steps_to_completion": self.steps_to_completion,
            "final_summary": self.final_summary,
            "error_message": self.error_message,
        }


class TrialMetricsExtractor:
    """Extract metrics from a single trial directory."""
    
    def __init__(self, trial_dir: Path):
        self.trial_dir = Path(trial_dir)
        self.agent_dir = self.trial_dir / "agent"
        self.claude_code_file = self.agent_dir / "claude-code.txt"
        self.trial_result_file = self.trial_dir / "result.json"
        
    def extract(self) -> TrialMetrics:
        """Extract all metrics from the trial."""
        metrics = TrialMetrics()
        
        # Parse result.json for basic info
        self._parse_result_json(metrics)
        
        # Parse claude-code.txt for detailed metrics
        self._parse_claude_code(metrics)
        
        return metrics
    
    def _parse_result_json(self, metrics: TrialMetrics) -> None:
        """Parse harbor result.json for trial metadata and reward."""
        if not self.trial_result_file.exists():
            return
            
        try:
            with open(self.trial_result_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return
        
        # Basic identification
        metrics.trial_id = data.get("trial_name", "")
        metrics.task_id = data.get("task_name", "")
        metrics.dataset = data.get("source", "")
        
        # Agent info
        config = data.get("config", {})
        agent_config = config.get("agent", {})
        metrics.agent_import_path = agent_config.get("import_path", "")
        metrics.model = agent_config.get("model_name", "")
        
        # Derive agent variant from import path
        if "SourcegraphMCPAgent" in metrics.agent_import_path:
            metrics.agent = "sourcegraph_mcp"
        elif "DeepSearchMCPAgent" in metrics.agent_import_path:
            metrics.agent = "deepsearch_mcp"
        elif "BaselineClaudeCodeAgent" in metrics.agent_import_path:
            metrics.agent = "baseline"
        else:
            metrics.agent = "unknown"
        
        # Reward/status
        verifier_result = data.get("verifier_result", {})
        rewards = verifier_result.get("rewards", {})
        metrics.reward_score = rewards.get("reward", 0.0)
        metrics.status = "passed" if metrics.reward_score >= 1.0 else "failed"
        
        # Exception info
        exception_info = data.get("exception_info")
        if exception_info:
            metrics.status = "error"
            metrics.error_message = str(exception_info)
        
        # Timing from result.json
        metrics.timestamp = data.get("started_at", "")
        
        started = data.get("started_at")
        finished = data.get("finished_at")
        if started and finished:
            try:
                start_dt = datetime.fromisoformat(started)
                end_dt = datetime.fromisoformat(finished)
                metrics.timing.wall_clock_seconds = (end_dt - start_dt).total_seconds()
            except ValueError:
                pass
        
        # Component timing
        for component, attr in [
            ("agent_execution", "agent_execution_seconds"),
            ("agent_setup", "agent_setup_seconds"),
            ("environment_setup", "environment_setup_seconds"),
            ("verifier", "verifier_seconds"),
        ]:
            comp_data = data.get(component, {})
            if comp_data:
                comp_start = comp_data.get("started_at")
                comp_end = comp_data.get("finished_at")
                if comp_start and comp_end:
                    try:
                        s = datetime.fromisoformat(comp_start)
                        e = datetime.fromisoformat(comp_end)
                        setattr(metrics.timing, attr, (e - s).total_seconds())
                    except ValueError:
                        pass
    
    def _parse_claude_code(self, metrics: TrialMetrics) -> None:
        """Parse claude-code.txt (JSON lines) for detailed metrics."""
        if not self.claude_code_file.exists():
            return
        
        tool_counts = Counter()
        mcp_tools = set()
        mcp_servers = []
        permission_denials = []
        files_explored = set()
        files_modified = []
        assistant_turns = 0
        final_text = ""
        
        try:
            with open(self.claude_code_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    entry_type = entry.get("type")
                    
                    # System init - extract MCP servers and model
                    if entry_type == "system" and entry.get("subtype") == "init":
                        servers = entry.get("mcp_servers", [])
                        mcp_servers = [
                            {"name": s.get("name"), "status": s.get("status")}
                            for s in servers
                        ]
                        if not metrics.model:
                            metrics.model = entry.get("model", "")
                    
                    # Assistant messages - extract tool calls and text
                    elif entry_type == "assistant":
                        message = entry.get("message", {})
                        content = message.get("content", [])
                        
                        for item in content:
                            if item.get("type") == "tool_use":
                                tool_name = item.get("name", "")
                                tool_counts[tool_name] += 1
                                
                                # Track MCP tools
                                if tool_name.startswith("mcp__"):
                                    mcp_tools.add(tool_name)
                                
                                # Track file exploration
                                tool_input = item.get("input", {})
                                if tool_name in ("Read", "Grep", "Glob"):
                                    file_path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("file")
                                    if file_path:
                                        files_explored.add(file_path)
                                
                                # Track file modifications
                                if tool_name == "Edit":
                                    file_path = tool_input.get("file_path", "")
                                    old_str = tool_input.get("old_string", "")
                                    new_str = tool_input.get("new_string", "")
                                    if file_path:
                                        lines_removed = len(old_str.split('\n')) if old_str else 0
                                        lines_added = len(new_str.split('\n')) if new_str else 0
                                        files_modified.append({
                                            "path": file_path,
                                            "operation": "edit",
                                            "lines_added": lines_added,
                                            "lines_removed": lines_removed,
                                        })
                                        
                                elif tool_name == "Write":
                                    file_path = tool_input.get("file_path", "")
                                    content = tool_input.get("content", "")
                                    if file_path:
                                        lines_added = len(content.split('\n')) if content else 0
                                        files_modified.append({
                                            "path": file_path,
                                            "operation": "write",
                                            "lines_added": lines_added,
                                            "lines_removed": 0,
                                        })
                            
                            elif item.get("type") == "text":
                                final_text = item.get("text", "")
                        
                        assistant_turns += 1
                    
                    # Result entry - extract final cost/usage
                    elif entry_type == "result":
                        usage = entry.get("usage", {})
                        metrics.cost.tokens_input = usage.get("input_tokens", 0)
                        metrics.cost.tokens_output = usage.get("output_tokens", 0)
                        metrics.cost.tokens_cached_read = usage.get("cache_read_input_tokens", 0)
                        metrics.cost.tokens_cached_creation = usage.get("cache_creation_input_tokens", 0)
                        metrics.cost.tokens_total = (
                            metrics.cost.tokens_input +
                            metrics.cost.tokens_output +
                            metrics.cost.tokens_cached_read +
                            metrics.cost.tokens_cached_creation
                        )
                        metrics.cost.total_usd = entry.get("total_cost_usd", 0.0)
                        
                        # Permission denials
                        permission_denials = entry.get("permission_denials", [])
                        
                        # Duration
                        duration_ms = entry.get("duration_ms", 0)
                        if duration_ms and not metrics.timing.agent_execution_seconds:
                            metrics.timing.agent_execution_seconds = duration_ms / 1000.0
                        
                        # Turns
                        metrics.steps_to_completion = entry.get("num_turns", assistant_turns)
                        
                        # Final summary from result
                        result_text = entry.get("result", "")
                        if result_text:
                            final_text = result_text
        
        except IOError:
            return
        
        # Populate metrics
        metrics.tools.all_tools_called = dict(tool_counts)
        metrics.tools.mcp_tools_used = len(mcp_tools) > 0
        metrics.tools.mcp_tools_list = sorted(list(mcp_tools))
        metrics.tools.mcp_servers = mcp_servers
        metrics.tools.permission_denials = permission_denials
        
        metrics.code_changes.files_explored = sorted(list(files_explored))
        metrics.code_changes.files_modified = files_modified
        
        # Aggregate code change stats
        total_added = sum(f.get("lines_added", 0) for f in files_modified)
        total_removed = sum(f.get("lines_removed", 0) for f in files_modified)
        metrics.code_changes.total_lines_added = total_added
        metrics.code_changes.total_lines_removed = total_removed
        metrics.code_changes.total_files_touched = len(set(
            f.get("path") for f in files_modified
        ))
        
        if not metrics.steps_to_completion:
            metrics.steps_to_completion = assistant_turns
        
        # Truncate final summary if too long
        if len(final_text) > 2000:
            metrics.final_summary = final_text[:2000] + "..."
        else:
            metrics.final_summary = final_text


def extract_trial_metrics(trial_dir: str | Path) -> TrialMetrics:
    """Convenience function to extract metrics from a trial directory."""
    extractor = TrialMetricsExtractor(Path(trial_dir))
    return extractor.extract()


def extract_job_metrics(job_dir: str | Path) -> list[TrialMetrics]:
    """Extract metrics from all trials in a job directory."""
    job_dir = Path(job_dir)
    trials = []
    
    # Find all trial subdirectories (contain result.json)
    for trial_path in job_dir.iterdir():
        if trial_path.is_dir() and (trial_path / "result.json").exists():
            metrics = extract_trial_metrics(trial_path)
            trials.append(metrics)
    
    return trials


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python metrics_extractor.py <trial_dir>")
        sys.exit(1)
    
    trial_dir = Path(sys.argv[1])
    metrics = extract_trial_metrics(trial_dir)
    
    print(json.dumps(metrics.to_dict(), indent=2))
