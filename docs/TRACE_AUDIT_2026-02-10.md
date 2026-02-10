# Trace Audit Report — 2026-02-10

## Executive Summary

Audited 544 task directories across 37 official runs, spanning 13 benchmarks and 3 configurations (baseline, SG_base, SG_full). Found **1 critical data integrity issue** that corrupts SWE-bench Pro SG_full scores, plus systematic zero-token failures affecting multiple suites.

### Critical Finding

**SWE-bench Pro SG_full mean reward is 0.361 in the MANIFEST but should be ~0.667.** An auth-failed run (`swebenchpro_selected_opus_20260208_005525`) produced zero-token results that overwrote 11 valid passing results (reward=1.0) due to timestamp-based dedup.

---

## 1. MCP Tool Usage Validation

### 1.1 SG_full: Deep Search & MCP Usage

Among **MANIFEST tasks** (the ones used for scoring):
- **98% of SG_full tasks used MCP** (56/57 unique tasks)
- Only exception: `sgt-025` (PyTorch) which errored before running

Among **all 190 SG_full task dirs** (including duplicates from multiple runs):

| Suite | Tasks | w/MCP | w/DS | NoMCP | %MCP | %DS |
|-------|------:|------:|-----:|------:|-----:|----:|
| ccb_codereview | 3 | 3 | 3 | 0 | 100% | 100% |
| ccb_crossrepo | 5 | 5 | 5 | 0 | 100% | 100% |
| ccb_dependeval | 32 | 32 | 32 | 0 | 100% | 100% |
| ccb_dibench | 8 | 8 | 8 | 0 | 100% | 100% |
| ccb_k8sdocs | 5 | 5 | 5 | 0 | 100% | 100% |
| ccb_largerepo | 4 | 4 | 4 | 0 | 100% | 100% |
| ccb_linuxflbench | 5 | 5 | 5 | 0 | 100% | 100% |
| ccb_locobench | 25 | 25 | 25 | 0 | 100% | 100% |
| ccb_pytorch | 13 | 11 | 11 | 2 | 85% | 85% |
| ccb_repoqa | 11 | 10 | 10 | 1 | 91% | 91% |
| ccb_swebenchpro | 68 | 45 | 45 | 23 | 66% | 66% |
| ccb_sweperf | 3 | 3 | 3 | 0 | 100% | 100% |
| ccb_tac | 8 | 8 | 8 | 0 | 100% | 100% |
| **TOTAL** | **190** | **164** | **164** | **26** | **86%** | **86%** |

The 26 zero-MCP SG_full tasks are all from stale/auth-failed runs (protonmail, internetarchive, navidrome, nodebb, sgt-025). All valid MANIFEST tasks have MCP.

**Key insight on Deep Search**: Despite appearing "100% used" in the counts above, a deeper analysis shows that actual `deepsearch` invocations (the async agentic search) are extremely rare — only **1 of 129 traced tasks** made a direct `deepsearch` call. The counts above detect `deepsearch` in init tool listings. When filtering to actual `tool_use` events, Deep Search is virtually unused. The agent overwhelmingly prefers synchronous tools.

### 1.2 SG_base: MCP Usage

Among MANIFEST tasks: **100% of SG_base tasks used MCP** (57/57).

Among all 188 SG_base task dirs:

| Suite | Tasks | w/MCP | NoMCP | %MCP | Avg Calls |
|-------|------:|------:|------:|-----:|----------:|
| ccb_codereview | 3 | 3 | 0 | 100% | 12.7 |
| ccb_crossrepo | 5 | 5 | 0 | 100% | 13.8 |
| ccb_dependeval | 32 | 32 | 0 | 100% | 15.0 |
| ccb_dibench | 16 | 12 | 4 | 75% | 16.1 |
| ccb_k8sdocs | 5 | 5 | 0 | 100% | 21.6 |
| ccb_largerepo | 4 | 4 | 0 | 100% | 28.8 |
| ccb_linuxflbench | 5 | 5 | 0 | 100% | 29.0 |
| ccb_locobench | 25 | 25 | 0 | 100% | 22.5 |
| ccb_pytorch | 12 | 12 | 0 | 100% | 28.2 |
| ccb_repoqa | 10 | 10 | 0 | 100% | 13.1 |
| ccb_swebenchpro | 60 | 36 | 24 | 60% | 10.2 |
| ccb_sweperf | 3 | 3 | 0 | 100% | 19.7 |
| ccb_tac | 8 | 8 | 0 | 100% | 24.5 |

Zero-MCP SG_base tasks: All from stale/auth-failed runs, not in MANIFEST.

### 1.3 MCP Tool Distribution

**SG_base (3,114 total MCP calls across 188 task dirs):**

| Tool | Calls | Share |
|------|------:|------:|
| keyword_search | 742 | 23.8% |
| read_file | 518 | 16.6% |
| list_files | 406 | 13.0% |
| nls_search | 225 | 7.2% |
| list_repos | 200 | 6.4% |
| commit_search | 179 | 5.7% |
| find_references | 177 | 5.7% |
| go_to_definition | 176 | 5.7% |
| diff_search | 168 | 5.4% |
| compare_revisions | 163 | 5.2% |
| get_contributor_repos | 160 | 5.1% |

**SG_full (3,685 total MCP calls across 190 task dirs):**

| Tool | Calls | Share |
|------|------:|------:|
| keyword_search | 785 | 21.3% |
| read_file | 683 | 18.5% |
| list_files | 437 | 11.9% |
| nls_search | 227 | 6.2% |
| list_repos | 196 | 5.3% |
| commit_search | 186 | 5.0% |
| diff_search | 174 | 4.7% |
| compare_revisions | 171 | 4.6% |
| deepsearch_read | 168 | 4.6% |
| deepsearch | 165 | 4.5% |
| find_references | 165 | 4.5% |
| go_to_definition | 164 | 4.5% |
| get_contributor_repos | 164 | 4.5% |

