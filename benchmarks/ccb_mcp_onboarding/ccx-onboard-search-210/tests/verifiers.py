"""Verifiers for RepoQA SR-QA tasks. Scores agent function retrieval."""

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict


@dataclass
class VerificationResult:
    correct_function: float
    correct_path: float
    justification_score: float
    reasoning: str = ""


class SemanticRetrievalQAVerifier:
    def __init__(self, ground_truth: Dict[str, Any]):
        self.ground_truth = ground_truth

    def verify(self, agent_output: Dict[str, Any]) -> VerificationResult:
        try:
            path = agent_output.get("function_path", "")
            name = agent_output.get("function_name", "")
            justification = agent_output.get("justification", "")
        except (KeyError, TypeError) as e:
            return VerificationResult(0.0, 0.0, 0.0, f"Invalid output: {e}")

        canonical_path = self.ground_truth.get("canonical_path", "")
        canonical_name = self.ground_truth.get("canonical_name", "")
        nl_description = self.ground_truth.get("nl_description", "")

        path_score = self._path_similarity(path, canonical_path)
        name_score = self._name_similarity(name, canonical_name)

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

        justification_score = self._keyword_overlap(justification, nl_description)

        reasoning = (
            f"Path match: {path_score:.2f} (expected {canonical_path})\n"
            f"Name match: {name_score:.2f} (expected {canonical_name})\n"
            f"Justification keywords: {justification_score:.2f}"
        )
        return VerificationResult(function_score, path_score, justification_score, reasoning)

    @staticmethod
    def _path_similarity(p1: str, p2: str) -> float:
        p1, p2 = Path(p1).as_posix(), Path(p2).as_posix()
        return 1.0 if p1 == p2 else SequenceMatcher(None, p1, p2).ratio()

    @staticmethod
    def _name_similarity(n1: str, n2: str) -> float:
        return 1.0 if n1 == n2 else SequenceMatcher(None, n1.lower(), n2.lower()).ratio()

    @staticmethod
    def _keyword_overlap(text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        w1 = set(re.findall(r"\w+", text1.lower()))
        w2 = set(re.findall(r"\w+", text2.lower()))
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)
