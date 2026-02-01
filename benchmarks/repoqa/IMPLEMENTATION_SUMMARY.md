# RepoQA Adapter Implementation Summary

**Status**: ✅ Complete  
**Date**: December 20, 2025  
**Tests**: 23 passing (0 failures)

## What Was Implemented

A production-ready Harbor adapter that transforms the RepoQA benchmark into a **tool-sensitive evaluation framework** measuring how much Sourcegraph MCP improves code understanding.

## Core Components

### 1. Ground Truth Extraction (`ground_truth_extractor.py`)
- **PythonFunctionExtractor**: AST-based extraction of functions with semantic analysis
- **RepositoryAnalyzer**: Analyzes entire repositories to extract:
  - All function locations (path + name)
  - Call graphs (callers and callees)
  - Semantic tags:
    - `mutates_state`: Modifies globals, databases, file system
    - `throws_errors`: Raises exceptions  
    - `performs_io`: File/network I/O
    - `is_async`: Async/await functions
  - Natural language descriptions (from RepoQA dataset)

**Status**: Working. Tested on `requests` library (221 functions extracted).

### 2. Semantic Verifiers (`verifiers.py`)
Three task-specific verifiers scoring agent outputs:

#### SR-QA Verifier (Semantic Retrieval)
- Scores exact match on (path, name)
- Partial credit for path or name match
- Justification scored by keyword overlap with NL description
- Returns: `correct_function` (0-1), `correct_path` (0-1), `justification_score` (0-1)

#### MD-QA Verifier (Multi-Hop Dependency)
- Validates call path exists in call graph
- Scores root function match
- Partial credit for prefix-correct paths
- Returns: `correct_function`, `correct_path`, `justification_score`

#### NR-QA Verifier (Negative/Disambiguation)
- Binary scoring: correct or wrong (no partial credit)
- Checks for semantic constraint mention in justification
- Returns: `correct_function` (0 or 1), `correct_path` (0-1 partial), `justification_score` (0-1)

**Status**: Working. Tested with sample solutions, produces expected scores.

### 3. Adapter (`adapter.py`)
Converts RepoQA instances to Harbor task directories:

- Loads RepoQA dataset (JSONL format)
- Generates Harbor-compatible task structure per variant
- Creates task.toml with metadata
- Generates variant-specific instructions
- Embeds ground truth in task
- Produces execution script (test.sh)

**Status**: Working. Generates valid task directories.

### 4. CLI Tool (`run_adapter.py`)
Command-line interface for batch task generation:

```bash
python run_adapter.py \
  --dataset_path repoqa-instances.jsonl \
  --output_dir ./harbor_tasks \
  --variants sr-qa md-qa nr-qa \
  --languages python javascript \
  --limit 10
```

Supports filtering by:
- Language
- Specific instance IDs
- Limit (for testing)

**Status**: Working. Batch-generates tasks correctly.

## Documentation

### Design Document (DESIGN.md)
- Benchmark transformation rationale
- Task variant explanations
- Why it's tool-sensitive
- Scoring methodology
- Harbor task format specification
- Design principles and success criteria

### README (README.md)
- Overview and key differences from original RepoQA
- Architecture diagram
- Task variant descriptions
- Usage instructions
- Ground truth format
- Verifier output specification
- Why this measures MCP value

### Quick Start Guide (QUICKSTART.md)
- 10-minute setup
- Dataset format
- Task generation command
- Harbor execution
- Score interpretation
- Common issues and fixes

## Test Suite

### Unit Tests (test_adapter.py)
- RepoQALoader: Load dataset, filter instances ✅
- RepoQAAdapter: Generate tasks, set metadata ✅
- SemanticRetrievalQAVerifier: Score SR-QA outputs ✅
- NegativeRetrievalQAVerifier: Binary scoring ✅

### Integration Tests (test_ground_truth.py)
- PythonFunctionExtractor: Detect mutations, exceptions, I/O, async ✅
- RepositoryAnalyzer: Analyze full repos, build call graphs ✅
- FunctionMetadata: Dataclass operations ✅

**Total**: 23 tests, all passing

## Templates

### Dockerfile
- Lightweight Ubuntu base
- Git clone at specific commit
- Python dependencies (tree-sitter)

### Instructions (instruction_sr-qa.md, instruction_md-qa.md, instruction_nr-qa.md)
- Variant-specific task descriptions
- Tool usage guidance (Sourcegraph MCP)
- Output format specifications
- Scoring rubric

### Task Configuration (task.toml)
- Metadata fields (repo, commit, language, variant)
- Timeouts (verifier, agent, environment)
- Resource limits (CPU, memory, storage)

