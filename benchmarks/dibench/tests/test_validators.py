#!/usr/bin/env python3
"""Tests for DI-Bench validators."""

import json
import tempfile
from pathlib import Path

import pytest

# Import from parent directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from validators import (
    PythonValidator,
    RustValidator,
    JavaScriptValidator,
    CSharpValidator,
    get_validator,
    validate_task,
)


class TestPythonValidator:
    """Test Python requirements.txt validation."""

    def test_valid_requirements(self):
        """Test validation of valid requirements.txt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            req_file = repo_path / "requirements.txt"
            req_file.write_text("requests==2.28.0\nflask>=1.0\nnumpy")

            validator = PythonValidator(repo_path)
            is_valid, errors = validator.validate()
            assert is_valid, f"Unexpected errors: {errors}"

    def test_invalid_requirements_syntax(self):
        """Test detection of invalid requirement syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            req_file = repo_path / "requirements.txt"
            # Invalid: has spaces around operator
            req_file.write_text("requests = = 2.28.0")

            validator = PythonValidator(repo_path)
            is_valid, errors = validator.validate()
            # Should detect syntax error
            assert not is_valid or len([e for e in errors if "Invalid requirement" in e]) > 0

    def test_empty_requirements(self):
        """Test detection of empty requirements.txt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            req_file = repo_path / "requirements.txt"
            req_file.write_text("# Just comments\n# No dependencies")

            validator = PythonValidator(repo_path)
            is_valid, errors = validator.validate()
            # Should flag missing dependencies (warning, not critical error)
            assert any("No dependencies found" in e for e in errors)

    def test_pyproject_toml_validation(self):
        """Test pyproject.toml syntax validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pyproject = repo_path / "pyproject.toml"
            pyproject.write_text("""[project]
name = "my-project"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest>=6.0"]
""")

            validator = PythonValidator(repo_path)
            is_valid, errors = validator.validate()
            assert is_valid, f"Unexpected errors: {errors}"

    def test_malformed_toml(self):
        """Test detection of malformed TOML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pyproject = repo_path / "pyproject.toml"
            # Mismatched brackets
            pyproject.write_text("[project\nname = \"test\"")

            validator = PythonValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid


class TestRustValidator:
    """Test Rust Cargo.toml validation."""

    def test_valid_cargo_toml(self):
        """Test validation of valid Cargo.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            cargo = repo_path / "Cargo.toml"
            cargo.write_text("""[package]
name = "my-project"
version = "0.1.0"

[dependencies]
serde = "1.0"
tokio = { version = "1.0", features = ["full"] }
""")

            validator = RustValidator(repo_path)
            is_valid, errors = validator.validate()
            assert is_valid, f"Unexpected errors: {errors}"

    def test_missing_cargo_toml(self):
        """Test detection of missing Cargo.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = RustValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid
            assert any("build files" in e.lower() for e in errors)

    def test_missing_package_section(self):
        """Test detection of missing [package] section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            cargo = repo_path / "Cargo.toml"
            cargo.write_text("[dependencies]\nserde = \"1.0\"")

            validator = RustValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid
            assert any("[package]" in e for e in errors)

    def test_empty_dependencies(self):
        """Test detection of empty dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            cargo = repo_path / "Cargo.toml"
            cargo.write_text("""[package]
name = "my-project"
version = "0.1.0"

[dependencies]
""")

            validator = RustValidator(repo_path)
            is_valid, errors = validator.validate()
            assert any("No dependencies" in e for e in errors)

    def test_malformed_toml(self):
        """Test detection of malformed TOML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            cargo = repo_path / "Cargo.toml"
            cargo.write_text("[package\nname = \"test\"")  # Missing closing bracket

            validator = RustValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid


class TestJavaScriptValidator:
    """Test JavaScript package.json validation."""

    def test_valid_package_json(self):
        """Test validation of valid package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pkg = repo_path / "package.json"
            pkg.write_text(json.dumps({
                "name": "my-project",
                "version": "1.0.0",
                "dependencies": {
                    "express": "^4.18.0",
                    "lodash": "^4.17.21"
                }
            }))

            validator = JavaScriptValidator(repo_path)
            is_valid, errors = validator.validate()
            assert is_valid, f"Unexpected errors: {errors}"

    def test_missing_package_json(self):
        """Test detection of missing package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = JavaScriptValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid
            assert any("build files" in e.lower() for e in errors)

    def test_missing_name_field(self):
        """Test detection of missing name field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pkg = repo_path / "package.json"
            pkg.write_text(json.dumps({
                "version": "1.0.0",
                "dependencies": {"express": "^4.18.0"}
            }))

            validator = JavaScriptValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid
            assert any("name" in e for e in errors)

    def test_invalid_json(self):
        """Test detection of invalid JSON syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pkg = repo_path / "package.json"
            pkg.write_text('{"name": "test",}')  # Trailing comma

            validator = JavaScriptValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid
            assert any("JSON" in e for e in errors)

    def test_empty_dependencies(self):
        """Test detection of empty dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pkg = repo_path / "package.json"
            pkg.write_text(json.dumps({
                "name": "my-project",
                "version": "1.0.0"
            }))

            validator = JavaScriptValidator(repo_path)
            is_valid, errors = validator.validate()
            assert any("No dependencies" in e for e in errors)


class TestCSharpValidator:
    """Test C# .csproj validation."""

    def test_valid_csproj(self):
        """Test validation of valid .csproj."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            csproj = repo_path / "MyProject.csproj"
            csproj.write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net7.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.0" />
  </ItemGroup>
</Project>""")

            validator = CSharpValidator(repo_path)
            is_valid, errors = validator.validate()
            assert is_valid, f"Unexpected errors: {errors}"

    def test_missing_csproj(self):
        """Test detection of missing .csproj file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = CSharpValidator(repo_path)
            is_valid, errors = validator.validate()
            assert not is_valid
            assert any(".csproj" in e for e in errors)

    def test_invalid_xml(self):
        """Test detection of invalid XML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            csproj = repo_path / "MyProject.csproj"
            # More obviously malformed XML
            csproj.write_text("Not valid XML at all <Project")

            validator = CSharpValidator(repo_path)
            is_valid, errors = validator.validate()
            # Should detect non-XML content or mismatched tags
            assert any("XML" in e or "Mismatched" in e for e in errors)

    def test_empty_dependencies(self):
        """Test detection of empty dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            csproj = repo_path / "MyProject.csproj"
            csproj.write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net7.0</TargetFramework>
  </PropertyGroup>
</Project>""")

            validator = CSharpValidator(repo_path)
            is_valid, errors = validator.validate()
            assert any("No package references" in e for e in errors)


class TestGetValidator:
    """Test validator factory function."""

    def test_get_python_validator(self):
        """Test getting Python validator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = get_validator("python", repo_path)
            assert isinstance(validator, PythonValidator)

    def test_get_rust_validator(self):
        """Test getting Rust validator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = get_validator("rust", repo_path)
            assert isinstance(validator, RustValidator)

    def test_get_javascript_validator(self):
        """Test getting JavaScript validator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = get_validator("javascript", repo_path)
            assert isinstance(validator, JavaScriptValidator)

    def test_get_csharp_validator(self):
        """Test getting C# validator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = get_validator("csharp", repo_path)
            assert isinstance(validator, CSharpValidator)

    def test_invalid_language(self):
        """Test handling of invalid language."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            validator = get_validator("invalid", repo_path)
            assert validator is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