**Note**: The deepsearch/deepsearch_read counts include init-line references. Actual tool_use invocations are much lower.

---

## 2. Baseline Contamination Check

### 2.1 MCP Tool Calls: CLEAN

**175 baseline traces checked. 0 contain MCP tool invocations.** No baseline agent ever called an MCP/Sourcegraph tool. The baseline configuration correctly excludes MCP tools from the agent's toolset.

### 2.2 Instruction Contamination: 30 of 156 Tasks

30 baseline `instruction.txt` files (19.2%) contain Sourcegraph/MCP references. All contamination is in runs from Feb 3-5, 2026; runs from Feb 6 onward are clean.

| Source | Tasks Affected | Severity |
|--------|---------------|----------|
| RepoQA (10/10) | "Use Sourcegraph MCP liberally" in instructions | High (but agents scored 1.0 regardless) |
| LargeRepo (4/4) | "use Sourcegraph MCP for broad search" | Medium |
| SWE-Pro gapfill OLD (6/6) | "If Sourcegraph MCP is configured" blocks | Medium |
| K8s Docs (2/5) | Brief SG mention | Low |
| LoCoBench (7/20) | MCP Search Instructions section | Low |
| PyTorch (1/12) | "use Sourcegraph MCP if available" | Low |

**Impact: ZERO functional effect.** The baseline agent has no MCP tools in its toolset, so these instructions are ignored. The agent cannot call tools it doesn't have. However, the contaminated instructions waste context tokens on irrelevant guidance.

---

## 3. Errors and Infrastructure Issues

### 3.1 CRITICAL: Auth-Failed Run Corrupts SG_full Scores

Run `swebenchpro_selected_opus_20260208_005525` failed due to authentication issues. It produced zero-token results for 21 SWE-bench Pro tasks. Because `generate_manifest.py` uses timestamp-based dedup (latest `started_at` wins), 11 valid passing results (reward=1.0) from the earlier run `swebenchpro_selected_opus_20260207_212514` are overwritten.

**Corrupted tasks (all reward=1.0 → 0.0):**
- instance_future-architect__vuls-4c04, vuls-d18e
- instance_gravitational__teleport-0415, teleport-3587
- instance_internetarchive__openlibrary-7f6b, openlibrary-d109, openlibrary-c506
- instance_qutebrowser (4 tasks: 233c, 394b, 3fd8, e534)
- instance_tutao__tutanota-f373

**Current vs Corrected SWE-bench Pro SG_full:**
- Current MANIFEST: mean=0.361 (13 passed, 22 failed, 1 errored)
- Corrected: mean=0.667 (24 passed, 11 failed, 1 errored)
- If errored tasks excluded: mean=0.686

**Fix: Archive `swebenchpro_selected_opus_20260208_005525` and regenerate MANIFEST.**

### 3.2 Zero-Token Infrastructure Failures

45 task results across 4 runs have `n_input_tokens=0, n_output_tokens=0` — the agent never ran.

| Run | Config | Zero-Token | Root Cause |
|-----|--------|-----------|------------|
| swebenchpro_gapfill_20260208_235352 | baseline | 11 | Auth failure |
| swebenchpro_gapfill_20260209_023525 | SG_base | 14 | Auth failure |
| swebenchpro_selected_20260208_005525 | SG_full | 13 | Auth failure |
| locobench_gapfill_20260209_010036 | SG_base | 7 | Auth failure |

**Impact on LoCoBench SG_base**: 7 zero-token tasks drag mean from 0.504 (18 valid) → 0.363 (25 total). This makes SG_base appear worse than baseline (0.449) when the valid mean is actually better (0.504).

### 3.3 Persistent Infrastructure Failures (6 Tasks)

These 6 unique tasks fail across ALL configs due to Docker/environment issues:

| Task | Root Cause |
|------|-----------|
| protonmail/webclients (4 tasks) | Node.js v16 in Docker; Claude Code requires >= v18 |
| internetarchive/openlibrary-92db | Setup returns RC=2 (gpg/curl failure) |
| tutao/tutanota-f373ac38 | Agent binary crash on launch |

These should be classified as `errored` (infrastructure) not `failed` (agent failure).

### 3.4 AgentSetupTimeoutError (18 tasks)

18 SWE-bench Pro SG_full tasks timed out during setup (3600s limit). Overlap with the persistent failures above (protonmail, navidrome, nodebb, openlibrary-92db).

### 3.5 PyTorch sgt-025 Docker Build Failure

2 attempts at sgt-025 under SG_full both failed with `RuntimeError: Docker compose command failed`. The Dockerfile references an unreachable PyTorch commit. Permanently broken for SG_full.

---

## 4. Corrected Scores

### MANIFEST Fixes Applied

1. **Dedup logic**: Now prefers non-zero-token results over zero-token results (prevents auth-failed runs from overwriting valid data)
2. **Infrastructure failure classification**: Zero-token (int 0) auth failures and null-token crash failures (<=5 claude-code.txt lines) are classified as `errored`
3. **Mean reward**: Errored tasks excluded from mean (infra failures are not agent failures)

### Per-Suite Corrected Scores

| Suite | Baseline | SG_base | SG_full |
|-------|---------|---------|---------|
| ccb_codereview | 0.933 | 0.980 | 1.000 |
| ccb_crossrepo | 0.571 | 0.587 | 0.387 |
| ccb_dependeval | 0.636 | 0.665 | 0.720 |
| ccb_dibench | 0.500 | 0.500 | 0.500 |
| ccb_k8sdocs | 0.920 | 0.920 | 0.920 |
| ccb_largerepo | 0.250 | 0.250 | 0.425 |
| ccb_linuxflbench | 0.860 | 0.820 | 0.880 |
| ccb_locobench | 0.449 | 0.504 (7 errored) | 0.499 |
| ccb_pytorch | 0.083 | 0.081 | 0.265 (1 errored) |
| ccb_repoqa | 1.000 | 1.000 | 1.000 |
| ccb_swebenchpro | 0.640 (16 errored) | 0.591 (19 errored) | 0.806 (5 errored) |
| ccb_sweperf | 0.591 | 0.032 | 0.367 |
| ccb_tac | 0.492 | 0.365 | 0.544 |