### Test Script (test.sh)
- Runs verifier on agent solution
- Produces reward.json for Harbor
- Error handling and fallbacks

## Key Achievements

1. **Transformed RepoQA**: From long-context memorization test → tool-sensitive semantic navigation benchmark

2. **Three Task Variants**: Each tests different aspects of code understanding
   - SR-QA: Semantic search capability
   - MD-QA: Graph reasoning and call path understanding
   - NR-QA: Semantic precision (avoid false positives)

3. **Comprehensive Ground Truth**: Full function metadata with call graphs and semantic tags

4. **Robust Scoring**: Handles partial matches, exact matches, and edge cases

5. **Production Ready**: 
   - 23 passing tests
   - Full documentation
   - Command-line interface
   - Harbor integration

## How It Measures MCP Value

### Without MCP (Baseline)
- Agent searches manually (grep, local navigation)
- Can't efficiently explore call graphs
- Limited by human navigation speed
- Likely to settle for approximate matches

### With MCP
- Sourcegraph Deep Search understands semantics
- Call graph queries answer relationship questions directly
- Can find functions by behavior, not name
- Better disambiguation among similar functions

**Expected Result**: MCP agent consistently outperforms baseline on all three variants, with largest gains on MD-QA (graph reasoning) and NR-QA (semantic disambiguation).

## File Structure

```
benchmarks/repoqa/
├── __init__.py                 # Package exports
├── adapter.py                  # Main adapter class
├── run_adapter.py              # CLI tool
├── ground_truth_extractor.py   # Function extraction
├── verifiers.py                # Task scoring
├── templates/
│   ├── task.toml
│   ├── instruction.md
│   ├── instruction_sr-qa.md
│   ├── instruction_md-qa.md
│   ├── instruction_nr-qa.md
│   ├── environment/
│   │   └── Dockerfile
│   └── tests/
│       └── test.sh
├── tests/
│   ├── __init__.py
│   ├── test_adapter.py         # 12 tests
│   └── test_ground_truth.py    # 11 tests
├── README.md                   # Full documentation
├── QUICKSTART.md               # Getting started guide
├── DESIGN.md                   # Design rationale
└── IMPLEMENTATION_SUMMARY.md   # This file
```

## Next Steps (Future Work)

1. **Extend Language Support**: JavaScript, Rust, Go (tree-sitter already supports these)
2. **Integrate with Real RepoQA Dataset**: Use published 500-task dataset
3. **Run Comparison Benchmarks**: Baseline vs. MCP measurements
4. **Analyze Results**: Token usage, accuracy, cost-effectiveness
5. **Publish Methodology**: Document findings and results

## Integration with CodeContextBench

The RepoQA adapter fits into the broader Phase 3 implementation:

- **DI-Bench Adapter** (✅ Complete): Tests dependency inference
- **DependEval Adapter** (🔄 In Progress): Tests multi-file editing
- **RepoQA Adapter** (✅ Complete): Tests semantic code navigation

Together, these adapters enable comprehensive measurement of Sourcegraph MCP value across different code understanding tasks.

## Command Reference

### Generate SR-QA Tasks Only
```bash
python run_adapter.py \
  --dataset_path data.jsonl \
  --output_dir tasks \
  --variants sr-qa \
  --limit 5
```

### Generate All Three Variants
```bash
python run_adapter.py \
  --dataset_path data.jsonl \
  --output_dir tasks \
  --variants sr-qa md-qa nr-qa \
  --limit 10
```

### Filter by Language
```bash
python run_adapter.py \
  --dataset_path data.jsonl \
  --output_dir tasks \
  --variants sr-qa \
  --languages python javascript
```

### Extract Ground Truth
```bash
python ground_truth_extractor.py /path/to/repo output.json
```

### Verify Solution
```bash
cd task_dir
./tests/test.sh
cat /logs/verifier/reward.json
```

## Testing

Run all tests:
```bash
cd benchmarks/repoqa
python -m pytest tests/ -v
```

Expected output:
```
23 passed in 0.06s
```

## References

- RepoQA Paper: https://arxiv.org/abs/2406.06025
- RepoQA Code: https://github.com/evalplus/repoqa
- Sourcegraph MCP: https://sourcegraph.com/docs/api/mcp
- DI-Bench Adapter: ../dibench/ (followed this pattern)

---

**Bead Closed**: CodeContextBench-1tn  
**Date Completed**: December 20, 2025  
**Verifier**: benchmarks/repoqa/tests/
