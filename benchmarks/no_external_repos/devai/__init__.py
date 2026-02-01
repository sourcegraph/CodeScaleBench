"""
DevAI benchmark adapter for Harbor.

DevAI is a benchmark suite featuring 55 tasks with 365 hierarchical requirements
for evaluating AI coding agents on real-world development scenarios.
"""

from benchmarks.devai.adapter import (
    DEVAI_DOMAINS,
    DevAILoader,
    DevAITask,
    Preference,
    Requirement,
)

__all__ = [
    "DEVAI_DOMAINS",
    "DevAILoader",
    "DevAITask",
    "Preference",
    "Requirement",
]