**Note**: SWE-bench Pro means are now computed over scored tasks only (errored excluded). Different configs have different errored counts due to per-batch auth failures. For fair cross-config comparison, use matched task sets.

### Weighted Averages (all suites, scored tasks only)

| Config | Total Tasks | Errored | Scored | Mean Reward |
|--------|--------:|--------:|-------:|------------:|
| Baseline | 161 | 16 | 145 | **0.578** |
| SG_base | 161 | 26 | 135 | **0.570** |
| SG_full | 156 | 6 | 150 | **0.657** |

**SG_full delta vs baseline: +0.079** on scored tasks.

---

## 5. Actions Taken

### Critical (Done)
1. **DONE**: Archived `swebenchpro_selected_opus_20260208_005525` (auth-failed run)
2. **DONE**: Fixed `generate_manifest.py` dedup to prefer non-zero-token results
3. **DONE**: Classified zero-token/crash tasks as `errored`, excluded from mean_reward
4. **DONE**: Regenerated MANIFEST.json

### Tracked (Beads Issues Filed)
5. **beads-rxg** (P1): Rerun 7 LoCoBench SG_base gap-fill tasks
6. **beads-1in** (P2): Investigate Deep Search non-adoption (1/129 usage)
7. **beads-5m5** (P4): Document PyTorch sgt-025 as permanently excluded

### No Action Needed
8. Instruction template cleanup — source templates already clean (commit b4d30b2c). Contamination only in historical run artifacts.

---

## 6. Data Quality Summary

| Check | Result |
|-------|--------|
| Baseline MCP tool calls | **CLEAN** (0/175 traces) |
| SG_base MCP adoption (MANIFEST) | **100%** scored tasks |
| SG_full MCP adoption (MANIFEST) | **98%** scored tasks (1 Docker errored) |
| Deep Search actual usage | **LOW** (~1/129 actual invocations) |
| Baseline instruction contamination | 30/156 runs (no functional impact, source templates clean) |
| Auth-failed run corruption | **FIXED** (archived + dedup hardened) |
| Infrastructure failures | Classified as `errored`, excluded from mean |
| Persistent Docker failures | 6 unique tasks (protonmail, openlibrary-92db, tutanota) |

**Bottom line**: All critical data integrity issues are resolved. The MANIFEST now correctly classifies infrastructure failures, excludes them from means, and prevents zero-token results from overwriting valid data. SG_full shows meaningful improvement over baseline (+0.079 weighted mean).

---

## 7. Matched-Task Comparison (Fair Cross-Config Analysis)

Because different configs have different error/exclusion counts (especially SWE-bench Pro), per-suite means are not directly comparable. This section uses only tasks that scored successfully in **all 3 configs** for an apples-to-apples comparison.

### 7.1 Matched-Task Suite Averages

125 tasks scored across all 3 configs:

| Suite | Matched | BL Mean | SG_b Mean | SG_f Mean | Δ SG_b | Δ SG_f |
|-------|--------:|--------:|----------:|----------:|-------:|-------:|
| ccb_codereview | 3 | 0.933 | 0.980 | 1.000 | +0.047 | +0.067 |
| ccb_crossrepo | 5 | 0.571 | 0.587 | 0.387 | +0.016 | -0.184 |
| ccb_dependeval | 32 | 0.636 | 0.665 | 0.720 | +0.029 | +0.083 |
| ccb_dibench | 8 | 0.500 | 0.500 | 0.500 | +0.000 | +0.000 |
| ccb_k8sdocs | 5 | 0.920 | 0.920 | 0.920 | +0.000 | +0.000 |
| ccb_largerepo | 4 | 0.250 | 0.250 | 0.425 | +0.000 | +0.175 |
| ccb_linuxflbench | 5 | 0.860 | 0.820 | 0.880 | -0.040 | +0.020 |
| ccb_locobench | 18 | 0.466 | 0.504 | 0.542 | +0.038 | +0.076 |
| ccb_pytorch | 11 | 0.091 | 0.081 | 0.182 | -0.010 | +0.091 |
| ccb_repoqa | 10 | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 |
| ccb_swebenchpro | 12 | 0.667 | 0.667 | 0.733 | +0.000 | +0.067 |
| ccb_sweperf | 3 | 0.591 | 0.032 | 0.367 | -0.559 | -0.224 |
| ccb_tac | 8 | 0.492 | 0.365 | 0.544 | -0.127 | +0.052 |
| **OVERALL** | **125** | **0.600** | **0.599** | **0.630** | **-0.000** | **+0.031** |

**Key takeaways**:
- SG_base is **neutral overall** (-0.000) — helps as often as it hurts
- SG_full provides a **+3.1pp improvement** on matched tasks
- SG_full wins on 7 suites, ties on 3 (ceiling-at-1.0), loses on 3
- SG_base loses badly on SWE-Perf (-0.559) and TAC (-0.127) but these are small-N suites

### 7.2 Outcome Flips (Pass/Fail Changes Between Configs)

Tasks where the binary outcome (pass=reward>0, fail=reward=0) changed:

**MCP Enables (BL=Fail → SG=Pass):**
| Task | BL | SG_b | SG_f | Suite |
|------|---:|-----:|-----:|-------|
| big-code-k8s-001 | 0.000 | 0.000 | 0.700 | LargeRepo (SG_full only) |
| vuls-139f3a81 | 0.000 | 1.000 | — | SWE-Pro (SG_base) |
| rust_api_microservice | 0.000 | — | 1.000 | LoCoBench (SG_full only) |
| dotenv-expand | 0.000 | 1.000 | 1.000 | DIBench |

