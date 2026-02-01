# RepoQA Adapter

A Harbor adapter that transforms the RepoQA benchmark into three tool-sensitive task variants for measuring semantic code navigation and codebase understanding improvements from Sourcegraph MCP.

## Overview

**RepoQA** (arXiv:2406.06025) is a benchmark for long-context code understanding. The original task presents agents with a 16K token code context and asks them to find a function matching a natural language description.

**Our Approach**: We derive a **tool-sensitive variant** that removes long-context memorization and instead tests **semantic code navigation using Sourcegraph MCP**. This enables measurement of how much Sourcegraph improves code understanding beyond memorization.

## Task Variants

### 1. Semantic Retrieval QA (SR-QA)
**Goal**: Locate a function by behavior, not name.

- **Input**: Function description (no code context, no function names)
- **Tools**: Sourcegraph MCP semantic search
- **Output**: Function path and name
- **Signal**: Can agents use semantic search to find functions?

**Why It's Tool-Sensitive**:
- No function names in the prompt → can't use grep
- No code context → can't scroll and find it
- Semantic description → requires understanding behavior, not keywords
- Solution: Use Sourcegraph Deep Search for semantic matching

### 2. Multi-Hop Dependency QA (MD-QA)
**Goal**: Understand call paths and data flow.

- **Input**: Question about which function handles/enforces a requirement
- **Tools**: Sourcegraph call graph queries
- **Output**: Root function + valid call path
- **Signal**: Can agents reason about function relationships?

**Why It's Tool-Sensitive**:
- Manual exploration is tedious in large codebases
- Call graph queries directly solve the problem
- Tests if agents prefer tools over guessing

### 3. Negative/Disambiguation QA (NR-QA)
**Goal**: Precision in function selection (avoid false positives).

- **Input**: Description + multiple similar functions + disambiguating constraint
- **Tools**: Semantic search + definition inspection
- **Output**: Correct function among candidates
- **Signal**: Semantic understanding vs. lexical matching?

**Why It's Tool-Sensitive**:
- Multiple plausible answers exist
- Semantic search disambiguates better than keyword search
- Requires understanding function semantics (mutations, exceptions, I/O)

## Key Differences from Original RepoQA

| Aspect | Original RepoQA | Our Adapter |
|--------|---|---|
| **Context** | 16K token code context provided | No context; use tools |
| **Signal** | Long-context needle finding | Tool-driven semantic search |
| **Metrics** | BLEU score matching | Exact path/name matching |
| **Tool Dependence** | Can succeed without tools | Tool-sensitive (MCP advantage) |
| **Baseline Comparison** | Model capabilities (window size) | Tool access (MCP vs. no MCP) |

## Architecture

```
repoqa/
├── adapter.py                      # Main adapter: RepoQA → Harbor tasks
├── run_adapter.py                  # CLI tool for task generation
├── ground_truth_extractor.py       # Extract function metadata from repos
├── verifiers.py                    # Score agent outputs
├── templates/
│   ├── task.toml                   # Harbor task config
│   ├── instruction.md              # Generic instruction
│   ├── instruction_sr-qa.md        # SR-QA specific
│   ├── instruction_md-qa.md        # MD-QA specific
│   ├── instruction_nr-qa.md        # NR-QA specific
│   ├── environment/
│   │   └── Dockerfile              # Task environment
│   └── tests/
│       └── test.sh                 # Verification script
└── DESIGN.md                       # Detailed design document
```

## Usage

### 1. Generate Tasks from RepoQA Dataset

```bash
python run_adapter.py \
  --dataset_path repoqa-instances.jsonl \
  --output_dir ./harbor_tasks \
  --variants sr-qa md-qa nr-qa \
  --languages python javascript \
  --limit 10
```

This creates Harbor-compatible task directories, one per variant per instance.

### 2. Verify Agent Solutions

Each task's `tests/test.sh` automatically scores the agent's output:

```bash
cd harbor_tasks/instance-001-sr-qa
./tests/test.sh
# Writes /logs/verifier/reward.json with scores
```

Scores include:
- `correct_function`: 0.0-1.0 (path and name match)
- `correct_path`: 0.0-1.0 (file path similarity)
- `justification_score`: 0.0-1.0 (keyword overlap with description)

### 3. Extract Ground Truth

To generate ground truth from a repository:

```bash
python ground_truth_extractor.py /path/to/repo output.json
```

This extracts:
- All functions and their locations
- Call graph (callers/callees)
- Semantic tags (mutates_state, throws_errors, performs_io, is_async)
- Natural language descriptions (from RepoQA dataset)

## Ground Truth Format

```json
{
  "src/auth/verify.py::verify_token": {
    "function_id": "src/auth/verify.py::verify_token",
    "canonical_path": "src/auth/verify.py",
    "canonical_name": "verify_token",
    "language": "python",
    "mutates_state": false,
    "throws_errors": true,
    "performs_io": false,
    "is_async": false,
    "callers": ["src/handlers/api.py::authenticate_request"],
    "callees": ["jwt.decode", "time.time"],
    "nl_description": "Validates JWT tokens from Authorization headers"
  }
}
```

## Verifier Output

Each task produces `reward.json`:

```json
{
  "correct_function": 0.5,
  "correct_path": 1.0,
  "justification_score": 0.8,
  "reasoning": "Path match: 1.00 (expected src/auth/verify.py)..."
}
```

Harbor aggregates these metrics across all tasks.

## Why This Measures MCP Value

### Without MCP (Baseline)
- Agent searches codebase manually (grep, local navigation)
- Limited by human navigation speed and attention
- Likely to miss context or settle for approximate matches
- Can't efficiently traverse call graphs

### With MCP (MCP Variant)
- Agent uses Sourcegraph semantic search
- Direct access to call graphs and dependencies
- Can find functions by behavior, not name
- Semantic understanding helps with disambiguation

**Expected Result**: MCP agent outperforms baseline on all three variants, with largest gains on MD-QA (graph reasoning) and NR-QA (semantic disambiguation).

## Semantic Tags Explanation

Used in NR-QA to disambiguate similar functions:

- **`mutates_state`**: Function modifies global/nonlocal state or database
- **`throws_errors`**: Function raises exceptions on error conditions
- **`performs_io`**: Function reads/writes files or network
- **`is_async`**: Function is async/await or callback-based

Example: Two functions both validate input, but only one throws exceptions on failure. The constraint helps agents pick the right one.

## Implementation Status

- [x] Ground truth extractor (Python)
- [x] Three verifier classes (SR-QA, MD-QA, NR-QA)
- [x] Adapter and CLI tool
- [x] Templates (instructions, Dockerfile, test script)
- [x] Documentation

## Next Steps

- [ ] Extend ground truth extractor to JavaScript, Rust, Go
- [ ] Integrate with RepoQA public dataset
- [ ] Run comparison benchmarks (baseline vs. MCP)
- [ ] Publish results and methodology
- [ ] Refine scoring based on early results

## References

- **RepoQA Paper**: https://arxiv.org/abs/2406.06025
- **RepoQA Code**: https://github.com/evalplus/repoqa
- **Sourcegraph MCP**: https://sourcegraph.com/docs/api/mcp
- **DI-Bench Adapter**: ../dibench/ (pattern reference)

## Design Rationale

See [DESIGN.md](DESIGN.md) for detailed design decisions, scoring methodology, and architectural choices.
