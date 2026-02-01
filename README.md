# CodeContextBench — Benchmark Definitions

Benchmark task definitions for evaluating AI coding agents on context-intensive software engineering tasks.

This repository contains only the **benchmark definitions** (task descriptions, ground truth, adapters, schemas). The orchestration dashboard, runners, agents, and analysis pipeline live in the companion **[CodeContextBench_Dashboard](https://github.com/sjarmak/CodeContextBench_Dashboard)** repository.

---

## Repository Structure

```
benchmarks/          # Task definitions organized by benchmark suite
  kubernetes_docs/   #   K8s documentation generation tasks
  big_code_mcp/      #   Large codebase navigation tasks
  github_mined/      #   GitHub-mined SWE tasks
  locobench_agent/   #   LoCoBench agent tasks
  sweperf/           #   SWE-Perf optimization tasks
  tac_mcp_value/     #   TAC MCP-value tasks
  10figure/          #   10-Figure corpus tasks
  ...
schemas/             # JSON schemas for MANIFEST.json, task.toml, etc.
swe_bench_configs/   # SWE-Bench integration configuration
```

Each benchmark directory contains:
- `MANIFEST.json` — metadata, task IDs, evaluation config
- Per-task subdirectories with `instruction.md`, `task.toml`, tests, and ground truth

---

## Usage with Dashboard

Set the `CCB_BENCHMARKS_DIR` environment variable in the Dashboard repo to point here:

```bash
export CCB_BENCHMARKS_DIR="/path/to/CodeContextBench"
```

Or place both repos as siblings (the default):

```
parent/
  CodeContextBench/          # this repo
  CodeContextBench_Dashboard/  # dashboard + orchestration
```

---

## Benchmark Suites

| Suite | Tasks | Description |
|-------|-------|-------------|
| kubernetes_docs | 5 | K8s package documentation generation |
| big_code_mcp | 12 | Large-repo code navigation & understanding |
| github_mined | 30 | Real GitHub SWE tasks (Harbor format) |
| locobench_agent | 50 | LoCoBench long-context agent tasks |
| sweperf | 20 | SWE-Bench performance optimization |
| tac_mcp_value | 20 | TheAgentCompany MCP-value tasks |
| 10figure | 0 | 10-Figure corpus (pending data) |

---

## select_tasks.py Scripts

Some benchmarks include `select_tasks.py` scripts that require the Dashboard repo's `src/` package on `PYTHONPATH`. To run them:

```bash
export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
python benchmarks/<suite>/select_tasks.py
```

---

## License

See [LICENSE](LICENSE).