**MCP Disables (BL=Pass → SG=Fail):**
| Task | BL | SG_b | SG_f | Suite |
|------|---:|-----:|-----:|-------|
| inducer-cgen | 1.000 | 0.000 | 0.000 | DIBench |
| sweperf-002 | 0.775 | 0.000 | — | SWE-Perf (SG_base only) |
| refactor_rename_01 | 0.920 | — | 0.000 | CrossRepo (SG_full only) |
| multifile_editing-ts | 1.000 | — | 0.000 | DependEval (SG_full only) |

**Net**: 4 enabled vs 4 disabled — MCP does not systematically flip outcomes. The value lies in partial-reward improvements on already-passing tasks.

---

## 8. MCP Impact Patterns

### 8.1 Task-Level Impact Classification

**SG_base vs Baseline** (133 matched pairs):
- **Helps** (reward delta > +0.01): 18 tasks (13.5%)
- **Neutral** (|delta| ≤ 0.01): 97 tasks (72.9%)
- **Hurts** (delta < -0.01): 18 tasks (13.5%)

**SG_full vs Baseline** (137 matched pairs):
- **Helps**: 29 tasks (21.2%)
- **Neutral**: 94 tasks (68.6%)
- **Hurts**: 14 tasks (10.2%)

SG_full has a 2:1 help-to-hurt ratio vs SG_base's 1:1 ratio. The enhanced configuration (Deep Search availability + richer preamble) improves outcomes.

### 8.2 Largest MCP Wins (SG_full vs Baseline)

| Suite | Task | BL | SG_f | Δ |
|-------|------|---:|-----:|--:|
| ccb_dibench | dotenv-expand | 0.000 | 1.000 | +1.000 |
| ccb_swebenchpro | vuls-139f3a81 | 0.000 | 1.000 | +1.000 |
| ccb_dependeval | multifile_editing-python-8597 | 0.180 | 1.000 | +0.820 |
| ccb_largerepo | big-code-k8s-001 | 0.000 | 0.700 | +0.700 |
| ccb_dependeval | multifile_editing-ts-4253 | 0.097 | 1.000 | +0.903 |

### 8.3 Largest MCP Losses (SG_full vs Baseline)

| Suite | Task | BL | SG_f | Δ |
|-------|------|---:|-----:|--:|
| ccb_dibench | inducer-cgen | 1.000 | 0.000 | -1.000 |
| ccb_crossrepo | refactor_rename_01 | 0.920 | 0.000 | -0.920 |
| ccb_sweperf | sweperf-001 | 0.998 | 0.122 | -0.876 |

### 8.4 SG_full-Only Value (9 Tasks)

Tasks where SG_base was neutral/negative but SG_full improved — indicating the enhanced configuration (Deep Search, richer preamble) provides unique value over basic MCP:

| Suite | Task | BL | SG_b | SG_f |
|-------|------|---:|-----:|-----:|
| ccb_dependeval | multifile_editing-python-8597 | 0.180 | 0.183 | 1.000 |
| ccb_largerepo | big-code-k8s-001 | 0.000 | 0.000 | 0.700 |
| ccb_sweperf | sweperf-003 | 0.274 | 0.053 | 0.660 |
| ccb_locobench | (multiple tasks) | — | — | — |

### 8.5 Per-Suite MCP Impact Profile

| Suite | Category | SG_b Help/Neutral/Hurt | SG_f Help/Neutral/Hurt |
|-------|----------|:---:|:---:|
| ccb_locobench | Search-heavy | +8/7/-3 | **+16/5/-4** |
| ccb_dependeval | Mixed | +4/23/-5 | +6/22/-4 |
| ccb_k8sdocs | Search-heavy | +0/5/-0 | +0/5/-0 |
| ccb_repoqa | Local-only | +0/10/-0 | +0/10/-0 |
| ccb_swebenchpro | Mixed | +1/19/-0 | +1/19/-0 |
| ccb_sweperf | Implementation | +0/0/-3 | +1/0/-2 |
| ccb_tac | Implementation | +1/5/-2 | +1/7/-0 |
| ccb_largerepo | Search-heavy | +0/4/-0 | +1/3/-0 |
| ccb_pytorch | Implementation | +0/11/-1 | +0/8/-1 |
| ccb_codereview | Mixed | +1/2/-0 | +1/2/-0 |
| ccb_crossrepo | Mixed | +0/4/-1 | +0/2/-3 |
| ccb_linuxflbench | Search-heavy | +0/5/-0 | +1/4/-0 |
| ccb_dibench | Local-only | +1/6/-1 | +1/6/-1 |

**Patterns**:
- **Search-heavy suites**: MCP mostly neutral-to-positive (LoCoBench SG_full has 16 helps)
- **Implementation suites**: MCP neutral-to-negative (SWE-Perf, TAC SG_base hurt)
- **Already-passing suites**: No room to improve (K8s Docs, RepoQA at ceiling)
- **MCP distraction**: TAC SG_base hurts (-2 tasks) but SG_full recovers (0 hurts) — the richer preamble reduces over-reliance on remote search

---

## 9. Efficiency Analysis

### 9.1 Token Usage & Cost per Config

| Config | Valid Tasks | Total Cost | Avg Cost/Task | Avg Wall (s) |
|--------|--------:|----------:|----------:|-------:|
| Baseline | 145 | $281 | $1.94 | 600 |
| SG_base | 135 | $294 | $2.18 | 509 |
| SG_full | 141 | $402 | $2.85 | 1,170 |

- SG_base is **15% faster** on wall clock but **12% more expensive** per task
- SG_full is **95% slower** on wall clock and **47% more expensive** per task
- Total benchmark cost across all configs: ~$977

