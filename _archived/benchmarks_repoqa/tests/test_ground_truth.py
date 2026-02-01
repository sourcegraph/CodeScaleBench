"""
Tests for ground truth extraction.
"""

import json
import tempfile
from pathlib import Path

import pytest

from ground_truth_extractor import (
    FunctionMetadata,
    PythonFunctionExtractor,
    RepositoryAnalyzer,
)


@pytest.fixture
def sample_python_file(tmp_path):
    """Create a sample Python file for testing."""
    py_file = tmp_path / "sample.py"
    py_file.write_text("""
import os

def simple_function():
    '''A simple function.'''
    return 42

def function_with_mutation():
    '''A function that mutates state.'''
    global some_global
    some_global = True
    return some_global

def function_with_exception():
    '''A function that raises exceptions.'''
    if not valid():
        raise ValueError("Invalid input")
    return True

def function_with_io():
    '''A function that performs I/O.'''
    with open("file.txt") as f:
        return f.read()

async def async_function():
    '''An async function.'''
    return 42
""")
    return py_file


@pytest.fixture
def sample_repo(tmp_path):
    """Create a sample repository structure."""
    repo = tmp_path / "repo"
    repo.mkdir()
    
    # Create some Python files
    (repo / "module1.py").write_text("""
def func_a():
    return 1

def func_b():
    return func_a() + 1
""")
    
    (repo / "module2.py").write_text("""
from module1 import func_b

def func_c():
    return func_b() + 2
""")
    
    # Create a subdirectory with Python files
    subdir = repo / "submodule"
    subdir.mkdir()
    (subdir / "nested.py").write_text("""
def nested_func():
    return 42
""")
    
    # Create a directory to ignore
    ignore_dir = repo / "venv"
    ignore_dir.mkdir()
    (ignore_dir / "should_ignore.py").write_text("def ignored(): pass")
    
    return repo


class TestPythonFunctionExtractor:
    """Test Python function extraction."""
    
    def test_extract_simple_function(self, sample_python_file):
        """Test extracting a simple function."""
        extractor = PythonFunctionExtractor(str(sample_python_file))
        
        with open(sample_python_file) as f:
            import ast
            tree = ast.parse(f.read())
        
        extractor.visit(tree)
        
        functions = extractor.functions
        assert len(functions) == 5
        
        # Find the simple_function (key is absolute path)
        simple_func = None
        for key, func in functions.items():
            if func.canonical_name == "simple_function":
                simple_func = func
                break
        
        assert simple_func is not None
        assert not simple_func.mutates_state
        assert not simple_func.throws_errors
        assert not simple_func.performs_io
    
    def test_detect_state_mutation(self, sample_python_file):
        """Test detecting state mutation."""
        extractor = PythonFunctionExtractor(str(sample_python_file))
        
        with open(sample_python_file) as f:
            import ast
            tree = ast.parse(f.read())
        
        extractor.visit(tree)
        functions = extractor.functions
        
        func = next((f for f in functions.values() if f.canonical_name == "function_with_mutation"), None)
        assert func is not None
        assert func.mutates_state is True
    
    def test_detect_exceptions(self, sample_python_file):
        """Test detecting exception raising."""
        extractor = PythonFunctionExtractor(str(sample_python_file))
        
        with open(sample_python_file) as f:
            import ast
            tree = ast.parse(f.read())
        
        extractor.visit(tree)
        functions = extractor.functions
        
        func = next((f for f in functions.values() if f.canonical_name == "function_with_exception"), None)
        assert func is not None
        assert func.throws_errors is True
    
    def test_detect_io(self, sample_python_file):
        """Test detecting I/O operations."""
        extractor = PythonFunctionExtractor(str(sample_python_file))
        
        with open(sample_python_file) as f:
            import ast
            tree = ast.parse(f.read())
        
        extractor.visit(tree)
        functions = extractor.functions
        
        func = next((f for f in functions.values() if f.canonical_name == "function_with_io"), None)
        assert func is not None
        assert func.performs_io is True
    
    def test_detect_async(self, sample_python_file):
        """Test detecting async functions."""
        extractor = PythonFunctionExtractor(str(sample_python_file))
        
        with open(sample_python_file) as f:
            import ast
            tree = ast.parse(f.read())
        
        extractor.visit(tree)
        functions = extractor.functions
        
        func = next((f for f in functions.values() if f.canonical_name == "async_function"), None)
        assert func is not None
        assert func.is_async is True


class TestRepositoryAnalyzer:
    """Test repository-wide analysis."""
    
    def test_analyze_repository(self, sample_repo):
        """Test analyzing an entire repository."""
        analyzer = RepositoryAnalyzer(sample_repo)
        
        # Debug: check what files exist
        py_files = list(sample_repo.rglob("*.py"))
        assert len(py_files) >= 2, f"Expected Python files, found: {py_files}"
        
        functions = analyzer.analyze(language="python")
        
        # Should find functions in all Python files (except venv)
        assert len(functions) >= 2, f"Expected at least 2 functions, found {len(functions)}: {functions}"
        
        # Check functions are found
        func_names = [f.canonical_name for f in functions.values()]
        assert "func_a" in func_names
        assert "func_b" in func_names
        assert "func_c" in func_names
    
    def test_exclude_paths(self, sample_repo):
        """Test that excluded paths are skipped."""
        analyzer = RepositoryAnalyzer(sample_repo)
        functions = analyzer.analyze(
            language="python",
            exclude_paths=["venv"]
        )
        
        # Should not find ignored function from venv
        func_names = [f.canonical_name for f in functions.values()]
        assert "ignored" not in func_names
    
    def test_call_graph_building(self, sample_repo):
        """Test call graph is built correctly."""
        analyzer = RepositoryAnalyzer(sample_repo)
        functions = analyzer.analyze(language="python")
        
        # func_b calls func_a, so func_a should have func_b as caller
        for func_id, func in functions.items():
            if func.canonical_name == "func_a":
                assert any("func_b" in caller for caller in func.callers)
    
    def test_save_to_json(self, sample_repo, tmp_path):
        """Test saving extracted functions to JSON."""
        analyzer = RepositoryAnalyzer(sample_repo)
        functions = analyzer.analyze(language="python")
        
        output_file = tmp_path / "ground_truth.json"
        analyzer.save(output_file)
        
        # Verify file exists and is valid JSON
        assert output_file.exists()
        
        with open(output_file) as f:
            data = json.load(f)
        
        assert len(data) >= 3
        
        # Check structure
        for func_id, func_data in data.items():
            assert "canonical_name" in func_data
            assert "canonical_path" in func_data
            assert "language" in func_data


class TestFunctionMetadata:
    """Test FunctionMetadata dataclass."""
    
    def test_create_metadata(self):
        """Test creating function metadata."""
        meta = FunctionMetadata(
            function_id="src/test.py::test_func",
            canonical_path="src/test.py",
            canonical_name="test_func",
            language="python",
            mutates_state=False,
            throws_errors=True,
            performs_io=False,
            is_async=False,
            callers=["caller1", "caller2"],
            callees=["callee1"],
            nl_description="Test function",
        )
        
        assert meta.canonical_name == "test_func"
        assert meta.throws_errors is True
        assert len(meta.callers) == 2
    
    def test_default_values(self):
        """Test default values."""
        meta = FunctionMetadata(
            function_id="test.py::func",
            canonical_path="test.py",
            canonical_name="func",
            language="python",
        )
        
        assert meta.mutates_state is False
        assert meta.throws_errors is False
        assert meta.performs_io is False
        assert meta.is_async is False
        assert meta.callers == []
        assert meta.callees == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
