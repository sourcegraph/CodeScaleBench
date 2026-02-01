# DI-Bench Python-Based Validators

## Overview

The DI-Bench adapter uses Python-based dependency validators instead of Docker-in-Docker with GitHub Actions (`act`) for validation. This approach:

- ✅ **Eliminates Docker-in-Docker complexity** - No nested container requirement
- ✅ **Works with Podman** - Compatible with our Podman setup
- ✅ **Faster execution** - No container startup overhead
- ✅ **Focuses on the task** - Validates dependency inference, not full CI/CD execution

## What the Validators Check

### Python Validator
- **Build files**: `requirements.txt`, `setup.py`, `pyproject.toml`
- **Syntax validation**:
  - Requirement format: `package_name==version`, `package>=2.0`, etc.
  - TOML bracket matching
  - String literal pairing
- **Dependency checks**:
  - At least one dependency declared
  - Valid version specifiers

### Rust Validator
- **Build file**: `Cargo.toml`
- **Syntax validation**:
  - Required `[package]` section
  - Bracket matching
  - String literal pairing
- **Dependency checks**:
  - `[dependencies]` section exists
  - At least one dependency declared
  - Valid dependency syntax (`name = "version"` or `name = { ... }`)

### JavaScript Validator
- **Build file**: `package.json`
- **Syntax validation**:
  - Valid JSON format
  - Required `name` and `version` fields
- **Dependency checks**:
  - At least one dependency or devDependency declared
  - Valid version specifiers

### C# Validator
- **Build file**: `*.csproj`
- **Syntax validation**:
  - Valid XML format
  - Bracket matching
- **Dependency checks**:
  - At least one `<PackageReference>` declared
  - Valid package reference format

## Usage in Test Scripts

The validators are invoked during task execution via the test script:

```bash
#!/bin/bash
cd /app/repo
python3 << 'EOF'
from validators import validate_task

language = 'python'  # or 'rust', 'javascript', 'csharp'
repo_path = '/app/repo'

is_valid, errors = validate_task(language, repo_path)

if is_valid:
    print("✓ Validation passed!")
    reward = 1
else:
    print("✗ Validation failed:")
    for error in errors:
        print(f"  - {error}")
    reward = 0

# Write reward for Harbor
with open('/logs/verifier/reward.txt', 'w') as f:
    f.write(str(reward))
EOF
```

## Validation Return Value

- **`reward = 1`**: All syntax validations passed (valid build files with declarations)
- **`reward = 0`**: Syntax errors or missing critical build files

## What This Validates

✅ **Agent correctly identified** build files to edit
✅ **Agent applied valid syntax** to dependency declarations
✅ **Agent fixed basic errors** (malformed JSON, mismatched brackets, etc.)
✅ **Build files are parseable** and syntactically correct

❌ **Does NOT check**:
- Whether dependencies actually exist on package registries
- Whether the project builds/compiles (requires language toolchains)
- Whether tests pass (requires running CI/CD)
- Whether all dependencies are found (focus: syntax + presence)

## Adding New Language Support

To add a new language validator:

1. Create a class inheriting from `DependencyValidator`:

```python
class GoValidator(DependencyValidator):
    language = "go"
    build_files = ["go.mod", "go.sum"]
    
    def validate_syntax(self) -> Tuple[bool, List[str]]:
        # Implement syntax validation
        pass
    
    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        # Check for dependency declarations
        pass
```

2. Register in `get_validator()`:

```python
validators = {
    "python": PythonValidator,
    "rust": RustValidator,
    "javascript": JavaScriptValidator,
    "csharp": CSharpValidator,
    "go": GoValidator,  # Add here
}
```

3. Add tests in `tests/test_validators.py`

## Testing

Run all validator tests:

```bash
cd adapters/dibench
python -m pytest tests/test_validators.py -v
```

Test a specific validator:

```bash
python -m pytest tests/test_validators.py::TestPythonValidator -v
```

## Implementation Details

### File: `validators.py`
- Base `DependencyValidator` class with common validation flow
- Language-specific validator classes
- Factory function `get_validator()` for instantiation
- Entry point `validate_task()` for test scripts

### File: `test_python.sh`
- Test script template that invokes Python validators
- Writes reward (0/1) to `/logs/verifier/reward.txt` for Harbor
- Handles import errors gracefully

### File: `Dockerfile.simplified`
- Multi-language environment without Docker-in-Docker
- Includes Python, Node.js, Rust, .NET, and pip
- Copies `validators.py` into container
- No `act` or Docker daemon required

## Integration with DI-Bench Adapter

When generating tasks, the adapter can use either approach:

1. **Old approach** (with Docker): Uses `act` to run full GitHub Actions CI/CD
   - Requires Docker-in-Docker
   - Full test execution
   - Slower, more infrastructure overhead

2. **New approach** (recommended): Uses Python validators
   - No Docker nesting
   - Syntax + presence validation only
   - Fast, Podman-compatible
   - Suitable for MCP benchmarking

## Migration Guide

To use the new validators in task generation:

1. Update `adapter.py` to use `Dockerfile.simplified` instead of `Dockerfile`
2. Use `test_python.sh` as template for test scripts
3. Copy `validators.py` to task containers
4. Update task templates to reference new validation approach

Example in adapter:

```python
# Instead of:
dockerfile_path = "templates/environment/Dockerfile"

# Use:
dockerfile_path = "templates/environment/Dockerfile.simplified"
```
