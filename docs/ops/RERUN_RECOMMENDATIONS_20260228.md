# Rerun Recommendations — 2026-02-28

**Context:** Cross-suite audit identified infrastructure bugs causing MCP to score 0 on tasks
where the baseline was scoring correctly. This document summarizes what was found, what was
fixed, what was archived, and what needs to be rerun.

---

## Summary of Bugs Found and Fixed

### Bug 1: Missing `/workspace` symlink in ccb_debug prove task sg_only Dockerfiles

**Root cause:** The baseline Dockerfiles for regression-prove tasks include
`RUN ln -sf /app /workspace || true` so that the verifier's hardcoded
`AGENT_TEST_PATH=/workspace/regression_test.py` resolves correctly.
The sg_only Dockerfiles were missing this symlink — the agent would hit EACCES
when trying to write to `/workspace`, fall back to `/app`, but the verifier
checked `/workspace` and reported "file not found" → reward=0.0.

**Impact:** 9 regression-prove tasks scored MCP=0.00 while baseline scored 0.50.

**Tasks fixed (Dockerfile.sg_only updated):**
- ccb_debug/ansible-galaxy-tar-regression-prove-001
- ccb_debug/flipt-auth-cookie-regression-prove-001
- ccb_debug/qutebrowser-adblock-cache-regression-prove-001
- ccb_debug/qutebrowser-darkmode-threshold-regression-prove-001
- ccb_debug/qutebrowser-hsv-color-regression-prove-001
- ccb_debug/qutebrowser-url-regression-prove-001
- ccb_debug/teleport-ssh-regression-prove-001
- ccb_debug/tutanota-search-regression-prove-001
- ccb_debug/vuls-oval-regression-prove-001

**Fix:** Added `RUN ln -sf /app /workspace || true` after the sg_only mode markers
in all 9 Dockerfiles. Committed in `30c785c6e`.

---

### Bug 2: Wrong base image in TAC task sg_only Dockerfiles

**Root cause:** Two TAC-based tasks had `Dockerfile.sg_only` files that used
`ubuntu:22.04` as the base instead of the correct TAC Docker image. The TAC
verifier calls `/utils/eval.py` via a custom `python_default` binary that only
exists in the TAC base image. On `ubuntu:22.04`, the verifier would crash
immediately → reward=0.0.

**Impact:** Both tasks scored MCP=0.00.

**Tasks fixed (Dockerfile.sg_only completely rewritten):**
- ccb_feature/bustub-hyperloglog-impl-001 (BL=0.17 → MCP=0.00)
  - Now uses: `ghcr.io/theagentcompany/sde-implement-hyperloglog-image:1.0.0`
  - Truncates: C/C++ source files (*.cpp, *.cc, *.h, *.hpp, etc.)
  - Clone manifest: `sg-evals/bustub--d5f79431` → `/workspace/.`
- ccb_test/openhands-search-file-test-001 (BL=0.40 → MCP=0.00)
  - Now uses: `ghcr.io/theagentcompany/sde-write-a-unit-test-for-search_file-function-image:1.0.0`
  - Truncates: Python files in `/workspace/openhands/`
  - Clone manifest: `sg-evals/OpenHands--latest` → `/workspace/openhands`

**Fix:** Rewrote both Dockerfiles to use correct TAC base images with proper
truncation, clone manifests, and sg_only markers. Committed in `fe4a52602`.

---

## Runs Archived

All runs containing data invalidated by the above bugs were archived to
`runs/official/archive/`.

| Run Directory | Reason |
|---|---|
| `build_haiku_20260223_124805` | Deprecated suite (ccb_build split → ccb_feature + ccb_refactor) |
| `ccb_build_haiku_022326` | Deprecated suite |
| `ccb_build_haiku_20260225_234223` | Deprecated suite |
| `ccb_build_haiku_20260226_015500_backfill` | Deprecated suite |
| `ccb_build_haiku_20260227_baseline_gapfill` | Deprecated suite |
| `ccb_debug_haiku_022326` | Bug 1: prove tasks all scored MCP=0 due to missing /workspace symlink |
| `debug_haiku_20260223_154724` | Bug 1: same (older format run, same bug) |
| `ccb_test_haiku_022326` | Bug 2: openhands scored MCP=0 due to wrong base image |

---

## What Does NOT Need Reruns (Genuine Failures)

These cases were investigated and determined to be real agent failures, not
infrastructure bugs:

