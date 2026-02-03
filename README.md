# CodeContextBench

Benchmark suite for evaluating how AI coding agents leverage external context tools on software engineering tasks across the SDLC. Developed as the reproducibility artifact for the paper *"CodeContextBench: A Systematic Evaluation Framework for Assessing the Impact of Enhanced Code Intelligence on AI Coding Agent Performance."*

This repository contains **benchmark task definitions**, **evaluation configs**, and a **metrics extraction pipeline**. Tasks are executed via the [Harbor](https://github.com/laude-institute/harbor/tree/main) runner with the Claude Code agent harness.

---

## Benchmark Suites

| Suite | Tasks | Languages | Evaluation Method | SDLC Phase |
|-------|------:|-----------|-------------------|------------|
| `ccb_swebenchpro` | 36 | Go, TypeScript, Python | LLM judge + test suite | Bug fixing |
| `ccb_locobench` | 25 | 9 languages | LLM judge + semantic similarity | Architecture, Refactoring |
| `ccb_pytorch` | 12 | C++ | LLM judge + test suite | Bug fixing |
| `ccb_repoqa` | 10 | Python, C++, Java, Rust, TypeScript | LLM judge + path/name matching | Code navigation |
| `ccb_dependeval` | 9 | Python, Java, JavaScript | LLM judge + test suite | Refactoring, Maintenance |
| `ccb_tac` | 8 | C++, Python | LLM judge + deterministic checks | Mixed (4 phases) |
| `ccb_dibench` | 8 | Python, Rust, JavaScript, C# | LLM judge + syntax/dependency validation | Dependency inference |
| `ccb_k8sdocs` | 5 | Go | LLM judge + test scripts | Documentation |
| `ccb_crossrepo` | 5 | Go | LLM judge + test suite | Architecture, Refactoring, Bug fix, Testing |
| `ccb_largerepo` | 4 | Go, Rust, C++, TypeScript | LLM judge + test suite | Feature implementation |
| `ccb_sweperf` | 3 | Python | LLM judge + test suite | Testing & QA |
| **Total** | **125** | | | |

---

## 3-Config Evaluation Matrix

All benchmarks are evaluated across three agent configurations that vary the external context tools available via MCP:

| Paper Config Name | `BASELINE_MCP_TYPE` | MCP Tools Available |
|-------------------|---------------------|---------------------|
| Baseline | `none` | None (agent uses only built-in tools) |
| MCP-Base | `sourcegraph_base` | `sg_keyword_search`, `sg_read_file`, `sg_find_file`, `sg_nls_search`, `sg_search_suggestions`, `sg_get_context` (6 tools) |
| MCP-Full | `sourcegraph_full` | All MCP-Base tools + `sg_deepsearch`, `sg_deepsearch_read` (8 tools) |

See [docs/CONFIGS.md](docs/CONFIGS.md) for the full tool-by-tool breakdown.

---

## Repository Structure

```
benchmarks/              # Task definitions organized by benchmark suite
  ccb_crossrepo/         #   Enterprise codebase challenges (5 tasks)
  ccb_dependeval/        #   Multi-file & cross-repo tasks (9 tasks)
  ccb_dibench/           #   Dependency inference tasks (8 tasks)
  ccb_k8sdocs/           #   K8s package documentation generation (5 tasks)
  ccb_largerepo/         #   Large-repo code navigation (4 tasks)
  ccb_locobench/         #   LoCoBench long-context agent tasks (25 tasks)
  ccb_pytorch/           #   GitHub-mined SWE tasks (12 tasks)
  ccb_repoqa/            #   Semantic code navigation (10 tasks)
  ccb_swebenchpro/       #   SWE-Bench Pro bug-fixing tasks (36 tasks)
  ccb_sweperf/           #   Performance testing (3 tasks)
  ccb_tac/               #   TheAgentCompany tasks (8 tasks)
configs/                 # 3-config comparison shell runners + task selection
  run_selected_tasks.sh  #   Unified runner for all 125 tasks
  locobench_3config.sh   #   Per-suite runner: LoCoBench (25 tasks)
  swebenchpro_3config.sh #   Per-suite runner: SWE-Bench Pro (36 tasks)
  largerepo_3config.sh   #   Per-suite runner: Large Repo (4 tasks)
  k8s_docs_3config.sh    #   Per-suite runner: K8s Docs (5 tasks)
  pytorch_3config.sh     #   Per-suite runner: PyTorch (12 tasks)
  repoqa_3config.sh      #   Per-suite runner: RepoQA (10 tasks)
  dependeval_3config.sh  #   Per-suite runner: DependEval (9 tasks)
  tac_3config.sh         #   Per-suite runner: TheAgentCompany (8 tasks)
  dibench_3config.sh     #   Per-suite runner: DIBench (8 tasks)
  crossrepo_3config.sh   #   Per-suite runner: CrossRepo (5 tasks)
  sweperf_3config.sh     #   Per-suite runner: SWE-Perf (3 tasks)
  selected_benchmark_tasks.json  # Canonical task selection (125 tasks)
scripts/                 # Metrics extraction and evaluation pipeline
  ccb_metrics/           #   Python package: models, extractors, discovery, judge context
  generate_eval_report.py  # CLI: deterministic evaluation report generator
docs/                    # Configuration documentation and diagnosis reports
schemas/                 # JSON schemas for MANIFEST.json, task.toml, etc.
```

Each benchmark directory contains:
- `MANIFEST.json` -- metadata, task IDs, evaluation config
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
- `eval_report.json` -- full structured report
- `REPORT.md` -- markdown tables (performance, efficiency, tool utilization)
- `harness_configs.json` -- exact harness configuration per run
- CSV files per table for downstream analysis

See `python3 scripts/generate_eval_report.py --help` for all options.

---

## Running with Harbor

The unified runner executes all 125 tasks across the 3-config matrix:

```bash
# Run all 125 tasks across 3 configs
bash configs/run_selected_tasks.sh

# Run only the baseline config
bash configs/run_selected_tasks.sh --baseline-only

# Dry run to list tasks without executing
bash configs/run_selected_tasks.sh --dry-run
```

Per-suite runners are also available for individual benchmarks:

```bash
bash configs/swebenchpro_3config.sh      # 36 SWE-Bench Pro tasks
bash configs/locobench_3config.sh        # 25 LoCoBench tasks
bash configs/pytorch_3config.sh          # 12 PyTorch tasks
bash configs/repoqa_3config.sh           # 10 RepoQA tasks
bash configs/dependeval_3config.sh       # 9 DependEval tasks
bash configs/tac_3config.sh              # 8 TheAgentCompany tasks
bash configs/dibench_3config.sh          # 8 DIBench tasks
bash configs/crossrepo_3config.sh        # 5 CrossRepo tasks
bash configs/k8s_docs_3config.sh         # 5 K8s Docs tasks
bash configs/largerepo_3config.sh         # 4 Large Repo tasks
bash configs/sweperf_3config.sh          # 3 SWE-Perf tasks
```

All runners support `--baseline-only` and `--full-only` flags.

Requires [Harbor](https://github.com/laude-institute/harbor/tree/main) installed and configured with a Claude API key.

---

## License

See [LICENSE](LICENSE).
