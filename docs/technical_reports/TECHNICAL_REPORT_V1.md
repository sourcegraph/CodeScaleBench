# CodeContextBench: A Systematic Evaluation Framework for Assessing the Impact of Enhanced Code Intelligence on AI Coding Agent Performance

**White Paper Technical Report**
**Date:** February 27, 2026

---

## Abstract

CodeContextBench (CCB) is a benchmark suite of 251 software engineering tasks spanning the full Software Development Lifecycle (SDLC) designed to measure whether external code intelligence tools -- specifically Sourcegraph's Model Context Protocol (MCP) tools -- improve AI coding agent performance. The benchmark evaluates agents under two controlled conditions: a baseline with full local source code and no external tools, and an MCP-augmented configuration where source code is unavailable locally and the agent must use remote code intelligence tools (semantic search, symbol resolution, dependency tracing, etc.) to navigate codebases. Across 250 valid paired task evaluations using Claude Haiku 4.5 (1 baseline infrastructure error excluded from 251 registered tasks), the overall MCP effect is +0.047 (95% bootstrap CI: [+0.007, +0.085]) — a small but statistically significant positive. The effect is strongly task-dependent: MCP-unique cross-repository discovery tasks show +0.183, while SDLC tasks with full local code show -0.019 (not significant). This report documents the complete design, construction, information retrieval evaluation pipeline, task curation methodology, ground truth and verifier architecture, and findings from the benchmark's execution.

---

## Table of Contents

