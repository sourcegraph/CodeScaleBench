"""Pair Scheduler - orchestrates baseline vs MCP paired runs.

Ensures that for each (task, model, seed) combination:
1. Baseline run executes first (or in parallel)
2. MCP run executes with identical invariants
3. Both runs are linked via pair_id and invariant_hash
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable

from lib.matrix.expander import RunSpec, PairSpec
from lib.runner.executor import HarborExecutor, ExecutionResult


class RunStatus(str, Enum):
    """Status of a scheduled run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ScheduledRun:
    """A run scheduled for execution."""
    run_spec: RunSpec
    status: RunStatus = RunStatus.PENDING
    result: ExecutionResult | None = None
    scheduled_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class PairExecution:
    """Tracks execution of a baseline + MCP pair."""
    pair_spec: PairSpec
    baseline_run: ScheduledRun
    mcp_run: ScheduledRun
    status: RunStatus = RunStatus.PENDING


class PairScheduler:
    """Schedules and executes paired baseline/MCP runs.
    
    Strategies:
    - Sequential: Run baseline first, then MCP
    - Parallel: Run both simultaneously (default)
    
    The scheduler ensures:
    1. Both runs share identical invariants
    2. Results are linked via pair_id
    3. Failures in one run don't block the other
    """
    
    def __init__(
        self,
        executor: HarborExecutor,
        parallel_pairs: bool = True,
        on_run_complete: Callable[[ScheduledRun], None] | None = None
    ):
        self.executor = executor
        self.parallel_pairs = parallel_pairs
        self.on_run_complete = on_run_complete
        
        self._runs: dict[str, ScheduledRun] = {}
        self._pairs: dict[str, PairExecution] = {}
    
    def schedule(
        self,
        runs: list[RunSpec],
        pairs: list[PairSpec]
    ) -> tuple[list[ScheduledRun], list[PairExecution]]:
        """Schedule runs and pairs for execution.
        
        Args:
            runs: List of run specifications
            pairs: List of pair specifications
            
        Returns:
            Tuple of (scheduled_runs, pair_executions)
        """
        now = datetime.utcnow().isoformat() + "Z"
        
        for run in runs:
            scheduled = ScheduledRun(
                run_spec=run,
                status=RunStatus.PENDING,
                scheduled_at=now
            )
            self._runs[run.run_id] = scheduled
        
        for pair in pairs:
            baseline = self._runs.get(pair.baseline_run_id)
            mcp = self._runs.get(pair.mcp_run_id)
            
            if baseline and mcp:
                pair_exec = PairExecution(
                    pair_spec=pair,
                    baseline_run=baseline,
                    mcp_run=mcp,
                    status=RunStatus.PENDING
                )
                self._pairs[pair.pair_id] = pair_exec
        
        return list(self._runs.values()), list(self._pairs.values())
    
    def execute_all(self, dry_run: bool = False) -> list[ScheduledRun]:
        """Execute all scheduled runs.
        
        Args:
            dry_run: If True, generate configs but don't execute
            
        Returns:
            List of completed ScheduledRuns
        """
        if self.parallel_pairs and self._pairs:
            return self._execute_pairs_parallel(dry_run)
        else:
            return self._execute_sequential(dry_run)
    
    def _execute_sequential(self, dry_run: bool) -> list[ScheduledRun]:
        """Execute all runs sequentially."""
        results = []
        
        for run_id, scheduled in self._runs.items():
            if scheduled.status != RunStatus.PENDING:
                continue
            
            scheduled.status = RunStatus.RUNNING
            scheduled.started_at = datetime.utcnow().isoformat() + "Z"
            
            result = self.executor.execute(scheduled.run_spec, dry_run=dry_run)
            
            scheduled.result = result
            scheduled.finished_at = datetime.utcnow().isoformat() + "Z"
            scheduled.status = RunStatus.COMPLETED if result.success else RunStatus.FAILED
            
            if self.on_run_complete:
                self.on_run_complete(scheduled)
            
            results.append(scheduled)
        
        return results
    
    def _execute_pairs_parallel(self, dry_run: bool) -> list[ScheduledRun]:
        """Execute paired runs in parallel within each pair."""
        results = []
        
        paired_run_ids = set()
        for pair in self._pairs.values():
            paired_run_ids.add(pair.baseline_run.run_spec.run_id)
            paired_run_ids.add(pair.mcp_run.run_spec.run_id)
        
        for run_id, scheduled in self._runs.items():
            if run_id in paired_run_ids:
                continue
            if scheduled.status != RunStatus.PENDING:
                continue
            
            self._execute_single(scheduled, dry_run)
            results.append(scheduled)
        
        for pair_id, pair_exec in self._pairs.items():
            pair_results = self._execute_pair(pair_exec, dry_run)
            results.extend(pair_results)
        
        return results
    
    def _execute_pair(self, pair_exec: PairExecution, dry_run: bool) -> list[ScheduledRun]:
        """Execute a single pair (baseline + MCP).
        
        For now, executes sequentially. Could be made truly parallel
        with asyncio or threading if needed.
        
        After both complete, validates that they ran the same tasks.
        """
        results = []
        pair_exec.status = RunStatus.RUNNING
        
        self._execute_single(pair_exec.baseline_run, dry_run)
        results.append(pair_exec.baseline_run)
        
        self._execute_single(pair_exec.mcp_run, dry_run)
        results.append(pair_exec.mcp_run)
        
        if pair_exec.baseline_run.status == RunStatus.COMPLETED and \
           pair_exec.mcp_run.status == RunStatus.COMPLETED:
            # Both runs completed - mark pair as completed
            # Task validation is handled by HarborExecutor (task count check)
            pair_exec.status = RunStatus.COMPLETED
            print(f"✓ {pair_exec.pair_spec.pair_id}: Pair completed successfully")
        else:
            pair_exec.status = RunStatus.FAILED
        
        return results
    
    def _execute_single(self, scheduled: ScheduledRun, dry_run: bool) -> None:
        """Execute a single run."""
        scheduled.status = RunStatus.RUNNING
        scheduled.started_at = datetime.utcnow().isoformat() + "Z"
        
        result = self.executor.execute(scheduled.run_spec, dry_run=dry_run)
        
        scheduled.result = result
        scheduled.finished_at = datetime.utcnow().isoformat() + "Z"
        scheduled.status = RunStatus.COMPLETED if result.success else RunStatus.FAILED
        
        if self.on_run_complete:
            self.on_run_complete(scheduled)
    
    def get_run(self, run_id: str) -> ScheduledRun | None:
        """Get a scheduled run by ID."""
        return self._runs.get(run_id)
    
    def get_pair(self, pair_id: str) -> PairExecution | None:
        """Get a pair execution by ID."""
        return self._pairs.get(pair_id)
    
    def get_status_summary(self) -> dict:
        """Get summary of run statuses."""
        run_counts = {}
        for scheduled in self._runs.values():
            status = scheduled.status.value
            run_counts[status] = run_counts.get(status, 0) + 1
        
        pair_counts = {}
        for pair_exec in self._pairs.values():
            status = pair_exec.status.value
            pair_counts[status] = pair_counts.get(status, 0) + 1
        
        return {
            "runs": run_counts,
            "pairs": pair_counts,
            "total_runs": len(self._runs),
            "total_pairs": len(self._pairs)
        }