### 9.2 Wall Clock by Suite (seconds, mean)

| Suite | BL | SG_b | SG_f | Δ SG_b | Δ SG_f |
|-------|---:|-----:|-----:|-------:|-------:|
| ccb_codereview | 217 | 198 | 203 | -9% | -6% |
| ccb_crossrepo | 533 | 528 | 610 | -1% | +14% |
| ccb_dependeval | 341 | 374 | 380 | +10% | +11% |
| ccb_dibench | 434 | 365 | 268 | -16% | -38% |
| ccb_k8sdocs | 447 | 168 | 72 | -62% | **-84%** |
| ccb_largerepo | 1,280 | 1,036 | 1,247 | -19% | -3% |
| ccb_linuxflbench | 348 | 880 | 411 | +153% | +18% |
| ccb_locobench | 599 | 641 | 1,528 | +7% | +155% |
| ccb_pytorch | 1,046 | 1,155 | 1,296 | +10% | +24% |
| ccb_repoqa | 164 | 133 | 163 | -19% | -1% |
| ccb_swebenchpro | 1,094 | 712 | 1,613 | -35% | +47% |
| ccb_sweperf | 950 | 1,198 | 1,198 | +26% | +26% |
| ccb_tac | 990 | 932 | 724 | -6% | **-27%** |

**MCP Speed Wins**: K8s Docs (-84% SG_full), DIBench (-38%), TAC (-27%), RepoQA (-19%), LargeRepo (-19%)
**MCP Speed Losses**: LoCoBench (+155% SG_full), LinuxFLBench (+153% SG_base), SWE-Pro (+47% SG_full)

### 9.3 Cost-Effectiveness (Cost per Reward Point)

| Suite | BL $/reward | SG_b $/reward | SG_f $/reward | Best Config |
|-------|----------:|------------:|------------:|-------------|
| ccb_k8sdocs | $1.00 | $0.79 | $0.69 | **SG_full** |
| ccb_swebenchpro | $6.03 | $5.70 | $2.97 | **SG_full** |
| ccb_tac | $5.19 | $7.51 | $4.55 | **SG_full** |
| ccb_pytorch | $25.50 | $26.45 | $9.77 | **SG_full** |
| ccb_largerepo | $21.67 | $19.51 | $13.61 | **SG_full** |
| ccb_sweperf | $2.22 | $184.05 | $5.68 | Baseline |
| ccb_locobench | $8.55 | $7.74 | $15.99 | SG_base |
| ccb_crossrepo | $4.71 | $4.32 | $10.10 | SG_base |

SG_full delivers the best cost/reward for 5 of 8 suites with meaningful cost variation. The two suites where MCP hurts cost-effectiveness (SWE-Perf, CrossRepo) are small-N benchmarks.

### 9.4 MCP Tool Distribution (3,174 total invocations across SG configs)

| Tool | Calls | Share | Purpose |
|------|------:|------:|---------|
| keyword_search | 1,279 | 40.3% | Exact code search |
| read_file | 885 | 27.9% | File content retrieval |
| list_files | 604 | 19.0% | Directory exploration |
| nls_search | 118 | 3.7% | Semantic/NLS search |
| find_references | 76 | 2.4% | Symbol references |
| go_to_definition | 74 | 2.3% | Symbol definitions |
| list_repos | 64 | 2.0% | Repository discovery |
| commit_search | 41 | 1.3% | Commit history |
| diff_search | 18 | 0.6% | Code diff search |
| compare_revisions | 10 | 0.3% | Revision comparison |
| deepsearch_read | 4 | 0.1% | Deep Search results |
| deepsearch | 1 | 0.03% | Deep Search invocation |

**Key observations**:
- Top 3 tools (keyword_search + read_file + list_files) account for **87%** of all MCP usage
- Deep Search is virtually unused (1 actual invocation out of 152 SG_full tasks = 0.7%)
- Advanced tools (find_references, go_to_definition, commit_search) used sparingly
- Agent strongly prefers synchronous, low-latency tools over async Deep Search

---

## 10. Remaining Gaps & Recommendations

### 10.1 Data Completeness

| Issue | Tasks | Impact | Priority |
|-------|------:|--------|----------|
| LoCoBench SG_base 7 zero-token | 7 | Inflates error rate, depresses mean | P1 |
| PyTorch sgt-025 Docker broken | 1 | Cannot score SG_full | P4 (permanent) |
| SWE-bench Pro errored (infra) | 40 | Uneven comparison across configs | P2 |
| 106 tasks missing cost data (H3 bug) | 106 | Cost estimates imprecise | P3 |

### 10.2 Actionable Recommendations

1. **Rerun LoCoBench SG_base** (7 tasks) — the only gap that's both fixable and materially affects results
2. **Deep Search adoption**: Consider adding explicit prompting in SG_full preamble to encourage DS use. Current 0.7% adoption means the SG_full improvement comes almost entirely from the enhanced preamble, not Deep Search itself
3. **SWE-Perf investigation**: SG_base regression is catastrophic (-0.559). Root cause: agent spends time searching remote repos instead of focused implementation. Consider excluding MCP for performance-tuning tasks
4. **TAC SG_base distraction**: Agent over-reads remote files instead of implementing. SG_full recovers because richer preamble guides MCP use more carefully
5. **Cost recovery**: Extract costs from claude-code.txt transcripts for the 106 H3-affected tasks to improve cost estimates

### 10.3 Overall Assessment

| Metric | Baseline | SG_base | SG_full |
|--------|----------|---------|---------|
| Scored Task Mean | 0.578 | 0.570 | 0.657 |
| Matched-Task Mean (N=125) | 0.600 | 0.599 | 0.630 |
| Avg Cost/Task | $1.94 | $2.18 | $2.85 |
| Avg Wall Clock | 600s | 509s | 1,170s |
| Cost/Reward Point | $4.41 | $4.56 | $5.13 |
| Tasks Helped (vs BL) | — | 18 | 29 |
| Tasks Hurt (vs BL) | — | 18 | 14 |

