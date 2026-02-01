#!/usr/bin/env python3
"""
DI-Bench Python-based validators for dependency inference tasks.

Replaces Docker-in-Docker CI/CD execution with syntax validation and
dependency checking for Python, Rust, JavaScript, and C# projects.
"""

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class DependencyValidator(ABC):
    """Base class for dependency validators."""

    language: str
    build_files: List[str]

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    @abstractmethod
    def validate_syntax(self) -> Tuple[bool, List[str]]:
        """Validate syntax of build files. Returns (is_valid, errors)."""
        pass

    @abstractmethod
    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """Validate dependency declarations. Returns (is_valid, errors)."""
        pass

    def validate(self) -> Tuple[bool, List[str]]:
        """Run all validations. Returns (is_valid, all_errors)."""
        errors = []

        # Check that at least one build file exists
        found_any = False
        for build_file in self.build_files:
            build_path = self.repo_path / build_file
            if build_path.exists():
                found_any = True
                break

        if not found_any:
            return False, [f"No build files found. Expected one of: {', '.join(self.build_files)}"]

        # Run syntax validation
        syntax_ok, syntax_errors = self.validate_syntax()
        errors.extend(syntax_errors)

        # Run dependency validation (non-critical warnings are OK)
        deps_ok, deps_errors = self.validate_dependencies()
        # Only add critical errors (not warnings about missing dependencies)
        errors.extend([e for e in deps_errors if "not found" in e.lower() or "error" in e.lower()])

        # Return based on critical errors only
        return len(errors) == 0, errors if errors else deps_errors