1. [Introduction and Motivation](#1-introduction-and-motivation)
2. [Research Questions](#2-research-questions)
3. [Benchmark Architecture](#3-benchmark-architecture)
4. [Task Taxonomy and SDLC Alignment](#4-4-taxonomy-and-sdlc-alignment)
5. [Task Curation Methodology](#5-5-curation-methodology)
6. [Ground Truth and Oracle System](#6-ground-truth-and-oracle-system)
7. [Verification and Scoring Pipeline](#7-verification-and-scoring-pipeline)
8. [Information Retrieval Evaluation Pipeline](#8-information-retrieval-evaluation-pipeline)
9. [Agent and Infrastructure Design](#9-agent-and-infrastructure-design)
10. [Key Decisions](#10-key-decisions)
11. [Preliminary Results](#11-preliminary-results)
12. [Threats to Validity](#12-threats-to-validity)
13. [Future Work](#13-future-work)
14. [Development Process: Building a Benchmark with Claude Code](#14-development-process-building-a-benchmark-with-claude-code)
15. [Appendices](#15-appendices)

---

## 1. Introduction and Motivation

AI coding agents increasingly rely on external context tools -- code search, symbol resolution, dependency tracing -- to navigate large and unfamiliar codebases. The Model Context Protocol (MCP) has emerged as a standard interface for connecting agents to these tools. Yet no benchmark systematically measures whether these tools actually improve agent performance across the full software development lifecycle.

CodeContextBench fills this gap by evaluating the same agent on identical tasks under two conditions: one with only local tools, and one augmented with Sourcegraph MCP tools. The benchmark addresses a fundamental question facing practitioners and tool providers: **does enhanced code intelligence measurably help AI agents complete real-world software engineering tasks?**

### 1.1 The Context Access Gap

Modern enterprise development spans dozens of repositories, millions of lines of code, and complex dependency chains. Local file access -- grep, glob, read -- is often insufficient when the relevant context spans organizational boundaries. MCP tools promise to bridge this gap by providing semantic search, cross-repository symbol resolution, and AI-powered deep search at scale. But this promise has not been systematically validated.

### 1.2 Design Philosophy

CodeContextBench is built on three core principles:

1. **Information Parity**: Both configurations have access to the same information -- the only difference is the access method (local files vs. remote MCP tools). This ensures we measure tool _effectiveness_, not information advantage. For the MCP-augmented configuration, local source code is removed, and we note that it is not typical that for massive and/or sprawled codebases an agent is unlikely to have complete local access to all relevant information and therefore deltas reported here are a lower bound conservative estimate of value.

2. **Dual Evaluation Modes (Direct vs. Artifact)**: Tasks are evaluated through two complementary modes that capture fundamentally different agent capabilities. _Direct_ tasks require the agent to modify code in-place -- the verifier compiles, tests, or diffs the agent's changes against the real codebase. _Artifact_ tasks require the agent to produce a structured `answer.json` containing files, symbols, dependency chains, and narrative explanation -- the verifier scores against a closed-world oracle. Direct mode measures whether MCP helps agents _build and fix_ software; artifact mode measures whether MCP helps agents _discover and reason about_ codebases. This separation prevents conflating code generation ability with information retrieval ability.

3. **SDLC Alignment**: Tasks are organized by development lifecycle phase and use case categories, enabling practitioners to understand MCP impact on specific development activities they perform daily.

4. **Deterministic, Layered Verification**: Every task has a deterministic verifier that produces a reproducible score without LLM involvement. Optional layers (LLM judge, IR metrics, statistical analysis) provide deeper insight but never override the primary score. This ensures benchmark results are reproducible and auditable.

---

## 2. Research Questions

| ID      | Question                                                                                                      | Measurement                                                     |
| ------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **RQ1** | Does access to MCP-based code intelligence improve AI agent task completion rates across SDLC phases?         | Mean reward, pass rate (baseline vs. MCP)                       |
| **RQ2** | On which task types does MCP provide the greatest (or least) benefit?                                         | Per-suite and per-phase delta analysis                          |
| **RQ3** | How does information retrieval quality correlate with task outcomes?                                          | Spearman rank correlation (file recall, MRR, MAP vs. reward)    |
| **RQ4** | What are the efficiency trade-offs of MCP tool usage?                                                         | Token cost, wall-clock time, TTFR (Time to First Relevant file) |
| **RQ5** | Can MCP tools enable agents to complete org-scale discovery tasks that are infeasible with local-only access? | MCP-unique task scores, cross-repo coverage                     |

---

## 3. Benchmark Architecture

### 3.1 High-Level Architecture Diagram

```
                         CodeContextBench Architecture
 ┌─────────────────────────────────────────────────────────────────────┐
 │                        TASK DEFINITIONS                            │
 │  benchmarks/                                                       │
 │  ├── ccb_understand/  (20 tasks)    ├── ccb_mcp_crossrepo_tracing/ │
 │  ├── ccb_design/      (20 tasks)    ├── ccb_mcp_security/          │
 │  ├── ccb_fix/         (25 tasks)    ├── ccb_mcp_incident/          │
 │  ├── ccb_build/       (25 tasks)    ├── ccb_mcp_onboarding/        │
 │  ├── ccb_test/        (20 tasks)    ├── ccb_mcp_compliance/        │
 │  ├── ccb_document/    (20 tasks)    ├── ccb_mcp_crossorg/          │
 │  ├── ccb_secure/      (20 tasks)    ├── ccb_mcp_domain/            │
 │  └── ccb_debug/       (20 tasks)    ├── ccb_mcp_migration/         │
 │       170 SDLC tasks                ├── ccb_mcp_org/               │
 │                                     ├── ccb_mcp_platform/          │
 │                                     └── 81 MCP-unique tasks        │
 └───────────────────┬─────────────────────────────────────────────────┘
                     │
                     ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │                     EXECUTION LAYER (Harbor)                       │
 │                                                                     │
 │  ┌──────────────────┐          ┌──────────────────┐                │
 │  │  Config: Baseline │          │ Config: MCP  │                │
 │  │  ┌──────────────┐ │          │ ┌──────────────┐  │                │
 │  │  │ Full source   │ │          │ │ Truncated src│  │                │
 │  │  │ Local tools   │ │          │ │ 13 SG MCP    │  │                │
 │  │  │ No MCP        │ │          │ │ tools         │  │                │
 │  │  │ Dockerfile    │ │          │ │ Dockerfile.  │  │                │
 │  │  │               │ │          │ │ sg_only      │  │                │
 │  │  └──────────────┘ │          │ └──────────────┘  │                │
 │  └──────────────────┘          └──────────────────┘                │
 │                     ▼                     ▼                         │
 │              result.json           result.json                      │
 │              trajectory.jsonl      trajectory.jsonl                  │
 └───────────────────┬─────────────────────────────────────────────────┘
                     │
                     ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │                   EVALUATION PIPELINE                               │
 │                                                                     │
 │  Layer 1: Deterministic Verifiers  ──→  reward (0.0-1.0)           │
 │  Layer 2: Optional LLM Judge       ──→  judge_score (0.0-1.0)      │
 │  Layer 3: IR Metrics Pipeline       ──→  file_recall, MRR, TTFR    │
 │  Layer 4: Statistical Analysis      ──→  bootstrap CIs, paired Δ   │
 │  Layer 5: Report Generation         ──→  MANIFEST.json, reports     │
 └─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Per-Task Directory Structure

Each task follows a standardized directory layout:

```
benchmarks/<suite>/<task-id>/
├── task.toml                    # Metadata: id, repo, language, difficulty, time_limit
├── instruction.md               # Human-readable task description
├── instruction_mcp.md           # MCP-aware variant (optional)
├── environment/
│   ├── Dockerfile               # Baseline: full source code
│   ├── Dockerfile.sg_only       # MCP: truncated source
│   └── Dockerfile.artifact_only # MCP-unique: minimal image
├── tests/
│   ├── test.sh                  # Harbor-compatible entry point
│   ├── eval.sh                  # Evaluation logic (MCP-unique)
│   ├── oracle_checks.py         # Oracle scoring (MCP-unique)
│   ├── task_spec.json           # Oracle specification
│   └── sgonly_verifier_wrapper.sh # Repo restoration for SG-only
└── solution/
    └── solve.sh                 # Reference solution (where available)
```

### 3.3 Two-Configuration Evaluation Matrix

| Config       | Internal Name           | Source Access   | MCP Tools            | Dockerfile           | Agent Preamble          |
| ------------ | ----------------------- | --------------- | -------------------- | -------------------- | ----------------------- |
| **Baseline** | `baseline-local-direct` | Full local code | None                 | `Dockerfile`         | Evaluation context only |
| **MCP**      | `mcp-remote-direct`     | Truncated/empty | 13 Sourcegraph tools | `Dockerfile.sg_only` | V5 MCP-first preamble   |

For MCP-unique tasks, an additional artifact variant is used:

- `baseline-local-artifact`: Full local code, structured `answer.json` output
- `mcp-remote-artifact`: Truncated source, MCP tools, structured `answer.json` output

---

## 4. Task Taxonomy and SDLC Alignment

### 4.1 SDLC Phase Suites (170 tasks)

Tasks are drawn from established benchmarks and custom-authored challenges, then organized by their primary SDLC phase:

| Suite            | SDLC Phase                | Tasks | Difficulty Range | Languages                            |
| ---------------- | ------------------------- | ----: | ---------------- | ------------------------------------ |
| `ccb_understand` | Requirements & Discovery  |    20 | hard             | C++, Go, Java, Python, TS            |
| `ccb_design`     | Architecture & Design     |    20 | hard--very_hard  | C, C++, Go, Java, Python             |
| `ccb_fix`        | Bug Repair                |    25 | medium--hard     | C++, Go, Java, JS, Python, TS        |
| `ccb_build`      | Feature & Refactoring     |    25 | medium--hard     | C#, C++, Go, Java, JS, Rust, TS      |
| `ccb_test`       | Testing & QA              |    20 | medium--hard     | C, C#, C++, Go, Java, JS, Python, TS |
| `ccb_document`   | Documentation             |    20 | hard             | C++, Go, Java, Python, TS            |
| `ccb_secure`     | Security & Compliance     |    20 | medium--hard     | C, C++, Go, Java, Python             |
| `ccb_debug`      | Debugging & Investigation |    20 | medium--expert   | C, C++, Go, Python, TS               |

### 4.2 MCP-Unique Suites (81 tasks)

These tasks specifically measure org-scale cross-repository discovery capabilities. Each task requires the agent to find information distributed across 3-20 repositories:

| Suite                       | Use Case Category            | Tasks | Description                               |
| --------------------------- | ---------------------------- | ----: | ----------------------------------------- |
| `ccb_mcp_crossrepo_tracing` | A: Dependency Tracing        |     1 | Blast radius analysis, dependency chains  |
| `ccb_mcp_security`          | B: Vulnerability Remediation |    10 | CVE impact, missing auth middleware       |
| `ccb_mcp_migration`         | C: Framework Migration       |     7 | API migrations, breaking changes          |
| `ccb_mcp_incident`          | D: Incident Debugging        |    11 | Error-to-code-path tracing                |
| `ccb_mcp_onboarding`        | E: Onboarding                |    11 | API consumption, tribal knowledge         |
| `ccb_mcp_compliance`        | F: Compliance                |     7 | Standards adherence across repos          |
| `ccb_mcp_crossorg`          | G: Cross-Org Discovery       |     5 | Interface implementations                 |
| `ccb_mcp_domain`            | H: Domain Lineage            |    10 | Config propagation, architecture patterns |
| `ccb_mcp_org`               | I: Organizational Context    |     5 | Agentic discovery                         |
| `ccb_mcp_platform`          | J: Platform Knowledge        |     5 | Service templates, infrastructure         |

### 4.3 Repository and Language Coverage

Tasks span **10 programming languages** across **40+ open-source repositories**:

```
Language Distribution (by task count):
  Python     ████████████████████████  65
  Go         ███████████████████       50
  Java       ██████████████            38
  C++        █████████████             35
  TypeScript ██████████                25
  JavaScript ████████                  18
  C          ████                       8
  Rust       ██                         5
  C#         ██                         4
  Other      █                          3

Repository Scale:
  Large monorepos:    kubernetes/kubernetes, pytorch/pytorch, torvalds/linux
  Mid-size projects:  django/django, grafana/grafana, apache/kafka
  Cross-org polyrepos: Grafana+Loki+Mimir, K8s+etcd+containerd
  Distributed ecosystems: Apache Kafka/Flink/Camel, Envoy/Istio
```

### 4.4 Difficulty Distribution

| Difficulty | Tasks | Percentage | Description                                                |
| ---------- | ----: | ---------- | ---------------------------------------------------------- |
| medium     |   ~30 | 12%        | Dependency installation, straightforward fixes, unit tests |
| hard       |  ~140 | 58%        | Multi-file changes, cross-repo reasoning, runbooks         |
| very_hard  |   ~10 | 4%         | Deep dependency chain analysis, architectural refactoring  |
| expert     |     5 | 2%         | Linux kernel fault localization                            |

---

## 5. Task Curation Methodology

### 5.1 Task Provenance

The 251 tasks in CodeContextBench fall into two broad provenance categories:

**SDLC tasks (170 tasks):** The majority (~158) are fully original tasks authored for CodeContextBench, each grounded in a real repository at a pinned commit and targeting a genuine development scenario (a real bug, a real missing feature, a real documentation gap) identified through analysis of repository issues, PRs, and codebases on GitHub. A smaller number of tasks are adapted from or inspired by existing benchmarks while retaining CCB-specific instructions and verifiers:

- 8 dependency-installation tasks adapted from DIBench patterns
- 5 Linux kernel fault-localization tasks with a custom 10-point rubric from the LinuxFL benchmark
- 6 code-review tasks using synthetic defect injection (null-deref, resource-leak, etc.) from the Qodo Git Code Review benchmark
- 1 task sourced from TheAgentCompany (bustub-hyperloglog-impl-001)

All tasks, regardless of inspiration source, use CCB-authored instructions and CCB-built verifiers running inside the CCB Docker environment.

**MCP-unique tasks (81 tasks):** Derived from a custom **Use Case Registry** (`configs/use_case_registry.json`) for cross-repository code intelligence. Each use case was validated against Sourcegraph's actual search capabilities and curated into a benchmark task with oracle ground truth. These tasks specifically target org-scale scenarios where information is distributed across 3-20 repositories.

### 5.2 GitHub Usage for Task Sourcing

All tasks are grounded in real open-source codebases hosted on GitHub. The task authoring process involved:

1. **Repository and commit selection**: For each task, a specific repository and commit were chosen to provide a realistic development context. Repositories range from large monorepos (kubernetes/kubernetes, torvalds/linux) to mid-size projects (django/django, grafana/grafana) to cross-ecosystem polyrepos (Apache Kafka + Flink + Camel). Commits are pinned to ensure reproducibility.

2. **Scenario identification**: Task scenarios were identified by examining real repository activity -- open issues, merged PRs, documentation gaps, architectural patterns, and known bugs. For example, PyTorch compiler fusion tasks were modeled on real PRs (e.g., PR #167499); code review tasks inject synthetic defects modeled on real-world vulnerability patterns (null-deref, resource-leak, race-condition, injection, etc.).

3. **MCP-unique repo sets**: Cross-repository tasks use curated **repo set fixtures** (`fixtures/repo_sets/*.json`) defining 11 ecosystems (kubernetes-ecosystem, apache-kafka-ecosystem, compiler-toolchain, mozilla-firefox, etc.). Each repo set specifies the repositories, their relationships, and the Sourcegraph mirror names used for MCP access.

4. **Mirror creation for MCP access**: Repositories not natively indexed in Sourcegraph are mirrored to the `sg-evals` GitHub organization at pinned commits, ensuring the MCP tools search the exact version the task targets (see Section 9.5).

### 5.3 MCP Benefit Scoring for Task Selection

Tasks from existing benchmarks were filtered in part using a systematic scoring formula that estimates the expected benefit from code navigation tools:

```
code_nav_score = 0.25 * context_complexity
                  + 0.30 * cross_file_deps
                  + 0.20 * semantic_search_potential
                  + 0.25 * task_category_weight
```

**Component definitions:**

| Component                   | Weight | Description                                    | Scoring Logic                                                                            |
| --------------------------- | ------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `context_complexity`        | 0.25   | Scale of codebase the agent must navigate      | `clamp(context_length / 1M, 0, 1)` with per-task adjustments based on LOC and file count |
| `cross_file_deps`           | 0.30   | Number of files the agent must reason across   | `clamp(files_count / 20)` with higher values for tasks spanning many files               |
| `semantic_search_potential` | 0.20   | Likelihood that semantic search aids discovery | 0.7-0.9 for large repos; task-type heuristics                                            |
| `task_category_weight`      | 0.25   | Inherent MCP affinity of the task category     | architectural_understanding: 1.0, big_code_feature: 0.95, dependency: 0.5                |

**Category affinity values** (from `MCP_CATEGORY_AFFINITY`):

| Category                    | Affinity | Rationale                              |
| --------------------------- | -------- | -------------------------------------- |
| architectural_understanding | 1.00     | Requires broad codebase navigation     |
| big_code_feature            | 0.95     | Large-scale feature implementation     |
| cross_file_refactoring      | 0.90     | Multi-file dependency tracking         |
| find_in_codebase            | 0.85     | Direct search task                     |
| security_audit              | 0.80     | Cross-component vulnerability analysis |
| performance_investigation   | 0.75     | System-wide profiling needs            |
| documentation               | 0.70     | API surface discovery                  |
| bug_investigation           | 0.65     | Root cause tracing                     |
| unit_test                   | 0.60     | Test target identification             |
| dependency                  | 0.50     | Often resolvable locally               |

### 5.4 SDLC Phase Assignment

Each task is assigned to one of 8 SDLC phases based on the primary development activity it targets. The assignment is made at task authoring time using the task's `category` field and the nature of the work involved. For example, a task requiring the agent to trace a dependency chain and write an architecture document maps to "Design"; a task requiring the agent to find and fix a null-pointer dereference maps to "Fix". The `sdlc_phase` field in `selected_benchmark_tasks.json` records this assignment for each task.

---

## 6. Ground Truth and Oracle System

### 6.1 Role of Ground Truth

Ground truth serves two distinct purposes in CodeContextBench, and it is important to distinguish them:

1. **Task scoring (verifiers)**: For MCP-unique artifact tasks, ground truth is used _directly_ in scoring -- `oracle_checks.py` compares the agent's `answer.json` against the oracle to compute file-set F1, symbol recall, chain recall, etc. (see Section 7.4). For SDLC direct tasks, ground truth is embedded in the verifier itself -- the test suite, expected defects, or rubric criteria define what "correct" means, and the verifier scores against those expectations without referencing a separate ground truth registry.

2. **Information retrieval analysis (IR metrics)**: Ground truth file lists are used _post-hoc_ by the IR evaluation pipeline (Section 8) to measure retrieval quality -- did the agent access the files it needed to? This is a diagnostic layer that does not affect task scores. It answers questions like "did the MCP tools help the agent find the right files faster?" by comparing the agent's file-access trace against the known-relevant files.

The ground truth registry (`configs/ground_truth_files.json`) is primarily built for purpose #2. Purpose #1 uses task-local oracle files (`task_spec.json`, `expected_defects.json`, etc.) that are packaged with each task.

### 6.2 Multi-Source Ground Truth Architecture

Ground truth for the IR pipeline is extracted from multiple sources depending on the task type, using a 6-level priority chain:

```
Priority Chain for Ground Truth Discovery:
1. tests/ground_truth.json        ← Explicit ground truth (highest priority)
2. tests/expected_defects.json    ← Injected defect annotations
3. tests/expected_changes.json    ← Expected file modifications
4. solution/solve.sh              ← Reference solution patches
5. instruction.md                 ← Regex extraction from instructions
6. configs/ground_truth_files.json ← Benchmark-wide registry
```

### 6.3 Ground Truth Extraction Strategies

Ground truth extraction uses task-type-specific strategies that match how each task category defines its expected outcomes:

**SDLC tasks (170 tasks)** use a unified extractor (`_gt_sdlc()`) that walks the 6-level priority chain described above. For most tasks, ground truth files come from `ground_truth.json` or are extracted from `instruction.md` via regex patterns matching file path references. Specialized handling exists for specific task patterns:

- **Bug-fix tasks** (ccb_fix): Ground truth extracted from `solution/solve.sh` patches or `expected_changes.json`, identifying which files should be modified
- **Code-review tasks** (ccb_test): `expected_defects.json` provides structured defect annotations (file, line range, defect type)
- **Fault-localization tasks** (ccb_debug): Ground truth file paths extracted from `instruction.md`

**MCP-unique tasks (81 tasks)** use `oracle_answer.json` as the authoritative source, providing structured ground truth with files, symbols, dependency chains, and keywords (see Section 6.5).

### 6.4 Ground Truth Data Model

```python
@dataclass
class TaskGroundTruth:
    task_id: str
    files: list[str]              # Required file paths
    source: str                    # Which extractor produced this
    confidence: str                # "high" | "medium" | "low"
    defect_annotations: list[DefectAnnotation]  # Optional
    output_files: list[str]        # Expected output files
    evidence_files: list[str]      # Supporting evidence files
    gt_type: str                   # "patch" | "oracle" | "instruction"

@dataclass
class DefectAnnotation:
    file: str
    line_start: int
    line_end: int
    defect_type: str  # null-deref | resource-leak | race-condition | ...
```

### 6.5 MCP-Unique Oracle System

MCP-unique tasks use a **closed-world oracle** system with 7 deterministic check functions:

```
Oracle Answer Structure (answer.json):
{
  "files": [                         ← File set match (F1)
    {"repo": "org/name", "path": "path/to/file.go"}
  ],
  "symbols": [                       ← Symbol resolution (Recall)
    {"repo": "org/name", "path": "path/to/file.go", "name": "SymbolName"}
  ],
  "chain": [                         ← Dependency chain (Chain recall)
    {"repo": "org/name", "path": "path/to/file.go", "symbol": "Step1"},
    {"repo": "org/name", "path": "path/to/file.go", "symbol": "Step2"}
  ],
  "text": "Narrative explanation..."  ← Keyword presence + Provenance
}
```

**Oracle Check Functions** (from `oracle_checks.py`):

| Check                       | Metric           | Description                                                                   |
| --------------------------- | ---------------- | ----------------------------------------------------------------------------- |
| `check_file_set_match()`    | F1 score         | Overlap between agent's files and oracle files with 3-pass repo normalization |
| `check_symbol_resolution()` | Recall           | Symbol matching with repo-normalized 2-pass lookup                            |
| `check_dependency_chain()`  | Chain recall     | Order correctness of dependency chain steps                                   |
| `check_provenance()`        | Provenance score | Must-cite paths/repos appearing in narrative text                             |
| `check_keyword_presence()`  | Keyword recall   | Case-insensitive required keyword matching                                    |
| `check_json_schema()`       | Schema validity  | Structural validation of answer JSON (1.0 or 0.0)                             |
| `check_test_ratio()`        | Pass ratio       | Fraction of test commands passing                                             |

**Composite Score Calculation:**

```
composite_score = mean(primary_check_scores)
```

### 6.6 Repository Name Normalization

Oracle evaluation handles the divergence between mirror names and upstream names with 3-pass matching:

```
Pass 1: Exact match     (sg-evals/kafka--0753c489 == sg-evals/kafka--0753c489)
Pass 2: Normalized repo  (sg-evals/kafka--0753c489 → kafka → apache/kafka)
Pass 3: Path-only        (ignore repo entirely, match on file path alone)
```

### 6.7 Oracle Auto-Curation

Oracle answers were auto-curated via Sourcegraph queries and validated with a **fail2pass gate**:

- Gold answer (all oracle items) must score **1.0**
- Empty answer (no items) must score **0.0**

All 81 MCP-unique tasks passed this validation before inclusion.

### 6.8 Oracle Calibration

Beyond the fail2pass gate (Section 6.7), oracle calibration validates that check functions produce meaningful score discrimination on **partial** answers — a subset of oracle items must produce a score strictly between 0.0 and 1.0, confirming the scoring function rewards incremental progress.

Because both configs have **information parity** — baseline receives all repos cloned locally in `/workspace`, while MCP accesses the same repos via Sourcegraph MCP tools — the oracle measures how effectively the agent discovers and assembles cross-repo information, not whether the information is accessible at all. The 12-task starter pack confirmed that baseline agents can and do achieve non-zero scores (mean 0.722) using local search tools alone, while MCP agents achieve higher scores on average (mean 0.884) — see Section 11.1 for full results. MCP-unique tasks are designed to measure tool-assisted _search quality_ across polyrepo codebases, not information access gaps.

---

## 7. Verification and Scoring Pipeline

### 7.1 Overview

Every task produces a single reward score (0.0--1.0) via a deterministic, in-container verifier. Additional analysis layers (LLM judge, IR metrics, statistical tests) provide deeper insight but never override the primary score.

### 7.2 Verifier System Architecture

Harbor uploads each task's `tests/` directory to `/tests/` inside the container and invokes the entry-point script after the agent finishes. The entry point writes a floating-point score to `/logs/verifier/reward.txt`. All verifiers follow the exit-code-first convention: exit 0 if score > 0.0, exit 1 otherwise.

```
 Harbor Container
 ┌─────────────────────────────────────────────────────────┐
 │  Agent writes to /workspace/                            │
 │          │                                              │
 │          ▼                                              │
 │  /tests/test.sh  (SDLC tasks)                          │
 │  /tests/eval.sh  (MCP-unique tasks)                    │
 │          │                                              │
 │          ├── sources shared libraries as needed:        │
 │          │   ├── verifier_lib.sh  (IR metrics helpers)  │
 │          │   ├── answer_json_verifier_lib.sh            │
 │          │   │   (artifact mode extraction)             │
 │          │   └── sgonly_verifier_wrapper.sh             │
 │          │       (repo restoration for MCP)        │
 │          │                                              │
 │          ├── runs task-specific scoring logic            │
 │          │                                              │
 │          ▼                                              │
 │  /logs/verifier/reward.txt   (0.0 -- 1.0)              │
 └─────────────────────────────────────────────────────────┘
```

### 7.3 SDLC Task Verifiers (test.sh)

Each SDLC task has a custom `test.sh` tailored to its evaluation needs. Four major patterns cover the 170 tasks:

**Build/feature tasks** detect agent code changes (via `git diff`, staged changes, new commits, and untracked files), then score a weighted composite:

```
composite = 0.4 × task_quality + 0.3 × file_recall + 0.2 × file_precision + 0.1 × dep_accuracy
```

Where `task_quality` combines compilation success, keyword hits against expected patterns, and multi-file breadth. The shared `verifier_lib.sh` library provides the IR metric computation (precision, recall, F1, dependency-chain accuracy, MRR) used by these verifiers.

**Bug-fix tasks** run the project's own test suite (pytest, `go test`, etc.) against the agent's changes and compute a pass ratio:

```
reward = tests_passed / (tests_passed + tests_failed)
```

A `trap EXIT` guard ensures `reward.txt` is written even on timeout.

**Fault-localization tasks** (e.g., Linux kernel) score against a 10-point rubric applied to the agent's `fault_localization_result.json`: file-level match (4 pts), method-level match (3 pts), required fields present (1 pt), reasoning provided (1 pt), valid confidence score (1 pt).

**Code-review tasks** use a hybrid F1 + fix score. For each expected defect in `expected_defects.json`, the verifier checks whether the agent reported a defect in the same file within a line-proximity window (±50 lines). Fix quality is scored by pattern-matching the agent's changes against expected remediation patterns:

```
reward = 0.5 × detection_F1 + 0.5 × fix_score
```

The verifier strips markdown code fences from agent output and handles nested JSON structures (agents sometimes wrap JSON in `{"review": {"defects": [...]}}` instead of flat `{"defects": [...]}`).

### 7.4 MCP-Unique Task Verifiers (eval.sh + oracle_checks.py)

All 81 MCP-unique tasks use an identical `eval.sh` template that delegates scoring to `oracle_checks.py`:

```bash
# eval.sh (uniform across all MCP-unique tasks)
1. Restore full repo if sg_only mode (source sgonly_verifier_wrapper.sh)
2. Validate /workspace/answer.json exists and is valid JSON
3. Run: python3 oracle_checks.py --answer answer.json --spec task_spec.json
4. Write the composite score to /logs/verifier/reward.txt
```

`oracle_checks.py` is a stdlib-only Python module (no external dependencies) that runs all checks configured in `task_spec.json` and returns the mean of their primary scores. The 3-pass repo-name normalization described in Section 6.6 is implemented here. See Section 6.5 for the check functions and composite scoring formula.

### 7.5 Shared Verifier Libraries

Four shared libraries handle cross-cutting concerns:

| Library                       | Purpose                                                                                                                                   | Used By                          |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| `verifier_lib.sh`             | IR metric computation (precision, recall, F1, MRR, dependency-chain accuracy), solution.md parsing, path normalization                    | Build, design, and feature tasks |
| `answer_json_verifier_lib.sh` | Extracts analysis text and file lists from `answer.json` in artifact mode; applies agent diffs to `/repo_full` for zero-copy verification | Artifact-mode SDLC tasks         |
| `sgonly_verifier_wrapper.sh`  | Restores full source at verify time by cloning mirrors from `/tmp/.sg_only_clone_manifest.json`, then overlays agent changes              | All MCP (sg_only) runs           |
| `oracle_checks.py`            | Deterministic oracle scoring (file F1, symbol recall, chain recall, provenance, keyword recall) with 3-pass repo normalization            | All MCP-unique tasks             |

### 7.6 SG-Only Verifier Wrapper (Clone-at-Verify)

A key design for fair MCP evaluation: during the agent's run, source code is truncated (empty files). At verification time, `sgonly_verifier_wrapper.sh` restores the full codebase:

```
                     Agent Runtime                    Verification Time
                     ─────────────                    ─────────────────
 Dockerfile.sg_only:                    sgonly_verifier_wrapper.sh:
 ┌────────────────┐                    ┌──────────────────────┐
 │ Truncated src  │                    │ Read clone manifest  │
 │ (empty files)  │ ──Agent edits──→   │ Back up agent files  │
 │                │                    │ Clone mirror repos   │
 │ Agent uses MCP │                    │ Re-inject defects    │
 │ to read code   │                    │ Overlay agent changes│
 └────────────────┘                    │ Run original test.sh │
                                       └──────────────────────┘
```

The clone manifest (`/tmp/.sg_only_clone_manifest.json`) is written at Docker build time and specifies which `sg-evals` mirrors to clone and where to place them. This ensures the verifier operates on the same full codebase as the baseline configuration, producing comparable scores.

### 7.7 Scoring Types

| Scoring Type      | Score Range | Task Types                                    | Description                                                                 |
| ----------------- | ----------- | --------------------------------------------- | --------------------------------------------------------------------------- |
| **checklist**     | 0.0--1.0    | Build, design, documentation, security, debug | Weighted sum of discrete checks (compilation, keywords, file breadth, etc.) |
| **test-ratio**    | 0.0--1.0    | Bug-fix tasks                                 | Fraction of project test cases passing                                      |
| **F1-hybrid**     | 0.0--1.0    | Code review                                   | 0.5 × detection_F1 + 0.5 × fix_score                                        |
| **rubric**        | 0.0--1.0    | Fault localization                            | Points-based rubric (e.g., 10-point for Linux kernel)                       |
| **oracle-checks** | 0.0--1.0    | MCP-unique (artifact)                         | Composite mean of file/symbol/chain/keyword checks                          |
| **external**      | 0.0--1.0    | TAC-sourced tasks                             | External evaluator                                                          |

All scoring types produce a single float in [0.0, 1.0] written to `/logs/verifier/reward.txt`. The primary benchmark metric is mean reward across all tasks in a suite.

---

## 8. Information Retrieval Evaluation Pipeline

### 8.1 Pipeline Architecture

The IR evaluation pipeline measures retrieval quality, utilization, and downstream impact in 5 stages:

```
 Agent Traces                    Stage 1-2            Stage 3-4           Stage 5
 ────────────                    ─────────            ─────────           ───────

 trajectory.json   ┐             File-Level           Utilization         Artifact
 claude-code.txt   ├──normalize──→ IR Metrics    ──→   Probes       ──→   Assembly
 result.json       ┘             Chunk-Level          Error Taxonomy

 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    Data Flow                                           │
 │                                                                        │
 │ normalize_retrieval_events.py                                          │
 │   Input:  trajectory.json + claude-code.txt + result.json              │
 │   Output: {task}.retrieval_events.json (schema v1.0)                   │
 │                                                                        │
 │ retrieval_eval_pipeline.py (5 stages)                                  │
 │   Input:  *.retrieval_events.json                                      │
 │   Output: *.retrieval_metrics.json + run_retrieval_summary.json        │
 │                                                                        │
 │ retrieval_impact_analysis.py                                           │
 │   Input:  retrieval metrics + result.json pairs                        │
 │   Output: correlation_analysis.json + matched_comparison.json          │
 └─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Stage 1: File-Level IR Metrics

Computes standard information retrieval metrics by comparing retrieved files against ground truth:

| Metric                 | Description                                   | Formula                                  |
| ---------------------- | --------------------------------------------- | ---------------------------------------- | ---------------- | ---- | --------- | --- |
| **P@K**                | Precision at K (k=1,3,5,10)                   | `                                        | relevant ∩ top_k | / k` |
| **R@K**                | Recall at K                                   | `                                        | relevant ∩ top_k | /    | relevant  | `   |
| **F1@K**               | Harmonic mean of P@K and R@K                  | `2 × P@K × R@K / (P@K + R@K)`            |
| **MRR**                | Mean Reciprocal Rank                          | `1 / rank_of_first_relevant`             |
| **nDCG@K**             | Normalized Discounted Cumulative Gain         | Standard nDCG formula                    |
| **MAP**                | Mean Average Precision                        | Average of P@k at each relevant position |
| **File Recall**        | Fraction of GT files found anywhere           | `                                        | GT ∩ retrieved   | /    | GT        | `   |
| **Context Efficiency** | Fraction of retrieved files that are relevant | `                                        | GT ∩ retrieved   | /    | retrieved | `   |

**Time-to-context metrics:**

- **TTFR**: Time to First Relevant file (seconds)
- **TTFR_tokens**: Tokens consumed before first relevant file
- **Cost_before_first_relevant**: USD spent before first hit

### 8.3 Stage 2: Chunk-Level Relevance

When ground truth includes line-level annotations:

```
chunk_recall = |GT_chunks_whose_file_accessed| / |GT_chunks|
```

Falls back to `file_level_only` when chunk ground truth is unavailable.

### 8.4 Stage 3: Utilization Probes

Measures how effectively the agent uses retrieved information:

| Probe                                          | Description                                 |
| ---------------------------------------------- | ------------------------------------------- |
| `util_read_overlap_with_relevant_files`        | \|files_read ∩ relevant\| / \|relevant\|    |
| `util_write_overlap_with_relevant_files_proxy` | \|files_written ∩ relevant\| / \|relevant\| |
| `util_write_overlap_with_expected_edit_files`  | Stronger write metric (when available)      |
| `util_read_before_write_ratio`                 | Fraction of writes preceded by reads        |

### 8.5 Stage 4: Error Taxonomy and Calibration Slices

Classifies retrieval errors into 5 categories:

| Error Label                | Description                                      |
| -------------------------- | ------------------------------------------------ |
| `irrelevant_retrieval`     | Agent retrieved files not in ground truth        |
| `missed_key_evidence`      | Key ground truth files never retrieved           |
| `wrong_evidence_used`      | Agent used wrong files for reasoning             |
| `unused_correct_retrieval` | Agent retrieved but ignored relevant files       |
| `ambiguity_near_miss`      | Agent found files close to but not exactly in GT |

**Calibration slices**: candidate_set_size (small/medium/large), evidence_type (local/mcp)

### 8.6 Stage 5: Artifact Assembly

- **Per-task**: `{task_name}.retrieval_metrics.json` with all stage outputs
- **Run-level**: `run_retrieval_summary.json` with aggregated statistics (mean/std/median per metric)

### 8.7 Retrieval Event Schema (v1.0)

Each tool call is normalized into a structured event:

```json
{
  "step_index": 5,
  "tool_name": "mcp__sourcegraph__keyword_search",
  "tool_category": "code_search",
  "is_mcp": true,
  "target_files": ["src/main.go", "pkg/handler.go"],
  "hits_ground_truth": true,
  "cumulative_tokens": 15000,
  "elapsed_seconds": 12.5,
  "matched_ground_truth_files": ["src/main.go"]
}
```

**Tool categories** (11 types): file_read, file_search, symbol_navigation, code_search, commit_search, deep_search, file_write, other

### 8.8 Downstream Impact Analysis

**Correlation analysis** (`retrieval_impact_analysis.py`):

- Spearman rank correlation between retrieval metrics (file_recall, MRR, MAP, context_efficiency) and outcomes (reward, cost, runtime, output_tokens)
- Association-only language (no causal claims)
- Requires minimum sample size

**Matched comparison**:

- Pairs baseline vs. MCP configs for the same canonical task
- Computes deltas: mean/median/IQR for reward, cost, time, file_recall, MRR
- Requires ≥3 matched tasks per run

### 8.9 Key Design Principles of the IR Pipeline

1. **Standalone & Non-Ranking**: IR metrics do not modify leaderboard scoring
2. **Graceful Degradation**: Handles missing traces and ground truth with explicit flags (`degraded_reason`)
3. **Fair Comparison**: Both baseline and MCP configs scored equally -- baseline CAN score non-zero for local repos
4. **Three-Pass Matching**: Exact repo → normalized repo → path-only for mirror/upstream name handling
5. **Stdlib Only**: Core modules use only Python stdlib (no external dependencies)
6. **Cost Awareness**: Tracks cache reads ($1/Mtok) separately from output tokens ($5/Mtok)

---

## 9. Agent and Infrastructure Design

### 9.1 Agent Architecture (Claude Baseline Agent)

The primary agent (`agents/claude_baseline_agent.py`, 2,090 lines) is a Harbor-compatible agent that wraps Claude Code for benchmark execution:

```
 ┌─────────────────────────────────────────────────────────────┐
 │                Claude Baseline Agent                        │
 │                                                             │
 │  ┌─────────────────┐    ┌──────────────────────────────┐   │
 │  │ Config Detection │    │ V5 Preamble Template         │   │
 │  │ BASELINE_MCP_TYPE│    │ ┌──────────────────────────┐ │   │
 │  │ ├── none         │    │ │ # Source Code Access     │ │   │
 │  │ ├── sourcegraph  │    │ │ Files are NOT present.   │ │   │
 │  │ ├── sg_full      │────│ │ Use Sourcegraph MCP      │ │   │
 │  │ └── artifact_full│    │ │ tools to read code.      │ │   │
 │  └─────────────────┘    │ │ {repo_scope}             │ │   │
 │                          │ │ {workflow_tail}          │ │   │
 │  ┌─────────────────┐    │ └──────────────────────────┘ │   │
 │  │ Repo Resolution  │    └──────────────────────────────┘   │
 │  │ _get_repo_display│                                       │
 │  │ _get_repo_list   │    ┌──────────────────────────────┐   │
 │  │ Priority:        │    │ System Prompt Assembly       │   │
 │  │ 1. ENV vars      │    │ EVALUATION_CONTEXT +         │   │
 │  │ 2. Docker parse  │    │ MCP-specific guidance +      │   │
 │  │ 3. Fallback      │    │ Repo scoping rules           │   │
 │  └─────────────────┘    └──────────────────────────────┘   │
 └─────────────────────────────────────────────────────────────┘
```

### 9.2 MCP Preamble

The MCP preamble is a block of instructions prepended to the task prompt for MCP runs only. Baseline runs receive the raw task instruction with no preamble. Its purpose is twofold:

1. **Communicate the environment constraint**: Inform the agent that local source files are truncated or absent and that it must use the available Sourcegraph MCP tools to access code.
2. **Provide tool guidance**: Give the agent a mapping of which MCP tools to use for which purposes (e.g., `keyword_search` for exact matches, `nls_search` for conceptual queries, `go_to_definition` / `find_references` for symbol navigation) and a suggested workflow (search → read → edit/answer).

The preamble also performs **repository scoping** — a `{repo_scope}` placeholder is substituted at launch time with the specific `repo:^github.com/ORG/REPO$` filter patterns for the task's target repositories, so the agent searches the correct repos from its first query.

The current preamble (V5) went through 5 design iterations to balance forcing MCP adoption against over-constraining agent behavior (see Section 10.1 for the full iteration history).

### 9.3 MCP Tool Suite

The MCP configuration provides 13 Sourcegraph MCP tools:

| Tool                    | Category    | Purpose                               |
| ----------------------- | ----------- | ------------------------------------- |
| `keyword_search`        | Code Search | Exact keyword matching across repos   |
| `nls_search`            | Code Search | Semantic/natural language code search |
| `deepsearch`            | Deep Search | AI-powered semantic analysis          |
| `deepsearch_read`       | Deep Search | Read Deep Search results              |
| `read_file`             | File Access | Read specific file contents           |
| `list_files`            | File Access | List directory contents               |
| `list_repos`            | Repository  | List available repositories           |
| `go_to_definition`      | Symbol Nav  | Find symbol definitions               |
| `find_references`       | Symbol Nav  | Find symbol usages                    |
| `commit_search`         | History     | Search commit messages                |
| `diff_search`           | History     | Search code changes                   |
| `compare_revisions`     | History     | Compare between commits/branches      |
| `get_contributor_repos` | Repository  | Find repos by contributor             |

### 9.4 Docker Environment Variants

```
 ┌────────────────────────────────────────────────────────────────┐
 │                Three Dockerfile Variants                       │
 │                                                                │
 │  Dockerfile (Baseline)     Dockerfile.sg_only    Dockerfile.   │
 │  ┌────────────────────┐   ┌──────────────────┐  artifact_only │
 │  │ FROM base_image    │   │ FROM base_image  │  ┌────────────┐│
 │  │ CLONE full repo    │   │ CLONE + truncate │  │ FROM ubuntu ││
 │  │ at pinned commit   │   │ all source files │  │ No code     ││
 │  │                    │   │ recommit (no git │  │ .artifact_  ││
 │  │ Full source access │   │ history bypass)  │  │ only_mode   ││
 │  │                    │   │                  │  │ marker file ││
 │  │ Verifier runs      │   │ Clone manifest   │  │             ││
 │  │ against local code │   │ for verifier     │  │ Agent writes││
 │  │                    │   │ restoration      │  │ answer.json ││
 │  └────────────────────┘   └──────────────────┘  └────────────┘│
 └────────────────────────────────────────────────────────────────┘
```

**File extension truncation** (95+ types): `.py`, `.js`, `.ts`, `.go`, `.java`, `.rs`, `.c`, `.cpp`, `.h`, `.yaml`, `.toml`, `.json`, `.xml`, `.md`, and more.

### 9.5 Repository Mirror Strategy

Repos not natively indexed in Sourcegraph are mirrored to the `sg-evals` GitHub organization:

```bash
# Orphan-commit mirror creation
git clone --depth 1 --branch "$tag" "https://github.com/${source_repo}.git"
git checkout --orphan orphan-main
git add -A
git commit -m "Mirror of ${source_repo} at ${tag}"
git push --force origin orphan-main:main
```

**Naming convention**: `{repo_name}--{commit_short_8chars}` (e.g., `kafka--0753c489`)

**Why mirrors are needed**: Sourcegraph Deep Search indexes only HEAD. Mirrors pin HEAD to the exact commit the task targets, ensuring the agent searches the correct version.

**Scale**: 200+ mirrors in the `sg-evals` organization covering all benchmark repos.

### 9.6 Execution Infrastructure

| Component         | Implementation                                 |
| ----------------- | ---------------------------------------------- |
| **Runner**        | Harbor (Docker-based task isolation)           |
| **Agent**         | Claude Code (Claude Haiku 4.5)                  |
| **MCP Endpoint**  | Sourcegraph `.api/mcp/v1`                      |
| **Time Limits**   | 300--1,800 seconds per task                    |
| **Parallelism**   | Up to 8 concurrent tasks with 2s stagger       |
| **Multi-Account** | Round-robin across 2 Max subscription accounts |
| **Token Auth**    | OAuth with 30-minute refresh margin            |
| **Results**       | `runs/staging/` → promote to `runs/official/`  |

---

## 10. Key Decisions

### 10.1 Preamble Design Iterations

The agent preamble -- instructions prepended to each task -- underwent 5 major iterations:

| Version   | Date      | Strategy                         | Outcome                                                                                   |
| --------- | --------- | -------------------------------- | ----------------------------------------------------------------------------------------- |
| **V1/V2** | Early Feb | Minimal MCP mentions             | 0 SG tool calls even with tools available                                                 |
| **V3**    | Feb 7     | "MANDATORY" triple reinforcement | 90%+ adoption but overly prescriptive; caused "MCP death spiral" on broken mirrors        |
| **V4**    | Feb 12    | "Soft guidance" header           | 60% zero-MCP adoption; too permissive                                                     |
| **V5**    | Feb 20    | "Truncation constraint" lead     | Effective: leads with "files not present", forces MCP without mandating specific workflow |

**The "MCP Death Spiral" discovery** (V3 era): When the aggressive V3 preamble mandated MCP usage, agents on tasks with broken mirrors or wrong repo names would waste their entire context window on failing SG queries, scoring 0.0 where baseline scored 1.0. This directly motivated the V5 design.

**The git history bypass bug** (V5 motivation): Five of 9 test tasks used `git show HEAD:filename` to recover full source from git history, completely defeating sg_only truncation. V5 fix: recommit truncated state so `git show HEAD:` returns empty files.

### 10.2 SG_base Dropping Decision (Feb 12)

**Data that informed the decision**:

| Config   | n_tasks | Mean Reward | Key Finding                    |
| -------- | ------- | ----------- | ------------------------------ |
| Baseline | 161     | 0.521       | Reference performance          |
| SG_base  | 161     | 0.478       | Slightly _worse_ than baseline |
| SG_full  | 156     | 0.631       | +0.111 vs baseline             |

**Rationale**: SG_base (keyword+NLS search only, no Deep Search) showed no meaningful improvement over baseline. The value came from the comprehensive MCP configuration. Maintaining 3 configs tripled compute cost without providing discriminative data.

### 10.3 DependEval Benchmark Removal

DependEval (9 tasks for dependency resolution) was removed because:

- Missing `code_content.txt` files
- Empty problem statements
- Wrong ground_truth format
- "Code is inline, not in repos" -- fundamentally incompatible with MCP comparison since there was no external repository to index

### 10.4 Verifier Bug Discoveries and Fixes

Major verifier bugs discovered through QA audit (Feb 6):

| Bug                                 | Impact                                                                  | Fix                            |
| ----------------------------------- | ----------------------------------------------------------------------- | ------------------------------ |
| TAC score extraction silent failure | 3 tasks reported 0 instead of real scores (1.0, 0.667, 0.2)             | Fixed `\|\| echo "0"` fallback |
| CrossRepo wrong path                | All 8 runs crashed: `/task/tests/` instead of `/tests/`                 | Updated paths                  |
| PyTorch `make test` no-op           | 10/12 tasks had broken verifiers: `test/` dir caused GNU make collision | Renamed target                 |
| CodeReview brittle matching         | `"For is null"` vs `"For == null"` penalized correct code               | Relaxed matching               |
| Baseline instruction contamination  | 30/156 instructions had SG refs leaking into baseline                   | Cleaned                        |

---

## 11. Preliminary Results

### 11.1 Data Availability

All 251 registered tasks have both baseline and MCP results. One SDLC task (`openlibrary-solr-boolean-fix-001`) errored on the baseline side due to an infrastructure failure (agent never executed), leaving **250 valid paired evaluations**: **169 SDLC** tasks across 8 suites and **81 MCP-unique** tasks across 11 suites. All results use the Claude Haiku 4.5 model. The SDLC tasks use `baseline-local-direct` (full source, no MCP) versus `mcp-remote-direct` (truncated source, Sourcegraph MCP enabled). MCP-unique tasks use the corresponding artifact or direct config variant depending on verifier requirements. All confidence intervals reported below use the percentile bootstrap method (10,000 resamples, seed=42) on paired deltas (see Appendix A).

### 11.2 SDLC Suite Results (Paired Comparison)

Paired baseline vs. MCP results across all 8 SDLC suites (169 valid paired tasks):

| Suite | n | Baseline Mean | MCP Mean | Delta | 95% Bootstrap CI |
|-------|---|--------------|----------|-------|--------|
| understand | 20 | 0.660 | 0.851 | **+0.190** | [+0.043, +0.361] |
| document | 20 | 0.847 | 0.895 | **+0.048** | [+0.015, +0.088] |
| test | 20 | 0.480 | 0.480 | +0.000 | [-0.098, +0.104] |
| secure | 20 | 0.669 | 0.659 | -0.010 | [-0.096, +0.091] |
| fix | 24 | 0.499 | 0.484 | -0.015 | [-0.092, +0.051] |
| design | 20 | 0.753 | 0.718 | -0.036 | [-0.157, +0.086] |
| build | 25 | 0.494 | 0.372 | **-0.121** | [-0.288, +0.025] |
| debug | 20 | 0.670 | 0.487 | **-0.183** | [-0.301, -0.067] |

**SDLC total**: Baseline mean 0.627 (n=169), MCP mean 0.608 (n=169), delta **-0.019** (95% CI: [-0.064, +0.025]). The CI spans zero, indicating no statistically significant MCP effect on SDLC tasks with full local source code.

MCP-unique tasks (81 paired, cross-repository discovery):

| Suite | n | Baseline Mean | MCP Mean | Delta | 95% Bootstrap CI |
|-------|---|--------------|----------|-------|--------|
| security | 10 | 0.341 | 0.782 | **+0.440** | [+0.256, +0.636] |
| onboarding | 11 | 0.365 | 0.702 | **+0.337** | [+0.102, +0.598] |
| org | 5 | 0.443 | 0.640 | **+0.197** | [+0.046, +0.382] |
| incident | 11 | 0.545 | 0.722 | **+0.177** | [-0.019, +0.390] |
| domain | 10 | 0.442 | 0.606 | **+0.163** | [+0.017, +0.333] |
| crossorg | 5 | 0.457 | 0.611 | +0.154 | [-0.039, +0.369] |
| crossrepo_tracing | 9 | 0.618 | 0.707 | +0.089 | [-0.011, +0.194] |
| compliance | 7 | 0.626 | 0.709 | +0.082 | [-0.154, +0.290] |
| migration | 7 | 0.815 | 0.866 | +0.051 | [-0.011, +0.144] |
| platform | 5 | 0.726 | 0.678 | -0.049 | [-0.133, +0.018] |
| crossrepo | 1 | 0.867 | 0.767 | -0.100 | — |

**MCP-unique total**: Baseline mean 0.525 (n=81), MCP mean 0.708 (n=81), delta **+0.183** (95% CI: [+0.116, +0.255]). MCP wins on 47 of 81 tasks.

**Overall**: Baseline mean 0.594 (n=250), MCP mean 0.640 (n=250), delta **+0.047** (95% CI: [+0.007, +0.085]). The overall confidence interval excludes zero, indicating a statistically significant positive MCP effect across the full benchmark.

The results show a clear bifurcation by task category. For **SDLC tasks** where the agent already has full local source code, MCP provides marginal or negative value (SDLC delta -0.019, CI spans zero). The strongest SDLC gains are on retrieval-heavy tasks: **understand** (+0.190, CI excludes zero) and **document** (+0.048, CI excludes zero). The clearest SDLC negative is **debug** (-0.183, CI excludes zero), where MCP adds overhead without compensating retrieval benefit. **Build** (-0.121) also shows a meaningful negative, though the CI narrowly includes zero. For **MCP-unique tasks** requiring cross-repository discovery across 3-20 repos, MCP provides substantial value (+0.183, CI excludes zero), with the strongest effects on **security** (+0.440), **onboarding** (+0.337), and **org** (+0.197) tasks — all with CIs excluding zero. **Domain** (+0.163) also shows a significant positive effect under bootstrap.

### 11.3 Reward by Language

Baseline reward varies significantly by primary language:

| Language | n | Mean Reward | Pass Rate |
|----------|---|-------------|-----------|
| C | 10 | 0.801 | 100.0% |
| Go | 71 | 0.670 | 93.0% |
| TypeScript | 6 | 0.597 | 83.3% |
| C++ | 21 | 0.596 | 71.4% |
| Python | 36 | 0.590 | 83.3% |
| JavaScript | 6 | 0.592 | 66.7% |
| Java | 18 | 0.568 | 83.3% |
| Rust | 4 | 0.500 | 50.0% |
| C# | 3 | 0.183 | 33.3% |

C tasks have the highest mean reward (0.801), driven by the Linux kernel fault localization tasks where the agent performs well with local grep-based navigation. Go tasks dominate the sample (71 tasks, primarily Kubernetes ecosystem) with the highest pass rate at 93.0%. C++ and Rust show lower performance, reflecting the complexity of build systems and type-level reasoning in those languages. C# tasks have the lowest performance (0.183 mean), suggesting potential environment issues rather than fundamental language difficulty.

### 11.4 Reward by Difficulty

| Difficulty | n | Baseline Mean | Pass Rate |
|-----------|---|--------------|-----------|
| Medium | 26 | 0.592 | 69.2% |
| Hard | 145 | 0.628 | 86.9% |
| Expert | 5 | 0.800 | 100.0% |

The counterintuitive result that "hard" tasks outperform "medium" tasks reflects that difficulty ratings were assigned based on expected human effort, not agent capability. Difficulty is a task-authoring metadata field (`task.toml` / selection registry `difficulty`) set from the anticipated human effort and coordination complexity of the scenario, rather than calibrated to current model behavior. Expert tasks (all Linux kernel fault localization) score highest because they are well-structured pattern-matching problems that agents handle effectively despite the large codebase scale.

### 11.5 Reward by Codebase Size

This analysis uses the size proxies in `selected_benchmark_tasks.json` (`context_length`, `files_count`) and reports the paired subset of selected SDLC tasks where those fields are available (**n=109** of 170 paired SDLC tasks).

| Context Length | n | Baseline Mean | MCP Mean | Delta | Baseline Pass | MCP Pass |
|---------------|---|--------------|----------|-------|---------------|----------|
| 10K--100K tokens | 5 | 0.800 | 0.400 | -0.400 | 80.0% | 40.0% |
| 100K--1M tokens | 104 | 0.650 | 0.682 | +0.032 | 87.5% | 88.5% |

| Files Count | n | Baseline Mean | MCP Mean | Delta | Baseline Pass | MCP Pass |
|------------|---|--------------|----------|-------|---------------|----------|
| <10 files | 9 | 0.157 | 0.211 | +0.054 | 44.4% | 22.2% |
| 10--100 files | 100 | 0.702 | 0.710 | +0.008 | 91.0% | 92.0% |

The strongest pattern in this paired slice is by `context_length`: the larger proxy bucket (100K--1M tokens) is slightly MCP-positive (+0.032), while the tiny 10K--100K bucket (n=5) is MCP-negative. The `files_count` buckets are less informative because the <10-file subset is very small and mixes low reward with low pass rates under both configs.

### 11.6 Information Retrieval Metrics

The IR evaluation pipeline (Section 8) produces file-level recall, MRR, MAP, nDCG, context efficiency, and utilization probes for tasks with ground truth file sets. Results from the full pipeline run (n=594 computable tasks out of 1,005 event files):

**Aggregate File-Level IR Metrics:**

| Metric | Mean | Median | Std | n |
|--------|------|--------|-----|---|
| File Recall | 0.375 | 0.111 | 0.424 | 594 |
| MRR | 0.347 | 0.007 | 0.443 | 594 |
| MAP | 0.232 | 0.008 | 0.340 | 594 |
| Context Efficiency | 0.190 | 0.013 | 0.280 | 594 |
| Precision@1 | 0.298 | 0.000 | 0.458 | 594 |
| Recall@5 | 0.223 | 0.000 | 0.345 | 594 |
| nDCG@10 | 0.275 | 0.000 | 0.371 | 594 |

**High-Confidence Subset** (medium/high-confidence ground truth, n=26):

| Metric | Mean | Median |
|--------|------|--------|
| File Recall | 0.494 | 0.590 |
| MRR | 0.482 | 0.417 |
| MAP | 0.431 | 0.366 |
| Context Efficiency | 0.432 | 0.287 |
| TTFR | 24.9s | 11.1s |

**Utilization Probes** (n=594):

| Probe | Mean | Median |
|-------|------|--------|
| Read Overlap with Relevant Files | 0.337 | 0.093 |
| Write Overlap with Relevant Files | 0.056 | 0.000 |
| Read-Before-Write Ratio | 0.195 | 0.000 |

**Error Taxonomy** (n=594):

| Error Type | Mean Count | Median |
|------------|-----------|--------|
| Irrelevant Retrieval | 39.7 | 7.0 |
| Missed Key Evidence | 5.8 | 3.0 |
| Wrong Evidence Used | 2.2 | 1.0 |
| Unused Correct Retrieval | 2.2 | 0.0 |
| Ambiguity Near Miss | 17.2 | 0.0 |

**Retrieval-Outcome Correlation:** Spearman rho = 0.078 (p=0.737, n=26 high-confidence tasks), indicating negligible correlation between retrieval quality (MRR) and task outcome (reward) in the current sample. The wide median-mean gaps across all IR metrics reflect a bimodal distribution: agents either find the right files early (high MRR) or miss them entirely (MRR=0). The dominant retrieval strategy is file reads (364 tasks), followed by code search (115 tasks), with MCP-based retrieval accounting for 229 of 594 evidence traces.

### 11.7 MCP Tool Usage Patterns

Analysis of tool call patterns across 213 MCP task runs:

**Overall tool usage:**
- Mean total tool calls per task: **36.8** (21.5 MCP + 15.3 local)
- Mean MCP ratio: **0.670** (67% of tool calls use MCP tools)
- Zero-MCP tasks (agent never called MCP): **7/213 (3.3%)**
- Deep Search usage: **near zero** (0.0 mean calls per task)

**Search strategy distribution:**
- Keyword-only: **118 tasks (55%)**
- Mixed (keyword + NLS): **61 tasks (29%)**
- NLS-focused: **3 tasks (1%)**
- No search: **31 tasks (15%)**

**MCP tool usage by suite:**

| Suite | n | Mean MCP Calls | Mean Local Calls | MCP Ratio | Keyword | NLS |
|-------|---|---------------|-----------------|-----------|---------|-----|
| build | 25 | 22.2 | 26.2 | 0.516 | 4.9 | 0.5 |
| debug | 20 | 21.1 | 20.2 | 0.602 | 9.5 | 0.5 |
| design | 20 | 26.1 | 10.6 | 0.782 | 6.5 | 0.8 |
| document | 20 | 23.8 | 4.8 | 0.839 | 4.3 | 0.4 |
| fix | 25 | 20.1 | 39.8 | 0.350 | 5.3 | 0.2 |
| secure | 26 | 22.7 | 16.5 | 0.662 | 6.8 | 0.5 |
| test | 20 | 10.9 | 13.8 | 0.532 | 2.6 | 0.8 |
| understand | 21 | 25.7 | 8.6 | 0.718 | 6.9 | 0.1 |
| mcp_unique | 37 | 20.7 | 1.6 | 0.918 | 9.2 | 1.0 |

The **fix** suite has the lowest MCP ratio (0.350) and highest local call count (39.8), reflecting that bug-fixing tasks require extensive local code editing after initial search. **Document** and **mcp_unique** suites have the highest MCP ratios (0.839 and 0.918 respectively), as these tasks are primarily about information retrieval rather than code modification. The near-total absence of Deep Search calls across all suites confirms that agents default to keyword search and rarely invoke the more expensive semantic analysis tools without explicit preamble guidance. Note: MCP tool usage statistics are drawn from the subset of MCP runs with extractable transcripts (n=213) and may not cover all 250 valid paired tasks.

**Reward--MCP correlation:** Spearman rho between MCP ratio and reward is **+0.293** in the analyzed paired slice, indicating a weak positive correlation — higher MCP tool usage is modestly associated with better outcomes, but the relationship is not strong enough to imply causation.

### 11.8 Cost Analysis

At Haiku pricing ($1/Mtok input, $5/Mtok output):

**Per-suite cost (baseline):**

| Suite | n | Mean Input Tokens | Mean Output Tokens | Est. Cost/Task |
|-------|---|------------------|-------------------|---------------|
| build | 19 | 5,940,659 | 722 | $5.94 |
| debug | 20 | 3,866,034 | 186 | $3.87 |
| design | 13 | 2,045,816 | 213 | $2.05 |
| document | 14 | 1,533,600 | 81 | $1.53 |
| fix | 20 | 8,321,921 | 400 | $8.32 |
| secure | 37 | 3,200,342 | 367 | $3.20 |
| test | 17 | 3,928,643 | 543 | $3.93 |
| understand | 37 | 1,916,541 | 262 | $1.92 |
| mcp_unique | 12 | 1,402,706 | 104 | $1.40 |

**Aggregate cost comparison:**

| Config | n | Mean Cost/Task | Total Cost |
|--------|---|---------------|-----------|
| Baseline | 234 | $0.75 | $175.68 |
| MCP | 206 | $0.47 | $97.01 |

MCP runs cost **37% less** on average ($0.47 vs $0.75 per task). This is driven by the truncated-source environment: with less local code to read, the agent processes fewer input tokens. The **fix** suite is the most expensive ($8.32/task baseline) due to large codebases and extensive multi-file editing. The **mcp_unique** suite is cheapest ($1.40/task) because artifact-mode tasks produce a short JSON answer rather than extensive code changes.

### 11.9 Correlation Analysis

| Correlation (Spearman rho) | Value | n | Interpretation |
|---------------------------|-------|---|---------------|
| Output tokens vs. reward | -0.187 | 193 | Weak negative: more output does not mean better results |
| Elapsed time vs. reward | -0.139 | 211 | Weak negative: longer runs slightly associated with lower reward |
| MCP ratio vs. reward | +0.293 | 206 | Weak positive: more MCP usage modestly associated with better outcomes |

The negative correlation between output tokens and reward (-0.187) suggests that agents generating more code are not necessarily producing better solutions — verbose output may indicate the agent is struggling. The weak MCP-reward correlation (+0.293) implies MCP tools are helpful but not deterministic: the agent's ability to formulate effective queries and interpret results matters more than simply using the tools.

---

## 12. Threats to Validity

### 12.1 Internal Validity

| Threat                        | Mitigation                                                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Agent non-determinism**     | Paired execution (both configs run simultaneously per task); multi-trial evaluation with bootstrap CIs planned |
| **Verifier limitations**      | Multiple verifier types per task category; optional LLM judge layer; QA audit process (6 dimensions)           |
| **Instruction contamination** | Automated checking for MCP/Sourcegraph references in baseline instructions                                     |
| **Infrastructure confounds**  | Error fingerprinting (12 patterns) separates infra failures from task failures                                 |
| **Preamble effects**          | V5 preamble isolated: leads with truncation constraint, avoids prescriptive workflow                           |

### 12.2 External Validity

| Threat                  | Mitigation                                                                                    |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| **Single agent**        | Framework supports 6 agent harnesses (Claude Code, Codex, Cursor, Gemini, Copilot, OpenHands) |
| **Single MCP provider** | MCP protocol is standardized; framework can accommodate other providers                       |
| **Task selection bias** | Transparent MCP benefit scoring; systematic selection criteria documented                     |
| **Repository coverage** | 40+ repos across 10 languages, including enterprise-scale monorepos                           |

### 12.3 Construct Validity

| Threat                                   | Discussion                                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Truncated source vs. real enterprise** | Truncation simulates the MCP use case but doesn't perfectly model partial local context     |
| **Time limits**                          | Fixed limits may disadvantage MCP when remote API latency adds overhead                     |
| **Oracle completeness**                  | Closed-world oracles may miss valid alternative solutions                                   |
| **Scoring normalization**                | Different verifier types (test-ratio, checklist, similarity) may not be directly comparable |
| **Single-trial CIs**                     | Bootstrap CIs capture cross-task variability but not within-task variance; multi-trial data would enable two-level resampling |

---

## 13. Future Work

### 13.1 Deep Search Forcing for Targeted Scenarios

Current results show Deep Search was rarely invoked organically (1/129 SG_full tasks in early runs). Future work will introduce task variants that explicitly require Deep Search synthesis — particularly for incident debugging and cross-org discovery tasks where multi-step reasoning across repos should benefit from AI-powered semantic analysis. This includes designing preamble variants that steer agents toward Deep Search for appropriate task types.

### 13.2 SCIP-Indexed Codebase Comparisons

The initial configuration space included a SCIP (Source Code Intelligence Protocol) config that was dropped because only Kubernetes had SCIP indexing at the time. As SCIP coverage expands across more repositories, a natural extension is comparing MCP tool effectiveness on SCIP-indexed codebases — where `go_to_definition` and `find_references` return compiler-accurate results — against the current text-search-based navigation. This would isolate the value of precise code intelligence from broader search capabilities.

### 13.3 Alternative Context Retrieval Providers

The benchmark currently evaluates a single MCP provider (Sourcegraph). The MCP protocol is standardized, making it straightforward to evaluate alternative context retrieval solutions such as the GitHub MCP server. Comparing providers on the same task set would reveal whether retrieval quality differences across providers translate to measurable agent performance differences.

### 13.4 Multi-Harness Evaluation

All current results use Claude Code as the sole agent harness. The framework already supports 6 harness configurations (Claude Code, Codex, Cursor, Gemini, Copilot, OpenHands). Running the full benchmark across multiple harnesses would separate MCP tool effectiveness from agent-specific strengths, answering whether the MCP benefit generalizes across different AI coding tools or is specific to Claude Code's tool-use patterns.

---

## 14. Development Process: Building a Benchmark with Claude Code

### 14.1 Meta-Recursive Development

CodeContextBench was itself primarily developed using Claude Code, creating a meta-recursive situation: an AI coding agent building a benchmark to evaluate AI coding agents' use of code intelligence tools. This section documents the development process for both methodological transparency and as a case study in AI-assisted benchmark construction.

### 14.2 Development Timeline

```
 Jan 30 ─── Feb 3 ─── Feb 6 ─── Feb 10 ─── Feb 15 ─── Feb 20 ─── Feb 25 ─── Feb 26
    │          │         │          │           │           │          │          │
    ▼          ▼         ▼          ▼           ▼           ▼          ▼          ▼
  Paper     Task      QA Audit   Trace      Enterprise  V5 Preamble  Oracle    Fix suite
  draft +   selection  (28       audit,     expansion,  sg_only      curation  expanded
  initial   pipeline,  issues),  SG_base    governance  Dockerfile   complete  (22→25),
  PRD       SDLC       verifier  dropped,   simulation  redesign     for 73    verifier
            taxonomy,  bugs,     Opus 4.6                             MCP tasks bug fix,
            5→3 cfg    mirrors   reruns                                         IR refresh
```

### 14.3 Scale of Claude Code Usage

The development produced **590+ conversation sessions** (JSONL transcripts) spanning January 30 -- February 26, 2026. Claude Code was used to:

- **Design and implement** the task selection algorithm and MCP scoring formula
- **Generate** all 255 `Dockerfile.sg_only` variants and 85 `Dockerfile.artifact_only` files
- **Build** the IR evaluation pipeline (5 stages, ~3,500 lines of Python)
- **Create** the oracle evaluation system (7 check functions, 3-pass repo normalization)
- **Develop** the agent preamble through 5 iterations (V1→V5)
- **Implement** the clone-at-verify pattern for fair MCP evaluation
- **Author** infrastructure scripts (mirror creation, token management, parallel execution)
- **Debug** critical issues (verifier bugs, git history bypass, MCP death spiral)
- **Produce** analysis reports and statistical evaluation code

### 14.4 Key Workflow Pattern

The development followed a consistent pattern:

1. **User provides high-level intent** → "I want SDLC-aligned task taxonomy"
2. **Claude Code explores codebase** → reads existing tasks, benchmarks, documentation
3. **Claude Code generates PRD** → structured user stories with acceptance criteria
4. **Implementation via autonomous sessions** → Ralph agent system executes PRDs
5. **User reviews and iterates** → identifies gaps, requests changes
6. **QA and validation** → automated checks + manual audit

### 14.5 Decisions Made Through Claude Code Dialogue

Major architectural decisions emerged through iterative dialogue:

1. **SDLC taxonomy** (Feb 1): User requested "more systematic approach to selecting benchmark tasks." Claude Code analyzed 200+ existing tasks and proposed the 8-phase SDLC mapping.

2. **MCP scoring formula** (Feb 1): The 4-component weighted scoring formula was designed collaboratively, with Claude Code proposing the component weights based on analysis of task metadata.

3. **SG_base dropping** (Feb 12): Claude Code analyzed run data showing SG_base offered no improvement over baseline, and recommended consolidation to 2 configs.

4. **V5 preamble design** (Feb 20): After discovering the git history bypass bug, Claude Code designed the "truncation constraint" approach that leads with "files not present."

5. **Oracle auto-curation** (Feb 24): Claude Code designed the Sourcegraph-query-based oracle curation pipeline and validated all 81 MCP-unique tasks.

### 14.6 Lessons Learned

1. **AI is effective at benchmark infrastructure**: Generating Dockerfiles, writing evaluation scripts, and building metrics pipelines are well-suited to AI-assisted development.

2. **Domain expertise remains critical**: The SDLC taxonomy, scoring methodology, and validity threat analysis required human judgment that couldn't be fully automated.

3. **Iterative QA is essential**: The Feb 6 QA audit found 28 issues (9 critical) in infrastructure that was largely AI-generated. Systematic validation caught bugs that individual reviews missed.

4. **Preamble engineering is non-trivial**: Five iterations were needed to find the right balance between forcing MCP usage and avoiding prescriptive constraints.

---

## 15. Appendices

### Appendix A: Statistical Methods

| Method             | Purpose                                        | Implementation                      |
| ------------------ | ---------------------------------------------- | ----------------------------------- |
| **Welch's t-test** | Unequal-variance comparison (baseline vs. MCP) | `statistics.py:welchs_t_test()`     |
| **Cohen's d**      | Effect size with 95% CI                        | `statistics.py:cohens_d()`          |
| **McNemar's test** | Paired nominal outcomes (pass/fail per task)   | `statistics.py:mcnemar_test()`      |
| **Bootstrap CI**   | Non-parametric confidence intervals            | Percentile method, 10,000 resamples |
| **Spearman rank**  | IR metric → reward correlation                 | `retrieval_impact_analysis.py`      |

**Bootstrap CI methodology**: All confidence intervals reported in Section 11 use the percentile bootstrap method on paired deltas. For each task pair, the delta is computed as `reward_mcp - reward_baseline`. The vector of deltas is resampled with replacement 10,000 times (seed=42 for reproducibility), the mean is computed for each resample, and the 2.5th and 97.5th percentiles of the bootstrap distribution define the 95% CI bounds. This non-parametric approach makes no normality assumption, which is appropriate for bounded [0, 1] reward data that often exhibits bimodal distributions. Tasks with infrastructure errors (agent never executed) are excluded from paired analysis. The computation is implemented in `scripts/compute_bootstrap_cis.py` and the core bootstrap function in `scripts/ccb_metrics/statistics.py:bootstrap_ci()`.

### Appendix B: Task ID Naming Conventions

| Suite Type    | Pattern                       | Example                         |
| ------------- | ----------------------------- | ------------------------------- |
| SDLC          | `{repo}-{desc}-{phase}-{NNN}` | `kubernetes-scheduler-arch-001` |
| MCP-unique    | `ccx-{family}-{NNN}`          | `ccx-dep-trace-001`             |
| SWE-bench Pro | `{org}__{repo}-{issue}`       | `django__django-16820`          |

### Appendix C: MCP-Unique Task ID Registry

| ID Range | Use Case Category                     | Repo Sets                                |
| -------- | ------------------------------------- | ---------------------------------------- |
| 001-020  | A-F (core categories)                 | kubernetes, kafka, envoy, grafana        |
| 101-112  | Compiler toolchain + Mozilla Firefox  | llvm, gcc, firefox                       |
| 121-132  | Firefox, GCC, OpenJDK, Rust           | firefox, gcc, jdk, rust                  |
| 133-141  | Chromium, AOSP, LibreOffice, ArangoDB | chromium, android, libreoffice, arangodb |

### Appendix D: Complete Scoring Type Reference

| Verifier      | Score Type    | Formula                                                                     | Used By                   |
| ------------- | ------------- | --------------------------------------------------------------------------- | ------------------------- |
| SWE-bench Pro | test-ratio    | `pass_count / total_tests`                                                  | Bug fix tasks             |
| LargeRepo     | checklist     | `0.3×keyword + 0.2×files + 0.2×tests + 0.3×unit`                            | Large codebase tasks      |
| DocGen        | checklist     | Weighted keyword checks                                                     | Documentation tasks       |
| CrossRepo     | similarity    | `0.4×file_coverage + 0.6×pattern_score`                                     | Cross-repo tasks          |
| CodeReview    | F1-hybrid     | `0.5×detection_F1 + 0.5×fix_score`                                          | Code review tasks         |
| LinuxFLBench  | checklist     | 10-point rubric (file 4 + method 3 + reasoning 1 + confidence 1 + fields 1) | Kernel fault localization |
| Oracle        | oracle-checks | `mean(check_scores)`                                                        | MCP-unique tasks          |

### Appendix E: QA Audit Framework (6 Dimensions)

| Dimension                               | Focus                                         | Example Finding                           |
| --------------------------------------- | --------------------------------------------- | ----------------------------------------- |
| **1. Instruction Contamination**        | MCP/SG refs in baseline instructions          | 30/156 instructions had SG refs (cleaned) |
| **2. Reproducibility**                  | Pinned images, exact commits, no network deps | LargeRepo had unpinned clones (fixed)     |
| **3. Verifier Correctness**             | Tests that always pass/fail                   | PyTorch `make test` was a no-op (fixed)   |
| **4. Ghost & False-Positive Detection** | 0-token results, duplicate runs               | Ghost runs from Harbor scaffolding        |
| **5. Error Misclassification**          | Infra errors counted as task inability        | Token refresh failures misclassified      |
| **6. Tool Effectiveness**               | MCP adoption rates, Deep Search compliance    | V3: 90% adoption but over-constrained     |

### Appendix F: Repository Health Checks

Pre-commit validation via `scripts/repo_health.py`:

- CLAUDE.md consistency between root and local guides
- Documentation link integrity
- Script index accuracy
- Task.toml ↔ selected_benchmark_tasks.json metadata sync
- Dockerfile variant completeness

### Appendix G: Error Fingerprint Patterns

| Pattern                    | Description                       | Auto-Retry    |
| -------------------------- | --------------------------------- | ------------- |
| `token_refresh_403`        | OAuth token refresh failure       | Yes           |
| `api_500`                  | API 500 server error              | Yes           |
| `api_rate_limit`           | Rate limit / overloaded           | Yes (backoff) |
| `context_window_exceeded`  | Context window exhausted          | No            |
| `timeout`                  | Task timeout                      | No            |
| `mcp_connection`           | MCP server connection failure     | Yes           |
| `verifier_parse_error`     | Verifier output parse error       | No            |
| `deep_search_polling_only` | Deep Search polling-only response | Yes (retry)   |

---

## Glossary

| Term                | Definition                                                                           |
| ------------------- | ------------------------------------------------------------------------------------ |
| **CCB**             | CodeContextBench                                                                     |
| **Harbor**          | Docker-based task isolation runner                                                   |
| **MCP**             | Model Context Protocol -- standard interface for connecting agents to external tools |
| **SDLC**            | Software Development Lifecycle                                                       |
| **SG**              | Sourcegraph                                                                          |
| **MRR**             | Mean Reciprocal Rank                                                                 |
| **nDCG**            | Normalized Discounted Cumulative Gain                                                |
| **MAP**             | Mean Average Precision                                                               |
| **TTFR**            | Time to First Relevant file                                                          |
| **Oracle**          | Exhaustive ground truth specification for MCP-unique tasks                           |
| **sg-evals**        | GitHub organization hosting version-pinned repository mirrors                        |
| **Preamble**        | Instructions prepended to task description for MCP-augmented agents                  |
| **Clone-at-verify** | Pattern where full repo is cloned at verification time (not during agent execution)  |

---
