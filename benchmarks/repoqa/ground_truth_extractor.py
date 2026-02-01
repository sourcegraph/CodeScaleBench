"""
Ground truth extraction for RepoQA adapter.

Extracts function metadata, call graphs, and semantic tags from source code.
"""

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class FunctionMetadata:
    """Ground truth metadata for a single function."""
    function_id: str              # "path/to/file.py::function_name"
    canonical_path: str           # Relative path
    canonical_name: str           # Function name
    language: str                 # python, javascript, rust, etc.
    
    # Semantic tags
    mutates_state: bool = False   # Modifies globals, database, file system
    throws_errors: bool = False   # Raises exceptions
    performs_io: bool = False     # File I/O, network I/O
    is_async: bool = False        # async/await
    
    # Call graph
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)
    
    # Natural language description (from original RepoQA)
    nl_description: str = ""


class PythonFunctionExtractor(ast.NodeVisitor):
    """Extract functions and semantic information from Python code."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.functions: Dict[str, FunctionMetadata] = {}
        self.current_function: Optional[str] = None
        self.io_keywords = {'open', 'read', 'write', 'requests', 'urllib', 'socket', 'http'}
        self.state_keywords = {'global', 'nonlocal', 'setattr', 'delattr', 'append', 'extend', 'update', 'pop', 'clear'}
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition."""
        func_name = node.name
        function_id = f"{self.filepath}::{func_name}"
        
        # Analyze function body
        mutates_state = self._has_state_mutation(node)
        throws_errors = self._has_exceptions(node)
        performs_io = self._has_io_operations(node)
        callees = self._extract_callees(node)
        
        self.functions[function_id] = FunctionMetadata(
            function_id=function_id,
            canonical_path=self.filepath,
            canonical_name=func_name,
            language="python",
            mutates_state=mutates_state,
            throws_errors=throws_errors,
            performs_io=performs_io,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            callees=callees,
        )
        
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition."""
        # Treat like regular function but mark as async
        func_name = node.name
        function_id = f"{self.filepath}::{func_name}"
        
        mutates_state = self._has_state_mutation(node)
        throws_errors = self._has_exceptions(node)
        performs_io = self._has_io_operations(node)
        callees = self._extract_callees(node)
        
        self.functions[function_id] = FunctionMetadata(
            function_id=function_id,
            canonical_path=self.filepath,
            canonical_name=func_name,
            language="python",
            mutates_state=mutates_state,
            throws_errors=throws_errors,
            performs_io=performs_io,
            is_async=True,
            callees=callees,
        )
        
        self.generic_visit(node)
    
    def _has_state_mutation(self, node: ast.AST) -> bool:
        """Check if function modifies global/nonlocal state."""
        for child in ast.walk(node):
            if isinstance(child, ast.Global):
                return True
            if isinstance(child, ast.Nonlocal):
                return True
            # Check for attribute assignments (obj.attr = value)
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Attribute):
                        return True
            # Check for method calls that mutate
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    method_name = child.func.attr
                    if method_name in {'append', 'extend', 'update', 'pop', 'clear', 'remove', 'insert'}:
                        return True
        return False
    
    def _has_exceptions(self, node: ast.AST) -> bool:
        """Check if function raises exceptions."""
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                return True
        return False
    
    def _has_io_operations(self, node: ast.AST) -> bool:
        """Check if function performs I/O operations."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                # Check function name
                if isinstance(child.func, ast.Name):
                    if child.func.id in {'open', 'read', 'write'}:
                        return True
                # Check attribute calls
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr in {'read', 'write', 'open', 'get', 'post', 'request'}:
                        return True
        return False
    
    def _extract_callees(self, node: ast.AST) -> List[str]:
        """Extract functions called by this function."""
        callees = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    callees.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    # Try to construct the full call chain
                    parts = []
                    current = child.func
                    while isinstance(current, ast.Attribute):
                        parts.insert(0, current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.insert(0, current.id)
                        callees.append('.'.join(parts))
        return list(set(callees))  # Deduplicate


class RepositoryAnalyzer:
    """Analyze an entire repository for function metadata."""
    
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)
        self.all_functions: Dict[str, FunctionMetadata] = {}
        self.call_graph: Dict[str, Set[str]] = {}  # Maps func_id -> set of callers
    
    def analyze(self, language: str = "python", exclude_paths: Optional[List[str]] = None) -> Dict[str, FunctionMetadata]:
        """
        Analyze repository and extract all functions.
        
        Args:
            language: Programming language to analyze
            exclude_paths: Paths to exclude (e.g., tests, venv)
        """
        exclude_paths = exclude_paths or ['__pycache__', '.git', 'venv', 'node_modules', 'test']
        
        if language == "python":
            return self._analyze_python(exclude_paths)
        else:
            raise NotImplementedError(f"Language {language} not yet supported")
    
    def _analyze_python(self, exclude_paths: List[str]) -> Dict[str, FunctionMetadata]:
        """Analyze Python repository."""
        for py_file in self.repo_path.rglob("*.py"):
            # Skip excluded paths (check path components, not substring)
            parts = py_file.parts
            if any(excluded in parts for excluded in exclude_paths):
                continue
            
            try:
                self._analyze_python_file(py_file)
            except Exception as e:
                print(f"Warning: Failed to analyze {py_file}: {e}")
        
        # Build call graph
        self._build_call_graph()
        
        return self.all_functions
    
    def _analyze_python_file(self, filepath: Path) -> None:
        """Analyze a single Python file."""
        relative_path = filepath.relative_to(self.repo_path)
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
        except SyntaxError:
            return
        
        extractor = PythonFunctionExtractor(str(relative_path))
        extractor.visit(tree)
        
        self.all_functions.update(extractor.functions)
    
    def _build_call_graph(self) -> None:
        """Build reverse call graph (who calls each function)."""
        # Initialize
        for func_id in self.all_functions:
            self.call_graph[func_id] = set()
        
        # Build from callees
        for func_id, metadata in self.all_functions.items():
            for callee_name in metadata.callees:
                # Try to match callee to a function in our database
                for other_id, other_metadata in self.all_functions.items():
                    if other_metadata.canonical_name == callee_name:
                        self.call_graph[other_id].add(func_id)
        
        # Update metadata with callers
        for func_id, callers in self.call_graph.items():
            self.all_functions[func_id].callers = sorted(list(callers))
    
    def to_json(self) -> str:
        """Serialize all functions to JSON."""
        data = {
            func_id: asdict(metadata)
            for func_id, metadata in self.all_functions.items()
        }
        return json.dumps(data, indent=2)
    
    def save(self, output_path: Path) -> None:
        """Save extracted metadata to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(self.to_json())


def extract_repository_ground_truth(
    repo_path: Path,
    language: str = "python",
    exclude_paths: Optional[List[str]] = None,
) -> Dict[str, FunctionMetadata]:
    """
    Extract ground truth from a repository.
    
    Args:
        repo_path: Path to repository root
        language: Programming language
        exclude_paths: Paths to exclude
    
    Returns:
        Dictionary mapping function_id -> FunctionMetadata
    """
    analyzer = RepositoryAnalyzer(repo_path)
    return analyzer.analyze(language=language, exclude_paths=exclude_paths)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python ground_truth_extractor.py <repo_path> [output_path]")
        sys.exit(1)
    
    repo_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else repo_path / "ground_truth.json"
    
    print(f"Analyzing repository: {repo_path}")
    analyzer = RepositoryAnalyzer(repo_path)
    functions = analyzer.analyze()
    
    print(f"Found {len(functions)} functions")
    analyzer.save(output_path)
    print(f"Saved to {output_path}")
