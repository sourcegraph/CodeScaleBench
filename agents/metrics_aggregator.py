"""
Metrics Aggregator for Ablation Studies.

Aggregates trial metrics into:
- Agent-level summaries (per variant)
- Job-level comparative summaries
"""

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .metrics_extractor import TrialMetrics, extract_trial_metrics


@dataclass
class AgentMetrics:
    """Aggregated metrics for a single agent variant."""
    agent: str
    variant: str
    import_path: str = ""
    
    # Task counts
    tasks_completed: int = 0
    tasks_passed: int = 0
    tasks_failed: int = 0
    tasks_error: int = 0
    pass_rate: float = 0.0
    
    # Averages
    avg_wall_clock_seconds: float = 0.0
    avg_agent_execution_seconds: float = 0.0
    avg_cost_usd: float = 0.0
    avg_tokens_input: float = 0.0
    avg_tokens_output: float = 0.0
    avg_tokens_total: float = 0.0
    avg_tools_called: float = 0.0
    avg_mcp_tools_called: float = 0.0
    avg_steps_to_completion: float = 0.0
    avg_files_modified: float = 0.0
    avg_lines_added: float = 0.0
    
    # Medians
    median_wall_clock_seconds: float = 0.0
    median_cost_usd: float = 0.0
    median_steps_to_completion: float = 0.0
    
    # Aggregates
    total_cost_usd: float = 0.0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_files_modified: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    
    # MCP usage
    mcp_used: bool = False
    mcp_usage_rate: float = 0.0
    mcp_tools_seen: list = field(default_factory=list)
    
    # Trial details
    trials: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent": self.agent,
            "variant": self.variant,
            "import_path": self.import_path,
            "task_counts": {
                "completed": self.tasks_completed,
                "passed": self.tasks_passed,
                "failed": self.tasks_failed,
                "error": self.tasks_error,
                "pass_rate": self.pass_rate,
            },
            "averages": {
                "wall_clock_seconds": self.avg_wall_clock_seconds,
                "agent_execution_seconds": self.avg_agent_execution_seconds,
                "cost_usd": self.avg_cost_usd,
                "tokens_input": self.avg_tokens_input,
                "tokens_output": self.avg_tokens_output,
                "tokens_total": self.avg_tokens_total,
                "tools_called": self.avg_tools_called,
                "mcp_tools_called": self.avg_mcp_tools_called,
                "steps_to_completion": self.avg_steps_to_completion,
                "files_modified": self.avg_files_modified,
                "lines_added": self.avg_lines_added,
            },
            "medians": {
                "wall_clock_seconds": self.median_wall_clock_seconds,
                "cost_usd": self.median_cost_usd,
                "steps_to_completion": self.median_steps_to_completion,
            },
            "aggregates": {
                "total_cost_usd": self.total_cost_usd,
                "total_tokens_input": self.total_tokens_input,
                "total_tokens_output": self.total_tokens_output,
                "total_files_modified": self.total_files_modified,
                "total_lines_added": self.total_lines_added,
                "total_lines_removed": self.total_lines_removed,
            },
            "mcp_usage": {
                "used": self.mcp_used,
                "usage_rate": self.mcp_usage_rate,
                "tools_seen": self.mcp_tools_seen,
            },
            "trial_ids": [t.trial_id for t in self.trials],
        }


@dataclass
class JobMetrics:
    """Aggregated metrics for an entire ablation study job."""
    job_name: str
    description: str = ""
    timestamp: str = ""
    dataset: str = ""
    tasks_evaluated: int = 0
    
    agents: dict = field(default_factory=dict)  # agent_name -> AgentMetrics
    
    # Comparative stats
    comparative_stats: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "job_name": self.job_name,
            "description": self.description,
            "timestamp": self.timestamp,
            "dataset": self.dataset,
            "tasks_evaluated": self.tasks_evaluated,
            "agents": {
                name: agent.to_dict() 
                for name, agent in self.agents.items()
            },
            "comparative_stats": self.comparative_stats,
        }


def _safe_mean(values: list) -> float:
    """Calculate mean, returning 0 for empty lists."""
    return statistics.mean(values) if values else 0.0


def _safe_median(values: list) -> float:
    """Calculate median, returning 0 for empty lists."""
    return statistics.median(values) if values else 0.0


