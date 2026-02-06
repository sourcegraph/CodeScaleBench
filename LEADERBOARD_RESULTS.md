# CodeContextBench Leaderboard Results

*Generated: 2026-02-06T21:39:02.415676+00:00*

## Aggregate Ranking

*No entries with complete coverage of all 13 benchmarks.*

### Partial Coverage (not ranked in aggregate)

| Agent | Config | Score (qualifying) | Benchmarks | Tasks | Pass Rate |
|-------|--------|--------------------|------------|-------|-----------|
| anthropic/claude-opus-4-5-20251101 | sourcegraph_full | 0.860 | 1/13 | 5 | 1.000 |
| anthropic/claude-opus-4-5-20251101 | baseline | 0.642 | 8/13 | 100 | 0.640 |
| anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.559 | 7/13 | 96 | 0.625 |

## Per-Benchmark Rankings

### ccb_codereview (3 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.933 | 1.000 | 3/3 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.893 | 1.000 | 3/3 | Yes |

### ccb_crossrepo (5 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| - | anthropic/claude-opus-4-5-20251101 | baseline | 0.000 | 0.000 | 4/5 | No |
| - | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.000 | 0.000 | 4/5 | No |

### ccb_dibench (8 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.500 | 0.500 | 8/8 | Yes |
| - | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.500 | 0.500 | 4/8 | No |

### ccb_k8sdocs (5 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.920 | 1.000 | 5/5 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.920 | 1.000 | 5/5 | Yes |

### ccb_largerepo (4 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.250 | 0.250 | 4/4 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.250 | 0.250 | 4/4 | Yes |

### ccb_linuxflbench (5 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.860 | 1.000 | 5/5 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_full | 0.860 | 1.000 | 5/5 | Yes |
| 3 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.740 | 1.000 | 5/5 | Yes |

### ccb_locobench (25 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| - | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.504 | 1.000 | 18/25 | No |
| - | anthropic/claude-opus-4-5-20251101 | baseline | 0.487 | 1.000 | 20/25 | No |

### ccb_pytorch (12 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.083 | 0.083 | 12/12 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.081 | 0.083 | 12/12 | Yes |

### ccb_repoqa (10 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 1.000 | 1.000 | 10/10 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 1.000 | 1.000 | 10/10 | Yes |

### ccb_swebenchpro (36 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| - | anthropic/claude-opus-4-5-20251101 | baseline | 0.600 | 0.600 | 20/36 | No |
| - | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.591 | 0.591 | 22/36 | No |

### ccb_sweperf (3 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| 1 | anthropic/claude-opus-4-5-20251101 | baseline | 0.591 | 1.000 | 3/3 | Yes |
| 2 | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.032 | 0.667 | 3/3 | Yes |

### ccb_tac (8 tasks)

| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |
|------|-------|--------|-------------|-----------|-------|----------|
| - | anthropic/claude-opus-4-5-20251101 | baseline | 0.000 | 0.000 | 6/8 | No |
| - | anthropic/claude-opus-4-5-20251101 | sourcegraph_base | 0.000 | 0.000 | 6/8 | No |

---

*Scoring rules: see [docs/LEADERBOARD.md](docs/LEADERBOARD.md)*
