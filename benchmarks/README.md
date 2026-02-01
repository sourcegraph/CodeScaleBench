# CodeContextBench Benchmarks

This directory contains all benchmark task definitions for evaluating coding agents with and without Sourcegraph MCP. The canonical task selection is defined in [`selected_benchmark_tasks.json`](../selected_benchmark_tasks.json) (125 tasks across 11 benchmarks).

See [`docs/TASK_SELECTION.md`](../docs/TASK_SELECTION.md) for the selection methodology.

---

## Active Benchmarks

### 1. [swebench_pro/](swebench_pro/) - Multi-Language Bug Fixing
**Tasks**: 36
**Languages**: Go, TypeScript, Python
**SDLC Phase**: Implementation (bug fix)
**Focus**: Long-horizon software engineering on production codebases
**Repositories**: flipt-io/flipt, tutao/tutanota, internetarchive/openlibrary, ansible/ansible, and more
**Task Format**: Harbor (via adapter, pre-generated)

---

### 2. [locobench_agent/](locobench_agent/) - Long-Context Agent Tasks
**Tasks**: 25
**Languages**: Rust, C#, C, C++, Python, Java, JavaScript, TypeScript, Go
**SDLC Phases**: Architecture & Design, Implementation (refactoring), Implementation (bug fix)
**Focus**: Architectural understanding, cross-file refactoring, bug investigation on synthetic codebases
**Task Format**: Harbor (via adapter, pre-generated)

---

### 3. [github_mined/](github_mined/) - Real PyTorch Pull Requests
**Tasks**: 12
**Languages**: C++ (PyTorch)
**SDLC Phase**: Implementation (bug fix)
**Focus**: Multi-file code changes on real production codebase
**Repository**: PyTorch (pytorch/pytorch)
**Task Format**: Harbor (task.toml, instruction.md, tests/)

---

### 4. [big_code_mcp/](big_code_mcp/) - Large Codebase Navigation
**Tasks**: 4
**Languages**: Go, Rust, C++, TypeScript
**SDLC Phase**: Implementation (feature)
**Focus**: Feature implementation in very large codebases
**Repositories**: Kubernetes, Servo, TensorRT-LLM, VS Code
**Task Format**: Harbor (task.toml, instruction.md, tests/)

---

### 5. [kubernetes_docs/](kubernetes_docs/) - Documentation Generation
**Tasks**: 5
**Languages**: Go
**SDLC Phase**: Documentation
**Focus**: Reconstruct doc.go/README content for stripped Kubernetes packages
**Repositories**: kubernetes/kubernetes, kubernetes/enhancements
**Task Format**: Harbor (task.toml, instruction.md, tests/)

---

### 6. [tac_mcp_value/](tac_mcp_value/) - TheAgentCompany Tasks
**Tasks**: 8
**Languages**: C++, Python
**SDLC Phases**: Requirements & Discovery, Implementation (feature), Testing & QA, Maintenance
**Focus**: Diverse SDE tasks (codebase search, implementation, unit testing, troubleshooting)
**Task Format**: Harbor (task.toml, instruction.md, tests/)

---

### 7. [dependeval_benchmark/](dependeval_benchmark/) - Multi-File & Cross-Repo Tasks
**Tasks**: 9
**Languages**: Python, Java, JavaScript
**SDLC Phases**: Implementation (refactoring), Maintenance
**Types**: Dependency Recognition (DR), Repository Construction (RC), Multi-file Editing (ME)
**Task Format**: Harbor (task.toml, instruction.md, tests/)

---

### 8. [sweperf/](sweperf/) - Performance Testing
**Tasks**: 3
**Languages**: Python
**SDLC Phase**: Testing & QA
**Focus**: Performance-oriented software engineering tasks
**Task Format**: Harbor (via adapter, pre-generated)

---

