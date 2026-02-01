# CodeContextBench Benchmarks

This directory contains all standardized benchmarks for evaluating coding agents with and without Sourcegraph MCP.

## Active Benchmarks

### 1. [big_code_mcp/](big_code_mcp/) - Large Codebase MCP Comparison
**Status**: Production-ready  
**Task Count**: 4 tasks  
**Focus**: Stale diagnostics, architecture understanding in large codebases  
**Repositories**: VS Code, Kubernetes, Servo, TensorRT  
**Suitable For**: Testing MCP value on real large-codebase problems  
**Task Format**: Harbor (task.toml, instruction.md, tests/)

**Run**:
```bash
harbor run --path benchmarks/big_code_mcp/big-code-vsc-001 \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

---

### 2. [github_mined/](github_mined/) - Real PyTorch Pull Requests
**Status**: Production-ready  
**Task Count**: 25 tasks  
**Focus**: Multi-file code changes on real production codebase  
**Repository**: PyTorch (pytorch/pytorch)  
**Suitable For**: General agent capability, test/debug workflows  
**Limitations**: All agents have repo code access (not MCP-sensitive)  
**Task Format**: Harbor (task.toml, instruction.md, tests/)

**Run**:
```bash
harbor run --path benchmarks/github_mined \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 5
```

**Note**: See [README.md](github_mined/README.md) for limitations and future improvements.

---

### 3. [dependeval_benchmark/](dependeval_benchmark/) - Multi-File & Cross-Repo Tasks
**Status**: Production-ready  
**Task Count**: 9 tasks  
**Types**: Dependency Recognition (DR), Repository Construction (RC), Multi-file Editing (ME)  
**Languages**: Python, Java, JavaScript  
**Focus**: Code understanding, dependency tracking  
**Suitable For**: MCP value on multi-file/cross-repo reasoning  
**Task Format**: Harbor (task.toml, instruction.md, tests/)

**Run**:
```bash
harbor run --path benchmarks/dependeval_benchmark/DR_python/dependency_recognition-python-unknown \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

---

### 4. [10figure/](10figure/) - Legacy Codebase Challenges
**Status**: Production-ready  
**Task Count**: 4 tasks (one per type)  
**Types**: Cross-file reasoning, refactor/rename, API upgrades, bug localization  
**Repositories**: Kubernetes, Envoy, Django, TensorFlow, and others  
**Focus**: Complex transformations in large OSS codebases  
**Suitable For**: Testing comprehension of large, unfamiliar codebases  
**Task Format**: Harbor (task.toml, instruction.md, tests/)

**Prerequisites**:
- `~/10Figure-Codebases/` corpus (23 OSS repos, ~5GB)
- `~/harbor-10figure-dataset/` infrastructure

**Run**:
```bash
harbor run --path benchmarks/10figure/api_upgrade_01 \
  --agent-import-path agents.mcp_variants:FullToolkitAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

---

### 5. [dibench/](dibench/) - Dependency Inference Benchmark
**Status**: Production-ready (migrated from Harbor adapter)  
**Task Count**: Variable (generate with adapter)  
**Focus**: Dependency inference and resolution  
**Languages**: Python, Rust, C#, JavaScript  
**Suitable For**: Testing agents on dependency discovery tasks  
**Task Format**: Harbor (via adapter)

**Generate Tasks**:
```bash
cd benchmarks/dibench
python run_adapter.py \
  --dataset_path path/to/dibench-regular.jsonl \
  --repo_instances_dir .cache/repo-data \
  --output_dir ./tasks \
  --limit 5
```

**Run**:
```bash
harbor run --path benchmarks/dibench/tasks/python-instance-001 \
  --agent-import-path agents.mcp_variants:DeepSearchFocusedAgent
