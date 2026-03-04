"""Manifest Builder - creates experiment manifest files.

The manifest tracks the overall experiment, all runs, and all pairs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lib.config.schema import ExperimentConfig
from lib.config.loader import get_config_hash
from lib.matrix.expander import RunSpec, PairSpec
from lib.runner.pair_scheduler import ScheduledRun, PairExecution


class ExperimentManifest:
    """Represents the manifest for an experiment."""
    
    SCHEMA_VERSION = "1.0.0"
    
    def __init__(
        self,
        experiment_id: str,
        config: ExperimentConfig,
        config_path: str | Path,
        config_hash: str
    ):
        self.experiment_id = experiment_id
        self.config = config
        self.config_path = str(config_path)
        self.config_hash = config_hash
        
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self.finished_at: str | None = None
        self.status = "created"
        
        self.runs: dict[str, dict] = {}
        self.pairs: dict[str, dict] = {}
    
    def add_run(self, run_spec: RunSpec) -> None:
        """Add a run to the manifest."""
        self.runs[run_spec.run_id] = {
            "run_id": run_spec.run_id,
            "status": "pending",
            "mcp_mode": run_spec.mcp_mode,
            "model": run_spec.model,
            "benchmark": run_spec.benchmark,
            "task_ids": run_spec.task_ids,
            "seed": run_spec.seed,
            "pair_id": run_spec.pair_id,
            "invariant_hash": run_spec.invariant_hash,
        }
    
    def add_pair(self, pair_spec: PairSpec) -> None:
        """Add a pair to the manifest."""
        self.pairs[pair_spec.pair_id] = {
            "pair_id": pair_spec.pair_id,
            "status": "pending",
            "baseline_run_id": pair_spec.baseline_run_id,
            "mcp_run_id": pair_spec.mcp_run_id,
            "mcp_mode": pair_spec.mcp_mode,
            "invariant_hash": pair_spec.invariant_hash,
        }
    
    def update_run(self, scheduled: ScheduledRun) -> None:
        """Update a run's status in the manifest."""
        if scheduled.run_spec.run_id in self.runs:
            self.runs[scheduled.run_spec.run_id].update({
                "status": scheduled.status.value,
                "started_at": scheduled.started_at,
                "finished_at": scheduled.finished_at,
            })
            
            if scheduled.result:
                self.runs[scheduled.run_spec.run_id].update({
                    "success": scheduled.result.success,
                    "duration_seconds": scheduled.result.duration_seconds,
                    "harbor_job_dir": str(scheduled.result.harbor_job_dir) if scheduled.result.harbor_job_dir else None,
                    "log_path": str(scheduled.result.log_path) if scheduled.result.log_path else None,
                    "error_message": scheduled.result.error_message,
                })
    
    def update_pair(self, pair_exec: PairExecution) -> None:
        """Update a pair's status in the manifest."""
        if pair_exec.pair_spec.pair_id in self.pairs:
            self.pairs[pair_exec.pair_spec.pair_id].update({
                "status": pair_exec.status.value,
            })
    
    def finalize(self, status: str = "completed") -> None:
        """Mark the experiment as finished."""
        self.finished_at = datetime.utcnow().isoformat() + "Z"
        self.status = status
    
    def to_dict(self) -> dict:
        """Convert manifest to dictionary."""
        return {
            "schema_version": self.SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "config": {
                "source_file": self.config_path,
                "config_hash": f"sha256:{self.config_hash}",
                "experiment_name": self.config.experiment_name,
                "description": self.config.description,
                "benchmarks": [b.name for b in self.config.benchmarks],
                "models": self.config.models,
                "mcp_modes": self.config.mcp_modes,
                "seeds": self.config.seeds,
                "tags": self.config.tags,
            },
            "matrix_summary": {
                "total_runs": len(self.runs),
                "total_pairs": len(self.pairs),
                "dimensions": self.config.get_matrix_dimensions(),
            },
            "runs": [
                {"run_id": r["run_id"], "status": r["status"], "mcp_mode": r["mcp_mode"]}
                for r in self.runs.values()
            ],
            "pairs": [
                {"pair_id": p["pair_id"], "status": p["status"], "mcp_mode": p["mcp_mode"]}
                for p in self.pairs.values()
            ],
        }
    
    def save(self, output_dir: Path) -> Path:
        """Save manifest to file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "manifest.json"
        
        with open(manifest_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        
        return manifest_path


class ManifestBuilder:
    """Builds and manages experiment manifests."""

    def __init__(self, output_root: str | Path = "runs", category: str | None = None):
        self.output_root = Path(output_root)
        self.category = category
        # Route through category subdirectory if provided
        if self.category:
            self.output_root = self.output_root / self.category
        self.output_root.mkdir(parents=True, exist_ok=True)
    
    def create(
        self,
        experiment_id: str,
        config: ExperimentConfig,
        config_path: str | Path,
        runs: list[RunSpec],
        pairs: list[PairSpec]
    ) -> ExperimentManifest:
        """Create a new experiment manifest.
        
        Args:
            experiment_id: Unique experiment identifier
            config: Experiment configuration
            config_path: Path to config file
            runs: List of run specifications
            pairs: List of pair specifications
            
        Returns:
            ExperimentManifest instance
        """
        config_hash = get_config_hash(config_path)
        
        manifest = ExperimentManifest(
            experiment_id=experiment_id,
            config=config,
            config_path=config_path,
            config_hash=config_hash
        )
        
        for run in runs:
            manifest.add_run(run)
        
        for pair in pairs:
            manifest.add_pair(pair)
        
        manifest.status = "pending"
        
        return manifest
    
    def get_experiment_dir(self, experiment_id: str) -> Path:
        """Get the output directory for an experiment."""
        return self.output_root / experiment_id
    
    def get_runs_dir(self, experiment_id: str) -> Path:
        """Get the runs directory for an experiment."""
        return self.get_experiment_dir(experiment_id) / "runs"
    
    def get_pairs_dir(self, experiment_id: str) -> Path:
        """Get the pairs directory for an experiment."""
        return self.get_experiment_dir(experiment_id) / "pairs"
    
    def save_manifest(self, manifest: ExperimentManifest) -> Path:
        """Save manifest to the experiment directory."""
        exp_dir = self.get_experiment_dir(manifest.experiment_id)
        return manifest.save(exp_dir)
    
    def load_manifest(self, experiment_id: str) -> dict | None:
        """Load an existing manifest."""
        manifest_path = self.get_experiment_dir(experiment_id) / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                return json.load(f)
        return None
