"""
Agents module for Claude Code ablation studies.

This module provides:
- Agent implementations (MCP agents, baseline agents)
- Metrics extraction from trial data
- Metrics aggregation for analysis
- Report generation for comparisons
- Ablation study configuration parsing
"""

from .metrics_extractor import (
    TrialMetrics,
    TrialMetricsExtractor,
    extract_trial_metrics,
    extract_job_metrics,
)

from .metrics_aggregator import (
    AgentMetrics,
    JobMetrics,
    aggregate_agent_metrics,
    aggregate_job_metrics,
    aggregate_from_job_directory,
    save_job_metrics,
)

from .report_generator import (
    generate_comparative_report,
    save_report,
)

from .ablation_config import (
    AblationJobConfig,
    AgentConfig,
    DatasetConfig,
    TasksConfig,
    EnvironmentConfig,
    OutputConfig,
    parse_ablation_config,
    create_example_config,
)

# Harness agents require the ``harbor`` package (only available inside
# Docker containers).  They are re-exported via __getattr__ so the rest
# of this package works without harbor installed.

__all__ = [
    # Metrics extraction
    "TrialMetrics",
    "TrialMetricsExtractor", 
    "extract_trial_metrics",
    "extract_job_metrics",
    
    # Aggregation
    "AgentMetrics",
    "JobMetrics",
    "aggregate_agent_metrics",
    "aggregate_job_metrics",
    "aggregate_from_job_directory",
    "save_job_metrics",
    
    # Reports
    "generate_comparative_report",
    "save_report",
    
    # Configuration
    "AblationJobConfig",
    "AgentConfig",
    "DatasetConfig",
    "TasksConfig",
    "EnvironmentConfig",
    "OutputConfig",
    "parse_ablation_config",
    "create_example_config",

    # Harness agents (lazy-imported, require harbor)
    "CodexHarnessAgent",
    "CopilotHarnessAgent",
    "CursorHarnessAgent",
    "GeminiHarnessAgent",
    "OpenHandsHarnessAgent",
]


_HARNESS_AGENTS = {
    "CodexHarnessAgent",
    "CopilotHarnessAgent",
    "CursorHarnessAgent",
    "GeminiHarnessAgent",
    "OpenHandsHarnessAgent",
}


def __getattr__(name):
    if name in _HARNESS_AGENTS:
        from . import harnesses
        return getattr(harnesses, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
