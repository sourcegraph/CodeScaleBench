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