**Summary**: MCP with basic configuration (SG_base) is **neutral on reward** but provides modest speed improvements on search-heavy tasks. MCP with enhanced configuration (SG_full) delivers a **+3.1pp matched-task improvement** and **+7.9pp scored-task improvement** at ~47% higher cost. The value proposition is strongest for search-heavy (K8s Docs, LargeRepo) and multi-file (DependEval, LoCoBench) tasks, and weakest for pure implementation tasks (SWE-Perf, CrossRepo).

---

## 11. MCP Impact by Codebase Size and Complexity

### 11.1 Methodology

Each task has two types of size/complexity metadata:

- **Predicted metrics** (all 137 matched tasks): `context_complexity` (cc, 0–1) and `cross_file_deps` (cfd, 0–1) from `mcp_breakdown` in the task registry. These are assigned per-suite with limited within-suite variation.
- **Actual codebase metrics** (25 LoCoBench tasks): `context_length` (total characters) and `files_count` from task.toml. These provide real variation within a single benchmark.

### 11.2 Context Complexity (Codebase Size Proxy)

| CC Bucket | N | BL | SG_f | Δ | Help | Neut | Hurt | Dominant Suites |
|-----------|--:|---:|-----:|--:|-----:|-----:|-----:|-----------------|
| Low (0.40–0.59) | 23 | 0.564 | 0.521 | -0.043 | 2 | 15 | 6 | TAC(8), SWE-Pro(4), SWE-Perf(3) |
| Med (0.60–0.79) | 47 | 0.505 | 0.562 | +0.057 | 9 | 32 | 6 | DependEval(27), PyTorch(11) |
| High (0.80–1.00) | 67 | 0.670 | 0.696 | +0.026 | 18 | 41 | 8 | LoCoBench(25), RepoQA(10), LargeRepo(4) |

**Insight**: Medium and high-cc tasks benefit from MCP. Low-cc tasks (small codebases: TAC, SWE-Perf) see a slight negative delta — the agent wastes time searching remotely when the codebase is small enough to navigate locally.

### 11.3 Cross-File Dependencies

| CFD Bucket | N | BL | SG_f | Δ | Help | Neut | Hurt | Dominant Suites |
|------------|--:|---:|-----:|--:|-----:|-----:|-----:|-----------------|
| Low (<0.40) | 34 | 0.411 | 0.398 | -0.013 | 3 | 25 | 6 | PyTorch(11), TAC(8), K8s Docs(5) |
| Med (0.40–0.69) | 36 | 0.669 | 0.722 | +0.053 | 2 | 32 | 2 | RepoQA(10), SWE-Pro(9), DIBench(8) |
| High (0.70–1.00) | 67 | 0.633 | 0.677 | +0.044 | 24 | 31 | 12 | LoCoBench(25), DependEval(27), LargeRepo(4) |

**Insight**: MCP benefit scales with cross-file dependencies. Tasks requiring coordination across many files (cfd≥0.40) see consistent positive deltas. Low-cfd tasks (single-file implementations) see slight regression.

### 11.4 Combined Complexity Quadrants

| Quadrant | N | BL | SG_f | Δ | H/N/L |
|----------|--:|---:|-----:|--:|-------|
| **Large & Multi-file** (cc≥0.7, cfd≥0.5) | 67 | 0.633 | 0.693 | **+0.060** | 25/32/10 |
| Large & Simple (cc≥0.7, cfd<0.5) | 0 | — | — | — | — |
| Small & Multi-file (cc<0.7, cfd≥0.5) | 36 | 0.594 | 0.594 | +0.000 | 4 / 28 / 4 |
| Small & Simple (cc<0.7, cfd<0.5) | 34 | 0.500 | 0.488 | -0.013 | 0 / 28 / 6 |

**Key finding**: The **Large & Multi-file** quadrant is where MCP delivers clear value (+6.0pp, 2.5:1 help-to-hurt ratio). Small & Simple tasks see slight regression — MCP overhead without benefit.

### 11.5 Task Difficulty

| Difficulty | N | BL | SG_f | Δ | Help Rate |
|-----------|--:|---:|-----:|--:|----------:|
| easy | 4 | 0.625 | 0.625 | +0.000 | 0% |
| medium | 53 | 0.737 | 0.774 | +0.037 | 15% |
| hard | 50 | 0.505 | 0.529 | +0.024 | 8% |
| very_hard | 8 | 0.449 | 0.457 | +0.008 | 13% |
| expert | 22 | 0.436 | 0.481 | **+0.045** | **57%** |

**Insight**: Expert-level tasks have both the lowest baseline scores and the highest MCP help rate (57%). MCP provides the most value on problems that are inherently difficult for the agent.

### 11.6 LoCoBench: Actual Codebase Size

LoCoBench is the only suite with real per-task codebase metrics (25 matched tasks, all in the 500K–2.5M character range):

| Size | N | Avg Chars | BL | SG_f | Δ | Help | Hurt |
|------|--:|----------:|---:|-----:|--:|-----:|-----:|
| Medium (500K–1M) | 5 | 776K | 0.446 | 0.551 | +0.105 | 4 | 1 |
| Large (1M–2M) | 17 | 1.3M | 0.526 | 0.538 | +0.012 | 9 | 3 |
| Very Large (2M+) | 3 | 2.3M | 0.160 | 0.333 | +0.173 | 3 | 0 |

MCP benefit is positive at all sizes. Very large codebases (2M+ chars) show the strongest delta (+0.173, 3/3 helped), though N is small. The Pearson correlation between `context_length` and MCP delta is r=–0.348 (N=25), but this is driven by the large middle bucket where many tasks are already near ceiling — the trend reverses when looking at the endpoints.

### 11.7 Language

