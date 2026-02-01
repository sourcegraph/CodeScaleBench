# DependEval Phase 3 Benchmark

This directory contains the DependEval benchmark tasks generated for Phase 3 evaluation: testing whether Sourcegraph MCP (Model Context Protocol) improves code understanding for multi-file and cross-repository tasks.

## Overview

- **Task count**: 9 samples
- **Task types**: 
  - DR (Dependency Recognition): Identify function calls and dependencies
  - RC (Repository Construction): Build call graphs from code
  - ME (Multi-file Editing): Make coherent changes across multiple files
- **Languages**: Python, Java, JavaScript
- **Data source**: DependEval dataset (https://github.com/ink7-sudo/DependEval)

## Task Structure

Each task directory follows the Harbor benchmark format:

```
<task_type>_<language>/
└── <task_name>/
    ├── task.toml              # Task metadata
    ├── instruction.md         # Agent instructions (what to do)
    ├── ground_truth.json      # Expected answer
    ├── environment/
    │   ├── Dockerfile         # Container setup with code clone
    │   ├── code_content.txt    # Code files and structure
    │   ├── ground_truth.json   # Ground truth answer
    │   └── eval_scripts/
    │       └── eval_*.py       # Evaluation script (scores answer)
    ├── solution/
    │   └── solve.sh           # Oracle solution
    └── tests/
        └── test.sh            # Test runner
```

## Running the Benchmark

### Prerequisites

```bash
# Set up environment
source .env.local
export ANTHROPIC_API_KEY SOURCEGRAPH_URL SOURCEGRAPH_ACCESS_TOKEN GITHUB_TOKEN

# Install Harbor
cd CodeContextBench
source harbor/bin/activate
```

### Baseline Run (No MCP)

```bash
# Run a single task with Claude Code (no MCP)
harbor run \
    --path benchmarks/dependeval_benchmark/DR_python/dependency_recognition-python-unknown \
    --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
    --model anthropic/claude-haiku-4-5-20251001 \
    -n 1
```

### MCP-Enabled Run

```bash
# Run with Sourcegraph MCP
harbor run \
    --path benchmarks/dependeval_benchmark/DR_python/dependency_recognition-python-unknown \
    --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
    --model anthropic/claude-haiku-4-5-20251001 \
    -n 1
```

### Full Comparison

```bash
# Run complete baseline vs MCP comparison
bash scripts/run_dependeval_comparison.sh

# Analyze results
python scripts/analyze_dependeval_comparison.py jobs/dependeval-comparison-YYYYMMDD-HHMM
```

## What Gets Evaluated

### Dependency Recognition (DR)
- **Input**: Code snippet with function calls
- **Task**: Identify which functions are called
- **Evaluation**: Precision/recall of identified dependencies

Example task: `DR_python/`

### Repository Construction (RC)
- **Input**: Code snippets from a repository
- **Task**: Build a call graph showing relationships between functions
- **Evaluation**: F1 score on graph structure (15% nodes, 85% edges)

Example task: `RC_java/`

### Multi-file Editing (ME)
- **Input**: Description of a code change to make
- **Task**: Edit multiple files to implement the change coherently
- **Evaluation**: Similarity to ground truth implementation

Example task: `ME_javascript/`

## Phase 3 Hypothesis

**Hypothesis**: Agents with access to Sourcegraph MCP (code search) will perform better on multi-file and cross-repository tasks because:

1. **DR tasks**: Search helps identify which functions exist and are called
2. **RC tasks**: Search helps build accurate call graphs across files
3. **ME tasks**: Search helps find where to make changes and understand dependencies

## Indexed Repositories

All 150 DependEval repositories have been indexed into Sourcegraph:
- **Endpoint**: https://sourcegraph.sourcegraph.com
- **External Service ID**: RXh0ZXJuYWxTZXJ2aWNlOjExNDg=
- **Status**: Indexing in progress (may take hours to fully sync)

## Results and Analysis

Results from comparisons will be saved to:
```
jobs/dependeval-comparison-YYYYMMDD-HHMM/
├── baseline/
│   └── <task_name>/
│       ├── run.log
│       ├── trajectory.json     # Agent's action sequence
│       └── reward.txt          # Final score
└── mcp/
    └── <task_name>/
        ├── run.log
        ├── trajectory.json
        └── reward.txt
```

## Key Files

- [scripts/run_dependeval_comparison.sh](../../scripts/run_dependeval_comparison.sh) - Run full comparison
- [scripts/analyze_dependeval_comparison.py](../../scripts/analyze_dependeval_comparison.py) - Analyze results
- [agents/mcp_variants.py](../../agents/mcp_variants.py) - MCP variants (StrategicDeepSearchAgent recommended)
- [AGENTS.md](../../AGENTS.md) - Project guidelines

## Notes

- Tasks use lowercase repo names (e.g., `yarolegovich/discretescrollview`) for Sourcegraph API compatibility
- Evaluation scripts use simplified scoring (no LLM judge, unlike original DependEval)
- Some tasks may fail if code clone doesn't work - this is expected for research-only projects
- Oracle solution typically scores 1.0 on its task

## See Also

- [DependEval Repository](https://github.com/ink7-sudo/DependEval)
- [Sourcegraph Documentation](https://docs.sourcegraph.com)
- [Harbor Benchmarking Guide](../../docs/)
