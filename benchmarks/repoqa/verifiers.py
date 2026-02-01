"""
Verifiers for RepoQA adapter task variants.

Scores agent outputs against ground truth using semantic similarity.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    """Result of verifying an agent output."""
    correct_function: float       # 0.0-1.0
    correct_path: float           # 0.0-1.0
    justification_score: float    # 0.0-1.0
    reasoning: str = ""          # Explanation of scores


class BaseVerifier(ABC):
    """Base class for task variant verifiers."""
    
    def __init__(self, ground_truth: Dict[str, Any]):
        self.ground_truth = ground_truth
    
    @abstractmethod
    def verify(self, agent_output: Dict[str, Any]) -> VerificationResult:
        """Verify agent output against ground truth."""
        pass
    
    def _path_similarity(self, path1: str, path2: str) -> float:
        """Calculate similarity between two file paths."""
        # Normalize paths
        p1 = Path(path1).as_posix()
        p2 = Path(path2).as_posix()
        
        if p1 == p2:
            return 1.0
        
        # Use sequence matching for partial credit
        ratio = SequenceMatcher(None, p1, p2).ratio()
        return ratio
    
    def _name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two function names."""
        if name1 == name2:
            return 1.0
        
        # Use sequence matching
        ratio = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
        return ratio
    
    def _keyword_overlap(self, text1: str, text2: str) -> float:
        """Calculate keyword overlap between two texts."""
        if not text1 or not text2:
            return 0.0
        
        # Extract keywords (alphanumeric sequences)
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0


class SemanticRetrievalQAVerifier(BaseVerifier):
    """
    Verifies SR-QA tasks (find function by description).
    
    Ground truth format:
    {
        "function_id": "path/to/file.py::function_name",
        "canonical_path": "path/to/file.py",
        "canonical_name": "function_name",
        ...
    }
    """
    
    def verify(self, agent_output: Dict[str, Any]) -> VerificationResult:
        """Verify agent found the correct function."""
        try:
            path = agent_output.get("function_path", "")
            name = agent_output.get("function_name", "")
            justification = agent_output.get("justification", "")
        except (KeyError, TypeError) as e:
            return VerificationResult(
                correct_function=0.0,
                correct_path=0.0,
                justification_score=0.0,
                reasoning=f"Invalid output format: {e}"
            )
        
        canonical_path = self.ground_truth.get("canonical_path", "")
        canonical_name = self.ground_truth.get("canonical_name", "")
        nl_description = self.ground_truth.get("nl_description", "")
        
        # Score path
        path_score = self._path_similarity(path, canonical_path)
        
        # Score function name
        name_score = self._name_similarity(name, canonical_name)
        
        # Combined function score (require both path and name)
        if path_score == 1.0 and name_score == 1.0:
            function_score = 1.0
        elif path_score == 1.0 and name_score > 0.7:
            function_score = 0.8
        elif path_score > 0.8 and name_score == 1.0:
            function_score = 0.8
        elif path_score > 0.5 and name_score > 0.5:
            function_score = 0.3
        else:
            function_score = 0.0
        
        # Score justification
        justification_score = self._keyword_overlap(justification, nl_description)
        
        reasoning = (
            f"Path match: {path_score:.2f} (expected {canonical_path})\n"
            f"Name match: {name_score:.2f} (expected {canonical_name})\n"
            f"Justification keywords: {justification_score:.2f}"
        )
        
        return VerificationResult(
            correct_function=function_score,
            correct_path=path_score,
            justification_score=justification_score,
            reasoning=reasoning
        )


class MultiHopDependencyQAVerifier(BaseVerifier):
    """
    Verifies MD-QA tasks (find call path through dependency graph).
    
    Ground truth format:
    {
        "function_id": "path/to/file.py::function_name",
        "canonical_path": "path/to/file.py",
        "canonical_name": "function_name",
        "callees": ["func_a", "func_b", ...],
        "callers": ["func_x", "func_y", ...],
        ...
    }
    """
    
    def __init__(self, ground_truth: Dict[str, Any], all_functions: Dict[str, Any]):
        super().__init__(ground_truth)
        self.all_functions = all_functions  # For call graph validation
    
    def verify(self, agent_output: Dict[str, Any]) -> VerificationResult:
        """Verify agent found a valid call path."""
        try:
            root_function = agent_output.get("root_function", "")
            dependency_path = agent_output.get("dependency_path", [])
        except (KeyError, TypeError) as e:
            return VerificationResult(
                correct_function=0.0,
                correct_path=0.0,
                justification_score=0.0,
                reasoning=f"Invalid output format: {e}"
            )
        
        target_function = self.ground_truth.get("function_id", "")
        
        # Score root function
        root_score = self._function_id_similarity(root_function, target_function)
        
        # Score dependency path
        path_validity = self._validate_path(dependency_path)
        
        reasoning = (
            f"Root function match: {root_score:.2f} (expected {target_function})\n"
            f"Path validity: {path_validity:.2f} (length: {len(dependency_path)})"
        )
        
        return VerificationResult(
            correct_function=root_score,
            correct_path=path_validity,
            justification_score=0.5,  # Placeholder for now
            reasoning=reasoning
        )
    
    def _function_id_similarity(self, id1: str, id2: str) -> float:
        """Calculate similarity between function IDs."""
        if id1 == id2:
            return 1.0
        
        # Parse IDs (format: "path::name")
        parts1 = id1.split("::")
        parts2 = id2.split("::")
        
        if len(parts1) == 2 and len(parts2) == 2:
            path_sim = self._path_similarity(parts1[0], parts2[0])
            name_sim = self._name_similarity(parts1[1], parts2[1])
            return (path_sim + name_sim) / 2
        
        return SequenceMatcher(None, id1, id2).ratio()
    
    def _validate_path(self, path: List[str]) -> float:
        """
        Validate if the provided path is valid in the call graph.
        
        Returns: confidence score (0.0-1.0)
        """
        if not path or len(path) < 2:
            return 0.0
        
        # Check if each consecutive pair exists in our function database
        valid_steps = 0
        total_steps = len(path) - 1
        
        for i in range(len(path) - 1):
            current = path[i]
            next_func = path[i + 1]
            
            # Try to find these in our function database
            # For now, simple check - in production would validate against call graph
            if current in self.all_functions and next_func in self.all_functions:
                valid_steps += 1
        
        return valid_steps / total_steps if total_steps > 0 else 0.0


