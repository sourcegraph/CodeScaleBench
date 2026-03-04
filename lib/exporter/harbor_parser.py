"""Harbor Parser - parses Harbor job/trial outputs.

Extracts metrics, timing, and tool usage from Harbor artifacts.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolUsageStats:
    """Statistics about tool usage in a run."""
    total_tool_calls: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
    mcp_tool_calls: int = 0
    local_tool_calls: int = 0


@dataclass
class HarborTrialResult:
    """Parsed result from a single Harbor trial."""
    trial_name: str
    task_id: str
    task_name: str
    
    reward: float | None = None
    resolved: bool = False
    
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    
    agent_execution_seconds: float | None = None
    verifier_seconds: float | None = None
    environment_setup_seconds: float | None = None
    
    agent_info: dict | None = None
    verifier_result: dict | None = None
    
    error: str | None = None
    exception_info: dict | None = None
    
    tool_usage: ToolUsageStats | None = None
    
    trial_dir: Path | None = None
    trajectory_path: Path | None = None


@dataclass
class HarborJobResult:
    """Parsed result from a Harbor job."""
    job_id: str
    job_name: str
    
    started_at: str | None = None
    finished_at: str | None = None
    
    n_total_trials: int = 0
    n_errors: int = 0
    
    metrics: list[dict] = field(default_factory=list)
    reward_stats: dict = field(default_factory=dict)
    
    trials: list[HarborTrialResult] = field(default_factory=list)
    
    job_dir: Path | None = None
    config: dict | None = None


class HarborParser:
    """Parses Harbor job and trial outputs."""
    
    def __init__(self, jobs_dir: str | Path = "runs"):
        self.jobs_dir = Path(jobs_dir)
    
    def parse_job(self, job_dir: Path | str) -> HarborJobResult | None:
        """Parse a Harbor job directory.
        
        Args:
            job_dir: Path to the job directory
            
        Returns:
            HarborJobResult or None if parsing fails
        """
        job_dir = Path(job_dir)
        if not job_dir.exists():
            return None
        
        result_path = job_dir / "result.json"
        if not result_path.exists():
            return None
        
        try:
            with open(result_path) as f:
                result_data = json.load(f)
        except json.JSONDecodeError:
            return None
        
        config = None
        config_path = job_dir / "config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                pass
        
        job_result = HarborJobResult(
            job_id=result_data.get("id", ""),
            job_name=job_dir.name,
            started_at=result_data.get("started_at"),
            finished_at=result_data.get("finished_at"),
            n_total_trials=result_data.get("n_total_trials", 0),
            job_dir=job_dir,
            config=config,
        )
        
        stats = result_data.get("stats", {})
        job_result.n_errors = stats.get("n_errors", 0)
        
        evals = stats.get("evals", {})
        for eval_name, eval_data in evals.items():
            job_result.metrics = eval_data.get("metrics", [])
            job_result.reward_stats = eval_data.get("reward_stats", {})
            break
        
        for item in job_dir.iterdir():
            if item.is_dir() and item.name != "__pycache__":
                trial_result = self.parse_trial(item)
                if trial_result:
                    job_result.trials.append(trial_result)
        
        return job_result
    
    def parse_trial(self, trial_dir: Path | str) -> HarborTrialResult | None:
        """Parse a Harbor trial directory.
        
        Args:
            trial_dir: Path to the trial directory
            
        Returns:
            HarborTrialResult or None if parsing fails
        """
        trial_dir = Path(trial_dir)
        if not trial_dir.exists():
            return None
        
        result_path = trial_dir / "result.json"
        if not result_path.exists():
            return None
        
        try:
            with open(result_path) as f:
                result_data = json.load(f)
        except json.JSONDecodeError:
            return None
        
        verifier_result = result_data.get("verifier_result", {})
        rewards = verifier_result.get("rewards", {})
        reward = rewards.get("reward")
        
        timing_sections = {}
        for section in ["environment_setup", "agent_setup", "agent_execution", "verifier"]:
            section_data = result_data.get(section, {})
            if section_data:
                started = section_data.get("started_at")
                finished = section_data.get("finished_at")
                if started and finished:
                    try:
                        from datetime import datetime
                        start_dt = datetime.fromisoformat(started.replace("Z", "+00:00").rstrip("+00:00"))
                        end_dt = datetime.fromisoformat(finished.replace("Z", "+00:00").rstrip("+00:00"))
                        timing_sections[section] = (end_dt - start_dt).total_seconds()
                    except (ValueError, TypeError):
                        pass
        
        duration = None
        started_at = result_data.get("started_at")
        finished_at = result_data.get("finished_at")
        if started_at and finished_at:
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00").rstrip("+00:00"))
                end_dt = datetime.fromisoformat(finished_at.replace("Z", "+00:00").rstrip("+00:00"))
                duration = (end_dt - start_dt).total_seconds()
            except (ValueError, TypeError):
                pass
        
        trajectory_path = None
        agent_dir = trial_dir / "agent"
        if agent_dir.exists():
            claude_code_txt = agent_dir / "claude-code.txt"
            if claude_code_txt.exists():
                trajectory_path = claude_code_txt
        
        tool_usage = None
        if trajectory_path:
            tool_usage = self._extract_tool_usage(trajectory_path)
        
        trial_result = HarborTrialResult(
            trial_name=result_data.get("trial_name", trial_dir.name),
            task_id=result_data.get("task_name", ""),
            task_name=result_data.get("task_name", ""),
            reward=reward,
            resolved=reward == 1.0 if reward is not None else False,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            agent_execution_seconds=timing_sections.get("agent_execution"),
            verifier_seconds=timing_sections.get("verifier"),
            environment_setup_seconds=timing_sections.get("environment_setup"),
            agent_info=result_data.get("agent_info"),
            verifier_result=verifier_result,
            exception_info=result_data.get("exception_info"),
            error=str(result_data.get("exception_info")) if result_data.get("exception_info") else None,
            tool_usage=tool_usage,
            trial_dir=trial_dir,
            trajectory_path=trajectory_path,
        )
        
        return trial_result
    
    def _extract_tool_usage(self, trajectory_path: Path) -> ToolUsageStats:
        """Extract tool usage statistics from Claude Code output.
        
        Parses the claude-code.txt file to count tool invocations.
        """
        try:
            content = trajectory_path.read_text(errors="ignore")
        except Exception:
            return ToolUsageStats()
        
        tool_counts: dict[str, int] = defaultdict(int)
        mcp_tool_calls = 0
        local_tool_calls = 0
        
        tool_patterns = [
            r'"tool":\s*"(\w+)"',
            r'"name":\s*"(\w+)"',
            r'Tool:\s*(\w+)',
            r'Using tool:\s*(\w+)',
        ]
        
        for pattern in tool_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                tool_name = match.group(1)
                if tool_name.lower() not in ("true", "false", "null", "none"):
                    tool_counts[tool_name] += 1
        
        mcp_pattern = re.compile(r'mcp__\w+__\w+', re.IGNORECASE)
        for match in mcp_pattern.finditer(content):
            tool_name = match.group(0)
            tool_counts[tool_name] += 1
            mcp_tool_calls += 1
        
        standard_tools = {"Read", "Edit", "Bash", "Grep", "Glob", "Write", "Search"}
        for tool, count in tool_counts.items():
            if tool in standard_tools or not tool.startswith("mcp__"):
                local_tool_calls += count
        
        return ToolUsageStats(
            total_tool_calls=sum(tool_counts.values()),
            by_tool=dict(tool_counts),
            mcp_tool_calls=mcp_tool_calls,
            local_tool_calls=local_tool_calls - mcp_tool_calls,
        )
    
    def find_job_dir(self, run_id: str, benchmark: str) -> Path | None:
        """Find the Harbor job directory for a run.
        
        Args:
            run_id: The v2 run ID
            benchmark: Benchmark name
            
        Returns:
            Path to job directory or None
        """
        expected_name = f"{benchmark}_{run_id}"
        
        job_dir = self.jobs_dir / expected_name
        if job_dir.exists():
            return job_dir
        
        for item in self.jobs_dir.iterdir():
            if item.is_dir() and run_id in item.name:
                return item
        
        return None
