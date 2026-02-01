# CodeContextBench

Benchmark suite for evaluating how AI coding agents leverage external context tools (MCP servers) on software engineering tasks across the SDLC. Developed as the reproducibility artifact for the paper *"Evaluating the Impact of Model Context Protocol on AI Coding Agent Performance Across the Software Development Lifecycle."*

This repository contains **benchmark task definitions**, **evaluation configs**, and a **metrics extraction pipeline**. Tasks are executed via the [Harbor](https://github.com/mainmatter/harbor) runner with the Claude Code agent harness.

---

## Benchmark Suites

| Suite | Tasks | Languages | Evaluation Method | SDLC Phase |
|-------|------:|-----------|-------------------|------------|
| `kubernetes_docs` | 5 | Go | LLM judge + test scripts | Documentation |
| `big_code_mcp` | 4 | Go, Rust, C++, TypeScript | Test suite | Code navigation |
| `locobench_agent` | 50 | Multi-language | Semantic similarity | Long-context reasoning |
| `swebench_pro` | 50 | Multi-language | Test suite | Bug fixing |
| `github_mined` | 25 | Python | Test suite | Feature implementation |

Additional benchmark suites (`sweperf`, `tac_mcp_value`, `dibench`, `repoqa`, etc.) are included in early stages of development.

---

## 3-Config Evaluation Matrix

All benchmarks are evaluated across three agent configurations that vary the external context tools available via MCP:

| Paper Config Name | `BASELINE_MCP_TYPE` | MCP Tools Available |
|-------------------|---------------------|---------------------|
| Baseline | `none` | None (agent uses only built-in tools) |
| MCP-NoDeepSearch | `sourcegraph_no_deepsearch` | `sg_keyword_search`, `sg_read_file`, `sg_find_file`, `sg_nls_search`, `sg_search_suggestions`, `sg_get_context` (6 tools) |
| MCP-Full | `sourcegraph_hybrid` | All MCP-NoDeepSearch tools + `sg_deepsearch`, `sg_deepsearch_read` (8 tools) |

See [docs/CONFIGS.md](docs/CONFIGS.md) for the full tool-by-tool breakdown.

---

## Repository Structure

```
benchmarks/              # Task definitions organized by benchmark suite
  kubernetes_docs/       #   K8s package documentation generation (5 tasks)
  big_code_mcp/          #   Large-repo code navigation (4 tasks)
  locobench_agent/       #   LoCoBench long-context agent tasks (50 tasks)
  swebench_pro/          #   SWE-Bench Pro bug-fixing tasks (731 available, 50 selected)
  github_mined/          #   GitHub-mined SWE tasks (25 tasks)
  ...                    #   Additional suites in development
ralph/                   # Agent working directory
  configs/               #   3-config comparison YAML + shell runners per benchmark
  scripts/               #   Metrics extraction and evaluation pipeline
    ccb_metrics/         #     Python package: models, extractors, discovery, judge context
    generate_eval_report.py  # CLI: deterministic evaluation report generator
docs/                    # Configuration documentation and diagnosis reports
schemas/                 # JSON schemas for MANIFEST.json, task.toml, etc.
swe_bench_configs/       # SWE-Bench integration configuration
```

Each benchmark directory contains:
- `MANIFEST.json` — metadata, task IDs, evaluation config
- Per-task subdirectories with `instruction.md`, `task.toml`, tests, and ground truth (or `solution/`)

---

## Metrics Extraction Pipeline

The `scripts/` directory contains a stdlib-only Python 3.10+ pipeline for extracting deterministic metrics from Harbor run output:

```bash
# Generate evaluation report from Harbor runs
python3 scripts/generate_eval_report.py \
  --runs-dir /path/to/runs/official/ \
  --output-dir ./eval_reports/

# Generate LLM judge context files
python3 -m scripts.ccb_metrics.judge_context \
  --runs-dir /path/to/runs/official/ \
  --benchmarks-dir ./benchmarks/ \
  --output-dir ./judge_contexts/
```

The report generator produces:
- `eval_report.json` — full structured report
- `REPORT.md` — markdown tables (performance, efficiency, tool utilization)
- `harness_configs.json` — exact harness configuration per run
- CSV files per table for downstream analysis

See `python3 scripts/generate_eval_report.py --help` for all options.

---

## Running with Harbor

Each benchmark has a shell runner in `configs/` that executes all tasks across the 3-config matrix:

```bash
# Run all 50 LoCoBench tasks across 3 configs
bash configs/locobench_3config.sh

# Run only the baseline config
bash configs/locobench_3config.sh --baseline-only

# Run only MCP-Full config
bash configs/locobench_3config.sh --full-only
```

Available runners: `locobench_3config.sh`, `swebenchpro_3config.sh`, `bigcode_3config.sh`, `k8s_docs_3config.sh`.

Requires [Harbor](https://github.com/mainmatter/harbor) installed and configured with a Claude API key.

---

## License

See [LICENSE](LICENSE).