class NegativeRetrievalQAVerifier(BaseVerifier):
    """
    Verifies NR-QA tasks (disambiguation - pick the right function among similar ones).
    
    Ground truth format:
    {
        "function_id": "path/to/file.py::correct_function",
        "canonical_path": "path/to/file.py",
        "canonical_name": "correct_function",
        "semantic_constraint": "mutates the database",
        ...
        "distractors": [
            {"name": "similar_function_1", "reason": "doesn't mutate"},
            ...
        ]
    }
    """
    
    def verify(self, agent_output: Dict[str, Any]) -> VerificationResult:
        """Verify agent selected the correct function, not a distractor."""
        try:
            path = agent_output.get("function_path", "")
            name = agent_output.get("function_name", "")
            justification = agent_output.get("justification", "")
        except (KeyError, TypeError) as e:
            return VerificationResult(
                correct_function=0.0,
                correct_path=0.0,
                justification_score=0.0,
                reasoning=f"Invalid output format: {e}"
            )
        
        canonical_path = self.ground_truth.get("canonical_path", "")
        canonical_name = self.ground_truth.get("canonical_name", "")
        semantic_constraint = self.ground_truth.get("semantic_constraint", "")
        
        # Exact match required for correct_function (no partial credit)
        path_match = self._path_similarity(path, canonical_path) == 1.0
        name_match = self._name_similarity(name, canonical_name) == 1.0
        
        function_score = 1.0 if (path_match and name_match) else 0.0
        
        # Path score can be partial
        path_score = self._path_similarity(path, canonical_path)
        
        # Check if justification mentions the semantic constraint
        constraint_in_justification = semantic_constraint.lower() in justification.lower()
        justification_score = 0.8 if constraint_in_justification else 0.2
        
        reasoning = (
            f"Exact match: {function_score == 1.0}\n"
            f"Path similarity: {path_score:.2f}\n"
            f"Constraint mentioned: {constraint_in_justification}\n"
            f"Constraint: {semantic_constraint}"
        )
        
        return VerificationResult(
            correct_function=function_score,
            correct_path=path_score,
            justification_score=justification_score,
            reasoning=reasoning
        )


class RepoQAVerifier:
    """
    Unified verifier for all RepoQA task variants.
    """
    
    def __init__(
        self,
        ground_truth_path: Path,
        task_variant: str,
        all_functions: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize verifier.
        
        Args:
            ground_truth_path: Path to ground_truth.json file
            task_variant: "sr-qa", "md-qa", or "nr-qa"
            all_functions: For MD-QA validation, all functions in repo
        """
        with open(ground_truth_path) as f:
            self.ground_truth = json.load(f)
        
        self.task_variant = task_variant
        self.all_functions = all_functions or {}
        
        # Select appropriate verifier
        if task_variant == "sr-qa":
            self.verifier = SemanticRetrievalQAVerifier(self.ground_truth)
        elif task_variant == "md-qa":
            self.verifier = MultiHopDependencyQAVerifier(self.ground_truth, self.all_functions)
        elif task_variant == "nr-qa":
            self.verifier = NegativeRetrievalQAVerifier(self.ground_truth)
        else:
            raise ValueError(f"Unknown task variant: {task_variant}")
    
    def verify(self, solution_path: Path) -> VerificationResult:
        """Verify agent solution."""
        with open(solution_path) as f:
            agent_output = json.load(f)
        
        return self.verifier.verify(agent_output)


def verify_and_write_reward(
    ground_truth_path: Path,
    solution_path: Path,
    output_path: Path,
    task_variant: str,
    all_functions: Optional[Dict[str, Any]] = None
) -> None:
    """
    Verify solution and write reward.json for Harbor.
    
    Args:
        ground_truth_path: Path to ground_truth.json
        solution_path: Path to agent's solution.json
        output_path: Path to write reward.json
        task_variant: Task variant ("sr-qa", "md-qa", "nr-qa")
        all_functions: For MD-QA, all functions in repo
    """
    verifier = RepoQAVerifier(ground_truth_path, task_variant, all_functions)
    result = verifier.verify(solution_path)
    
    reward = {
        "correct_function": result.correct_function,
        "correct_path": result.correct_path,
        "justification_score": result.justification_score,
        "reasoning": result.reasoning,
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(reward, f, indent=2)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 5:
        print("Usage: python verifiers.py <task_variant> <ground_truth> <solution> <output>")
        print("  task_variant: sr-qa, md-qa, or nr-qa")
        sys.exit(1)
    
    variant = sys.argv[1]
    gt_path = Path(sys.argv[2])
    sol_path = Path(sys.argv[3])
    out_path = Path(sys.argv[4])
    
    verify_and_write_reward(gt_path, sol_path, out_path, variant)
    print(f"Reward written to {out_path}")
