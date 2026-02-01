# DI-Bench Adapter Usage Guide

## Quick Start

### 1. Download DI-Bench Data

```bash
# Download dataset
mkdir -p ~/.cache/dibench/repo-data
cd ~/.cache/dibench

# Download from DI-Bench releases
wget https://github.com/microsoft/DI-Bench/releases/download/v1.0/dibench-regular-python.tar.gz
wget https://github.com/microsoft/DI-Bench/releases/download/v1.0/dibench-regular.jsonl

# Extract
tar -xvzf dibench-regular-python.tar.gz -C repo-data/
```

### 2. Generate Harbor Tasks

```bash
cd benchmarks/dibench

# Generate 10 Python tasks
python run_adapter.py \
    --dataset_path ~/.cache/dibench/dibench-regular.jsonl \
    --repo_instances_dir ~/.cache/dibench/repo-data \
    --output_dir ./dibench_tasks \
    --languages python \
    --limit 10
```

### 3. Run with Harbor

**Option A: Run individual task**
```bash
harbor run --path ./benchmarks/dibench/dibench_tasks/python-instance-001 \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001
```

**Option B: Run all tasks in directory**
```bash
harbor run --dataset ./benchmarks/dibench/dibench_tasks \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001 \
           --n-concurrent 4
```

**Option C: Use custom registry (for dataset-style usage)**
```bash
# 1. Generate registry
python generate_registry.py \
    --tasks_dir ./dibench_tasks \
    --output ./dibench-registry.json

# 2. Use with Harbor
harbor run --dataset dibench@1.0 \
           --registry ./dibench-registry.json \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001
```

## Advanced Usage

### Filter by Language

```bash
# Generate only Rust tasks
python run_adapter.py \
    --dataset_path ~/.cache/dibench/dibench-regular.jsonl \
    --repo_instances_dir ~/.cache/dibench/repo-data \
    --output_dir ./dibench_tasks \
    --languages rust

# Multiple languages
python run_adapter.py \
    --dataset_path ~/.cache/dibench/dibench-regular.jsonl \
    --repo_instances_dir ~/.cache/dibench/repo-data \
    --output_dir ./dibench_tasks \
    --languages python rust csharp
```

### Specific Instances

```bash
python run_adapter.py \
    --dataset_path ~/.cache/dibench/dibench-regular.jsonl \
    --repo_instances_dir ~/.cache/dibench/repo-data \
    --output_dir ./dibench_tasks \
    --instance_ids instance-042 instance-101
```

### Batch Processing

```bash
# Generate all Python tasks
python run_adapter.py \
    --dataset_path ~/.cache/dibench/dibench-regular.jsonl \
    --repo_instances_dir ~/.cache/dibench/repo-data \
    --output_dir ./dibench_tasks_full \
    --languages python

# Run evaluation
harbor run --path ./dibench_tasks_full \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001 \
           --n-concurrent 10 \
           --output-dir ./results
```

## Environment Variables

```bash
# GitHub token for act (CI runner)
export GITHUB_TOKEN=your_github_token

# Harbor environment
export ANTHROPIC_API_KEY=<your-anthropic-key>
```

## Directory Structure

After running the adapter:

```
adapters/dibench/
├── dibench_tasks/           # Generated Harbor tasks
│   ├── python-instance-001/
│   ├── python-instance-002/
│   └── ...
└── dibench-registry.json    # Optional: custom registry
```

## Tips

1. **Start small**: Use `--limit 5` to test before generating all tasks
2. **Check disk space**: Each task includes full repo copy (50-500MB)
3. **Use filters**: `--languages` to focus on specific languages
4. **Parallel execution**: Use `--n-concurrent` based on your system resources

## Troubleshooting

**Issue**: Tasks not found
```bash
# Use relative paths from CodeContextBench root
harbor run --path ./benchmarks/dibench/dibench_tasks/python-instance-001 \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001
```

**Issue**: Docker build fails
```bash
# Check Docker is running
docker ps

# Verify Sysbox is installed
docker run --runtime=sysbox-runc hello-world
```

**Issue**: Large disk usage
```bash
# Clean up generated tasks after evaluation
rm -rf ./dibench_tasks

# Or keep only specific tasks
find ./dibench_tasks -name "python-*" -type d
```
