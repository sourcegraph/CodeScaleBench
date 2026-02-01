# DI-Bench Adapter for Harbor

This adapter converts [DI-Bench](https://github.com/microsoft/DI-Bench) (Dependency Inference Benchmark) tasks into Harbor's task format.

## Overview

DI-Bench is a benchmark for evaluating Large Language Models on dependency inference tasks. It tests whether LLMs can correctly infer and configure dependencies for software projects across multiple programming languages.

### Supported Languages
- Python
- Rust
- C# (csharp)
- JavaScript/TypeScript

## Prerequisites

1. **Download DI-Bench Dataset**

   Download the dataset from the [DI-Bench releases page](https://github.com/microsoft/DI-Bench/releases).

   ```bash
   # Create cache directory
   mkdir -p .cache/repo-data

   # Extract dataset for each language
   tar -xvzf dibench-regular-python.tar.gz -C .cache/repo-data
   tar -xvzf dibench-regular-rust.tar.gz -C .cache/repo-data
   tar -xvzf dibench-regular-csharp.tar.gz -C .cache/repo-data
   tar -xvzf dibench-regular-javascript.tar.gz -C .cache/repo-data
   ```

2. **Install Dependencies**

   ```bash
   cd adapters/dibench
   pip install -e .
   ```

## Usage

### Basic Usage

```bash
python run_adapter.py \
    --dataset_path path/to/dibench-regular.jsonl \
    --repo_instances_dir .cache/repo-data \
    --output_dir ./dibench_tasks
```

### Advanced Usage

```bash
# Generate only Python tasks
python run_adapter.py \
    --dataset_path dibench-regular.jsonl \
    --repo_instances_dir .cache/repo-data \
    --output_dir ./dibench_tasks \
    --languages python

# Generate first 10 tasks
python run_adapter.py \
    --dataset_path dibench-regular.jsonl \
    --repo_instances_dir .cache/repo-data \
    --output_dir ./dibench_tasks \
    --limit 10

# Generate specific instances
python run_adapter.py \
    --dataset_path dibench-regular.jsonl \
    --repo_instances_dir .cache/repo-data \
    --output_dir ./dibench_tasks \
    --instance_ids instance-001 instance-042

# Generate multiple languages
python run_adapter.py \
    --dataset_path dibench-regular.jsonl \
    --repo_instances_dir .cache/repo-data \
    --output_dir ./dibench_tasks \
    --languages python rust csharp
```

## Task Structure

Each generated Harbor task contains:

```
task-name/
├── instruction.md          # Task description and requirements
├── task.toml              # Harbor configuration
├── environment/
│   ├── Dockerfile         # Multi-language environment setup
│   └── repo/              # Copy of the repository
├── solution/
│   └── solve.sh           # Reference solution (applies patch)
└── tests/
    ├── test.sh            # Runs CI/CD tests
    └── instance.json      # Instance metadata
```

## How It Works

1. **Task Loading**: The adapter loads DI-Bench instances from the JSONL dataset file
2. **Repository Setup**: Each instance's repository is copied to the task environment
3. **Instruction Generation**: Creates clear instructions for dependency inference
4. **Test Integration**: Uses GitHub Actions runner (`act`) to execute CI/CD tests
5. **Evaluation**: Success is measured by whether tests pass after dependency configuration

## Task Flow

For each DI-Bench instance, agents need to:

1. Analyze the project structure in `/app/repo`
2. Review source code to identify dependencies
3. Edit build files (e.g., `requirements.txt`, `Cargo.toml`, `package.json`, `.csproj`)
4. Add all necessary dependency configurations
5. Ensure the project builds and tests pass

## Requirements

### System Requirements
- Docker with Sysbox runtime (for secure CI/CD execution)
- Python 3.10+
- Sufficient disk space for repository data

### Python Dependencies
- See `pyproject.toml` for full list

## Dataset Information

DI-Bench provides two dataset variants:
- **Regular**: Standard difficulty instances
- **Large**: More complex, larger projects

Each instance includes:
- Repository source code
- CI/CD configuration
- Environment specifications
- Reference solution (patch with correct dependencies)

## Evaluation Methodology

The evaluation follows DI-Bench's approach:

1. Agent modifies build files to add dependency configurations
2. The modified files are applied to the repository
3. CI/CD tests are executed using GitHub Actions (via `act`)
4. Success = all tests pass (reward = 1), Failure = any test fails (reward = 0)

## Troubleshooting

### Common Issues

**Docker permission errors**: Ensure Docker daemon is running and user has proper permissions

**Sysbox requirement**: DI-Bench requires Sysbox for isolation. Install from [nestybox/sysbox](https://github.com/nestybox/sysbox)

**Missing dataset**: Download from DI-Bench releases and extract to `.cache/repo-data/{language}/`

**Large environment**: The Dockerfile includes all language runtimes for maximum compatibility

## References

- [DI-Bench GitHub Repository](https://github.com/microsoft/DI-Bench)
- [DI-Bench Dataset Releases](https://github.com/microsoft/DI-Bench/releases)
- [Harbor Framework](https://harborframework.com)

## License

This adapter follows Harbor's licensing. DI-Bench is licensed under MIT by Microsoft.
