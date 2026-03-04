"""Canonical Exporter - emits v2 canonical JSON outputs.

Converts Harbor outputs to the standardized v2 format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lib.matrix.expander import RunSpec
from lib.runner.pair_scheduler import ScheduledRun, PairExecution
from lib.runner.manifest import ExperimentManifest
from lib.exporter.harbor_parser import HarborParser, HarborJobResult


@dataclass
class CanonicalResults:
    """Canonical results for a single run."""
    schema_version: str = "1.0.0"
    
    run_id: str = ""
    experiment_id: str = ""
    pair_id: str | None = None
    
    invariants: dict = field(default_factory=dict)
    mcp_config: dict = field(default_factory=dict)
    timing: dict = field(default_factory=dict)
    summary_metrics: dict = field(default_factory=dict)
    per_task_metrics: list[dict] = field(default_factory=list)
    tool_usage: dict = field(default_factory=dict)
    harbor_artifacts: dict = field(default_factory=dict)
    
    error: dict | None = None


class V2Exporter:
    """Exports Harbor results to canonical v2 format.
    
    This exporter:
    1. Reads Harbor job/trial outputs
    2. Converts to canonical JSON schema
    3. Writes to runs/ directory structure
    
    The export is deterministic and idempotent.
    """
    
    SCHEMA_VERSION = "1.0.0"
    
    def __init__(
        self,
        output_root: str | Path = "runs",
        jobs_dir: str | Path = "runs"
    ):
        self.output_root = Path(output_root)
        self.jobs_dir = Path(jobs_dir)
        self.parser = HarborParser(jobs_dir)
    
    def export_run(
        self,
        scheduled: ScheduledRun,
        experiment_id: str
    ) -> Path | None:
        """Export a single run to canonical format.
        
        Args:
            scheduled: The scheduled run with results
            experiment_id: Parent experiment ID
            
        Returns:
            Path to the results.json file, or None on failure
        """
        run_spec = scheduled.run_spec
        result = scheduled.result
        
        if not result:
            return self._export_error_run(run_spec, experiment_id, "No execution result")
        
        harbor_job_result = None
        if result.harbor_job_dir and result.harbor_job_dir.exists():
            harbor_job_result = self.parser.parse_job(result.harbor_job_dir)
        
        canonical = CanonicalResults(
            schema_version=self.SCHEMA_VERSION,
            run_id=run_spec.run_id,
            experiment_id=experiment_id,
            pair_id=run_spec.pair_id,
        )
        
        canonical.invariants = {
            "invariant_hash": run_spec.invariant_hash,
            "benchmark": run_spec.benchmark,
            "benchmark_version": run_spec.benchmark_version,
            "task_ids": run_spec.task_ids,
            "model": run_spec.model,
            "seed": run_spec.seed,
            "agent": {
                "name": run_spec.agent_import_path.split(":")[-1],
                "import_path": run_spec.agent_import_path,
                "version": run_spec.agent_version,
            },
            "environment": {
                "type": run_spec.execution_config.get("environment", {}).get("type", "docker"),
                "backend": "local",
            }
        }
        
        mcp_enabled = run_spec.mcp_mode != "baseline"
        canonical.mcp_config = {
            "mcp_mode": run_spec.mcp_mode,
            "mcp_enabled": mcp_enabled,
            "mcp_servers": [],
            "mcp_config_hash": None,
        }
        
        if result.mcp_config:
            canonical.mcp_config.update({
                "mcp_servers": result.mcp_config.mcp_servers,
                "mcp_config_hash": result.mcp_config.mcp_config_hash,
            })
        
        canonical.timing = {
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_seconds": result.duration_seconds,
        }
        
        if harbor_job_result:
            canonical.summary_metrics = self._extract_summary_metrics(harbor_job_result)
            canonical.per_task_metrics = self._extract_per_task_metrics(harbor_job_result)
            canonical.tool_usage = self._extract_tool_usage(harbor_job_result)
        else:
            canonical.summary_metrics = {
                "total_tasks": len(run_spec.task_ids),
                "resolved": 0,
                "failed": 0,
                "errored": 1 if not result.success else 0,
                "resolution_rate": 0.0,
                "mean_reward": 0.0,
            }
        
        canonical.harbor_artifacts = {
            "job_dir": str(result.harbor_job_dir) if result.harbor_job_dir else None,
            "trial_dirs": [],
            "result_json": str(result.harbor_result_path) if result.harbor_result_path else None,
            "logs": [str(result.log_path)] if result.log_path else [],
        }
        
        if harbor_job_result:
            canonical.harbor_artifacts["trial_dirs"] = [
                str(t.trial_dir) for t in harbor_job_result.trials if t.trial_dir
            ]
        
        if not result.success:
            canonical.error = {
                "error_class": result.error_class,
                "error_message": result.error_message,
            }
        
        return self._write_results(canonical, experiment_id, run_spec.run_id)
    
    def _export_error_run(
        self,
        run_spec: RunSpec,
        experiment_id: str,
        error_message: str
    ) -> Path:
        """Export a run that failed before execution."""
        canonical = CanonicalResults(
            schema_version=self.SCHEMA_VERSION,
            run_id=run_spec.run_id,
            experiment_id=experiment_id,
            pair_id=run_spec.pair_id,
        )
        
        canonical.invariants = {
            "invariant_hash": run_spec.invariant_hash,
            "benchmark": run_spec.benchmark,
            "benchmark_version": run_spec.benchmark_version,
            "task_ids": run_spec.task_ids,
            "model": run_spec.model,
            "seed": run_spec.seed,
        }
        
        canonical.mcp_config = {
            "mcp_mode": run_spec.mcp_mode,
            "mcp_enabled": run_spec.mcp_mode != "baseline",
        }
        
        canonical.error = {
            "error_class": "ExportError",
            "error_message": error_message,
        }
        
        now = datetime.utcnow().isoformat() + "Z"
        canonical.timing = {
            "started_at": now,
            "finished_at": now,
            "duration_seconds": 0,
        }
        
        canonical.summary_metrics = {
            "total_tasks": len(run_spec.task_ids),
            "resolved": 0,
            "failed": 0,
            "errored": 1,
            "resolution_rate": 0.0,
            "mean_reward": 0.0,
        }
        
        return self._write_results(canonical, experiment_id, run_spec.run_id)
    
    def _extract_summary_metrics(self, job_result: HarborJobResult) -> dict:
        """Extract summary metrics from Harbor job result."""
        trials = job_result.trials
        total = len(trials)
        resolved = sum(1 for t in trials if t.resolved)
        errored = sum(1 for t in trials if t.error)
        failed = total - resolved - errored
        
        rewards = [t.reward for t in trials if t.reward is not None]
        mean_reward = sum(rewards) / len(rewards) if rewards else 0.0
        
        return {
            "total_tasks": total,
            "resolved": resolved,
            "failed": failed,
            "errored": errored,
            "resolution_rate": resolved / total if total > 0 else 0.0,
            "mean_reward": mean_reward,
        }
    
    def _extract_per_task_metrics(self, job_result: HarborJobResult) -> list[dict]:
        """Extract per-task metrics from Harbor job result."""
        metrics = []
        
        for trial in job_result.trials:
            task_metrics = {
                "task_id": trial.task_id,
                "resolved": trial.resolved,
                "reward": trial.reward,
                "error": trial.error,
                "duration_seconds": trial.duration_seconds,
                "agent_execution_seconds": trial.agent_execution_seconds,
                "verifier_seconds": trial.verifier_seconds,
            }
            metrics.append(task_metrics)
        
        return metrics
    
    def _extract_tool_usage(self, job_result: HarborJobResult) -> dict:
        """Aggregate tool usage across all trials."""
        total_calls = 0
        by_tool: dict[str, int] = {}
        mcp_calls = 0
        local_calls = 0
        
        for trial in job_result.trials:
            if trial.tool_usage:
                total_calls += trial.tool_usage.total_tool_calls
                mcp_calls += trial.tool_usage.mcp_tool_calls
                local_calls += trial.tool_usage.local_tool_calls
                
                for tool, count in trial.tool_usage.by_tool.items():
                    by_tool[tool] = by_tool.get(tool, 0) + count
        
        return {
            "total_tool_calls": total_calls,
            "by_tool": by_tool,
            "mcp_tool_calls": mcp_calls,
            "local_tool_calls": local_calls,
        }
    
    def _write_results(
        self,
        canonical: CanonicalResults,
        experiment_id: str,
        run_id: str
    ) -> Path:
        """Write canonical results to file."""
        run_dir = self.output_root / experiment_id / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        results_path = run_dir / "results.json"
        
        results_dict = {
            "schema_version": canonical.schema_version,
            "run_id": canonical.run_id,
            "experiment_id": canonical.experiment_id,
            "pair_id": canonical.pair_id,
            "invariants": canonical.invariants,
            "mcp_config": canonical.mcp_config,
            "timing": canonical.timing,
            "summary_metrics": canonical.summary_metrics,
            "per_task_metrics": canonical.per_task_metrics,
            "tool_usage": canonical.tool_usage,
            "harbor_artifacts": canonical.harbor_artifacts,
        }
        
        if canonical.error:
            results_dict["error"] = canonical.error
        
        with open(results_path, "w") as f:
            json.dump(results_dict, f, indent=2)
        
        harbor_ref_path = run_dir / "harbor_ref.json"
        with open(harbor_ref_path, "w") as f:
            json.dump(canonical.harbor_artifacts, f, indent=2)
        
        return results_path
    
    def export_experiment(
        self,
        manifest: ExperimentManifest,
        scheduled_runs: list[ScheduledRun],
        pair_executions: list[PairExecution]
    ) -> Path:
        """Export an entire experiment.
        
        Args:
            manifest: The experiment manifest
            scheduled_runs: List of executed runs
            pair_executions: List of pair executions
            
        Returns:
            Path to the experiment directory
        """
        exp_dir = self.output_root / manifest.experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        
        for scheduled in scheduled_runs:
            self.export_run(scheduled, manifest.experiment_id)
            manifest.update_run(scheduled)
        
        from lib.exporter.comparison import ComparisonBuilder
        comparison_builder = ComparisonBuilder(self.output_root)
        
        for pair_exec in pair_executions:
            comparison_builder.build_comparison(
                pair_exec,
                manifest.experiment_id,
                self
            )
            manifest.update_pair(pair_exec)
        
        manifest.finalize()
        manifest.save(exp_dir)
        
        self._write_index(manifest, scheduled_runs, pair_executions)
        
        return exp_dir
    
    def _write_index(
        self,
        manifest: ExperimentManifest,
        scheduled_runs: list[ScheduledRun],
        pair_executions: list[PairExecution]
    ) -> Path:
        """Write the index.json file for quick lookups."""
        exp_dir = self.output_root / manifest.experiment_id
        
        runs_by_mode: dict[str, list[str]] = {}
        runs_by_model: dict[str, list[str]] = {}
        runs_by_task: dict[str, list[str]] = {}
        
        for scheduled in scheduled_runs:
            run_spec = scheduled.run_spec
            
            mode = run_spec.mcp_mode
            if mode not in runs_by_mode:
                runs_by_mode[mode] = []
            runs_by_mode[mode].append(run_spec.run_id)
            
            model = run_spec.model
            if model not in runs_by_model:
                runs_by_model[model] = []
            runs_by_model[model].append(run_spec.run_id)
            
            for task_id in run_spec.task_ids:
                if task_id not in runs_by_task:
                    runs_by_task[task_id] = []
                runs_by_task[task_id].append(run_spec.run_id)
        
        pairs_by_task: dict[str, list[str]] = {}
        for pair_exec in pair_executions:
            for task_id in pair_exec.pair_spec.task_ids:
                if task_id not in pairs_by_task:
                    pairs_by_task[task_id] = []
                pairs_by_task[task_id].append(pair_exec.pair_spec.pair_id)
        
        baseline_rates = []
        mcp_rates = []
        for scheduled in scheduled_runs:
            if scheduled.result and scheduled.result.raw_harbor_result:
                rate = self._extract_resolution_rate(scheduled.result.raw_harbor_result)
                if scheduled.run_spec.mcp_mode == "baseline":
                    baseline_rates.append(rate)
                else:
                    mcp_rates.append(rate)
        
        baseline_mean = sum(baseline_rates) / len(baseline_rates) if baseline_rates else 0.0
        mcp_mean = sum(mcp_rates) / len(mcp_rates) if mcp_rates else 0.0
        improvement = ((mcp_mean - baseline_mean) / baseline_mean * 100) if baseline_mean > 0 else 0.0
        
        index = {
            "schema_version": self.SCHEMA_VERSION,
            "experiment_id": manifest.experiment_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "runs_by_mcp_mode": runs_by_mode,
            "runs_by_model": runs_by_model,
            "runs_by_task": runs_by_task,
            "pairs_by_task": pairs_by_task,
            "aggregate_stats": {
                "baseline": {
                    "total_runs": len(runs_by_mode.get("baseline", [])),
                    "mean_resolution_rate": baseline_mean,
                },
                "mcp": {
                    "total_runs": sum(len(v) for k, v in runs_by_mode.items() if k != "baseline"),
                    "mean_resolution_rate": mcp_mean,
                },
                "improvement_pct": improvement,
            }
        }
        
        index_path = exp_dir / "index.json"
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)
        
        return index_path
    
    def _extract_resolution_rate(self, harbor_result: dict) -> float:
        """Extract resolution rate from Harbor result."""
        stats = harbor_result.get("stats", {})
        evals = stats.get("evals", {})
        
        for eval_data in evals.values():
            n_trials = eval_data.get("n_trials", 0)
            reward_stats = eval_data.get("reward_stats", {})
            rewards = reward_stats.get("reward", {})
            
            resolved = len(rewards.get("1.0", []))
            if n_trials > 0:
                return resolved / n_trials
        
        return 0.0
