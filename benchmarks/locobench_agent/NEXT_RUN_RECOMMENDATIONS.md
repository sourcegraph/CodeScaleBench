# LoCoBench Next Run Recommendations

**Date**: 2026-01-25  
**Previous Run**: 50 tasks, baseline + deepsearch, ~45% avg reward, 0 passing (>=0.8)  
**Next Run Model**: Claude Opus 4.5

---

## Changes Made

### 1. instruction.md Template (UPDATED)

Location: `/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/templates/instruction.md`

Changes:
- Added structured output requirements with specific sections (Key Files, Code Evidence, Analysis, Summary)
- Added explicit instructions for code modification tasks: "IMPLEMENT the code changes directly in /app/project/"
- Added task type guidance (analysis vs modification tasks)
- Added Deep Search MCP usage instructions with repository reference requirements
- Emphasized file path format requirements for verifier alignment

### 2. CLAUDE.md Template (CREATED)

Location: `/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/templates/CLAUDE.md`

New file containing:
- Sourcegraph Deep Search MCP tool documentation (since skills don't load in headless mode)
- Effective search strategies
- Example workflow for using MCP tools
- Task output requirements
- Code modification task guidance

### 3. Model Configuration (UPDATED)

Files updated:
- `/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/configs_v2/examples/locobench_50_tasks_comparison.sh`
- `/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/configs_v2/examples/locobench_50_tasks_comparison.yaml`

Change: `claude-sonnet-4-20250514` -> `claude-opus-4-5-20251101`

### 4. Verifier Weights (UPDATED)

Location: `/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/templates/tests/verify.py`

Old weights:
- keyword_overlap: 0.50 (too dominant)
- file_references: 0.20
- code_blocks: 0.20
- length_score: 0.10

New weights:
- keyword_overlap: 0.35 (reduced - ground truth keywords can be overly specific)
- file_references: 0.30 (increased - shows agent explored codebase)
- code_blocks: 0.25 (increased - shows evidence-based analysis)
- length_score: 0.10 (unchanged)

---

## Key Findings from Previous Run Analysis

### Solution.md Truncation: NOT AN ISSUE
- All 100 solution.md files analyzed
- Average length: ~1,900 words
- Length score: 1.0 (100%) for all tasks
- Files have proper markdown structure with conclusions

### Sourcegraph Skill: NOT LOADING IN HEADLESS MODE
- Evidence: `"skills": []` in agent init messages
- MCP server connects successfully
- Solution: Included skill content directly in CLAUDE.md template

### Root Cause of Low Scores
- keyword_overlap averaged only 0.21 (21%)
- Ground truth keywords too specific (exact paths, function names)
- Valid alternative phrasings penalized
- Adjusted weights to reduce keyword dominance

---

## Expected Improvements

| Metric | Previous Run | Expected |
|--------|--------------|----------|
| Avg Reward | 0.44 | 0.60+ |
| Keyword Overlap | 0.21 | 0.35+ |
| File Ref Score | 0.58 | 0.70+ |
| Passing (>=0.8) | 0% | 15%+ |

---

## Pre-Run Checklist

### Verify Changes
- [x] instruction.md updated with structured output requirements
- [x] CLAUDE.md created with Sourcegraph skill content
- [x] Model updated to claude-opus-4-5-20251101 in configs
- [x] Verifier weights adjusted

### Before Running
- [ ] Verify ANTHROPIC_API_KEY is set in ~/evals/.env.local
- [ ] Verify SOURCEGRAPH_ACCESS_TOKEN is set for MCP mode
- [ ] Run single task test to verify configuration

### Run Command
```bash
cd /home/stephanie_jarmak/evals/custom_agents/agents/claudecode
./configs_v2/examples/locobench_50_tasks_comparison.sh
```

Or for specific variants:
```bash
./configs_v2/examples/locobench_50_tasks_comparison.sh --baseline-only
./configs_v2/examples/locobench_50_tasks_comparison.sh --mcp-only
```

---

## Files Modified Summary

| File | Change |
|------|--------|
| templates/instruction.md | Structured output requirements, code modification guidance |
| templates/CLAUDE.md | New file with Sourcegraph skill content |
| templates/tests/verify.py | Adjusted scoring weights |
| configs_v2/examples/locobench_50_tasks_comparison.sh | Model -> Opus 4.5 |
| configs_v2/examples/locobench_50_tasks_comparison.yaml | Model -> Opus 4.5 |
