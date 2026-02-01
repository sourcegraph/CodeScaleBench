#!/usr/bin/env python3
"""Integration tests for DI-Bench validators with realistic project structures."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from validators import validate_task


class TestIntegration:
    """End-to-end integration tests with realistic projects."""

    def test_python_project_with_dependencies(self):
        """Test a realistic Python project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create Python project structure
            (repo_path / "src").mkdir()
            (repo_path / "src" / "main.py").write_text("import requests\nimport flask")
            
            # Create requirements.txt with dependencies
            (repo_path / "requirements.txt").write_text(
                "requests==2.28.0\n"
                "flask==2.3.0\n"
                "pytest>=6.0\n"
            )
            
            is_valid, errors = validate_task("python", repo_path)
            assert is_valid, f"Python project validation failed: {errors}"

    def test_rust_project_with_dependencies(self):
        """Test a realistic Rust project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create Rust project structure
            (repo_path / "src").mkdir()
            (repo_path / "src" / "main.rs").write_text("use serde::Deserialize;")
            
            # Create Cargo.toml
            (repo_path / "Cargo.toml").write_text("""[package]
name = "my-project"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
tokio = { version = "1.0", features = ["full"] }
""")
            
            is_valid, errors = validate_task("rust", repo_path)
            assert is_valid, f"Rust project validation failed: {errors}"

    def test_javascript_project_with_dependencies(self):
        """Test a realistic JavaScript project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create JavaScript project structure
            (repo_path / "src").mkdir()
            (repo_path / "src" / "index.js").write_text("const express = require('express');")
            
            # Create package.json
            (repo_path / "package.json").write_text(json.dumps({
                "name": "my-app",
                "version": "1.0.0",
                "dependencies": {
                    "express": "^4.18.0",
                    "axios": "^1.3.0"
                },
                "devDependencies": {
                    "jest": "^29.0.0"
                }
            }, indent=2))
            
            is_valid, errors = validate_task("javascript", repo_path)
            assert is_valid, f"JavaScript project validation failed: {errors}"

    def test_csharp_project_with_dependencies(self):
        """Test a realistic C# project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create C# project structure
            (repo_path / "src").mkdir()
            (repo_path / "src" / "Program.cs").write_text("using Newtonsoft.Json;")
            
            # Create .csproj
            (repo_path / "MyProject.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net7.0</TargetFramework>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.0" />
    <PackageReference Include="Microsoft.Extensions.Http" Version="7.0.0" />
  </ItemGroup>
</Project>""")
            
            is_valid, errors = validate_task("csharp", repo_path)
            assert is_valid, f"C# project validation failed: {errors}"

    def test_python_missing_dependencies(self):
        """Test detection when dependencies are missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create Python project with imports but empty requirements
            (repo_path / "main.py").write_text("import requests\nimport pandas")
            (repo_path / "requirements.txt").write_text("# Empty\n")
            
            is_valid, errors = validate_task("python", repo_path)
            # Should have warnings but not fail completely
            assert any("No dependencies" in e for e in errors)

    def test_rust_missing_dependencies(self):
        """Test detection when Cargo has no dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create Cargo.toml with no dependencies
            (repo_path / "Cargo.toml").write_text("""[package]
name = "my-project"
version = "0.1.0"

[dependencies]
""")
            
            is_valid, errors = validate_task("rust", repo_path)
            assert any("No dependencies" in e for e in errors)

    def test_python_syntax_error_in_requirements(self):
        """Test detection of syntax errors in requirements.txt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create requirements with syntax error
            (repo_path / "requirements.txt").write_text(
                "requests==2.28.0\n"
                "flask = = 2.3.0\n"  # Invalid syntax
            )
            
            is_valid, errors = validate_task("python", repo_path)
            assert not is_valid
            assert any("Invalid requirement" in e for e in errors)

    def test_javascript_invalid_json(self):
        """Test detection of invalid JSON in package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            # Create invalid JSON
            (repo_path / "package.json").write_text('{"name": "test",}')  # Trailing comma
            
            is_valid, errors = validate_task("javascript", repo_path)
            assert not is_valid
            assert any("JSON" in e for e in errors)

    def test_unsupported_language(self):
        """Test handling of unsupported language."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            
            is_valid, errors = validate_task("golang", repo_path)
            assert not is_valid
            assert any("Unsupported" in e for e in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
