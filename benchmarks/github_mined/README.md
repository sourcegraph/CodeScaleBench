# GitHub-Mined Benchmark

## Overview

The GitHub-Mined benchmark contains 25 real-world pull request tasks mined from the PyTorch repository. Each task represents a multi-file code change that was successfully merged into production.

## Dataset Characteristics

| Attribute | Value |
|-----------|-------|
| **Number of Tasks** | 25 |
| **Source Repository** | PyTorch (pytorch/pytorch) |
| **Task Type** | Multi-file bug fixes and improvements |
| **Sample Size** | Limited (single large codebase) |
| **Difficulty Range** | Medium to Hard |
| **Files Changed per Task** | 2-8 files |
| **Evaluation Method** | Test pass/fail |

## What This Benchmark Measures

✅ **Does measure:**
- Can agents make multi-file code changes?
- Do agents follow existing code patterns and conventions?
- Can agents run test suites and interpret results?
- Do agents make logically coherent changes across file boundaries?
- Agent success rate on real GitHub PRs

❌ **Does NOT measure:**
- Whether agents genuinely understand codebase architecture
- Whether agents use tools effectively or just pattern-match changes
- How efficiently agents retrieve relevant code
- Agent performance on diverse task types (features, refactoring, perf optimization)
- Whether baseline vs MCP comparison is fair (both agents have repo access, but different search strategies)

## Known Limitations

1. **Single Repository Scope**
   - All 25 tasks from PyTorch only
   - Cannot generalize to different codebases or languages
   - No diversity across codebase sizes or architecture styles

2. **Binary Success Metric**
   - Pass/fail based on test execution
   - Doesn't capture:
     - Whether agent understood the problem or got lucky
     - How many attempts/tokens were needed
     - Whether changes follow best practices
     - Quality of intermediate reasoning

3. **Limited Task Diversity**
   - Majority are bug fixes (~60%)
   - Few feature implementations (~15%)
   - No refactoring or performance optimization tasks
   - No system design or architectural changes

4. **Test Execution Dependency**
   - Requires PyTorch's full test suite to run
   - Environment setup may fail (missing deps, CUDA, etc.)
   - Test failures don't always reflect code quality
   - Some valid fixes may not be testable in isolation

5. **No Tool-Sensitivity Validation**
   - Doesn't measure whether agents use Sourcegraph MCP or manual grep
   - Can't distinguish between lucky guesses and informed searches
   - Process quality (how agent got to the solution) is invisible

## Baseline vs MCP Comparison Validity

### Valid for:
- Testing that agents can make syntactically correct changes
- Testing that agents understand test execution workflow
- General multi-file editing capability

### NOT valid for:
- Measuring MCP value (both agents access pre-cloned repo)
- Measuring search strategy effectiveness (no difference in code visibility)
- Comparing time/token efficiency (both agents have same information)

**Recommendation:** Use github_mined for general code change capability. For MCP evaluation, use big_code_mcp with process metrics (tool calls, retrieval patterns, context efficiency).

## Task Structure

Each task (sgt-001 through sgt-025) contains:

```
sgt-NNN/
├── instruction.md          # Task description, requirements, success criteria
├── repo_path               # Path to repository root in container
├── task.toml               # Harbor task metadata
├── environment/
│   └── Dockerfile          # Container image with pre-cloned repo
└── tests/
    └── test.sh             # Validation script (runs PyTorch test suite)
```

## How to Use

### Generate Tasks
```bash
cd ~/harbor
harbor run \
  --path benchmarks/github_mined \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 5  # Run 5 tasks as pilot
```

### Compare Baseline vs MCP
```bash
source .env.local
export ANTHROPIC_API_KEY SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL

# Baseline (local grep/find)
harbor run --path benchmarks/github_mined \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 25

# MCP (Sourcegraph semantic search)
harbor run \
  --path benchmarks/github_mined \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 25
```

### Validate Results
```bash
python scripts/validate_comparison_results.py baseline/ mcp/
```

## Future Improvements

To address limitations, consider:

1. **Expand to multiple repositories** - Include tasks from different Python projects (FastAPI, Django, NumPy, etc.)
2. **Add diverse task types** - Include feature implementation, refactoring, performance optimization
3. **Add process metrics** - Capture token usage, tool calls, context window utilization
4. **Add trajectory analysis** - Store agent reasoning, searches, and decision-making steps
5. **Add reference implementations** - Document what the "ideal" approach would look like for each task
6. **Task difficulty stratification** - Categorize by architectural scope, file count, domain knowledge required

See `history/benchmark-design-review-20251220.md` for detailed analysis of current limitations and proposed improvements.

## References

- **Repository:** https://github.com/pytorch/pytorch
- **Mining Details:** See `docs/MINING_EXECUTION_REPORT.md`
- **Design Review:** See `history/benchmark-design-review-20251220.md`
- **Related Beads:**
  - CodeContextBench-2wz: Design new benchmark for diverse task types
  - CodeContextBench-13j: Design new benchmark for process metrics
