---
name: check-infra
description: Verify infrastructure readiness before launching benchmark runs — tokens, Docker, disk, credentials. Triggers on check infra, infrastructure check, ready to run, pre-run check.
user-invocable: true
---

# Check Infrastructure

Verify all infrastructure prerequisites before launching a benchmark run.

## What It Checks

- OAuth token validity and time remaining (per account for multi-account setups)
- `.env.local` (project root) has `ANTHROPIC_API_KEY` and `SOURCEGRAPH_ACCESS_TOKEN`
- Docker daemon is running and responsive
- Disk space is sufficient (>5GB required, >20GB recommended)
- `harbor` CLI is installed
- `runs/official/` directory exists

## Steps

### 1. Run the checker

```bash
cd ~/CodeScaleBench && python3 scripts/check_infra.py
```

### 2. Present results

Show the table output directly — it's already formatted with color-coded status.

### 3. Fix any issues

If FAIL items found, provide the specific fix:
- **Token expired**: `source configs/_common.sh && refresh_claude_token`
- **Multi-account tokens**: `source configs/_common.sh && setup_multi_accounts && ensure_fresh_token_all`
- **Missing env.local**: Create `.env.local` (project root) with required exports
- **Docker down**: `sudo systemctl start docker`
- **Low disk**: `python3 scripts/archive_run.py --older-than 7 --execute`

## Variants

### JSON output
```bash
python3 scripts/check_infra.py --format json
```
