"""
Ablation Study Configuration Parser.

Parses YAML job configuration files for ablation studies, defining:
- Agent variants to compare
- Dataset and task selection
- Environment settings (model, concurrency, timeout)
- Output organization
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    """Configuration for a single agent variant."""
    name: str
    import_path: str
    variant: str = ""
    
    def __post_init__(self):
        if not self.variant:
            # Derive variant from import path
            if "SourcegraphMCPAgent" in self.import_path:
                self.variant = "mcp_sourcegraph"
            elif "DeepSearchMCPAgent" in self.import_path:
                self.variant = "mcp_deepsearch"
            elif "BaselineClaudeCodeAgent" in self.import_path:
                self.variant = "baseline"
            else:
                self.variant = self.name


@dataclass
class DatasetConfig:
    """Configuration for dataset selection."""
    name: str
    version: str = "1.0"
    
    @property
    def dataset_spec(self) -> str:
        """Return dataset@version format for harbor."""
        return f"{self.name}@{self.version}"


@dataclass
class TasksConfig:
    """Configuration for task selection."""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    all_tasks: bool = False
    
    def __post_init__(self):
        if not self.include:
            self.all_tasks = True


@dataclass
class EnvironmentConfig:
    """Configuration for execution environment."""
    model: str = "anthropic/claude-haiku-4-5"
    max_concurrent_trials: int = 1
    timeout_multiplier: float = 1.0


@dataclass
class OutputConfig:
    """Configuration for output organization."""
    jobs_dir: str = "test_claude_variants"
    
    def get_job_path(self, job_name: str) -> Path:
        """Get the full path for a job output directory."""
        return Path(self.jobs_dir) / job_name


@dataclass
class AblationJobConfig:
    """Complete configuration for an ablation study job."""
    name: str
    description: str = ""
    agents: list[AgentConfig] = field(default_factory=list)
    dataset: DatasetConfig = field(default_factory=lambda: DatasetConfig(name="swebench-verified"))
    tasks: TasksConfig = field(default_factory=TasksConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    
    def validate(self) -> list[str]:
        """Validate the configuration and return list of errors."""
        errors = []
        
        if not self.name:
            errors.append("Job name is required")
        
        if not self.agents:
            errors.append("At least one agent must be specified")
        
        for agent in self.agents:
            if not agent.import_path:
                errors.append(f"Agent '{agent.name}' must have an import_path")
        
        if not self.dataset.name:
            errors.append("Dataset name is required")
        
        return errors
    
    def get_trial_configurations(self) -> list[dict]:
        """Generate all trial configurations for this job."""
        trials = []
        
        tasks = self.tasks.include if not self.tasks.all_tasks else []
        
        for agent in self.agents:
            if tasks:
                for task in tasks:
                    if task not in self.tasks.exclude:
                        trials.append({
                            "agent": agent,
                            "task": task,
                            "dataset": self.dataset,
                            "environment": self.environment,
                        })
            else:
                # All tasks mode - task selection handled by harbor
                trials.append({
                    "agent": agent,
                    "task": None,  # Run all tasks
                    "dataset": self.dataset,
                    "environment": self.environment,
                })
        
        return trials


def parse_ablation_config(config_path: str | Path) -> AblationJobConfig:
    """Parse a YAML ablation study configuration file."""
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path) as f:
        raw_config = yaml.safe_load(f)
    
    if not raw_config:
        raise ValueError("Empty configuration file")
    
    # Handle 'job' wrapper if present
    if "job" in raw_config:
        job_config = raw_config["job"]
    else:
        job_config = raw_config
    
    # Parse agents
    agents = []
    for agent_data in job_config.get("agents", []):
        agents.append(AgentConfig(
            name=agent_data.get("name", ""),
            import_path=agent_data.get("import_path", ""),
            variant=agent_data.get("variant", ""),
        ))
    
    # Parse dataset
    dataset_data = job_config.get("dataset", {})
    dataset = DatasetConfig(
        name=dataset_data.get("name", "swebench-verified"),
        version=str(dataset_data.get("version", "1.0")),
    )
    
    # Parse tasks
    tasks_data = job_config.get("tasks", {})
    tasks = TasksConfig(
        include=tasks_data.get("include", []) if tasks_data else [],
        exclude=tasks_data.get("exclude", []) if tasks_data else [],
    )
    
    # Parse environment
    env_data = job_config.get("environment", {})
    environment = EnvironmentConfig(
        model=env_data.get("model", "anthropic/claude-haiku-4-5"),
        max_concurrent_trials=env_data.get("max_concurrent_trials", 1),
        timeout_multiplier=env_data.get("timeout_multiplier", 1.0),
    )
    
    # Parse output
    output_data = job_config.get("output", {})
    output = OutputConfig(
        jobs_dir=output_data.get("jobs_dir", "test_claude_variants"),
    )
    
    # Build config
    config = AblationJobConfig(
        name=job_config.get("name", ""),
        description=job_config.get("description", ""),
        agents=agents,
        dataset=dataset,
        tasks=tasks,
        environment=environment,
        output=output,
    )
    
    # Validate
    errors = config.validate()
    if errors:
        raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")
    
    return config


# Example YAML template
EXAMPLE_CONFIG_YAML = """
job:
  name: "sourcegraph_vs_baseline_swebench"
  description: "Compare Sourcegraph MCP vs Baseline on swebench-verified"

  agents:
    - name: "baseline"
      import_path: "agents.claude_baseline_agent:BaselineClaudeCodeAgent"
      variant: "baseline"
    - name: "sourcegraph_mcp"
      import_path: "agents.mcp_agents:SourcegraphMCPAgent"
      variant: "mcp_sourcegraph"
    # - name: "deepsearch_mcp"
    #   import_path: "agents.mcp_agents:DeepSearchMCPAgent"
    #   variant: "mcp_deepsearch"

  dataset:
    name: "swebench-verified"
    version: "1.0"

  tasks:
    # Option 1: All tasks (omit include or leave empty)
    # Option 2: Specific task list
    include:
      - "django__django-11179"
      # - "django__django-11180"
    exclude: []

  environment:
    model: "anthropic/claude-haiku-4-5"
    max_concurrent_trials: 2
    timeout_multiplier: 1.0

  output:
    jobs_dir: "test_claude_variants"
"""


def create_example_config(output_path: str | Path) -> None:
    """Create an example ablation study configuration file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(EXAMPLE_CONFIG_YAML)
    print(f"Created example config at: {output_path}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python ablation_config.py <config.yaml>")
        print("       python ablation_config.py --create-example <output.yaml>")
        sys.exit(1)
    
    if sys.argv[1] == "--create-example":
        output_path = sys.argv[2] if len(sys.argv) > 2 else "jobs/example_ablation.yaml"
        create_example_config(output_path)
    else:
        config = parse_ablation_config(sys.argv[1])
        print(f"Parsed config: {config.name}")
        print(f"  Agents: {[a.name for a in config.agents]}")
        print(f"  Dataset: {config.dataset.dataset_spec}")
        print(f"  Tasks: {config.tasks.include if config.tasks.include else 'all'}")
        print(f"  Model: {config.environment.model}")
        
        trials = config.get_trial_configurations()
        print(f"  Total trial configs: {len(trials)}")
