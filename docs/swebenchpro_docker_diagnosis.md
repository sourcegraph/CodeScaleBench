# SWE-bench Pro Docker Failure Diagnosis

**Date**: 2026-02-11
**Scope**: All SWE-bench Pro task runs across baseline, sourcegraph_base, sourcegraph_full configs

## Executive Summary

**42 infra failures** found across 21 unique tasks in 8 repos, in active (non-archived) runs.
Root causes are primarily **rate limiting** and **Node.js version conflicts**, NOT Docker build failures.

| Root Cause | Runs | Repos | Configs Affected |
|---|---|---|---|
| Rate limit ("hit your limit") | ~25 | qutebrowser, teleport, internetarchive, vuls, tutanota, element-hq, nodebb | BL, SG_base (Feb 8-9 runs) |
| Node.js version conflict (Alpine Node 16 vs required 18+) | ~10 | protonmail | BL, SG_base, SG_full |
| Agent setup timeout (chown on large workspace) | ~4 | protonmail (archive) | All configs |
| Empty transcript (JS bundle corruption) | ~3 | internetarchive | SG_full |

## Key Finding: NOT Docker Build Failures

The PRD assumed these were Docker environment issues. In reality:
- **Docker environments build and start successfully** in most cases (env_setup completes in 1-120s)
- **Agent setup completes** (Claude Code installs, instruction is loaded)
- The failures happen at **agent execution time** — either:
  1. Claude Code gets rate limited on first API call (subscription limit hit)
  2. Claude Code crashes on startup due to Node.js version mismatch (protonmail only)

## Detailed Diagnosis by Repo Group

### 1. protonmail/webclients (4 tasks × 3 configs = 10 active infra fails + 4 archived)

**Root Cause**: Node.js version conflict on Alpine Linux

The Docker image uses Alpine 3.18 which has Node.js 18.20.1 available via `apk add nodejs`, BUT the protonmail/webclients base image pre-installs Node 16.20.2. The install script's `apk add nodejs` doesn't upgrade the existing Node 16 installation, so Claude Code 2.1.38 (requires Node >= 18) crashes on startup with a minified JS dump.

**Evidence** (from `agent/setup/stdout.txt`):
```
(3/4) Installing nodejs (18.20.1-r0)
...
npm WARN EBADENGINE   package: '@anthropic-ai/claude-code@2.1.38',
npm WARN EBADENGINE   required: { node: '>=18.0.0' },
npm WARN EBADENGINE   current: { node: 'v16.20.2', npm: '8.19.4' }
```

**Classification**: (a) Node.js version incompatibility
**Shared across configs**: Yes — same Docker issue for all configs
**Proposed fix**: Update install.sh to force Node 18+ on Alpine:
```bash
# Remove old Node first, then install Node 18
apk del nodejs npm 2>/dev/null || true
apk add --no-cache curl bash nodejs npm
```
Or use nvm/volta to install a specific Node version.

### 2. qutebrowser (4 tasks × BL+SG_base = 6 infra fails; SG_full passes)

**Root Cause**: Rate limit on Max subscription ("You've hit your limit · resets 4am (UTC)")

**Evidence** (from `agent/claude-code.txt` JSONL):
```json
{"type":"assistant","message":{"content":[{"type":"text","text":"You've hit your limit · resets 4am (UTC)"}]}}
{"type":"result","is_error":true,"result":"You've hit your limit · resets 4am (UTC)"}
```

**Classification**: (c) Rate limiting
**Shared across configs**: BL and SG_base affected (ran during Feb 8-9 batch); SG_full ran later (Feb 10) and passed
**Proposed fix**: Re-run during off-peak hours or with fresh subscription accounts. NOT a Docker issue.

### 3. teleport/gravitational (4 tasks × BL+SG_base = 6 infra fails)

