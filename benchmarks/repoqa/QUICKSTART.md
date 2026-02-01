# RepoQA Adapter Quick Start

Get the RepoQA adapter running in 10 minutes.

## Prerequisites

- Python 3.9+
- Git
- Harbor installed and working
- A RepoQA dataset (JSONL format)

## 1. Install Dependencies

```bash
cd benchmarks/repoqa
pip install -e .
```

The package is lightweight—no heavy dependencies beyond what Harbor already requires.

## 2. Prepare Your Dataset

RepoQA dataset format (JSONL, one object per line):

```json
{
  "instance_id": "tensorflow-001",
  "repository": "tensorflow/tensorflow",
  "commit": "abc1234def5678",
  "language": "python",
  "function_description": "Validates input tensor shapes and types for operations",
  "canonical_function": "tensorflow/python/ops/check_ops.py::assert_all_finite",
  "canonical_path": "tensorflow/python/ops/check_ops.py",
  "canonical_name": "assert_all_finite",
  "semantic_metadata": {
    "mutates_state": false,
    "throws_errors": true,
    "performs_io": false,
    "is_async": false
  }
}
```

## 3. Generate Harbor Tasks

```bash
python run_adapter.py \
  --dataset_path /path/to/repoqa-dataset.jsonl \
  --output_dir ./repoqa_tasks \
  --variants sr-qa \
  --limit 3
```

Output:
```
INFO: Found 500 total instances in dataset
INFO: Generating 3 tasks for variant: sr-qa
INFO: [1/3] Generating tensorflow-001-sr-qa
INFO: [2/3] Generating tensorflow-002-sr-qa
INFO: [3/3] Generating tensorflow-003-sr-qa
INFO: Task generation complete!
  Variants: sr-qa
  Success: 3/3
  Errors:  0/3
```

## 4. Inspect a Task

```bash
ls repoqa_tasks/tensorflow-001-sr-qa/
# instruction.md
# task.toml
# tests/
# environment/

cat repoqa_tasks/tensorflow-001-sr-qa/instruction.md
# Shows SR-QA prompt directing agent to use Sourcegraph MCP
```

## 5. Run with Harbor

```bash
# Baseline (no MCP)
harbor run \
  --path repoqa_tasks/tensorflow-001-sr-qa \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1

# With MCP
harbor run \
  --path repoqa_tasks/tensorflow-001-sr-qa \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

## 6. Check Results

After Harbor finishes:

```bash
cat jobs/tensorflow-001-sr-qa/stdout.txt | tail -20
# Shows agent output and reward score

ls jobs/tensorflow-001-sr-qa/logs/verifier/
# reward.json - the actual scores
```

The `reward.json` contains:
- `correct_function`: Did agent find the right function?
- `correct_path`: Is the file path correct?
- `justification_score`: Does explanation match behavior?

## Generate All Three Variants

```bash
python run_adapter.py \
  --dataset_path /path/to/repoqa-dataset.jsonl \
  --output_dir ./repoqa_tasks_full \
  --variants sr-qa md-qa nr-qa \
  --limit 5
```

This creates 15 tasks total (5 instances × 3 variants).

## Filtering Options

```bash
# By language
python run_adapter.py ... --languages python javascript rust

# By specific IDs
python run_adapter.py ... --instance_ids tensorflow-001 pytorch-002

# Limit results
python run_adapter.py ... --limit 10
```

## Understanding the Scores

### SR-QA (Semantic Retrieval)
```json
{
  "correct_function": 1.0,     // Found exact function
  "correct_path": 1.0,         // File path was correct
  "justification_score": 0.8   // Explanation matched behavior
}
```

### MD-QA (Multi-Hop Dependency)
```json
{
  "correct_function": 1.0,     // Root function was correct
  "correct_path": 0.67,        // Call path was 2/3 correct
  "justification_score": 0.5   // Placeholder
}
```

### NR-QA (Negative/Disambiguation)
```json
{
  "correct_function": 1.0,     // Picked the right function (binary)
  "correct_path": 0.8,         // Path was similar
  "justification_score": 0.9   // Mentioned the constraint
}
```

## Common Issues

### "Dataset file not found"
```bash
python run_adapter.py --dataset_path $(pwd)/repoqa-dataset.jsonl ...
# Use absolute paths
```

### "Template not found"
Make sure you're running from the correct directory:
```bash
cd benchmarks/repoqa
python run_adapter.py ...
```

### Tasks not generating
Check the JSONL format:
```bash
head -1 repoqa-dataset.jsonl | python -m json.tool
# Should parse as valid JSON
```

## Next Steps

1. **Run baseline comparison**: Generate baseline and MCP results
2. **Analyze metrics**: Compare token usage, accuracy across variants
3. **Extend to more languages**: JavaScript, Rust, Go
4. **Collect more tasks**: Use RepoQA's full 500-task dataset

## Getting Help

- See [DESIGN.md](DESIGN.md) for architecture details
- Check [README.md](README.md) for full documentation
- Review [DI-Bench adapter](../dibench/) for pattern reference