def aggregate_agent_metrics(trials: list[TrialMetrics], agent_name: str) -> AgentMetrics:
    """Aggregate metrics from multiple trials for a single agent."""
    if not trials:
        return AgentMetrics(agent=agent_name, variant=agent_name)
    
    metrics = AgentMetrics(
        agent=agent_name,
        variant=trials[0].agent if trials else agent_name,
        import_path=trials[0].agent_import_path if trials else "",
        trials=trials,
    )
    
    # Count tasks
    metrics.tasks_completed = len(trials)
    metrics.tasks_passed = sum(1 for t in trials if t.status == "passed")
    metrics.tasks_failed = sum(1 for t in trials if t.status == "failed")
    metrics.tasks_error = sum(1 for t in trials if t.status == "error")
    metrics.pass_rate = metrics.tasks_passed / metrics.tasks_completed if metrics.tasks_completed > 0 else 0.0
    
    # Collect values for averaging
    wall_clocks = [t.timing.wall_clock_seconds for t in trials if t.timing.wall_clock_seconds > 0]
    agent_execs = [t.timing.agent_execution_seconds for t in trials if t.timing.agent_execution_seconds > 0]
    costs = [t.cost.total_usd for t in trials if t.cost.total_usd > 0]
    tokens_in = [t.cost.tokens_input for t in trials]
    tokens_out = [t.cost.tokens_output for t in trials]
    tokens_total = [t.cost.tokens_total for t in trials]
    steps = [t.steps_to_completion for t in trials if t.steps_to_completion > 0]
    files_mod = [t.code_changes.total_files_touched for t in trials]
    lines_added = [t.code_changes.total_lines_added for t in trials]
    
    # Tool usage counts
    total_tools = [sum(t.tools.all_tools_called.values()) for t in trials]
    mcp_tools = [len(t.tools.mcp_tools_list) for t in trials]
    mcp_used_count = sum(1 for t in trials if t.tools.mcp_tools_used)
    
    # Calculate averages
    metrics.avg_wall_clock_seconds = _safe_mean(wall_clocks)
    metrics.avg_agent_execution_seconds = _safe_mean(agent_execs)
    metrics.avg_cost_usd = _safe_mean(costs)
    metrics.avg_tokens_input = _safe_mean(tokens_in)
    metrics.avg_tokens_output = _safe_mean(tokens_out)
    metrics.avg_tokens_total = _safe_mean(tokens_total)
    metrics.avg_tools_called = _safe_mean(total_tools)
    metrics.avg_mcp_tools_called = _safe_mean(mcp_tools)
    metrics.avg_steps_to_completion = _safe_mean(steps)
    metrics.avg_files_modified = _safe_mean(files_mod)
    metrics.avg_lines_added = _safe_mean(lines_added)
    
    # Calculate medians
    metrics.median_wall_clock_seconds = _safe_median(wall_clocks)
    metrics.median_cost_usd = _safe_median(costs)
    metrics.median_steps_to_completion = _safe_median(steps)
    
    # Calculate aggregates
    metrics.total_cost_usd = sum(costs)
    metrics.total_tokens_input = sum(tokens_in)
    metrics.total_tokens_output = sum(tokens_out)
    metrics.total_files_modified = sum(files_mod)
    metrics.total_lines_added = sum(lines_added)
    metrics.total_lines_removed = sum(t.code_changes.total_lines_removed for t in trials)
    
    # MCP usage
    metrics.mcp_used = mcp_used_count > 0
    metrics.mcp_usage_rate = mcp_used_count / metrics.tasks_completed if metrics.tasks_completed > 0 else 0.0
    all_mcp_tools = set()
    for t in trials:
        all_mcp_tools.update(t.tools.mcp_tools_list)
    metrics.mcp_tools_seen = sorted(list(all_mcp_tools))
    
    return metrics


def aggregate_job_metrics(
    trials_by_agent: dict[str, list[TrialMetrics]],
    job_name: str,
    description: str = "",
    dataset: str = "",
) -> JobMetrics:
    """Aggregate metrics from all agents in a job."""
    job = JobMetrics(
        job_name=job_name,
        description=description,
        timestamp=datetime.now().isoformat(),
        dataset=dataset,
    )
    
    # Aggregate per-agent metrics
    all_tasks = set()
    for agent_name, trials in trials_by_agent.items():
        agent_metrics = aggregate_agent_metrics(trials, agent_name)
        job.agents[agent_name] = agent_metrics
        for trial in trials:
            all_tasks.add(trial.task_id)
    
    job.tasks_evaluated = len(all_tasks)
    
    # Build comparative stats
    job.comparative_stats = _build_comparative_stats(job.agents)
    
    return job