**Root Cause**: Rate limit (same as qutebrowser)
**Classification**: (c) Rate limiting
**Shared across configs**: BL + SG_base from same batch
**Note**: Also has 3 genuine failures (agent ran but didn't solve task) — those are real task difficulty, not infra.

### 4. internetarchive/openlibrary (4 tasks × 3 configs = 13 infra fails)

**Root Cause**: Mixed — rate limit (6), empty transcript/JS bundle corruption (6), agent setup timeout (1)
**Classification**: Primarily (c) rate limiting + (e) transcript corruption
**Note**: The 4 tasks have 12 passing runs in other batches, confirming Docker works fine.

### 5. vuls/future-architect (2 tasks × BL+SG_base = 3 infra fails)

**Root Cause**: Rate limit
**Classification**: (c) Rate limiting
**Note**: 5 passing runs exist, Docker works.

### 6. tutanota/tutao (1 task × BL+SG_base = 2 infra fails)

**Root Cause**: Rate limit
**Classification**: (c) Rate limiting
**Note**: SG_full passes. Docker works.

### 7. element-hq (1 task × SG_base = 1 infra fail)

**Root Cause**: Rate limit
**Classification**: (c) Rate limiting
**Note**: BL and SG_full pass. Docker works.

### 8. nodebb (1 task × SG_base = 1 infra fail)

**Root Cause**: Rate limit
**Classification**: (c) Rate limiting
**Note**: Other tasks pass, Docker works.

## MANIFEST Impact

Current MANIFEST (463 tasks, 39 runs) includes these infra-fail results as `reward=0.0`:

| Config | Infra-Fail Tasks (0 reward, 0 tokens) | Real Missing |
|---|---|---|
| baseline | ~17 across multiple repos | 0 (all 36 tasks present) |
| sourcegraph_base | ~20 across multiple repos | 0 (all 36 tasks present) |
| sourcegraph_full | ~5 (protonmail + internetarchive) | 2 protonmail tasks missing |

**The 42 infra failures inflate the failure rate**: tasks that never ran are scored as 0, bringing down config averages.

## Recommended Actions

1. **protonmail (Priority 1)**: Fix install.sh Node.js version handling for Alpine images. Then re-run all 4 tasks × 3 configs = 12 runs.

2. **Rate-limited tasks (Priority 2)**: Simply re-run with fresh subscription sessions. No Docker fixes needed. Affects: qutebrowser (6), teleport (6), internetarchive (6), vuls (3), tutanota (2), element-hq (1), nodebb (1) = **25 re-runs**.

3. **Transcript corruption (Priority 3)**: Re-run 3 internetarchive SG_full tasks. May be Harbor bug related to large workspaces.

4. **Total re-runs needed**: 12 (protonmail fix) + 25 (rate-limit retry) + 3 (corruption) = **~40 task runs**.

## Cross-Config Pattern

The rate-limit failures cluster in **BL and SG_base configs from the Feb 8-9 batch** (`swebenchpro_gapfill_opus_20260208_235352` and `swebenchpro_gapfill_opus_20260209_023525`). These ran when the subscription was likely exhausted. SG_full runs from the Feb 10 batch (`swebenchpro_rerun_opus_20260210_163436`) generally succeeded, confirming these aren't Docker issues.

The protonmail failure is Docker-related and affects ALL configs equally.

## Fix Applied: Protonmail Node.js Upgrade (2026-02-11)

**Problem**: Base images (`jefzda/sweap-images:protonmail.webclients-*`) ship Alpine 3.18.3 with Node.js v16.20.2 pre-installed at `/usr/local/bin/node`. Alpine's `apk add nodejs` installs Node 18.20.1 at `/usr/bin/node` but the old v16 binary at `/usr/local/bin/node` takes precedence in PATH. Claude Code ≥2.1.37 requires Node ≥18 and crashes on startup.

**Fix**: Added Node.js upgrade step to all 4 protonmail Dockerfiles (both local and Harbor cache):
```dockerfile
# Upgrade Node.js from v16 (base image) to v18 (required by Claude Code >= 2.1.37)
RUN apk del nodejs nodejs-current npm 2>/dev/null || true; \
    rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx 2>/dev/null || true; \
    apk add --no-cache nodejs npm
```

**Verification**:
- All 4 local Dockerfiles (`benchmarks/ccb_swebenchpro/tasks/instance_protonmail-webclients-*/environment/Dockerfile`) build successfully
- All 4 Harbor cached Dockerfiles (`~/.cache/harbor/tasks/*/instance_protonmail__webclients-*/environment/Dockerfile`) build successfully
- Node.js v18.20.1 confirmed in all 8 built images
- `npm install -g @anthropic-ai/claude-code@latest` succeeds without `EBADENGINE` warnings
- Claude Code installs and starts correctly

**Tasks fixed** (4 task IDs × 3 configs = 12 runs to re-run):
1. `instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f`
2. `instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c`
3. `instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b`
4. `instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492`

## US-003 Assessment: Non-Protonmail Docker Environments (2026-02-11)

### Conclusion: No Docker Fixes Needed

All 7 non-protonmail repos have **healthy, functional Docker environments**. Every repo has at least one passing run across configs, confirming Docker builds, agent setup, and test verification all work correctly.

### Per-Repo Docker Health

| Repo | Docker Works? | Passing Runs | Infra Errors | Error Type |
|---|---|---|---|---|
| qutebrowser | Yes | 6 pass, 0 fail | 6 | Rate limit (Feb 8-9 batch) |
| gravitational/teleport | Yes | 5 pass, 3 fail | 6 | Rate limit (Feb 8-9 batch) |
| future-architect/vuls | Yes | 5 pass, 3 fail | 3 | Rate limit (Feb 8-9 batch) |
| element-hq | Yes | 5 pass, 0 fail | 1 | Rate limit (SG_base only) |
| tutao/tutanota | Yes | 1 pass, 0 fail | 2 | Rate limit (BL + SG_base) |
| nodebb | Yes | 8 pass, 4 fail | 1 | Rate limit (SG_base only) |
| internetarchive | Yes | 21 pass, 0 fail (archived) | 4 active + 17 archived | Rate limit + transcript corruption |

### Root Cause: OAuth Rate Limiting

32 of the 32 non-protonmail infra failures have the same signature:
- **0 output tokens** (agent never started generating)
- **0-8 second agent execution** (immediate failure)
- **No exception recorded** (silent auth failure)
- **Clustered in Feb 8-9 batches** (`swebenchpro_gapfill_opus_20260208_*` and `_20260209_*`)

The Max subscription was exhausted during this batch window. Tasks from the Feb 10 SG_full batch succeeded on the same Docker environments.

### Unfixable Items

None. All tasks are runnable — they just need fresh subscription tokens.

### Tasks Requiring Re-Run (Rate Limit Recovery)

**Baseline** (~13 tasks):
- 3× qutebrowser, 3× gravitational/teleport, 4× internetarchive/openlibrary
- 2× future-architect/vuls, 1× tutao/tutanota

**SG_base** (~16 tasks):
- 3× qutebrowser, 3× gravitational/teleport, 4× internetarchive/openlibrary
- 2× future-architect/vuls, 1× tutao/tutanota, 1× element-hq, 1× nodebb

**SG_full** (~4 tasks):
- 4× internetarchive/openlibrary (transcript corruption + timeout)

**Total non-protonmail re-runs: ~33 task runs** (no Docker fixes, just fresh auth tokens)

### Combined Re-Run Plan (Protonmail + Rate Limit Recovery)

| Category | Tasks | Configs | Total Runs | Fix Required |
|---|---|---|---|---|
| Protonmail (Docker fix) | 4 | BL, SG_base, SG_full | 12 | Node.js v16→v18 (done in US-002) |
| Rate limit recovery | ~17 unique tasks | Mixed per task | ~33 | None (fresh subscription) |
| **Total** | | | **~45** | |
