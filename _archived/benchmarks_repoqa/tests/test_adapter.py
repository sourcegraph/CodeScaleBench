"""
Tests for RepoQA adapter.
"""

import json
import tempfile
from pathlib import Path

import pytest

from adapter import RepoQAAdapter, RepoQAInstance, RepoQALoader
from ground_truth_extractor import RepositoryAnalyzer
from verifiers import (
    NegativeRetrievalQAVerifier,
    SemanticRetrievalQAVerifier,
    VerificationResult,
)


@pytest.fixture
def sample_instance():
    """Create a sample RepoQA instance."""
    return {
        "instance_id": "test-001",
        "repository": "test/repo",
        "commit": "abc1234",
        "language": "python",
        "function_description": "Validates input tokens",
        "canonical_function": "src/validate.py::validate_token",
        "canonical_path": "src/validate.py",
        "canonical_name": "validate_token",
        "semantic_metadata": {
            "mutates_state": False,
            "throws_errors": True,
            "performs_io": False,
            "is_async": False,
        }
    }


@pytest.fixture
def sample_dataset(tmp_path, sample_instance):
    """Create a sample JSONL dataset file."""
    dataset_file = tmp_path / "dataset.jsonl"
    with open(dataset_file, "w") as f:
        f.write(json.dumps(sample_instance) + "\n")
    return dataset_file


class TestRepoQALoader:
    """Test RepoQA dataset loader."""
    
    def test_load_instance(self, sample_dataset, sample_instance):
        """Test loading a single instance."""
        loader = RepoQALoader(sample_dataset)
        
        instance = loader.load("test-001")
        assert instance.instance_id == "test-001"
        assert instance.repository == "test/repo"
        assert instance.language == "python"
    
    def test_all_ids(self, sample_dataset):
        """Test getting all instance IDs."""
        loader = RepoQALoader(sample_dataset)
        ids = loader.all_ids()
        assert "test-001" in ids
    
    def test_missing_instance(self, sample_dataset):
        """Test loading non-existent instance."""
        loader = RepoQALoader(sample_dataset)
        with pytest.raises(KeyError):
            loader.load("nonexistent")


class TestRepoQAAdapter:
    """Test RepoQA adapter."""
    
    def test_adapter_initialization(self, tmp_path, sample_dataset):
        """Test adapter initialization."""
        adapter = RepoQAAdapter(
            task_dir=tmp_path / "tasks",
            dataset_path=sample_dataset
        )
        # task_dir is created on demand, not during init
        assert adapter.loader is not None
        assert adapter.templates_dir.exists()
    
    def test_generate_sr_qa_task(self, tmp_path, sample_dataset):
        """Test generating SR-QA task."""
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        
        adapter = RepoQAAdapter(
            task_dir=task_dir,
            dataset_path=sample_dataset
        )
        
        adapter.generate_task("test-001", "test-001-sr-qa", task_variant="sr-qa")
        
        # Check task structure
        task_path = task_dir / "test-001-sr-qa"
        assert (task_path / "instruction.md").exists()
        assert (task_path / "task.toml").exists()
        assert (task_path / "environment" / "Dockerfile").exists()
        assert (task_path / "tests" / "test.sh").exists()
        assert (task_path / "tests" / "ground_truth.json").exists()
    
    def test_task_metadata(self, tmp_path, sample_dataset):
        """Test task metadata is properly set."""
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        
        adapter = RepoQAAdapter(
            task_dir=task_dir,
            dataset_path=sample_dataset
        )
        
        adapter.generate_task("test-001", "test-001-sr-qa", task_variant="sr-qa")
        
        # Check task.toml
        config_path = task_dir / "test-001-sr-qa" / "task.toml"
        config_text = config_path.read_text()
        
        assert "test/repo" in config_text
        assert "python" in config_text
        assert "sr-qa" in config_text
    
    def test_ground_truth_in_task(self, tmp_path, sample_dataset):
        """Test ground truth is saved in task."""
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        
        adapter = RepoQAAdapter(
            task_dir=task_dir,
            dataset_path=sample_dataset
        )
        
        adapter.generate_task("test-001", "test-001-sr-qa", task_variant="sr-qa")
        
        # Check ground truth
        gt_path = task_dir / "test-001-sr-qa" / "tests" / "ground_truth.json"
        with open(gt_path) as f:
            gt = json.load(f)
        
        assert gt["canonical_path"] == "src/validate.py"
        assert gt["canonical_name"] == "validate_token"
        assert gt["throws_errors"] is True


class TestSemanticRetrievalQAVerifier:
    """Test SR-QA verifier."""
    
    def test_perfect_match(self):
        """Test perfect match scoring."""
        ground_truth = {
            "canonical_path": "src/validate.py",
            "canonical_name": "validate_token",
            "nl_description": "Validates JWT tokens",
        }
        
        verifier = SemanticRetrievalQAVerifier(ground_truth)
        
        result = verifier.verify({
            "function_path": "src/validate.py",
            "function_name": "validate_token",
            "justification": "This validates JWT tokens",
        })
        
        assert result.correct_function == 1.0
        assert result.correct_path == 1.0
    
    def test_partial_match(self):
        """Test partial match scoring."""
        ground_truth = {
            "canonical_path": "src/validate.py",
            "canonical_name": "validate_token",
            "nl_description": "Validates JWT tokens",
        }
        
        verifier = SemanticRetrievalQAVerifier(ground_truth)
        
        result = verifier.verify({
            "function_path": "src/validation.py",  # Similar but not exact
            "function_name": "token_validator",     # Similar but not exact
            "justification": "Validates tokens",
        })
        
        assert 0 < result.correct_function < 1
        assert 0 < result.correct_path < 1
    
    def test_wrong_match(self):
        """Test wrong match scoring."""
        ground_truth = {
            "canonical_path": "src/validate.py",
            "canonical_name": "validate_token",
            "nl_description": "Validates JWT tokens",
        }
        
        verifier = SemanticRetrievalQAVerifier(ground_truth)
        
        result = verifier.verify({
            "function_path": "src/auth.py",
            "function_name": "authenticate",
            "justification": "Does auth stuff",
        })
        
        assert result.correct_function == 0.0


class TestNegativeRetrievalQAVerifier:
    """Test NR-QA verifier."""
    
    def test_correct_function(self):
        """Test correct function selection."""
        ground_truth = {
            "canonical_path": "src/validate.py",
            "canonical_name": "validate_token",
            "semantic_constraint": "throws exceptions on invalid input",
            "nl_description": "Validates tokens",
        }
        
        verifier = NegativeRetrievalQAVerifier(ground_truth)
        
        result = verifier.verify({
            "function_path": "src/validate.py",
            "function_name": "validate_token",
            "justification": "throws exceptions on invalid input",
        })
        
        assert result.correct_function == 1.0
    
    def test_wrong_function_is_zero(self):
        """Test wrong function gets zero (no partial credit)."""
        ground_truth = {
            "canonical_path": "src/validate.py",
            "canonical_name": "validate_token",
            "semantic_constraint": "throws exceptions",
            "nl_description": "Validates tokens",
        }
        
        verifier = NegativeRetrievalQAVerifier(ground_truth)
        
        result = verifier.verify({
            "function_path": "src/validate.py",
            "function_name": "check_token",  # Wrong, but close
            "justification": "checks tokens",
        })
        
        assert result.correct_function == 0.0  # Binary - wrong is wrong


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
