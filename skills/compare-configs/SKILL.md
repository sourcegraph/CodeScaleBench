---
name: compare-configs
description: Compare benchmark results across agent configurations (baseline, SG_full). Show where configs diverge. Triggers on compare configs, config comparison, which config wins, MCP impact.
user-invocable: true
---

# Compare Configs

Compare results between agent configurations to find signal about MCP tool impact.

## Steps

### 1. Run the comparison script

```bash
cd ~/CodeScaleBench && python3 scripts/compare_configs.py --format json
```

### 2. Parse and present the results

Present the JSON output as markdown tables covering:

**Overall pass rates:**

| Config | Pass | Total | Rate |
|--------|------|-------|------|
| baseline | X | Y | Z% |
| SG_full | X | Y | Z% |

**Divergence analysis:**
- Tasks where all configs pass (stable)
- Tasks where all configs fail (likely task/adapter issue)
- **Divergent tasks** (some pass, some fail) — this is the interesting signal
- Tasks where baseline fails but MCP passes — MCP tools are helping
- Tasks where MCP fails but baseline passes — MCP tools are hurting

**Divergent task detail table:**

| Suite | Task | baseline | SG_full | Signal |
|-------|------|----------|---------|--------|
| csb_sdlc_pytorch | sgt-005 | PASS | PASS | MCP-Full matches |

### 3. Highlight key findings

Focus the narrative on:
- **Biggest winner**: Which config has the highest pass rate
- **MCP helps**: Tasks where only MCP configs pass
- **MCP hurts**: Tasks where only baseline passes (investigate why)
- **All-fail**: Tasks failing everywhere (fix these first, helps all configs)

### 4. MCP-conditioned analysis (optional, when user asks about MCP specifically)

The basic divergence analysis treats all SG tasks equally. For deeper MCP insight, run the MCP audit which conditions on actual usage:

```bash
python3 scripts/mcp_audit.py --paired-only --json --verbose 2>/dev/null
```

This separates:
- **Used-MCP tasks**: Agent actually called MCP tools. Reward delta reflects true MCP value.
- **Zero-MCP tasks**: MCP available but unused. Reward delta reflects preamble overhead only.
- **Intensity buckets**: Light (1-5 calls), Moderate (6-20), Heavy (20+) — shows dose-response.

Present the MCP-conditioned reward delta table:

| Group | N | BL Reward | SF Reward | Delta |
|-------|--:|----------:|----------:|------:|
| Used-MCP | N | X | Y | +Z% |
| Zero-MCP | N | X | Y | -Z% |
| Light | N | X | Y | Z% |
| Moderate | N | X | Y | Z% |
| Heavy | N | X | Y | Z% |

**Key insight**: Overall SG vs BL delta is diluted by zero-MCP tasks. Conditioning on usage reveals the true MCP signal. For full analysis, suggest `/mcp-audit`.

## Variants

### Filter to one suite
```bash
python3 scripts/compare_configs.py --suite csb_sdlc_pytorch --format json
```

### Show only divergent tasks
```bash
python3 scripts/compare_configs.py --divergent-only --format json
```

### Table format (compact)
```bash
python3 scripts/compare_configs.py --format table
```
