"""
Kubernetes Documentation Benchmark Agents.

Specialized agent variants that filter documentation from Sourcegraph results.
"""

from .doc_benchmark_agents import (
    DocBenchmarkDeepSearchAgent,
    DocBenchmarkKeywordOnlyAgent,
    DocBenchmarkBaselineAgent,
    DOC_BENCHMARK_AGENTS,
    get_agent_class,
)

__all__ = [
    "DocBenchmarkDeepSearchAgent",
    "DocBenchmarkKeywordOnlyAgent",
    "DocBenchmarkBaselineAgent",
    "DOC_BENCHMARK_AGENTS",
    "get_agent_class",
]