```

See [README.md](dibench/README.md) for setup and [INTEGRATION.md](dibench/INTEGRATION.md) for details.

---

### 6. [repoqa/](repoqa/) - Tool-Sensitive Code Understanding
**Status**: Production-ready (newly completed)  
**Task Count**: Variable (generate with adapter)  
**Types**: SR-QA (semantic retrieval), MD-QA (multi-hop dependencies), NR-QA (disambiguation)  
**Languages**: Python, JavaScript  
**Focus**: Measuring Sourcegraph MCP value for code understanding  
**Suitable For**: Isolating MCP benefit on semantic search tasks  
**Task Format**: Harbor (via adapter)

**Generate Tasks**:
```bash
cd benchmarks/repoqa
python run_adapter.py \
  --dataset_path path/to/repoqa-instances.jsonl \
  --output_dir ./tasks \
  --variants sr-qa md-qa nr-qa \
  --limit 10
```

**Run**:
```bash
harbor run --path benchmarks/repoqa/tasks/sr-qa-requests-001 \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [README.md](repoqa/README.md) for design and [IMPLEMENTATION_SUMMARY.md](repoqa/IMPLEMENTATION_SUMMARY.md) for details.

---

### 7. [kubernetes_docs/](kubernetes_docs/) - Kubernetes Documentation Generation
**Status**: Pilot-ready  
**Task Count**: 5 tasks (scheduler plugins, API packages, kubelet subsystems)  
**Focus**: Reconstruct doc.go/README content for stripped Kubernetes packages  
**Repositories**: `kubernetes/kubernetes`, `kubernetes/enhancements`  
**Suitable For**: Measuring MCP retrieval value on long-form documentation tasks  
**Task Format**: Harbor (task.yaml, TASK.md, stripped code context, ground truth docs)

**Run**:
```bash
harbor run --path benchmarks/kubernetes_docs/pkg-doc-001 \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [README.md](kubernetes_docs/README.md) for setup requirements (doc stripping workflow, KEP ground truth extraction).

---

### 8. [swebench_pro/](swebench_pro/) - Multi-Language Long-Horizon Tasks (NEW)
**Status**: Production-ready  
**Task Count**: ~100 tasks (from ScaleAI/SWE-bench_Pro)  
**Languages**: Go, TypeScript, Python  
**Focus**: Long-horizon software engineering on production codebases  
**Repositories**: flipt-io/flipt, tutao/tutanota, internetarchive/openlibrary, and more  
**Suitable For**: Testing MCP value on multi-language, complex debugging tasks  
**Task Format**: Harbor (via adapter)

**Generate Tasks**:
```bash
cd benchmarks/swebench_pro
python run_adapter.py --all --limit 10 --task-dir ./tasks --enable-mcp
```

**Run**:
```bash
harbor run --path benchmarks/swebench_pro/tasks/instance_flipt-io__flipt-xxx \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

**SWE-agent Integration**: Use `agents.swe_agent_wrapper:SWEAgentMCPAgent` for SWE-agent with MCP.

See [README.md](swebench_pro/README.md) for setup and SWE-agent integration details.

---

## Benchmark Comparison Matrix

| Benchmark | MCP Value | Task Count | Repos | Setup Time | Best For |
|-----------|-----------|-----------|-------|-----------|----------|
| big_code_mcp | ⭐⭐⭐⭐⭐ (high) | 4 | Real (large) | 5min | MCP capability testing |
| github_mined | ⭐⭐ (low) | 25 | 1 (PyTorch) | 2min | General agent capability |
| dependeval | ⭐⭐⭐ (medium) | 9 | 150+ | 10min | Multi-file reasoning |
| 10figure | ⭐⭐⭐⭐ (high) | 4 | 23 | 20min | Large codebase understanding |
| dibench | ⭐⭐⭐ (medium) | Variable | Custom | 15min | Dependency inference |
| repoqa | ⭐⭐⭐⭐ (high) | Variable | Custom | 10min | Tool-sensitive MCP eval |
| kubernetes_docs | ⭐⭐⭐⭐ (high) | 5 | Kubernetes (code + KEPs) | 30min | Documentation & retrieval evaluation |
| swebench_pro | ⭐⭐⭐⭐⭐ (high) | ~100 | Multi-lang (Go, TS, Py) | 15min | Long-horizon multi-language |