| Language | N | BL | SG_f | Δ |
|----------|--:|---:|-----:|--:|
| JavaScript | 9 | 0.340 | 0.467 | **+0.127** |
| TypeScript | 9 | 0.354 | 0.457 | **+0.103** |
| Rust | 4 | 0.412 | 0.459 | +0.047 |
| Go | 22 | 0.664 | 0.703 | +0.039 |
| Python | 31 | 0.573 | 0.570 | -0.003 |
| Java | 8 | 0.733 | 0.696 | -0.036 |
| C | 13 | 0.626 | 0.667 | +0.041 |

**Insight**: JavaScript and TypeScript tasks benefit most from MCP (+10–13pp). These languages typically have deep `node_modules` trees and complex import graphs that benefit from remote search. Python tasks show no effect — the agent navigates Python codebases effectively without MCP.

### 11.8 Task Category

| Category | N | BL | SG_f | Δ | Help | Hurt |
|----------|--:|---:|-----:|--:|-----:|-----:|
| multifile_editing | 10 | 0.469 | 0.636 | **+0.167** | 6 | 4 |
| cross_file_refactoring | 11 | 0.394 | 0.429 | +0.035 | 9 | 2 |
| dependency_recognition | 22 | 0.714 | 0.750 | +0.036 | 1 | 0 |
| code_search (RepoQA) | 10 | 1.000 | 1.000 | +0.000 | 0 | 0 |
| documentation (K8s) | 5 | 0.920 | 0.920 | +0.000 | 0 | 0 |
| performance (SWE-Perf) | 3 | 0.591 | 0.367 | **-0.224** | 1 | 2 |

**Insight**: Multi-file editing tasks (+0.167) and cross-file refactoring (+0.035) benefit most — exactly the categories where codebase-wide search helps locate all relevant files. Performance optimization tasks are hurt — the agent needs focused local iteration, not broad search.

### 11.9 Baseline Performance as Predictor

| Baseline Performance | N | BL | SG_f | Δ | Help | Hurt |
|---------------------|--:|---:|-----:|--:|-----:|-----:|
| Failed (BL=0.0) | 27 | 0.000 | 0.139 | +0.139 | 5 | 0 |
| Low (0.01–0.49) | 16 | 0.213 | 0.344 | **+0.131** | 5 | 1 |
| Medium (0.50–0.99) | 29 | 0.735 | 0.694 | -0.041 | 6 | 8 |
| Perfect (BL=1.0) | 65 | 1.000 | 0.976 | -0.024 | 13 | 5 |

Pearson correlation: **r = –0.353** (N=137).

**However, the BL=0 bucket is contaminated by infrastructure failures.** Of the 27 BL=0 tasks:

- **8 had no trajectory** (`has_trajectory=False`) — the baseline agent never ran due to Docker/auth failures. These are not capability failures.
- **19 had trajectory and cost** — genuine agent capability failures.

Of the 5 apparent "MCP flips" (BL=0 → SGf>0):
- **3 are infrastructure artifacts**: `vuls-139f3a81`, `python_desktop_*`, `rust_api_*` — baseline failed for infra reasons; SG_full simply didn't have the same infra problem.
- **2 are genuine MCP value**: `big-code-k8s-001` (K8s taint — MCP search located all 6+ files needing changes) and `dotenv-expand` (MCP resolved dependency chain).

**Corrected analysis** (separating infra from capability):

| Baseline Performance | N | BL | SG_f | Δ | Help | Hurt | Notes |
|---------------------|--:|---:|-----:|--:|-----:|-----:|-------|
| BL=0 (infra fail) | 8 | 0.000 | 0.258 | +0.258 | 3 | 0 | Misleading — infra artifact |
| BL=0 (genuine fail) | 19 | 0.000 | 0.063 | +0.063 | 2 | 0 | Real but modest (7.4% flip rate) |
| Low (0.01–0.49) | 16 | 0.213 | 0.344 | **+0.131** | 5 | 1 | **Strongest genuine MCP benefit** |
| Medium (0.50–0.99) | 29 | 0.735 | 0.694 | -0.041 | 6 | 8 | MCP slight regression |
| Perfect (BL=1.0) | 65 | 1.000 | 0.976 | -0.024 | 13 | 5 | Ceiling — slight regression |

**Corrected finding**: MCP's strongest genuine benefit is in the **low-performing range (BL=0.01–0.49)**, where the agent runs and struggles but doesn't completely fail (+13.1pp, 5:1 help-to-hurt). For genuine total failures (BL=0 with trajectory), MCP rarely helps (2/19 = 7.4%) — the failures are typically too fundamental (hard PyTorch PRs, complex Ansible fixes) for search tools alone.

### 11.10 Summary: When Does MCP Help?

| Factor | MCP Helps When... | MCP Hurts When... |
|--------|-------------------|-------------------|
| **Codebase size** | Large codebases (cc≥0.7) | Small codebases (cc<0.6) |
| **File dependencies** | High cross-file coordination (cfd≥0.5) | Single-file tasks (cfd<0.4) |
| **Difficulty** | Expert-level tasks (57% help rate) | Easy tasks (0% help rate) |
| **Language** | JavaScript/TypeScript (+10-13pp) | Python (neutral), Java (–3.6pp) |
| **Task type** | Multi-file editing, cross-file refactoring | Performance optimization |
| **Baseline performance** | Agent struggles (BL 0.01–0.49, +13.1pp) | Agent already succeeds (–2.4pp) |

**The ideal MCP beneficiary**: An expert-difficulty, multi-file JavaScript/TypeScript task in a large codebase where the baseline agent struggles (partial score). The ideal non-beneficiary: A simple, single-file Python performance task where the baseline already passes. Note: tasks where the baseline *completely* fails (reward=0) are rarely rescued by MCP (7.4%) — the failures are typically too fundamental for search tools to fix.

---

