# SWE-Bench Pro Task Adaptation Analysis

## Background

CodeScaleBench has 7 TypeScript tasks (n=7, 1.9% of benchmark) and only 2 repos from
SWE-Bench Pro that are >1GB. Adding tasks from protonmail/WebClients (2.8GB, TypeScript)
would address both the TypeScript language gap and the large-repo coverage gap.

## Prior Protonmail Work (Archive Investigation)

The archive contains multiple failed protonmail runs from February 2026:

- `runs/archive/archive/ccb_fix_haiku_20260222_001122__wrong_dockerfile/` — 3 protonmail
  tasks (conv-testhooks, dropdown-sizing, holiday-calendar) failed due to wrong Dockerfiles
- `runs/archive/archive/qa_needed/zero_reward_invalid_20260225/` — protonmail tasks produced
  zero rewards, likely downstream of the Dockerfile issue
- `runs/archive/swebenchpro_selected_opus_20260203_160607/` — 4 protonmail instances all
  archived as `__archived_invalid`

**Root cause:** The originally retained protonmail tasks (`swebenchpro_retained_ids.json`)
were 30-34 file patches — extremely complex tasks that were hard to verify correctly. The
Dockerfiles were also misconfigured. Docker Hub auth issues prevented Daytona execution.

**Can the issues be resolved?** Yes:
1. Select simpler tasks (1-3 file patches instead of 30+ files)
2. Use correct SWEAP `dockerhub_tag` from the HF dataset for each task
3. Rehost images to GHCR via `scripts/rehost_sweap_images.py`
4. Run locally (12 slots) for SWEAP tasks until GHCR rehosting is complete

## HuggingFace Dataset Analysis

SWE-Bench Pro has 731 tasks across 11 repos:

| Repo | Tasks | Size | Language |
|------|-------|------|----------|
| protonmail/webclients | 65 | 2858 MB | TypeScript |
| gravitational/teleport | 76 | ~1300 MB | Go |
| element-hq/element-web | 56 | 457 MB | TypeScript |
| tutao/tutanota | 20 | 260 MB | TypeScript |
| ansible/ansible | 96 | ~200 MB | Python |
| internetarchive/openlibrary | 91 | ~150 MB | Python |
| flipt-io/flipt | 85 | ~100 MB | Go |
| qutebrowser/qutebrowser | 79 | 62 MB | Python |
| navidrome/navidrome | 57 | ~50 MB | Go |
| future-architect/vuls | 62 | 30 MB | Go |
| NodeBB/NodeBB | 44 | ~50 MB | JavaScript |

### Protonmail task complexity distribution

| Patch files | Count | Suitability |
|-------------|-------|-------------|
| 1-3 files | 17 | Good candidates |
| 4-6 files | 19 | Moderate |
| 7-10 files | 11 | Complex |
| 11-20 files | 14 | Very complex |
| 21-50 files | 3 | Previously selected, too complex |

## Proposed 8 New Tasks

### Protonmail/WebClients (5 tasks, 2.8GB TypeScript)

These are all 1-2 file patches, manageable complexity for both baseline and MCP agents:

| # | Instance ID suffix | Files | Lines | Problem |
|---|-------------------|-------|-------|---------|
| 1 | `c5a2089ca2bfe9aa` | 1 | 62 | useLinks failed-fetch reuse (API caching) |
| 2 | `2f66db85455f4b22` | 1 | 78 | Blockquote rendering in email messages |
| 3 | `944adbfe06644be0` | 2 | 38 | API error metrics tracking |
| 4 | `f161c10cf7d31abf` | 2 | 70 | Contact import date parsing |
| 5 | `51742625834d3bd0` | 2 | 202 | Punycode encoding for URL IDN phishing |

### Element-HQ/Element-Web (2 tasks, 457MB TypeScript)

Different TS codebase for diversity, also 1-file patches:

| # | Instance ID suffix | Files | Lines | Problem |
|---|-------------------|-------|-------|---------|
| 6 | `dae13ac8522fc6d4` | 1 | 70 | Unread indicators diverge between room/thread |
| 7 | `ee13e23b156fbad9` | 1 | 103 | RoomHeaderButtons crash on missing props |

### Gravitational/Teleport (1 task, 1.3GB Go)

Adds a fix task to complement the existing debug task:

| # | Instance ID suffix | Files | Lines | Problem |
|---|-------------------|-------|-------|---------|
| 8 | `3ff75e29fb2153a2` | 1 | 56 | MFA device deletion when MFA required |

## Impact on Benchmark

After adaptation:
- **TypeScript tasks:** 7 → 14 (doubles TS coverage)
- **Repos >1GB:** gains protonmail (2.8GB) for csb_sdlc_fix
- **csb_sdlc_fix:** 26 → 34 tasks (improved power from 25.6%)
- **Total benchmark:** 373 → 381 tasks

## Implementation Status

Tasks scaffolded via `scripts/scaffold_swebench_pro_tasks.py`:

| Task Name | Repo | Language |
|-----------|------|----------|
| teleport-users-can-delete-fix-001 | gravitational/teleport | Go |
| webclients-api-error-metrics-fix-001 | protonmail/webclients | TypeScript |
| webclients-incorrect-rendering-content-fix-001 | protonmail/webclients | TypeScript |
| webclients-contact-import-fails-fix-001 | protonmail/webclients | TypeScript |
| webclients-excessive-repeated-api-fix-001 | protonmail/webclients | TypeScript |
| webclients-implement-proper-punycode-fix-001 | protonmail/webclients | TypeScript |
| element-web-unread-indicators-diverge-fix-001 | element-hq/element-web | TypeScript |
| element-web-roomheaderbuttons-can-crash-fix-001 | element-hq/element-web | TypeScript |

All 8 registered in `configs/selected_benchmark_tasks.json`.

## Remaining Steps

1. Rehost the 8 SWEAP images from Docker Hub to GHCR
2. Run preflight validation: `python3 scripts/validate_tasks_preflight.py`
3. Execute baseline + MCP paired runs (3+ per task)

## SWEAP Image Handling

Each SWE-Bench Pro task has a unique Docker image at `jefzda/sweap-images:<tag>`.
These must be rehosted to `ghcr.io/sg-evals/sweap-images:<tag>` for Daytona.
The `scripts/rehost_sweap_images.py` script handles this automatically.

Until rehosted, tasks run locally (12 concurrent slots across 3 accounts).