def _build_comparative_stats(agents: dict[str, AgentMetrics]) -> dict:
    """Build comparative statistics across agents."""
    if not agents:
        return {}
    
    stats = {
        "pass_rates": {},
        "cost_efficiency": {},
        "speed": {},
        "mcp_usage": {},
    }
    
    for name, agent in agents.items():
        stats["pass_rates"][name] = agent.pass_rate
        
        stats["cost_efficiency"][name] = {
            "usd_per_task": agent.avg_cost_usd,
            "tokens_per_task": agent.avg_tokens_total,
        }
        
        stats["speed"][name] = {
            "avg_seconds": agent.avg_wall_clock_seconds,
            "median_seconds": agent.median_wall_clock_seconds,
            "avg_steps": agent.avg_steps_to_completion,
        }
        
        stats["mcp_usage"][name] = {
            "used": agent.mcp_used,
            "usage_rate": agent.mcp_usage_rate,
            "tools": agent.mcp_tools_seen,
            "avg_mcp_calls": agent.avg_mcp_tools_called,
        }
    
    # Add rankings
    if len(agents) > 1:
        # Rank by pass rate (higher is better)
        pass_rate_ranking = sorted(
            agents.keys(),
            key=lambda k: agents[k].pass_rate,
            reverse=True
        )
        stats["rankings"] = {
            "by_pass_rate": pass_rate_ranking,
            "by_cost": sorted(
                agents.keys(),
                key=lambda k: agents[k].avg_cost_usd
            ),
            "by_speed": sorted(
                agents.keys(),
                key=lambda k: agents[k].avg_wall_clock_seconds
            ),
        }
    
    return stats


def aggregate_from_job_directory(job_dir: str | Path) -> JobMetrics:
    """
    Aggregate metrics from a job directory structure.
    
    Expected structure:
    job_dir/
      {trial_dir}/
        result.json
        agent/
          claude-code.txt
    """
    job_dir = Path(job_dir)
    
    # Collect trials by agent variant
    trials_by_agent = defaultdict(list)
    
    for trial_path in job_dir.iterdir():
        if not trial_path.is_dir():
            continue
        
        result_file = trial_path / "result.json"
        if not result_file.exists():
            continue
        
        try:
            metrics = extract_trial_metrics(trial_path)
            agent_name = metrics.agent or "unknown"
            trials_by_agent[agent_name].append(metrics)
        except Exception as e:
            print(f"Warning: Failed to extract metrics from {trial_path}: {e}")
    
    job_name = job_dir.name
    
    # Try to get dataset from first trial
    dataset = ""
    for trials in trials_by_agent.values():
        if trials and trials[0].dataset:
            dataset = trials[0].dataset
            break
    
    return aggregate_job_metrics(
        dict(trials_by_agent),
        job_name=job_name,
        dataset=dataset,
    )


def save_job_metrics(job_metrics: JobMetrics, output_dir: str | Path) -> Path:
    """Save job metrics to JSON files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save main summary
    summary_path = output_dir / "metrics_summary.json"
    with open(summary_path, "w") as f:
        json.dump(job_metrics.to_dict(), f, indent=2)
    
    # Save per-agent metrics
    for agent_name, agent_metrics in job_metrics.agents.items():
        agent_path = output_dir / f"agent_metrics_{agent_name}.json"
        with open(agent_path, "w") as f:
            json.dump(agent_metrics.to_dict(), f, indent=2)
    
    # Save individual trial metrics
    trials_dir = output_dir / "trials"
    trials_dir.mkdir(exist_ok=True)
    for agent_metrics in job_metrics.agents.values():
        for trial in agent_metrics.trials:
            trial_path = trials_dir / f"{trial.trial_id}.json"
            with open(trial_path, "w") as f:
                json.dump(trial.to_dict(), f, indent=2)
    
    return summary_path


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python metrics_aggregator.py <job_dir>")
        sys.exit(1)
    
    job_dir = Path(sys.argv[1])
    job_metrics = aggregate_from_job_directory(job_dir)
    
    print(json.dumps(job_metrics.to_dict(), indent=2))