class PythonValidator(DependencyValidator):
    """Validator for Python projects using requirements.txt or pyproject.toml."""

    language = "python"
    build_files = ["requirements.txt", "setup.py", "pyproject.toml"]

    def validate_syntax(self) -> Tuple[bool, List[str]]:
        """Validate requirements.txt/setup.py syntax."""
        errors = []

        # Check requirements.txt if it exists
        req_path = self.repo_path / "requirements.txt"
        if req_path.exists():
            errors.extend(self._validate_requirements_txt(req_path))

        # Check pyproject.toml if it exists
        pyproject_path = self.repo_path / "pyproject.toml"
        if pyproject_path.exists():
            errors.extend(self._validate_pyproject_toml(pyproject_path))

        return len(errors) == 0, errors

    def _validate_requirements_txt(self, path: Path) -> List[str]:
        """Validate requirements.txt syntax."""
        errors = []
        try:
            with open(path) as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Basic validation: should be package_name or package_name==version
                    # Allow operators: ==, >=, <=, >, <, !=, ~=
                    if not self._is_valid_requirement(line):
                        errors.append(
                            f"requirements.txt:{i} - Invalid requirement syntax: {line}"
                        )
        except Exception as e:
            errors.append(f"Error reading requirements.txt: {e}")
        return errors

    def _validate_pyproject_toml(self, path: Path) -> List[str]:
        """Validate pyproject.toml syntax."""
        errors = []
        try:
            with open(path) as f:
                content = f.read()
                # Check for malformed TOML (basic check)
                if content.count("[") != content.count("]"):
                    errors.append("pyproject.toml: Mismatched brackets in TOML")
                if '"""' in content and content.count('"""') % 2 != 0:
                    errors.append("pyproject.toml: Unclosed multi-line string")
        except Exception as e:
            errors.append(f"Error reading pyproject.toml: {e}")
        return errors

    @staticmethod
    def _is_valid_requirement(line: str) -> bool:
        """Check if line is a valid requirement."""
        # Pattern: package_name with optional version specifiers
        # e.g., "requests", "requests==2.28.0", "requests>=2.28.0,<3.0"
        pattern = r"^[a-zA-Z0-9\-_.]+(\s*[><=!~]+\s*[0-9\.\*]+)?(\s*,\s*[><=!~]+\s*[0-9\.\*]+)*$"
        return bool(re.match(pattern, line))

    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """Check that at least some dependencies are declared."""
        errors = []

        req_path = self.repo_path / "requirements.txt"
        has_deps = False

        if req_path.exists():
            try:
                with open(req_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            has_deps = True
                            break
            except Exception:
                pass

        if not has_deps:
            errors.append(
                "No dependencies found in requirements.txt (expected for most projects)"
            )

        return len(errors) == 0, errors


class RustValidator(DependencyValidator):
    """Validator for Rust projects using Cargo.toml."""

    language = "rust"
    build_files = ["Cargo.toml"]

    def validate_syntax(self) -> Tuple[bool, List[str]]:
        """Validate Cargo.toml syntax."""
        errors = []
        cargo_path = self.repo_path / "Cargo.toml"

        if not cargo_path.exists():
            return False, ["Cargo.toml not found"]

        try:
            with open(cargo_path) as f:
                content = f.read()

                # Check for required [package] section
                if "[package]" not in content:
                    errors.append("Cargo.toml: Missing [package] section")

                # Check for mismatched brackets
                if content.count("[") != content.count("]"):
                    errors.append("Cargo.toml: Mismatched brackets")

                # Check for unclosed strings
                if content.count('"') % 2 != 0:
                    errors.append("Cargo.toml: Unclosed string literal")

                # Validate dependencies section format if present
                if "[dependencies]" in content:
                    errors.extend(self._validate_cargo_dependencies(content))

        except Exception as e:
            errors.append(f"Error reading Cargo.toml: {e}")

        return len(errors) == 0, errors

    @staticmethod
    def _validate_cargo_dependencies(content: str) -> List[str]:
        """Validate [dependencies] section format."""
        errors = []
        # Extract dependencies section
        match = re.search(
            r"\[dependencies\](.*?)(?=\[|$)", content, re.DOTALL
        )
        if match:
            deps_section = match.group(1)
            for line in deps_section.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Should be: name = "version" or name = { version = "...", ... }
                if "=" not in line:
                    errors.append(f"Cargo.toml: Invalid dependency syntax: {line}")
        return errors

    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """Check that at least some dependencies are declared."""
        errors = []
        cargo_path = self.repo_path / "Cargo.toml"

        if not cargo_path.exists():
            return False, ["Cargo.toml not found"]

        try:
            with open(cargo_path) as f:
                content = f.read()
                # Check for [dependencies] section with at least one dependency
                if "[dependencies]" not in content:
                    errors.append(
                        "No [dependencies] section found in Cargo.toml"
                    )
                else:
                    # Check that section is not empty
                    match = re.search(
                        r"\[dependencies\](.*?)(?=\[|$)", content, re.DOTALL
                    )
                    if match:
                        deps_section = match.group(1).strip()
                        has_deps = any(
                            line.strip() and not line.strip().startswith("#")
                            for line in deps_section.split("\n")
                        )
                        if not has_deps:
                            errors.append("No dependencies found in [dependencies] section")
        except Exception as e:
            errors.append(f"Error reading Cargo.toml: {e}")

        return len(errors) == 0, errors


class JavaScriptValidator(DependencyValidator):
    """Validator for JavaScript/TypeScript projects using package.json."""

    language = "javascript"
    build_files = ["package.json"]

    def validate_syntax(self) -> Tuple[bool, List[str]]:
        """Validate package.json syntax."""
        errors = []
        pkg_path = self.repo_path / "package.json"

        if not pkg_path.exists():
            return False, ["package.json not found"]

        try:
            with open(pkg_path) as f:
                data = json.load(f)
                # Check for required fields
                if "name" not in data:
                    errors.append("package.json: Missing 'name' field")
                if "version" not in data:
                    errors.append("package.json: Missing 'version' field")
        except json.JSONDecodeError as e:
            errors.append(f"package.json: Invalid JSON syntax: {e}")
        except Exception as e:
            errors.append(f"Error reading package.json: {e}")

        return len(errors) == 0, errors

    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """Check that at least some dependencies are declared."""
        errors = []
        pkg_path = self.repo_path / "package.json"

        if not pkg_path.exists():
            return False, ["package.json not found"]

        try:
            with open(pkg_path) as f:
                data = json.load(f)
                has_deps = bool(data.get("dependencies")) or bool(
                    data.get("devDependencies")
                )
                if not has_deps:
                    errors.append(
                        "No dependencies found in package.json (expected for most projects)"
                    )
        except Exception as e:
            errors.append(f"Error reading package.json: {e}")

        return len(errors) == 0, errors


class CSharpValidator(DependencyValidator):
    """Validator for C# projects using .csproj files."""

    language = "csharp"
    build_files = ["*.csproj"]

    def __init__(self, repo_path: Path):
        super().__init__(repo_path)
        # Find actual .csproj file
        csproj_files = list(repo_path.glob("*.csproj"))
        if csproj_files:
            self.build_files = [csproj_files[0].name]

    def validate_syntax(self) -> Tuple[bool, List[str]]:
        """Validate .csproj XML syntax."""
        errors = []
        csproj_files = list(self.repo_path.glob("*.csproj"))

        if not csproj_files:
            return False, ["No .csproj file found"]

        for csproj_path in csproj_files:
            try:
                with open(csproj_path) as f:
                    content = f.read()
                    # Basic XML validation
                    if not content.strip().startswith("<"):
                        errors.append(f"{csproj_path.name}: Not valid XML")
                    if content.count("<") != content.count(">"):
                        errors.append(f"{csproj_path.name}: Mismatched XML tags")
            except Exception as e:
                errors.append(f"Error reading {csproj_path.name}: {e}")

        return len(errors) == 0, errors

    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """Check that package references are declared."""
        errors = []
        csproj_files = list(self.repo_path.glob("*.csproj"))

        if not csproj_files:
            return False, ["No .csproj file found"]

        for csproj_path in csproj_files:
            try:
                with open(csproj_path) as f:
                    content = f.read()
                    # Check for ItemGroup with PackageReference
                    if "<PackageReference" not in content:
                        errors.append(
                            f"{csproj_path.name}: No package references found (expected for most projects)"
                        )
            except Exception as e:
                errors.append(f"Error reading {csproj_path.name}: {e}")

        return len(errors) == 0, errors


def get_validator(language: str, repo_path: Path) -> Optional[DependencyValidator]:
    """Get the appropriate validator for the language."""
    validators = {
        "python": PythonValidator,
        "rust": RustValidator,
        "javascript": JavaScriptValidator,
        "csharp": CSharpValidator,
    }

    validator_class = validators.get(language.lower())
    if validator_class:
        return validator_class(repo_path)
    return None


def validate_task(language: str, repo_path: Path) -> Tuple[bool, List[str]]:
    """
    Validate a DI-Bench task.

    Args:
        language: Project language (python, rust, javascript, csharp)
        repo_path: Path to the repository

    Returns:
        (is_valid, error_messages)
    """
    validator = get_validator(language, repo_path)
    if not validator:
        return False, [f"Unsupported language: {language}"]

    return validator.validate()