---

## Using With Benchmark Agents

All benchmarks work with the 5 standardized agents:

```bash
# Baseline (Claude Code, no MCP)
harbor run --path <task_path> \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001

# Strategic Deep Search (targeted MCP usage)
harbor run --path <task_path> \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001

# Deep Search Focused (MCP with aggressive Deep Search prompting)
harbor run --path <task_path> \
  --agent-import-path agents.mcp_variants:DeepSearchFocusedAgent \
  --model anthropic/claude-haiku-4-5-20251001

# MCP No Deep Search (keyword/NLS only)
harbor run --path <task_path> \
  --agent-import-path agents.mcp_variants:MCPNonDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001

# Full Toolkit (all tools, neutral prompting)
harbor run --path <task_path> \
  --agent-import-path agents.mcp_variants:FullToolkitAgent \
  --model anthropic/claude-haiku-4-5-20251001
```

See [AGENTS.md](../AGENTS.md#benchmark-agents) for agent details.

---

## Archived Benchmarks

Outdated or superseded benchmarks are archived in [history/archived_benchmarks/](../history/archived_benchmarks/):
- `dibench_tasks_raw/` - Raw tasks (use Harbor adapter instead)
- `repoqa_sr_qa_tasks_raw/` - Raw tasks (use Harbor adapter instead)
- `repoqa_validated_tasks_raw/` - Raw tasks (use Harbor adapter instead)
- `dependeval_filtered_raw/` - Intermediate processing artifact
- `github_mined_pilot_duplicate/` - Duplicate of github_mined

---

## Setup & Prerequisites

### Environment Variables
```bash
# For MCP-enabled runs
export SOURCEGRAPH_URL="https://sourcegraph.sourcegraph.com"
export SOURCEGRAPH_ACCESS_TOKEN="your-token"

# For baseline runs (unset MCP credentials)
unset SOURCEGRAPH_URL
unset SOURCEGRAPH_ACCESS_TOKEN
```

### Harbor Installation
```bash
# Install Harbor
uv tool install harbor

# Or from source
cd ~/harbor
pip install -e .
```

### Benchmark-Specific Setup

**10figure**: Requires corpus at `~/10Figure-Codebases/` and infrastructure at `~/harbor-10figure-dataset/`

**dibench**: Download dataset from [DI-Bench releases](https://github.com/microsoft/DI-Bench/releases) and extract to `.cache/repo-data`

**repoqa**: Download RepoQA dataset and point adapter to it


---

## Results & Analysis

After running benchmarks, results are in `jobs/`:
```bash
jobs/
├── <benchmark-name>-<agent>-<timestamp>/
│   ├── result.json
│   ├── trajectory.json
│   └── <task-name>/
│       ├── result.json
│       ├── trajectory.json
│       └── agent/
```

To analyze results:
```bash
python scripts/analyze_comparison.py jobs/<baseline>-* jobs/<mcp>-*
```

---

## Development

To add a new benchmark:
1. Create `benchmarks/<name>/` with Harbor adapter structure
2. Include README.md documenting purpose and setup
3. Create templates/ with instruction.md, task.toml, Dockerfile, test.sh
4. Create adapter.py with benchmark-specific loading logic
5. Update this README.md with benchmark details

See `~/harbor/adapters/ADAPTER_QUICKREF.md` for adapter development guide.

---

## Key Files

- [AGENTS.md](../AGENTS.md) - Agent definitions and comparison framework
- [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) - System architecture
- [scripts/](../scripts/) - Benchmark execution scripts
- [history/MIGRATION_SUMMARY.md](../history/MIGRATION_SUMMARY.md) - Recent migrations
