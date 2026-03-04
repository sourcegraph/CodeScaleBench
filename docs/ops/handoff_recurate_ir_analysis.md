# Handoff: Re-Curation IR Analysis

## Context
We re-curated ground truth for 311/367 benchmark tasks using a calibrated curator agent (Opus 4.6, phase1 prompt, hybrid backend). The new ground truth files are `_agent` variants that exist alongside the original manually-authored files.

**Commit**: `dd4d62eec3` — "Add calibrated curator ground truth (311/367) and harden Daytona sandbox lifecycle"

## What Was Done
- **Org: 207/207 complete** — all tasks have `oracle_answer_agent.json` in `benchmarks/csb_org_*/*/tests/`
- **SDLC: 104/160 complete** — tasks have `ground_truth_agent.json` in `benchmarks/csb_sdlc_*/*/tests/`
- **56 SDLC tasks still missing** — blocked by OAuth rate limits (Accounts 2+3 limited until Mar 6 3am UTC, Account 1 available)
- Missing SDLC concentrated in: `test` (16), `understand` (11), `debug` (10, 4 are known linux `--branch` parse bugs), `secure` (6), `document` (4), `feature` (4), `refactor` (2), `fix` (2), `design` (1)

## Files Modified
- `scripts/daytona_curator_runner.py` — hardened with orphan cleanup, auto-stop, signal handler, parallel=55 default
- `benchmarks/csb_org_*/*/tests/oracle_answer_agent.json` — 207 new curator-generated Org oracle files
- `benchmarks/csb_org_*/*/tests/ground_truth.json` — 207 updated (curator also writes canonical for Org)
- `benchmarks/csb_org_*/*/tests/ground_truth_meta.json` — 207 metadata files
- `benchmarks/csb_sdlc_*/*/tests/ground_truth_agent.json` — 104 new curator-generated SDLC ground truth files
- `benchmarks/csb_sdlc_*/*/tests/ground_truth_meta.json` — 104 metadata files

## Task 1: Complete Remaining 56 SDLC Tasks

Account 1 is available. Run:
```bash
source .env.local && export HARBOR_ENV=daytona DAYTONA_OVERRIDE_STORAGE=10240 CCB_ACCOUNT=1
python3 scripts/daytona_curator_runner.py \
  --sdlc-all --skip-agent-variants \
  --model claude-opus-4-6 --backend hybrid --prompt-version phase1 \
  --parallel 55
```

After completion, 4 linux kernel tasks will still fail (`linux-acpi-backlight-fault-001`, `linux-hda-intel-suspend-fault-001`, `linux-iwlwifi-subdevice-fault-001`, `linux-nfs-inode-revalidate-fault-001`) — their Dockerfiles use `git clone --branch` which gets parsed as a repo slug. These need manual ground truth.

## Task 2: Promote Agent Oracles

After all tasks complete, promote `_agent` variants to canonical:
```bash
python3 scripts/promote_agent_oracles.py --force
```

This replaces `ground_truth.json` / `oracle_answer.json` with the calibrated `_agent` versions.

## Task 3: Re-Run IR Analysis

The IR evaluation pipeline reads:
- SDLC: `ground_truth.json` (so promotion must happen first)
- Org: `oracle_answer.json` first, then `ground_truth.json` fallback

After promotion, regenerate the IR analysis:
```bash
# Normalize retrieval events from all official runs
python3 scripts/normalize_retrieval_events.py --runs-dir runs/official/

# Evaluate IR metrics against new ground truth
python3 scripts/compute_retrieval_metrics.py --runs-dir runs/official/ --output results/ir/

# Generate the V2 report with updated IR numbers
python3 scripts/extract_v2_report_data.py
```

Key metrics to compare before/after promotion:
- Per-suite F1, precision, recall
- Baseline vs SG_full delta (does MCP advantage change with better ground truth?)
- Overall aggregate F1

## Task 4: Quality Spot-Check (Before Promotion)

Before promoting, spot-check a sample of `_agent` vs canonical ground truth:
```bash
# Pick 5 random tasks and compare file lists
for f in $(find benchmarks/csb_sdlc_* -name ground_truth_agent.json | shuf | head -5); do
  canonical=$(dirname "$f")/ground_truth.json
  echo "=== $(basename $(dirname $(dirname $f))) ==="
  echo "Canonical files: $(python3 -c "import json; print(len(json.load(open('$canonical')).get('expected_files', [])))" 2>/dev/null || echo "N/A")"
  echo "Agent files: $(python3 -c "import json; print(len(json.load(open('$f')).get('expected_files', [])))")"
  echo ""
done
```

Look for:
- Agent producing 0 or 1 files (regex rescue, low quality) — should re-run
- Agent producing 50+ files (over-inclusion) — may need review
- Canonical having files the agent missed (recall regression)

## Key Architecture Notes

- `write_curator_outputs()` in `context_retrieval_agent.py` handles both SDLC and Org file writing
- When `overwrite=False` (default), writes `_agent` variants; when `overwrite=True`, writes canonical
- `ground_truth_meta.json` contains curator metadata: model, backend, prompt version, cost, timestamp
- The curator uses phase1 prompt (`PHASE1_CLI_PROMPTS` + `PHASE1_SUFFIX`) which is recall-focused (F1=0.749 on calibration set)
- Hybrid backend = local tools (Bash, Read, Glob, Grep) + Sourcegraph MCP (sg_keyword_search, sg_nls_search)

## Daytona Runner Changes (for reference)

The runner was hardened in this session to prevent orphaned sandbox accumulation:
1. `cleanup_orphaned_sandboxes()` runs at startup and shutdown
2. `auto_stop_interval=20` (minutes) — sandboxes auto-stop if idle
3. `auto_archive_interval=60` — auto-archive after 1 hour
4. SIGTERM/SIGINT signal handler cancels futures and triggers cleanup
5. `DEFAULT_PARALLEL=55` (was 20) — matches Tier 3 capacity (250 vCPU / 2 per sandbox = 125 max, minus headroom)
