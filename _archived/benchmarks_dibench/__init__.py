"""
DI-Bench Adapter for Harbor

Converts DI-Bench (Dependency Inference Benchmark) tasks to Harbor format.
"""

from .adapter import DIBenchAdapter, DIBenchLoader, DIBenchInstance

__version__ = "0.1.0"
__all__ = ["DIBenchAdapter", "DIBenchLoader", "DIBenchInstance"]
