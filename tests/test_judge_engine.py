#!/usr/bin/env python3
"""Unit tests for the CCB LLM judge engine.

All API calls are mocked — no ANTHROPIC_API_KEY required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ccb_metrics.judge import (
    JudgeInput,
    JudgeResult,
    LLMJudge,
    normalize_score,
)
from ccb_metrics.judge.backends import AnthropicBackend, JudgeBackendError

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_MOCK_BACKEND_RESPONSE: dict = {
    "reasoning": "The solution correctly implements the required feature.",
    "dimension_scores": {
        "correctness": {"score": 1.0, "evidence": "matches reference exactly"},
        "completeness": {"score": 0.5, "evidence": "covers most requirements"},
        "code_quality": {"score": 1.0, "evidence": "clean, idiomatic Python"},
        "retrieval_quality": {"score": 0.5, "evidence": "found most relevant files"},
        "efficiency": {"score": 1.0, "evidence": "minimal unnecessary steps"},
    },
    "overall_score": 0.82,
    "confidence": "high",
}


def _make_judge_input(
    *,
    oracle_ground_truth: str = "",
    oracle_evaluation_criteria: list[str] | None = None,
) -> JudgeInput:
    """Factory for JudgeInput with sensible defaults."""
    return JudgeInput(
        task_id="test-task-001",
        task_description="Implement a function that sorts a list in-place.",
        code_changes="def sort_list(lst):\n    lst.sort()\n",
        tool_calls="read_file, write_file",
        verifier_reward=0.75,
        oracle_ground_truth=oracle_ground_truth,
        oracle_expected_approach="Use list.sort() for in-place sort.",
        oracle_evaluation_criteria=oracle_evaluation_criteria or [],
    )


def _make_judge() -> LLMJudge:
    return LLMJudge(model="claude-haiku-4-5-20251001", temperature=0.0)


# ---------------------------------------------------------------------------
# 1. normalize_score
# ---------------------------------------------------------------------------


class TestNormalizeScore:
    """Tests for ccb_metrics.judge.models.normalize_score."""

    def test_string_pass(self):
        assert normalize_score("pass") == 1.0

    def test_string_partial(self):
        assert normalize_score("partial") == 0.5

    def test_string_fail(self):
        assert normalize_score("fail") == 0.0

    def test_numeric_string_1(self):
        assert normalize_score("1.0") == 1.0

    def test_garbage_returns_zero(self):
        assert normalize_score("garbage") == 0.0

    def test_float_passthrough(self):
        assert normalize_score(0.75) == 0.75


# ---------------------------------------------------------------------------
# 2. JudgeResult.to_dict() schema compliance
# ---------------------------------------------------------------------------


class TestJudgeResultToDict:
    """Tests for JudgeResult.to_dict() producing JSON-serialisable output."""

    def _make_result(self) -> JudgeResult:
        return JudgeResult(
            task_id="sgt-001",
            benchmark="ccb_pytorch",
            config="baseline",
            judge_score=0.85,
            dimension_scores={
                "correctness": 1.0,
                "completeness": 0.5,
                "code_quality": 1.0,
                "retrieval_quality": 0.5,
                "efficiency": 1.0,
            },
            oracle_confidence="high",
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
            rounds=1,
            judged_at="2026-01-01T00:00:00+00:00",
        )

    def test_to_dict_is_json_serialisable(self):
        """to_dict() output must round-trip through json.dumps without error."""
        d = self._make_result().to_dict()
        serialised = json.dumps(d)
        assert isinstance(serialised, str)

    def test_to_dict_has_required_schema_fields(self):
        """All required fields from judge_result.schema.json must be present."""
        d = self._make_result().to_dict()
        required = {"task_id", "benchmark", "config", "judge_score", "judge_model", "judged_at"}
        assert required.issubset(d.keys()), f"Missing fields: {required - d.keys()}"

    def test_to_dict_judge_model_is_model(self):
        """judge_model in output must equal the model field."""
        result = self._make_result()
        d = result.to_dict()
        assert d["judge_model"] == result.model

    def test_to_dict_rubric_contains_dimension_scores(self):
        """rubric key should map to dimension_scores dict."""
        result = self._make_result()
        d = result.to_dict()
        assert "rubric" in d
        assert d["rubric"] == result.dimension_scores

    def test_to_dict_judge_score_in_range(self):
        """judge_score must be a float in [0.0, 1.0]."""
        d = self._make_result().to_dict()
        assert 0.0 <= d["judge_score"] <= 1.0


# ---------------------------------------------------------------------------
# 3. LLMJudge.evaluate() — single round with oracle
# ---------------------------------------------------------------------------


class TestLLMJudgeEvaluateSingleRound:
    """Tests for LLMJudge.evaluate()."""

    def test_evaluate_with_oracle_returns_all_5_dimensions(self):
        """Single-round evaluate with oracle ground truth returns all 5 dimensions."""
        judge = _make_judge()
        judge_input = _make_judge_input(oracle_ground_truth="def sort_list(lst): lst.sort()")

        with patch.object(AnthropicBackend, "call", return_value=_MOCK_BACKEND_RESPONSE):
            result = judge.evaluate(judge_input)

        assert isinstance(result, JudgeResult)
        expected_dims = {"correctness", "completeness", "code_quality", "retrieval_quality", "efficiency"}
        assert set(result.dimension_scores.keys()) == expected_dims

    def test_evaluate_with_oracle_judge_score_is_weighted_average(self):
        """judge_score is the weighted average of dimension scores."""
        judge = _make_judge()
        judge_input = _make_judge_input(oracle_ground_truth="def sort_list(lst): lst.sort()")

        with patch.object(AnthropicBackend, "call", return_value=_MOCK_BACKEND_RESPONSE):
            result = judge.evaluate(judge_input)

        # Weights: correctness=0.30, completeness=0.25, code_quality=0.20,
        #          retrieval_quality=0.15, efficiency=0.10
        expected = (1.0 * 0.30 + 0.5 * 0.25 + 1.0 * 0.20 + 0.5 * 0.15 + 1.0 * 0.10)
        assert abs(result.judge_score - expected) < 1e-9

    def test_evaluate_without_oracle_uses_direct_review_prompt(self):
        """evaluate() uses DIRECT_REVIEW_PROMPT when no oracle data is present."""
        judge = _make_judge()
        judge_input = _make_judge_input(
            oracle_ground_truth="",
            oracle_evaluation_criteria=[],
        )

        captured_user_prompts: list[str] = []

        def mock_call(system_prompt: str, user_prompt: str) -> dict:
            captured_user_prompts.append(user_prompt)
            return _MOCK_BACKEND_RESPONSE

        with patch.object(AnthropicBackend, "call", side_effect=mock_call):
            result = judge.evaluate(judge_input)

        assert isinstance(result, JudgeResult)
        # DIRECT_REVIEW_PROMPT contains this unique sentinel phrase
        assert "No reference answer is available" in captured_user_prompts[0]

    def test_evaluate_with_oracle_uses_reference_correctness_prompt(self):
        """evaluate() uses REFERENCE_CORRECTNESS_PROMPT when oracle ground truth is set."""
        judge = _make_judge()
        judge_input = _make_judge_input(oracle_ground_truth="def sort_list(lst): lst.sort()")

        captured_user_prompts: list[str] = []

        def mock_call(system_prompt: str, user_prompt: str) -> dict:
            captured_user_prompts.append(user_prompt)
            return _MOCK_BACKEND_RESPONSE

        with patch.object(AnthropicBackend, "call", side_effect=mock_call):
            result = judge.evaluate(judge_input)

        assert isinstance(result, JudgeResult)
        # REFERENCE_CORRECTNESS_PROMPT contains "known-correct reference answer"
        assert "known-correct reference answer" in captured_user_prompts[0]


# ---------------------------------------------------------------------------
# 4. LLMJudge.evaluate_with_voting() — multi-round
# ---------------------------------------------------------------------------


class TestLLMJudgeEvaluateWithVoting:
    """Tests for LLMJudge.evaluate_with_voting()."""

    def test_evaluate_with_voting_3_rounds_produces_vote_distribution(self):
        """evaluate_with_voting(rounds=3) populates vote_distribution for all dims."""
        judge = _make_judge()
        judge_input = _make_judge_input(oracle_ground_truth="reference answer")

        with patch.object(AnthropicBackend, "call", return_value=_MOCK_BACKEND_RESPONSE):
            result = judge.evaluate_with_voting(judge_input, rounds=3)

        assert result.rounds == 3
        expected_dims = {"correctness", "completeness", "code_quality", "retrieval_quality", "efficiency"}
        assert set(result.vote_distribution.keys()) == expected_dims

    def test_evaluate_with_voting_vote_distribution_has_all_scores(self):
        """Each vote_distribution entry includes majority_count and all_scores."""
        judge = _make_judge()
        judge_input = _make_judge_input(oracle_ground_truth="reference answer")

        with patch.object(AnthropicBackend, "call", return_value=_MOCK_BACKEND_RESPONSE):
            result = judge.evaluate_with_voting(judge_input, rounds=3)

        for dim, info in result.vote_distribution.items():
            assert "majority_count" in info, f"Missing majority_count for {dim}"
            assert "all_scores" in info, f"Missing all_scores for {dim}"
            assert len(info["all_scores"]) == 3

    def test_evaluate_with_voting_confidence_in_provenance(self):
        """Provenance dict contains a confidence field after multi-round voting."""
        judge = _make_judge()
        judge_input = _make_judge_input(oracle_ground_truth="reference answer")

        with patch.object(AnthropicBackend, "call", return_value=_MOCK_BACKEND_RESPONSE):
            result = judge.evaluate_with_voting(judge_input, rounds=3)

        assert "confidence" in result.provenance
        confidence = result.provenance["confidence"]
        assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# 5. AnthropicBackend retry logic
# ---------------------------------------------------------------------------


class TestAnthropicBackendRetry:
    """Tests for retry-on-rate-limit behaviour."""

    def test_retry_on_429_then_success(self):
        """backend.call() retries after a 429 and succeeds on second attempt."""
        backend = AnthropicBackend(model="claude-haiku-4-5-20251001")

        valid_json_str = json.dumps(_MOCK_BACKEND_RESPONSE)
        call_count = 0

        def flaky_raw_call(system_prompt: str, user_prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise JudgeBackendError("rate limited", status_code=429)
            return valid_json_str

        with patch.object(AnthropicBackend, "_raw_call", side_effect=flaky_raw_call):
            with patch("ccb_metrics.judge.backends.time.sleep"):  # skip actual sleep
                result = backend.call("system", "user")

        assert call_count == 2
        assert result["reasoning"] == _MOCK_BACKEND_RESPONSE["reasoning"]

    def test_non_retryable_error_raised_immediately(self):
        """backend.call() raises immediately on non-retryable errors (e.g. 400)."""
        backend = AnthropicBackend(model="claude-haiku-4-5-20251001")

        def bad_raw_call(system_prompt: str, user_prompt: str) -> str:
            raise JudgeBackendError("bad request", status_code=400)

        with patch.object(AnthropicBackend, "_raw_call", side_effect=bad_raw_call):
            with pytest.raises(JudgeBackendError) as exc_info:
                backend.call("system", "user")

        assert exc_info.value.status_code == 400

    def test_parse_json_from_markdown_code_block(self):
        """_parse_json handles responses wrapped in ```json``` code blocks."""
        wrapped = f"```json\n{json.dumps(_MOCK_BACKEND_RESPONSE)}\n```"
        result = AnthropicBackend._parse_json(wrapped)
        assert result["reasoning"] == _MOCK_BACKEND_RESPONSE["reasoning"]
