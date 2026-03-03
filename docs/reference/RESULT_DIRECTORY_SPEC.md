# Official Results Directory Specification

> **When To Read This**: Before writing any script that scans `runs/official/` for
> coverage, pairing, or reporting. This doc prevents the #1 recurring agent mistake:
> incorrect task ID extraction leading to false "missing results" reports.

## Task Counts (as of 2026-03-03)

| Category | Count | Notes |
|---|---|---|
| SDLC tasks | 150 | 9 suites (feature/refactor/debug/design/document/fix/secure/test/understand) |
| Org tasks | 220 | 11 suites (csb_org_*) |
| **Total** | **370** | DOE-driven Neyman-optimal allocation. Old `csb_sdlc_build` was split into `csb_sdlc_feature` (23) + `csb_sdlc_refactor` (16) |

## Directory Layouts

`runs/official/` contains batches with **three different directory structures**.
Any scanner MUST handle all three or it will under-count results.

### Layout 1: Old Promoted Format (pre-2026-02-24)

```
runs/official/{suite}_{model}_{date}/
  baseline/
    {suite}_{task_id}_{config_name}/       ← wrapper dir
      {trial_dirname}/                     ← e.g. sgonly_task-name__AbCdEfG
        result.json                        ← TASK-LEVEL (has task_name)
      result.json                          ← BATCH-LEVEL (has stats, no task_name)
  mcp/
    {suite}_{task_id}_{config_name}/
      {trial_dirname}/
        result.json                        ← TASK-LEVEL
      result.json                          ← BATCH-LEVEL
```

**Config dir names**: `baseline`, `mcp`

Example (historical, from pre-split `csb_sdlc_build` runs): `csb_sdlc_build_haiku_022326/mcp/csb_sdlc_build_bustub-hyperloglog-impl-001_mcp-remote-direct/sgonly_bustub-hyperloglog-impl-0__2E3pTAv/result.json`

### Layout 2: Harbor Nested Format (2026-02-24+)

```
runs/official/{suite}_{model}_{timestamp}/
  baseline-local-direct/
    {harbor_timestamp}/                    ← e.g. 2026-02-26__00-09-23
      {task_dirname}/                      ← e.g. task-name__AbCdEfG
        result.json                        ← TASK-LEVEL
      result.json                          ← BATCH-LEVEL
  mcp-remote-direct/
    {harbor_timestamp}/
      {task_dirname}/
        result.json
```

**Config dir names**: `baseline-local-direct`, `mcp-remote-direct`

### Layout 3: CodeScaleBench-Org / Artifact Format

```
runs/official/{suite}_{model}_{timestamp}/
  baseline-local-direct/                   (or baseline-local-artifact)
    {harbor_timestamp}/
      bl_{TASK_ID}_{hash}__hash/           ← bl_ prefix, uppercase task ID
        result.json
  mcp-remote-direct/                       (or mcp-remote-artifact)
    {harbor_timestamp}/
      mcp_{TASK_ID}_{hash}__hash/          ← mcp_ prefix, uppercase task ID
        result.json
```

**Config dir names**: `baseline-local-artifact`, `mcp-remote-artifact`

## Config Name Equivalences

When determining if a result is "baseline" or "MCP":

| Logical Config | Directory Names |
|---|---|
| **Baseline** | `baseline`, `baseline-local-direct`, `baseline-local-artifact` |
| **MCP / SG_full** | `mcp`, `mcp-remote-direct`, `mcp-remote-artifact` |

## result.json: Two Flavors

**CRITICAL**: Not every `result.json` is a task result. There are two schemas:

### Batch-level (IGNORE for coverage)
```json
{
  "id": "...",
  "started_at": "...",
  "finished_at": "...",
  "n_total_trials": 1,
  "stats": { ... }
}
```
Key indicator: has `stats` or `n_total_trials`, does NOT have `task_name`.

### Task-level (USE for coverage)
```json
{
  "id": "...",
  "task_name": "sgonly_k8s-noschedule-taint-feat-001",
  "task_id": {"path": "/tmp/sgonly_k8s-noschedule-taint-feat-001"},
  "verifier_result": {"rewards": [...]},
  "started_at": "...",
  "finished_at": "...",
  ...
}
```
Key indicator: has `task_name` field.

## Task ID Extraction (THE HARD PART)

Task IDs appear in multiple fields with various prefixes and suffixes.
**Always try multiple sources** and normalize:

### Sources (in priority order)
1. `task_name` field (string like `"sgonly_k8s-noschedule-taint-feat-001"`)
2. `task_id` field — **WARNING: can be a dict** `{"path": "/tmp/sgonly_..."}`
3. Parent directory name (e.g. `sgonly_bustub-hyperloglog-impl-0__2E3pTAv`)

