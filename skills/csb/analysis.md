# CSB Analysis Skills

Compare configs, audit MCP usage, IR quality metrics, cost analysis, and trace evaluation. Use when analyzing benchmark results, comparing configurations, or investigating MCP impact.

**Relevant files:** `scripts/compare_configs.py`, `scripts/mcp_audit.py`, `scripts/ir_analysis.py`, `scripts/cost_report.py`, `scripts/audit_traces.py`

---

## Compare Configs

Compare results between agent configurations to find signal about MCP tool impact.

### Steps

#### 1. Run the comparison
```bash
cd ~/CodeScaleBench && python3 scripts/compare_configs.py --format json
```

#### 2. Present results as tables

**Overall pass rates** by config, **divergence analysis** (stable, all-fail, divergent), and **divergent task detail table**.

Focus on: biggest winner, MCP helps, MCP hurts, all-fail tasks.

#### 3. MCP-conditioned analysis (optional)

```bash
python3 scripts/mcp_audit.py --paired-only --json --verbose 2>/dev/null
```

Separates used-MCP vs zero-MCP tasks. Present reward delta table by intensity bucket.

### Variants
```bash
python3 scripts/compare_configs.py --suite csb_sdlc_pytorch --format json
python3 scripts/compare_configs.py --divergent-only --format json
python3 scripts/compare_configs.py --format table
```

---

## MCP Audit

Analyze MCP (Sourcegraph) tool usage across benchmark runs.

### What This Does

`scripts/mcp_audit.py`:
1. Collects `task_metrics.json` from paired_rerun batches
2. Pairs baseline vs sourcegraph_full tasks
3. Classifies by MCP usage: zero-MCP vs used-MCP (light/moderate/heavy)
4. Computes reward and time deltas conditioned on actual MCP usage
5. Identifies negative flips

### Steps

#### 1. Run the audit
```bash
cd ~/CodeScaleBench && python3 scripts/mcp_audit.py --json --verbose 2>/dev/null
```

#### 2. Present key findings

Tables: Overview, per-benchmark MCP adoption, reward deltas (used-MCP only), timing deltas.

#### 3. Investigate zero-MCP tasks

Classify: trivially local, explicit file list, full local codebase, both configs failed, agent confusion.

#### 4. Check for negative flips

Tasks where baseline passes but SG_full fails.

#### 5. MCP tool distribution

Show which tools are most/least used.

#### 6. Summary and recommendations

MCP value, MCP risk, optimization opportunities, cost-benefit.

### Variants
```bash
python3 scripts/mcp_audit.py --all-runs --json --verbose
python3 scripts/mcp_audit.py --verbose  # text output
```

### Key Technical Notes
- Transcript-first extraction: Tool counts from `claude-code.txt`, NOT `trajectory.json`
- Paired reruns: BL and SF concurrent on same VM
- MCP tool name variants: `sg_` prefix or not, script handles both

---

## IR Analysis

Measure how well agents find the right files, comparing baseline vs MCP retrieval against ground truth.

### Steps

#### 1. Ensure ground truth is built
```bash
cd ~/CodeScaleBench && python3 scripts/ir_analysis.py --build-ground-truth
```

#### 2. Run the IR analysis
```bash
cd ~/CodeScaleBench && python3 scripts/ir_analysis.py --json 2>/dev/null
```

#### 3. Present key findings

Per-benchmark IR scores, overall aggregates, statistical tests.

Key metrics: file recall, MRR, context efficiency, P@K.

### Variants
```bash
python3 scripts/ir_analysis.py --per-task --json 2>/dev/null
python3 scripts/ir_analysis.py --suite csb_sdlc_swebenchpro 2>/dev/null
```

### Ground Truth Sources

| Benchmark | Strategy | Confidence |
|-----------|----------|:----------:|
| SWE-bench Pro | Patch headers | high |
| PyTorch | Diff headers | high |
| K8s Docs | Directory listing | high |
| Governance/Enterprise | Test script paths | medium |
| Others | Instruction regex | low |

---

## Cost Report

Analyze token usage and estimated cost across benchmark runs.

### Steps
```bash
cd ~/CodeScaleBench && python3 scripts/cost_report.py
```

Shows: total cost/tokens/hours, per suite/config breakdown, config cost comparison, top 10 most expensive tasks.

### Variants
```bash
python3 scripts/cost_report.py --suite csb_sdlc_pytorch
python3 scripts/cost_report.py --config sourcegraph_full
python3 scripts/cost_report.py --format json
```

---

## Evaluate Traces

Comprehensive evaluation of benchmark run traces: data integrity, output quality, efficiency analysis.

### Phases

#### Phase 1: Scope Selection
- MANIFEST: `runs/official/MANIFEST.json`
- Audit script: `python3 scripts/audit_traces.py [--json] [--suite X] [--config X]`

#### Phase 2: Data Integrity
- MCP adoption validation (transcript-first, check both `sg_` prefix variants)
- Baseline contamination check (zero `mcp__sourcegraph` calls)
- Infrastructure failure detection (zero-token, crash, null-token H3 bug)
- Dedup integrity

#### Phase 3: Output Quality
- Per-suite reward analysis
- Cross-config comparison (matched tasks)
- Task-level quality patterns (MCP helps/hurts/neutral)

#### Phase 4: Efficiency
- Token usage and cost estimates
- Wall clock time deltas
- MCP tool distribution
- Cost-effectiveness ratios

#### Phase 5: Synthesis
Write report to `docs/TRACE_AUDIT_<date>.md`.

### Known Patterns
1. Zero-token (int 0) = auth failures
2. Null-token + no trajectory + <=5 lines = crash failures
3. Null-token + valid rewards = H3 token-logging bug (not failures)
4. MCP distraction on TAC
5. Deep Search unused (~1%)
6. SWE-Perf regression under MCP
7. Subagent MCP calls hidden in trajectory.json (only in claude-code.txt)
8. Zero-MCP is ~80% rational
9. Monotonic MCP intensity-reward: Light +2.2%, Moderate +3.6%, Heavy +6.1%
