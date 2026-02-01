# DI-Bench Adapter Quick Start

## Step 1: Download DI-Bench Dataset

```bash
# Download from releases (choose your dataset variant)
wget https://github.com/microsoft/DI-Bench/releases/download/v1.0/dibench-regular-python.tar.gz

# Create directory and extract
mkdir -p ~/.cache/dibench/repo-data
tar -xvzf dibench-regular-python.tar.gz -C ~/.cache/dibench/repo-data
```

## Step 2: Download the Dataset Metadata File

The JSONL dataset file contains metadata for all instances:

```bash
wget https://github.com/microsoft/DI-Bench/releases/download/v1.0/dibench-regular.jsonl
```

## Step 3: Run the Adapter

```bash
cd benchmarks/dibench

# Generate first 5 Python tasks
python run_adapter.py \
    --dataset_path dibench-regular.jsonl \
    --repo_instances_dir ~/.cache/dibench/repo-data \
    --output_dir ./output \
    --languages python \
    --limit 5
```

## Step 4: Run with Harbor

Once tasks are generated, you can run them with Harbor:

```bash
# Run a single task
harbor run --path ./benchmarks/dibench/output/python-instance-001 \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001

# Run all generated tasks
harbor run --dataset ./benchmarks/dibench/output \
           --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
           --model anthropic/claude-haiku-4-5-20251001 \
           --n-concurrent 4
```

## Example Task Structure

After generation, each task will have this structure:

```
output/python-instance-001/
├── instruction.md              # Task instructions
├── task.toml                  # Harbor configuration
├── environment/
│   ├── Dockerfile            # Environment setup
│   └── repo/                 # Project repository
│       ├── src/
│       ├── requirements.txt  # File to be edited
│       └── ...
├── solution/
│   └── solve.sh             # Reference solution
└── tests/
    ├── test.sh              # Runs CI/CD tests
    └── instance.json        # Instance metadata
```

## What Agents Need to Do

For each task, the agent should:

1. Read the project code in `/app/repo`
2. Identify all external dependencies
3. Edit the build file(s) (e.g., `requirements.txt`)
4. Add correct dependency specifications
5. Ensure tests pass

## Evaluation

Success is measured by whether the project's CI/CD tests pass after the agent's edits.

## Troubleshooting

**Issue**: "Dataset file not found"
- **Solution**: Make sure to download the JSONL metadata file

**Issue**: "Repository instances directory not found"
- **Solution**: Extract the tar.gz file to the correct location

**Issue**: "Docker build fails"
- **Solution**: Ensure Docker daemon is running and Sysbox is installed

## Next Steps

- Try different languages: `--languages rust csharp javascript`
- Increase concurrency: `--n-concurrent 10`
- Use different agents: `--agent openai-assistant`
- Analyze results and improve prompts

## Resources

- [DI-Bench Repository](https://github.com/microsoft/DI-Bench)
- [Harbor Documentation](https://harborframework.com)
- [Full README](./README.md)