### Prefixes to strip
- `sgonly_` — added by sg_only Dockerfile swap
- `mcp_` — added by MCP artifact runs
- `bl_` — added by baseline artifact runs
- `{suite}_` — suite prefix (e.g. `csb_sdlc_feature_`, `csb_sdlc_refactor_`)

### Suffixes to strip
- `__AbCdEfG` — Harbor 7-char random hash (after double underscore)
- `_AbCdEfG` — Harbor 7-char random hash (after single underscore, ambiguous)
- `_{config_name}` — config suffix in old promoted format

### Truncation warning
Harbor truncates directory names. A task ID like `bustub-hyperloglog-impl-001`
may appear as `bustub-hyperloglog-impl-0` in the directory name. **Always prefer
`task_name` from result.json** over the directory name.

### Recommended normalization function

```python
import re

BL_NAMES = {'baseline-local-direct', 'baseline-local-artifact', 'baseline'}
MCP_NAMES = {'mcp-remote-direct', 'mcp-remote-artifact', 'mcp'}

def normalize_task_id(raw: str, suites: set[str] = set()) -> str:
    """Extract bare task ID from any naming convention."""
    # Strip known prefixes
    for pfx in ('sgonly_', 'mcp_', 'bl_'):
        if raw.startswith(pfx):
            raw = raw[len(pfx):]
    # Strip suite prefix
    for suite in suites:
        if raw.startswith(suite + '_'):
            raw = raw[len(suite) + 1:]
    # Strip config suffix
    for cfg in BL_NAMES | MCP_NAMES:
        if raw.endswith(f'_{cfg}'):
            raw = raw[:-(len(cfg) + 1)]
    # Strip Harbor hash suffixes
    raw = re.sub(r'__[A-Za-z0-9]{6,8}$', '', raw)
    raw = re.sub(r'_[A-Za-z0-9]{6,8}$', '', raw)
    return raw.lower()

def extract_task_id_from_result(data: dict, parent_dir: str, suites: set[str]) -> str | None:
    """Try multiple sources to extract a task ID from a result.json."""
    candidates = set()

    # Source 1: task_name (always a string)
    tn = data.get('task_name', '')
    if isinstance(tn, str) and tn:
        candidates.add(normalize_task_id(tn, suites))

    # Source 2: task_id (may be dict with path key!)
    ti = data.get('task_id', '')
    if isinstance(ti, dict):
        ti = ti.get('path', '').split('/')[-1]
    if isinstance(ti, str) and ti:
        candidates.add(normalize_task_id(ti, suites))

    # Source 3: parent directory name
    candidates.add(normalize_task_id(parent_dir, suites))

    # Match against known task IDs
    return candidates  # caller checks against their task set
```

## Coverage Scanning: Correct Approach

```python
from pathlib import Path

# Use rglob to find ALL result.json at any depth
for rj in Path('runs/official').rglob('result.json'):
    data = json.loads(rj.read_text())

    # 1. Skip batch-level results
    if 'task_name' not in data:
        continue

    # 2. Determine config from PATH COMPONENTS (not from result content)
    parts = rj.relative_to(official).parts
    is_baseline = any(p in BL_NAMES for p in parts)
    is_mcp = any(p in MCP_NAMES for p in parts)

    # 3. Extract task ID using ALL sources
    candidates = extract_task_id_from_result(data, rj.parent.name, suites)

    # 4. Match against known task set (case-insensitive)
    for c in candidates:
        if c in known_tasks:
            # Record the match
            break
```

### Common mistakes that cause false negatives

| Mistake | Consequence |
|---|---|
| Only checking 2-3 levels deep | Misses Layout 1 (old promoted, 4 levels deep) |
| Using `task_id` field without checking if it's a dict | Crash or empty string |
| Not stripping `sgonly_` prefix from `task_name` | No match against selection file |
| Only recognizing `baseline-local-direct` / `mcp-remote-direct` | Misses `baseline` / `mcp` config dirs from old promoted batches |
| Using directory name for task ID | Harbor truncates long names — prefer `task_name` |
| Case-sensitive matching | Selection file has mixed CCX-/ccx- |

## Protonmail Removal (2026-02-26)

3 tasks removed from `csb_sdlc_fix` due to unresolvable `git apply --allow-empty` verifier bug:
- `protonmail-conv-testhooks-fix-001`
- `protonmail-dropdown-sizing-fix-001`
- `protonmail-holiday-calendar-fix-001`

This reduced SDLC from 170 to 167 tasks. Commit: `af3e69ab7`.
