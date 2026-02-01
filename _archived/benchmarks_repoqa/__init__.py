"""
RepoQA Adapter for Harbor

Converts RepoQA benchmark instances into Harbor task format with three variants:
- SR-QA: Semantic Retrieval (find function by description)
- MD-QA: Multi-Hop Dependency (find call path)  
- NR-QA: Negative/Disambiguation (pick correct function among similar ones)

The adapter removes long-context memorization and focuses on tool-driven
semantic code navigation using Sourcegraph MCP.
"""

__version__ = "0.1.0"
__author__ = "CodeContextBench Team"

from .adapter import RepoQAAdapter, RepoQAInstance
from .ground_truth_extractor import (
    FunctionMetadata,
    PythonFunctionExtractor,
    RepositoryAnalyzer,
    extract_repository_ground_truth,
)
from .verifiers import (
    BaseVerifier,
    MultiHopDependencyQAVerifier,
    NegativeRetrievalQAVerifier,
    RepoQAVerifier,
    SemanticRetrievalQAVerifier,
    VerificationResult,
)

__all__ = [
    "RepoQAAdapter",
    "RepoQAInstance",
    "FunctionMetadata",
    "PythonFunctionExtractor",
    "RepositoryAnalyzer",
    "extract_repository_ground_truth",
    "BaseVerifier",
    "SemanticRetrievalQAVerifier",
    "MultiHopDependencyQAVerifier",
    "NegativeRetrievalQAVerifier",
    "RepoQAVerifier",
    "VerificationResult",
]