### 9. [repoqa/](repoqa/) - Semantic Code Navigation
**Tasks**: 10
**Languages**: Python, C++, Java, Rust, TypeScript
**SDLC Phase**: Requirements & Discovery
**Focus**: Find a function by behavioral description (no name provided)
**Repositories**: psf/black, python-poetry/poetry, google/gson, square/retrofit, and more
**Task Format**: Harbor (via adapter, pre-generated)

---

### 10. [10figure/](10figure/) - Enterprise Codebase Challenges
**Tasks**: 5
**Languages**: Go
**SDLC Phases**: Architecture & Design, Implementation (bug fix), Implementation (refactoring), Testing & QA
**Focus**: API migration, bug localization, cross-file reasoning, symbol rename, and smoke testing on Kubernetes
**Repository**: kubernetes/kubernetes
**Task Format**: Harbor (task.toml, instruction.md, tests/)
**Note**: Requires `harbor-10figure:base` Docker image built from `base/` directory.

---

### 11. [dibench/](dibench/) - Dependency Inference
**Tasks**: 8
**Languages**: Python, Rust, JavaScript, C#
**SDLC Phase**: Implementation (feature)
**Focus**: Infer and configure missing dependencies in build files by analyzing source code
**Source**: Microsoft DI-Bench (https://github.com/microsoft/DI-Bench)
**Task Format**: Harbor (task.toml, instruction.md, tests/)
**Note**: Each task includes the full project repo with dependencies stripped from build files.

---

## Benchmark Summary

| Benchmark | Tasks | Languages | SDLC Phase |
|-----------|------:|-----------|------------|
| swebench_pro | 36 | Go, TypeScript, Python | Bug fixing |
| locobench_agent | 25 | 9 languages | Architecture, Refactoring |
| github_mined | 12 | C++ | Bug fixing |
| repoqa | 10 | Python, C++, Java, Rust, TypeScript | Code navigation |
| dependeval_benchmark | 9 | Python, Java, JavaScript | Refactoring, Maintenance |
| tac_mcp_value | 8 | C++, Python | Mixed (4 phases) |
| dibench | 8 | Python, Rust, JavaScript, C# | Dependency inference |
| kubernetes_docs | 5 | Go | Documentation |
| big_code_mcp | 4 | Go, Rust, C++, TypeScript | Feature implementation |
| 10figure | 5 | Go | Architecture, Bug fix, Refactoring, Testing |
| sweperf | 3 | Python | Testing & QA |
| **Total** | **125** | | |

---

## Running Benchmarks

### 3-Config Comparison (Recommended)

Each benchmark has a shell runner in [`configs/`](../configs/) that executes selected tasks across the 3-config matrix (Baseline, MCP-NoDeepSearch, MCP-Full):

```bash
# Run all selected tasks for a benchmark
bash configs/locobench_3config.sh
bash configs/swebenchpro_3config.sh
bash configs/bigcode_3config.sh
bash configs/k8s_docs_3config.sh

# Run all benchmarks from the unified runner
bash configs/run_selected_tasks.sh

# Run only baseline config
bash configs/locobench_3config.sh --baseline-only
```

### Single Task Run

```bash
harbor run --path benchmarks/big_code_mcp/big-code-vsc-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [`docs/CONFIGS.md`](../docs/CONFIGS.md) for the full tool-by-tool breakdown of each config.

---

## Archived Benchmarks

Unused or superseded benchmarks have been moved to [`_archived/`](../_archived/):
- `benchmarks_10figure/` - Original 10figure prototype (superseded by benchmarks/10figure/)
- `benchmarks_dibench/` - Original DI-Bench adapter (superseded by benchmarks/dibench/)
- `benchmarks_repoqa/` - Original RepoQA adapter (superseded by benchmarks/repoqa/)
- `benchmarks_no_external_repos/` - Hello world, PRD bench, DevAI bench prototypes

---

## Results & Analysis

After running benchmarks, generate evaluation reports:

```bash
python3 scripts/generate_eval_report.py \
  --runs-dir /path/to/runs/official/ \
  --output-dir ./eval_reports/
```

See the root [README.md](../README.md) for the full metrics extraction pipeline.
