"""Matrix expansion for v2 experiments.

Expands a configuration into individual run specifications,
handling all combinations of benchmarks, models, MCP modes, seeds, and tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lib.config.schema import (
    ExperimentConfig,
    BenchmarkConfig,
    TaskSelectorType,
)
from lib.matrix.id_generator import (
    generate_experiment_id,
    generate_run_id,
    generate_pair_id,
    compute_invariant_hash,
)
from lib.config.loader import get_config_hash


@dataclass
class RunSpec:
    """Specification for a single evaluation run."""
    run_id: str
    experiment_id: str
    pair_id: str | None

    benchmark: str
    benchmark_version: str
    task_ids: list[str]

    model: str
    mcp_mode: str
    seed: int

    agent_import_path: str
    agent_version: str

    invariant_hash: str

    execution_config: dict = field(default_factory=dict)
    mcp_server_config: dict | None = None
    use_subscription: bool = False  # Use Claude Code subscription instead of API
    auth_json_path: str | None = None  # Path to subscription credentials JSON


@dataclass
class PairSpec:
    """Specification for a baseline + MCP pair."""
    pair_id: str
    experiment_id: str
    invariant_hash: str
    
    baseline_run_id: str
    mcp_run_id: str
    mcp_mode: str
    
    benchmark: str
    task_ids: list[str]
    model: str
    seed: int


class MatrixExpander:
    """Expands experiment config into individual run and pair specifications."""
    
    def __init__(self, config: ExperimentConfig, config_path: str | Path):
        self.config = config
        self.config_path = Path(config_path)
        self.config_hash = get_config_hash(config_path)
        self.experiment_id = generate_experiment_id(
            config.experiment_name,
            self.config_hash
        )
    
    def expand(self) -> tuple[list[RunSpec], list[PairSpec]]:
        """Expand configuration into run and pair specifications.
        
        Returns:
            Tuple of (list of RunSpecs, list of PairSpecs)
        """
        runs: list[RunSpec] = []
        pairs: list[PairSpec] = []
        
        pair_groups: dict[str, dict[str, RunSpec]] = {}
        
        for benchmark in self.config.benchmarks:
            task_ids = self._resolve_task_ids(benchmark)
            
            for model in self.config.models:
                for seed in self.config.seeds:
                    invariant_hash = compute_invariant_hash(
                        benchmark=benchmark.name,
                        benchmark_version=benchmark.version,
                        task_ids=task_ids,
                        model=model,
                        seed=seed,
                        agent_import_path=self.config.agent.import_path,
                        environment_type=self.config.execution.environment.type
                    )
                    
                    pair_key = f"{benchmark.name}|{model}|{seed}|{invariant_hash[:16]}"
                    pair_groups[pair_key] = {}
                    
                    for mcp_mode in self.config.mcp_modes:
                        task_key = "_".join(sorted(task_ids)[:3])[:30]
                        run_id = generate_run_id(
                            mcp_mode=mcp_mode,
                            model=model,
                            task_id=task_key,
                            seed=seed,
                            experiment_id=self.experiment_id
                        )
                        
                        mcp_server_config = None
                        if mcp_mode != "baseline":
                            mcp_server_config = self._get_mcp_server_config(mcp_mode)
                        
                        run_spec = RunSpec(
                            run_id=run_id,
                            experiment_id=self.experiment_id,
                            pair_id=None,
                            benchmark=benchmark.name,
                            benchmark_version=benchmark.version,
                            task_ids=task_ids,
                            model=model,
                            mcp_mode=mcp_mode,
                            seed=seed,
                            agent_import_path=self.config.agent.import_path,
                            agent_version=self.config.agent.version,
                            invariant_hash=invariant_hash,
                            execution_config={
                                "concurrency": self.config.execution.concurrency,
                                "timeout_seconds": self.config.execution.timeout_seconds,
                                "environment": {
                                    "type": self.config.execution.environment.type,
                                    "delete_containers": self.config.execution.environment.delete_containers,
                                }
                            },
                            mcp_server_config=mcp_server_config,
                            use_subscription=(self.config.agent.auth_mode == "subscription"),
                            auth_json_path=self.config.agent.auth_json_path
                        )
                        
                        runs.append(run_spec)
                        pair_groups[pair_key][mcp_mode] = run_spec
        
        if self.config.pairing.enabled:
            pairs = self._create_pairs(pair_groups)
            
            pair_lookup = {p.baseline_run_id: p.pair_id for p in pairs}
            pair_lookup.update({p.mcp_run_id: p.pair_id for p in pairs})
            for run in runs:
                if run.run_id in pair_lookup:
                    run.pair_id = pair_lookup[run.run_id]
        
        return runs, pairs
    
    def _resolve_task_ids(self, benchmark: BenchmarkConfig) -> list[str]:
        """Resolve task IDs based on task selector."""
        selector = benchmark.task_selector
        
        if selector.type == TaskSelectorType.EXPLICIT:
            return selector.task_ids or []
        
        if selector.type == TaskSelectorType.FILE:
            if selector.tasks_file:
                tasks_path = Path(selector.tasks_file)
                if tasks_path.exists():
                    with open(tasks_path) as f:
                        return [
                            line.strip()
                            for line in f
                            if line.strip() and not line.startswith("#")
                        ]
            return []
        
        if selector.type == TaskSelectorType.ALL:
            return ["__ALL__"]
        
        if selector.type == TaskSelectorType.RANDOM_SAMPLE:
            return [f"__SAMPLE_{selector.sample_size}_SEED_{selector.seed}__"]
        
        if selector.type == TaskSelectorType.TAGS:
            tags_str = ",".join(selector.include_tags or [])
            return [f"__TAGS_{tags_str}__"]
        
        return []
    
    def _get_mcp_server_config(self, mcp_mode: str) -> dict | None:
        """Get MCP server configuration for a mode."""
        if mcp_mode in self.config.mcp_servers:
            server = self.config.mcp_servers[mcp_mode]
            return {
                "type": server.type,
                "url_template": server.url_template,
                "command": server.command,
                "args": server.args,
                "headers": server.headers,
                "env": server.env,
            }
        
        if mcp_mode in ("deepsearch", "deepsearch_hybrid"):
            return {
                "type": "http",
                "url_template": "${SOURCEGRAPH_URL}/.api/mcp/deepsearch",
                "headers": {"Authorization": "token ${SOURCEGRAPH_ACCESS_TOKEN}"}
            }
        
        if mcp_mode in ("sourcegraph", "sourcegraph_full", "sourcegraph_base"):
            return {
                "type": "http",
                "url_template": "${SOURCEGRAPH_URL}/.api/mcp/v1",
                "headers": {"Authorization": "token ${SOURCEGRAPH_ACCESS_TOKEN}"}
            }
        
        return None
    
    def _create_pairs(
        self,
        pair_groups: dict[str, dict[str, RunSpec]]
    ) -> list[PairSpec]:
        """Create pair specifications from grouped runs."""
        pairs = []
        baseline_mode = self.config.pairing.baseline_mode
        
        for pair_key, runs_by_mode in pair_groups.items():
            if baseline_mode not in runs_by_mode:
                continue
            
            baseline_run = runs_by_mode[baseline_mode]
            
            for mcp_mode, mcp_run in runs_by_mode.items():
                if mcp_mode == baseline_mode:
                    continue
                
                pair_id = generate_pair_id(baseline_run.run_id, mcp_run.run_id)
                
                pair_spec = PairSpec(
                    pair_id=pair_id,
                    experiment_id=self.experiment_id,
                    invariant_hash=baseline_run.invariant_hash,
                    baseline_run_id=baseline_run.run_id,
                    mcp_run_id=mcp_run.run_id,
                    mcp_mode=mcp_mode,
                    benchmark=baseline_run.benchmark,
                    task_ids=baseline_run.task_ids,
                    model=baseline_run.model,
                    seed=baseline_run.seed
                )
                
                pairs.append(pair_spec)
        
        return pairs
    
    def get_summary(self) -> dict:
        """Get a summary of the matrix expansion."""
        runs, pairs = self.expand()
        
        return {
            "experiment_id": self.experiment_id,
            "config_hash": self.config_hash,
            "total_runs": len(runs),
            "total_pairs": len(pairs),
            "dimensions": self.config.get_matrix_dimensions(),
            "runs_by_mode": self._group_by(runs, lambda r: r.mcp_mode),
            "runs_by_model": self._group_by(runs, lambda r: r.model),
            "pairs_by_mode": self._group_by(pairs, lambda p: p.mcp_mode),
        }
    
    @staticmethod
    def _group_by(items: list, key_fn) -> dict[str, int]:
        """Group items by a key function and count."""
        counts: dict[str, int] = {}
        for item in items:
            key = key_fn(item)
            counts[key] = counts.get(key, 0) + 1
        return counts