## 12. Missing Trajectory (H3 Bug) Deep Dive — LargeRepo & CrossRepo

### 12.1 Background

Sections 1–11 flagged multiple tasks with missing `trajectory.json` in the LargeRepo and CrossRepo suites. This section confirms whether those are infrastructure failures (requiring reruns) or the known H3 token-logging bug (scores valid, only cost data missing).

The H3 bug occurs when Harbor's `_get_session_dir` fails because Claude Code spawns subagents via the Task tool, creating multiple session directories. When this happens, `trajectory.json` is not written and token counts in `result.json` are `None` — but the agent still runs normally and the verifier still scores the output.

### 12.2 LargeRepo: 5/12 Missing Trajectory

| Task | Config | Traj | CC Lines | Reward | Tokens | Classification |
|------|--------|------|----------|--------|--------|----------------|
| big-code-k8s-001 | baseline | YES | 254 | 0.0 | 6.0M in | OK |
| big-code-k8s-001 | SG_base | YES | 252 | 0.0 | 4.5M in | OK |
| big-code-k8s-001 | **SG_full** | **NO** | 298 | **0.7** | None | H3 bug |
| big-code-servo-001 | **baseline** | **NO** | 414 | 0.0 | None | H3 bug |
| big-code-servo-001 | SG_base | YES | 303 | 0.0 | 10.1M in | OK |
| big-code-servo-001 | **SG_full** | **NO** | 514 | 0.0 | None | H3 bug |
| big-code-trt-001 | baseline | YES | 135 | 0.0 | 16.2M in | OK |
| big-code-trt-001 | SG_base | YES | 217 | 0.0 | 5.7M in | OK |
| big-code-trt-001 | SG_full | YES | 274 | 0.5 | 9.3M in | OK |
| big-code-vsc-001 | **baseline** | **NO** | 233 | 0.0 | None | H3 bug |
| big-code-vsc-001 | SG_base | YES | 348 | 1.0 | 2.2M in | OK |
| big-code-vsc-001 | **SG_full** | **NO** | 428 | 0.0 | None | H3 bug |

**Evidence of genuine execution** (all 5 missing-traj runs):
- `claude-code.txt` exists with 233–514 lines of agent output
- No `exception_info` in result.json
- Verifier ran and produced valid rewards
- `sessions/` directory exists in agent/
- Wall clock times are normal (20 min to 2 hours)

**Conclusion: Zero infrastructure failures. All 5 are H3 bug. Scores are valid. No reruns needed.**

### 12.3 CrossRepo: 7/15 Missing Trajectory

| Task | Config | Traj | CC Lines | Reward | Tokens | Classification |
|------|--------|------|----------|--------|--------|----------------|
| api_upgrade_01 | **baseline** | **NO** | 295 | 0.0 | None | H3 bug |
| api_upgrade_01 | SG_base | YES | — | 0.0 | 51K in | OK |
| api_upgrade_01 | SG_full | YES | — | 0.0 | 72K in | OK |
| bug_localization_01 | **baseline** | **NO** | 225 | 0.933 | None | H3 bug |
| bug_localization_01 | SG_base | YES | — | 0.933 | 112K in | OK |
| bug_localization_01 | SG_full | YES | — | 0.933 | 83K in | OK |
| cross_file_reasoning_01 | **baseline** | **NO** | 182 | 0.0 | None | H3 bug |
| cross_file_reasoning_01 | SG_base | YES | — | 0.0 | 26K in | OK |
| cross_file_reasoning_01 | **SG_full** | **NO** | 125 | 0.0 | None | H3 bug |
| refactor_rename_01 | **baseline** | **NO** | 673 | 0.920 | None | H3 bug |
| refactor_rename_01 | **SG_base** | **NO** | 398 | 1.000 | None | H3 bug |
| refactor_rename_01 | **SG_full** | **NO** | 792 | 0.0 | None | H3 bug |
| simple_test_01 | baseline | YES | — | 1.0 | 38K in | OK |
| simple_test_01 | SG_base | YES | — | 1.0 | 56K in | OK |
| simple_test_01 | SG_full | YES | — | 1.0 | 60K in | OK |

**`refactor_rename_01` is worst-affected** — missing trajectory in ALL 3 configs. With 398–792 lines of claude-code.txt, this task likely triggers heavy subagent (Task tool) usage, the known root cause of the H3 bug.

**Evidence of genuine execution** (all 7 missing-traj runs):
- `claude-code.txt` exists in all 15/15 runs (including missing-traj)
- Several missing-traj tasks scored well: `bug_localization_01` BL=0.933, `refactor_rename_01` BL=0.920 / SG_base=1.000
- No exceptions in any result.json
- `patch.diff` files exist in several missing-traj runs (agent made code changes)

**Conclusion: Zero infrastructure failures. All 7 are H3 bug. Scores are valid. No reruns needed.**

### 12.4 H3 Bug Impact Summary

Across the full benchmark:

| Suite | Total Runs | Missing Traj | H3 Bug | Infra Failure |
|-------|-----------|-------------|--------|---------------|
| LargeRepo | 12 | 5 (42%) | 5 | 0 |
| CrossRepo | 15 | 7 (47%) | 7 | 0 |
| **Total** | **27** | **12 (44%)** | **12** | **0** |

The H3 bug disproportionately affects these two suites (42–47% of runs) compared to the broader benchmark (~15% overall). This correlates with their heavy use of Claude Code's Task/subagent tool for multi-file exploration.

**Impact on analysis**:
- **Task scoring**: Unaffected — verifier results are valid regardless of trajectory
- **Token/cost analysis**: 12 runs lack token counts; costs recoverable from claude-code.txt JSONL transcripts
- **MCP tool usage analysis**: For missing-traj SG runs, MCP tool counts come from claude-code.txt (less complete than trajectory.json for subagent calls) — the audit_traces.py script already handles this by merging both sources