| Task | Suite | BL | MCP | Root Cause |
|---|---|---|---|---|
| flipt-eval-latency-fix-001 | ccb_fix | 0.55 | 0.00 | Agent wrote invalid Go (type errors, enum mismatch) |
| argocd-arch-orient-001 | ccb_understand | 0.00 | 0.81 | BL rate-limited (37+ tool calls on local code) |
| cilium-project-orient-001 | ccb_understand | 0.00 | 0.96 | BL rate-limited (token exhaustion before writing output) |
| terraform-plan-pipeline-qa-001 | ccb_understand | 0.00 | 0.95 | BL rate-limited |
| envoy-request-routing-qa-001 | ccb_understand | 0.00 | 0.87 | BL rate-limited |
| grpcurl-transitive-vuln-001 | ccb_secure | 0.00 | 0.67 | BL rate-limited (187 tool calls exhausting budget) |
| pytorch ccb_fix tasks (4) | ccb_fix | 0.00 | 0.00 | Genuine task difficulty (agent changes wrong files, file_recall=0) |

The baseline rate-limit failures in ccb_understand are a token-efficiency issue
(agents reading 40-180 local files before writing output). These are not setup
bugs and would recur without changes to agent behavior or task instructions.

---

## Rerun Plan

### Priority 1 — Full ccb_debug rerun (BLOCKS reported delta for debug suite)

No valid ccb_debug data exists in official/ after archiving. Both configs need runs.

**Action:** Full 20-task paired run (baseline-local-direct + mcp-remote-direct).

**Image rebuild required?** YES — all 9 prove task sg_only images must be rebuilt
before the MCP config run, otherwise the same bug recurs.

Tasks requiring new sg_only image builds (prove tasks):
```
ansible-galaxy-tar-regression-prove-001
flipt-auth-cookie-regression-prove-001
qutebrowser-adblock-cache-regression-prove-001
qutebrowser-darkmode-threshold-regression-prove-001
qutebrowser-hsv-color-regression-prove-001
qutebrowser-url-regression-prove-001
teleport-ssh-regression-prove-001
tutanota-search-regression-prove-001
vuls-oval-regression-prove-001
```

The 11 non-prove debug tasks (audit, fault, regression) do not require image rebuilds
for their sg_only variants — they were scoring normally in prior runs.

---

### Priority 2 — First ccb_feature and ccb_refactor runs (new suites, no data)

Neither suite has any official run data. These are new suites created when ccb_build
was split on 2026-02-28.

**Action:** Full 20-task paired run for each suite.

**Image rebuild required?**
- ccb_feature/bustub-hyperloglog-impl-001: YES — sg_only image needs rebuild
  (wrong base image was fixed in fe4a52602)
- All other ccb_feature + ccb_refactor tasks: check if they have prior sg_only images;
  most inherited from ccb_build so verify before running

---

### Priority 3 — Spot rerun of openhands-search-file-test-001 (ccb_test)

The existing ccb_test official data (from ccb_test_haiku_20260224_180149) does not
contain the openhands task. The buggy 022326 run was archived. A targeted single-task
rerun is needed to get valid MCP data for this task.

**Action:** Single-task paired run (baseline + MCP) for openhands-search-file-test-001.

**Image rebuild required?** YES — the sg_only image must be rebuilt with the TAC base
(fix committed in fe4a52602).

---

## Image Rebuild Summary for Daytona

| Task | Suite | Rebuild Trigger | Fixed In |
|---|---|---|---|
| ansible-galaxy-tar-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| flipt-auth-cookie-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| qutebrowser-adblock-cache-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| qutebrowser-darkmode-threshold-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| qutebrowser-hsv-color-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| qutebrowser-url-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| teleport-ssh-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| tutanota-search-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| vuls-oval-regression-prove-001 | ccb_debug | Added /workspace symlink to sg_only | 30c785c6e |
| bustub-hyperloglog-impl-001 | ccb_feature | Wrong base image (ubuntu→TAC) in sg_only | fe4a52602 |
| openhands-search-file-test-001 | ccb_test | Wrong base image (ubuntu→TAC) in sg_only | fe4a52602 |

**Only sg_only (mcp-remote-direct) images need rebuilding.** The baseline
(baseline-local-direct) Dockerfiles were not changed.

---

## Current Official Coverage After Archiving

Suites with valid data:

| Suite | BL Mean | MCP Mean | Delta | Notes |
|---|---|---|---|---|
| ccb_design | 0.753 | 0.718 | -0.035 | Clean |
| ccb_document | 0.847 | 0.895 | +0.048 | Clean |
| ccb_fix | 0.523 | 0.618 | +0.095 | Clean |
| ccb_secure | 0.669 | 0.659 | -0.010 | Clean |
| ccb_test | 0.480 | 0.480 | 0.000 | Clean (openhands MCP missing, needs spot rerun) |
| ccb_understand | 0.660 | 0.851 | +0.191 | Clean (BL=0 tasks are rate-limit, not bugs) |

Suites with no valid official data (need runs):

| Suite | Reason |
|---|---|
| ccb_debug | All runs archived (bugs); 9 sg_only images need rebuild first |
| ccb_feature | New suite (split from ccb_build); bustub sg_only needs rebuild |
| ccb_refactor | New suite (split from ccb_build) |
