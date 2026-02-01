# DI-Bench Harbor Integration Guide

## Overview

This document explains how the DI-Bench adapter integrates with the Harbor framework.

## Architecture

### Components

1. **DIBenchInstance**: Data model representing a DI-Bench repository instance
2. **DIBenchLoader**: Loads instances from JSONL dataset files
3. **DIBenchAdapter**: Main adapter class that converts instances to Harbor tasks
4. **Templates**: Reusable templates for task generation

### Data Flow

```
DI-Bench Dataset (JSONL)
        ↓
DIBenchLoader
        ↓
DIBenchInstance
        ↓
DIBenchAdapter
        ↓
Harbor Task Directory
```

## Integration Points

### 1. Dataset Loading

The adapter loads DI-Bench instances from JSONL files:

```python
loader = DIBenchLoader(dataset_path="dibench-regular.jsonl")
instance = loader.load("python/instance-001")
```

### 2. Task Generation

Each instance is converted to a Harbor task:

```python
adapter = DIBenchAdapter(
    task_dir=output_dir,
    repo_instances_dir=repo_dir,
    dataset_path=dataset_path
)
adapter.generate_task("python/instance-001", "python-instance-001")
```

### 3. Environment Setup

The Dockerfile template creates a multi-language environment supporting:
- Python 3.10+
- Node.js 18+
- Rust (latest stable)
- .NET 7.0+
- Docker-in-Docker (for act)

### 4. Evaluation

Tests run using GitHub Actions via `act`:

```bash
act -j test --secret GITHUB_TOKEN=$GITHUB_TOKEN
```

## Harbor Registry Integration

To register DI-Bench with Harbor's dataset registry:

```json
{
  "name": "dibench",
  "version": "1.0",
  "adapter": "dibench",
  "description": "Dependency Inference Benchmark",
  "languages": ["python", "rust", "csharp", "javascript"],
  "task_count": 400,
  "difficulty": "medium",
  "categories": ["dependency-inference", "build-configuration"]
}
```

## Usage in Harbor CLI

Once integrated, users can run:

```bash
# List DI-Bench datasets
harbor datasets list | grep dibench

# Run evaluation
harbor run --dataset dibench@1.0 \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001
```

## Customization

### Adding New Languages

To support additional languages:

1. Update `Dockerfile` template with language runtime
2. Add language-specific build file patterns
3. Update `dibench.yaml` configuration

### Modifying Evaluation

To change evaluation criteria:

1. Edit `templates/tests/test.sh`
2. Adjust reward calculation logic
3. Update timeout values in `task.toml`

## Performance Considerations

- **Disk Space**: Each task includes full repository copy (~50-500MB per task)
- **Build Time**: Docker images include all language runtimes (~5-10 minutes)
- **Evaluation Time**: CI/CD tests vary (30 seconds to 10 minutes per task)

### Optimization Tips

1. Use `--languages` filter to process specific languages
2. Use `--limit` for testing before full runs
3. Pre-build Docker images for faster iteration
4. Use concurrent execution (`--n-concurrent`)

## Debugging

### Enable verbose logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Check generated task

```bash
# Inspect task directory
ls -la output/python-instance-001/

# Validate task.toml
harbor validate output/python-instance-001/task.toml

# Test Docker build
cd output/python-instance-001/environment
docker build -t dibench-test .
```

### Test evaluation locally

```bash
# Build and run container
docker build -t dibench-test .
docker run -it --privileged dibench-test bash

# Inside container
cd /app/repo
bash /tests/test.sh
```

## Troubleshooting

### Common Issues

**Import errors in adapter.py**
- Ensure Harbor src path is correct
- Check Python path includes Harbor source

**Template rendering failures**
- Verify all placeholders match context keys
- Check for special characters in values

**Docker build failures**
- Increase build timeout in task.toml
- Check Dockerfile syntax
- Verify base image availability

**Test execution failures**
- Ensure sysbox runtime is installed
- Check GITHUB_TOKEN is set
- Verify act is installed in Docker image

## Contributing

To contribute improvements:

1. Test changes with multiple languages
2. Update parity_experiments.json
3. Run validation tests
4. Update documentation
5. Submit pull request to Harbor

## References

- [Harbor Framework Docs](https://harborframework.com)
- [DI-Bench Repository](https://github.com/microsoft/DI-Bench)
- [Harbor Adapter Guide](https://harborframework.com/docs/adapters)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
