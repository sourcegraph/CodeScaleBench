"""Harbor Executor - wraps Harbor CLI for v2 runs.

Generates Harbor YAML configs and executes runs via the harbor CLI.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from lib.matrix.expander import RunSpec
from lib.mcp.configurator import MCPConfigurator, MCPConfigResult

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a Harbor execution."""
    run_id: str
    success: bool
    started_at: str
    finished_at: str
    duration_seconds: float
    
    harbor_job_dir: Path | None = None
    harbor_result_path: Path | None = None
    harbor_config_path: Path | None = None
    log_path: Path | None = None
    
    error_message: str | None = None
    error_class: str | None = None
    
    mcp_config: MCPConfigResult | None = None
    
    raw_harbor_result: dict | None = None


class HarborExecutor:
    """Executes runs via Harbor CLI.
    
    This class:
    1. Generates Harbor YAML configuration from RunSpec
    2. Sets up MCP configuration via MCPConfigurator
    3. Invokes `harbor run` command
    4. Captures and returns results
    """
    
    def __init__(
        self,
        jobs_dir: str | Path = "runs",
        logs_dir: str | Path = "logs",
        generated_dir: str | Path = ".generated/v2",
        harbor_registry_url: str | None = None,
        force_rebuild: bool = False,
        category: str | None = None
    ):
        self.jobs_dir = Path(jobs_dir)
        # Route through category subdirectory if provided
        if category:
            self.jobs_dir = self.jobs_dir / category
        self.logs_dir = Path(logs_dir)
        self.generated_dir = Path(generated_dir)
        self.harbor_registry_url = harbor_registry_url or (
            "https://raw.githubusercontent.com/laude-institute/harbor/refs/heads/main/registry.json"
        )
        self.force_rebuild = force_rebuild
        
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        
        self.mcp_configurator = MCPConfigurator(logs_dir=self.logs_dir)
    
    def execute(
        self,
        run_spec: RunSpec,
        dry_run: bool = False
    ) -> ExecutionResult:
        """Execute a single run via Harbor.
        
        Args:
            run_spec: Specification for the run
            dry_run: If True, generate config but don't execute
            
        Returns:
            ExecutionResult with execution details
        """
        started_at = datetime.utcnow().isoformat() + "Z"
        
        try:
            harbor_config = self._generate_harbor_config(run_spec)
            config_path = self._write_harbor_config(run_spec, harbor_config)
            
            workspace_dir = self.generated_dir / run_spec.run_id
            workspace_dir.mkdir(parents=True, exist_ok=True)
            
            mcp_result = self.mcp_configurator.configure_for_run(
                workspace_dir=workspace_dir,
                mcp_mode=run_spec.mcp_mode,
                mcp_server_config=run_spec.mcp_server_config,
                workdir="/app"
            )
            
            if dry_run:
                finished_at = datetime.utcnow().isoformat() + "Z"
                return ExecutionResult(
                    run_id=run_spec.run_id,
                    success=True,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=0.0,
                    harbor_config_path=config_path,
                    mcp_config=mcp_result,
                )
            
            env = self._build_env(run_spec, mcp_result)
            log_path = self._get_log_path(run_spec)
            
            job_name = self._get_job_name(run_spec)
            job_dir = self.jobs_dir / job_name
            
            # Clean up old job directory before force rebuild to avoid permission errors
            if self.force_rebuild and job_dir.exists():
                try:
                    # Try regular rmtree first
                    import shutil
                    shutil.rmtree(job_dir)
                except (PermissionError, OSError):
                    # If permission error, try with sudo (for Docker-created files)
                    try:
                        subprocess.run(["sudo", "rm", "-rf", str(job_dir)], check=True)
                    except subprocess.CalledProcessError as e:
                        print(f"Warning: Could not clean up old job directory {job_dir}: {e}")
            
            # Pass expected task count and timeout for validation
            expected_tasks = len(run_spec.task_ids) if run_spec.task_ids else None
            task_timeout = run_spec.execution_config.get("timeout_seconds", 3600)
            result = self._run_harbor(
                config_path, env, log_path, 
                force_rebuild=self.force_rebuild,
                expected_task_count=expected_tasks,
                task_timeout_seconds=task_timeout
            )
            
            finished_at = datetime.utcnow().isoformat() + "Z"
            duration = (
                datetime.fromisoformat(finished_at.rstrip("Z")) -
                datetime.fromisoformat(started_at.rstrip("Z"))
            ).total_seconds()
            
            harbor_result = None
            harbor_result_path = job_dir / "result.json"
            if harbor_result_path.exists():
                with open(harbor_result_path) as f:
                    harbor_result = json.load(f)
            
            return ExecutionResult(
                run_id=run_spec.run_id,
                success=result["success"],
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                harbor_job_dir=job_dir if job_dir.exists() else None,
                harbor_result_path=harbor_result_path if harbor_result_path.exists() else None,
                harbor_config_path=config_path,
                log_path=log_path,
                error_message=result.get("error"),
                mcp_config=mcp_result,
                raw_harbor_result=harbor_result,
            )
            
        except Exception as e:
            finished_at = datetime.utcnow().isoformat() + "Z"
            duration = (
                datetime.fromisoformat(finished_at.rstrip("Z")) -
                datetime.fromisoformat(started_at.rstrip("Z"))
            ).total_seconds()
            
            return ExecutionResult(
                run_id=run_spec.run_id,
                success=False,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error_message=str(e),
                error_class=type(e).__name__,
            )
    
    def _generate_harbor_config(self, run_spec: RunSpec) -> dict:
        """Generate Harbor YAML configuration from RunSpec."""
        job_name = self._get_job_name(run_spec)
        
        config = {
            "job_name": job_name,
            "agents": [
                {
                    "name": run_spec.run_id,
                    "import_path": run_spec.agent_import_path,
                    "model_name": run_spec.model,
                }
            ],
            "datasets": [
                {
                    "registry": {
                        "url": self.harbor_registry_url
                    },
                    "name": run_spec.benchmark,
                    "version": run_spec.benchmark_version,
                }
            ],
            "orchestrator": {
                "type": "local",
                "n_concurrent_trials": run_spec.execution_config.get("concurrency", 1),
            },
            "environment": {
                "type": run_spec.execution_config.get("environment", {}).get("type", "docker"),
                "delete": run_spec.execution_config.get("environment", {}).get("delete_containers", self.force_rebuild),
            }
        }
        
        if run_spec.task_ids and run_spec.task_ids[0] not in ("__ALL__",) and not run_spec.task_ids[0].startswith("__"):
            config["datasets"][0]["task_names"] = run_spec.task_ids
        
        return config
    
    def _write_harbor_config(self, run_spec: RunSpec, config: dict) -> Path:
        """Write Harbor config to file."""
        config_path = self.generated_dir / f"{run_spec.run_id}_harbor.yaml"
        
        header = f"""# Auto-generated Harbor config for v2 run
# Run ID: {run_spec.run_id}
# Experiment ID: {run_spec.experiment_id}
# MCP Mode: {run_spec.mcp_mode}
# Generated: {datetime.utcnow().isoformat()}Z

"""
        
        with open(config_path, "w") as f:
            f.write(header)
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        return config_path
    
    def _build_env(self, run_spec: RunSpec, mcp_result: MCPConfigResult) -> dict[str, str]:
        """Build environment variables for Harbor run."""
        env = dict(os.environ)

        env.update(mcp_result.env_vars)

        env_json = {}
        # Handle API key: use subscription access token if in subscription mode
        if run_spec.use_subscription:
            # If auth_json_path is specified, load credentials from that file
            subscription_token = None
            if run_spec.auth_json_path:
                try:
                    auth_path = Path(run_spec.auth_json_path)
                    if auth_path.exists():
                        auth_data = json.load(open(auth_path))
                        subscription_token = auth_data.get("access_token") or auth_data.get("token")
                        if subscription_token:
                            logger.info(f"HarborExecutor: Loaded subscription token from {run_spec.auth_json_path}")
                except Exception as e:
                    logger.warning(f"HarborExecutor: Failed to load auth from {run_spec.auth_json_path}: {e}")
            # Fall back to environment variable
            if not subscription_token:
                subscription_token = os.environ.get("_SUBSCRIPTION_ACCESS_TOKEN")
            if subscription_token:
                env_json["ANTHROPIC_API_KEY"] = subscription_token
                logger.info("HarborExecutor: Using subscription OAuth access token as API key")
            else:
                logger.warning("HarborExecutor: Subscription mode enabled but no access token found")
        else:
            # Regular API mode
            if os.environ.get("ANTHROPIC_API_KEY"):
                env_json["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
        if os.environ.get("OPENAI_API_KEY"):
            env_json["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]
        if mcp_result.mcp_enabled and os.environ.get("SOURCEGRAPH_ACCESS_TOKEN"):
            env_json["SOURCEGRAPH_ACCESS_TOKEN"] = os.environ["SOURCEGRAPH_ACCESS_TOKEN"]
        
        # Extract repo and commit from first task ID for sg-evals org
        # Task ID format: instance_REPO__REPO-FULL_HASH
        # Extract: repo--HASH_FIRST_8_CHARS
        if run_spec.task_ids and len(run_spec.task_ids) > 0:
            task_id = run_spec.task_ids[0]
            repo_commit = self._extract_repo_commit(task_id)
            if repo_commit:
                env["SWEBENCH_REPO_COMMIT"] = repo_commit

        # Set subscription mode flag for agent to use
        if run_spec.use_subscription:
            env["USE_SUBSCRIPTION"] = "true"
            logger.info(f"HarborExecutor: Using subscription mode (no API key required)")

        env["HARBOR_ENV_JSON"] = json.dumps(env_json)
        
        return env
    
    def _extract_repo_commit(self, task_id: str) -> str | None:
        """Extract repo--commit from task ID.
        
        Task ID format: instance_REPO__REPO-FULL_HASH
        Example: instance_navidrome__navidrome-bf2bcb12799b21069f137749e0c331f761d1f693
        
        Returns: repo--HASH_FIRST_8_CHARS (e.g., navidrome--bf2bcb12)
        """
        try:
            # Split on "__" to get the second part
            if "__" not in task_id:
                return None
            
            repo_hash_part = task_id.split("__")[1]
            
            # Split on "-" to separate repo from hash
            parts = repo_hash_part.split("-", 1)
            if len(parts) != 2:
                return None
            
            repo_name = parts[0]
            full_hash = parts[1]
            short_hash = full_hash[:8]
            
            return f"{repo_name}--{short_hash}"
        except Exception:
            return None
    
    def _get_log_path(self, run_spec: RunSpec) -> Path:
        """Get log file path for a run."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return self.logs_dir / f"{run_spec.run_id}_{timestamp}.log"
    
    def _get_job_name(self, run_spec: RunSpec) -> str:
        """Get Harbor job name for a run."""
        return f"{run_spec.benchmark}_{run_spec.run_id}"
    
    def _count_completed_tasks_from_config(self, config_path: Path) -> int:
        """Count how many tasks actually completed by checking result.json files.
        
        Parses the Harbor config to find the job directory, then counts
        instance_*/result.json files to see how many tasks actually ran.
        """
        import yaml
        
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            
            job_name = config.get("job_name")
            if not job_name:
                return 0
            
            job_dir = self.jobs_dir / job_name
            if not job_dir.exists():
                return 0
            
            # Count instance directories with result.json
            completed = 0
            for instance_dir in job_dir.glob("instance_*"):
                result_file = instance_dir / "result.json"
                if result_file.exists():
                    completed += 1
            
            return completed
        except Exception as e:
            logger.warning(f"Could not count completed tasks: {e}")
            return 0
    
    def _run_harbor(
        self,
        config_path: Path,
        env: dict[str, str],
        log_path: Path,
        force_rebuild: bool = False,
        expected_task_count: int | None = None,
        task_timeout_seconds: int | None = None
    ) -> dict:
        """Execute harbor run command.
        
        Args:
            config_path: Path to Harbor YAML config
            env: Environment variables
            log_path: Where to write logs
            force_rebuild: Force Docker rebuild
            expected_task_count: Expected number of tasks to run (for validation)
            task_timeout_seconds: Timeout per task (to calculate total timeout)
        
        Returns:
            dict with success, return_code, error, and actual_task_count
        """
        env_json = env.pop("HARBOR_ENV_JSON", "{}")
        
        cmd = [
            "harbor", "run",
            "-c", str(config_path),
            "--jobs-dir", str(self.jobs_dir),
            "--ek", f"env={env_json}"
        ]
        
        if force_rebuild:
            cmd.append("--force-build")
        
        # Calculate total timeout: (expected_task_count × task_timeout) + 1 hour overhead
        # If not provided, default to 4 hours
        if expected_task_count and task_timeout_seconds:
            total_timeout = (expected_task_count * task_timeout_seconds) + 3600
            logger.info(f"Harbor timeout: {total_timeout}s ({expected_task_count} tasks × {task_timeout_seconds}s + 1h overhead)")
        else:
            total_timeout = 14400  # 4 hours default
        
        with open(log_path, "w") as log_file:
            try:
                result = subprocess.run(
                    cmd,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    timeout=total_timeout,
                    check=False
                )
                
                # Extract Harbor job ID from config to verify task completion
                actual_task_count = None
                if expected_task_count:
                    actual_task_count = self._count_completed_tasks_from_config(config_path)
                    task_mismatch = actual_task_count != expected_task_count
                else:
                    task_mismatch = False
                
                # CRITICAL: Fail if task counts don't match
                # This prevents silent partial runs that skew results
                success = result.returncode == 0 and not task_mismatch
                error = None
                if result.returncode != 0:
                    error = f"Harbor exit code {result.returncode}"
                if task_mismatch:
                    # Make this a hard failure
                    success = False
                    error = f"TASK COUNT MISMATCH: Expected {expected_task_count} tasks but only {actual_task_count} completed. Harbor likely timed out or crashed mid-batch."
                
                return {
                    "success": success,
                    "return_code": result.returncode,
                    "error": error,
                    "expected_tasks": expected_task_count,
                    "actual_tasks": actual_task_count,
                }
                
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "return_code": -1,
                    "error": "Harbor run timed out after 2 hours",
                    "expected_tasks": expected_task_count,
                    "actual_tasks": None,
                }
            except FileNotFoundError:
                return {
                    "success": False,
                    "return_code": -1,
                    "error": "Harbor CLI not found. Is it installed?",
                    "expected_tasks": expected_task_count,
                    "actual_tasks": None,
                }
            except Exception as e:
                return {
                    "success": False,
                    "return_code": -1,
                    "error": str(e),
                    "expected_tasks": expected_task_count,
                    "actual_tasks": None,
                }


def check_harbor_installed() -> bool:
    """Check if Harbor CLI is installed and accessible."""
    try:
        # Use --help since harbor doesn't support --version
        result = subprocess.run(
            ["harbor", "--help"],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
