# CodeScaleBench: A Systematic Evaluation Framework for Assessing the Impact of Enhanced Code Intelligence on AI Coding Agent Performance

**White Paper Technical Report -- V2**
**Date:** March 3, 2026
**Revision:** V2 (supersedes February 27 V1 report)

---

## Abstract

CodeScaleBench (CSB) is a benchmark suite of **370 software engineering tasks** spanning the full Software Development Lifecycle (SDLC), designed to measure whether external code intelligence tools -- specifically Sourcegraph's Model Context Protocol (MCP) tools -- improve AI coding agent performance. The benchmark evaluates agents under two controlled conditions: a baseline with full local source code and no external tools, and an MCP-augmented configuration where source code is unavailable locally and the agent must use remote code intelligence tools (semantic search, symbol resolution, dependency tracing, etc.) to navigate codebases. In the refreshed analysis snapshot used in this report update (generated March 3, 2026 from `runs/analysis`), there are **1,281 valid scored rows**, **1,822 total historical rows**, and **370 paired baseline/MCP tasks** after averaging multiple runs per task/config. The overall paired reward delta is **+0.0349** (MCP minus baseline), with **+0.0363** on SDLC and **+0.0339** on Org. Retrieval evaluation on the same snapshot yields **799** event files, **311** computable tasks, and aggregate file-level metrics of **0.4598 file recall** and **0.3644 MRR**. This report documents the benchmark design, construction, retrieval evaluation pipeline, verifier architecture, and current findings.

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
11. [Results](#11-results)
12. [Threats to Validity](#12-threats-to-validity)
13. [Future Work](#13-future-work)
14. [Development Process: Building a Benchmark with Claude Code](#14-development-process-building-a-benchmark-with-claude-code)
15. [Appendices](#15-appendices)

---

## 1. Introduction and Motivation

AI coding agents increasingly rely on external context tools -- code search, symbol resolution, dependency tracing -- to navigate large and unfamiliar codebases. The Model Context Protocol (MCP) has emerged as a standard interface for connecting agents to these tools. Yet no benchmark systematically measures whether these tools actually improve agent performance across the full software development lifecycle.

CodeScaleBench fills this gap by evaluating the same agent on identical tasks under two conditions: one with only local tools, and one augmented with Sourcegraph MCP tools. The benchmark addresses a fundamental question facing practitioners and tool providers: **does enhanced code intelligence measurably help AI agents complete real-world software engineering tasks?**

### 1.1 The Context Access Gap

Modern enterprise development spans dozens of repositories, millions of lines of code, and complex dependency chains. Local file access -- grep, glob, read -- is often insufficient when the relevant context spans organizational boundaries. MCP tools promise to bridge this gap by providing semantic search, cross-repository symbol resolution, and AI-powered deep search at scale. But this promise has not been systematically validated.

### 1.2 Design Philosophy

CodeScaleBench is built on three core principles:

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
| **RQ5** | Can MCP tools enable agents to complete org-scale discovery tasks that are infeasible with local-only access? | Org task scores, cross-repo coverage                     |

---

## 3. Benchmark Architecture

### 3.1 High-Level Architecture Diagram

```
                         CodeScaleBench Architecture
 ┌─────────────────────────────────────────────────────────────────────┐
 │                        TASK DEFINITIONS                            │
 │  benchmarks/                                                       │
 │  ├── csb_sdlc_understand/  (10 tasks)    ├── csb_org_crossrepo_tracing/ (22) │
 │  ├── csb_sdlc_design/      (14 tasks)    ├── csb_org_security/          (24) │
 │  ├── csb_sdlc_fix/         (26 tasks)    ├── csb_org_incident/          (20) │
 │  ├── csb_sdlc_feature/     (23 tasks)    ├── csb_org_onboarding/        (28) │
 │  ├── csb_sdlc_refactor/    (16 tasks)    ├── csb_org_compliance/        (18) │
 │  ├── csb_sdlc_test/        (18 tasks)    ├── csb_org_crossorg/          (15) │
 │  ├── csb_sdlc_document/    (13 tasks)    ├── csb_org_domain/            (20) │
 │  ├── csb_sdlc_secure/      (12 tasks)    ├── csb_org_migration/         (26) │
 │  └── csb_sdlc_debug/       (18 tasks)    ├── csb_org_org/               (15) │
 │       150 SDLC tasks (9 suites)     ├── csb_org_platform/          (18) │
 │                                     ├── csb_org_crossrepo/         (14) │
 │                                     └── 220 Org tasks (11 suites)       │
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
│   └── Dockerfile.artifact_only # Org: minimal image
├── tests/
│   ├── test.sh                  # Harbor-compatible entry point
│   ├── eval.sh                  # Evaluation logic (Org)
│   ├── oracle_checks.py         # Oracle scoring (Org)
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

Both SDLC and Org tasks use the same config pair (`baseline-local-direct` + `mcp-remote-direct`). Some legacy Org runs used `baseline-local-artifact` + `mcp-remote-artifact` configs; these are handled by analysis scripts but are no longer the default.

---

## 4. Task Taxonomy and SDLC Alignment

### 4.1 SDLC Phase Suites (150 tasks)

Tasks are drawn from established benchmarks and custom-authored challenges, then organized by their primary SDLC phase:

| Suite            | SDLC Phase                | Tasks | Difficulty Range | Languages                            |
| ---------------- | ------------------------- | ----: | ---------------- | ------------------------------------ |
| `csb_sdlc_fix`        | Bug Repair                |    26 | medium--hard     | C++, Go, Java, JS, Python, TS        |
| `csb_sdlc_feature`    | Feature Implementation    |    23 | medium--hard     | C#, C++, Go, Java, JS, Rust, TS      |
| `csb_sdlc_debug`      | Debugging & Investigation |    18 | medium--expert   | C, C++, Go, Python, TS               |
| `csb_sdlc_test`       | Testing & QA              |    18 | medium--hard     | C, C#, C++, Go, Java, JS, Python, TS |
| `csb_sdlc_refactor`   | Cross-File Refactoring    |    16 | medium--hard     | C++, Go, Java, Python, Rust          |
| `csb_sdlc_design`     | Architecture & Design     |    14 | hard--expert     | C, C++, Go, Java, Python             |
| `csb_sdlc_document`   | Documentation             |    13 | hard             | C++, Go, Java, Python, TS            |
| `csb_sdlc_secure`     | Security & Compliance     |    12 | medium--hard     | C, C++, Go, Java, Python             |
| `csb_sdlc_understand` | Requirements & Discovery  |    10 | hard             | C++, Go, Java, Python, TS            |

Suite sizes use DOE-driven Neyman-optimal allocation to maximize statistical power per suite. The old `csb_sdlc_build` suite was split into `csb_sdlc_feature` (23 tasks) and `csb_sdlc_refactor` (16 tasks) to better align with SDLC phases.

### 4.2 CodeScaleBench-Org Suites (220 tasks)

These tasks specifically measure org-scale cross-repository discovery capabilities. Each task requires the agent to find information distributed across 3-20 repositories:

| Suite                       | Use Case Category            | Tasks | Description                               |
| --------------------------- | ---------------------------- | ----: | ----------------------------------------- |
| `csb_org_onboarding`        | E: Onboarding                |    28 | API consumption, tribal knowledge         |
| `csb_org_migration`         | C: Framework Migration       |    26 | API migrations, breaking changes          |
| `csb_org_security`          | B: Vulnerability Remediation |    24 | CVE impact, missing auth middleware       |
| `csb_org_crossrepo_tracing` | A: Dependency Tracing        |    22 | Blast radius analysis, dependency chains  |
| `csb_org_domain`            | H: Domain Lineage            |    20 | Config propagation, architecture patterns |
| `csb_org_incident`          | D: Incident Debugging        |    20 | Error-to-code-path tracing                |
| `csb_org_compliance`        | F: Compliance                |    18 | Standards adherence across repos          |
| `csb_org_platform`          | J: Platform Knowledge        |    18 | Service templates, infrastructure         |
| `csb_org_crossorg`          | G: Cross-Org Discovery       |    15 | Interface implementations                 |
| `csb_org_org`               | I: Organizational Context    |    15 | Agentic discovery                         |
| `csb_org_crossrepo`         | K: Cross-Repo Discovery      |    14 | Cross-repo search, impact analysis        |

### 4.3 Repository and Language Coverage

Tasks span **9 primary programming languages** (C, C++, C#, Go, Java, JavaScript, Python, Rust, TypeScript) plus multi-language tasks, across **40+ open-source repositories**:

```
Language Coverage:
  Primary single-language labels: C, C++, C#, Go, Java, JavaScript, Python, Rust, TypeScript
  Multi-language tasks: explicitly labeled combinations (e.g., `java,cpp`, `go,protobuf`, `cpp,c,javascript`)

Repository Scale:
  Large monorepos:    kubernetes/kubernetes, pytorch/pytorch, torvalds/linux
  Mid-size projects:  django/django, grafana/grafana, apache/kafka
  Cross-org polyrepos: Grafana+Loki+Mimir, K8s+etcd+containerd
  Distributed ecosystems: Apache Kafka/Flink/Camel, Envoy/Istio
```

### 4.4 Difficulty Distribution

| Difficulty | Tasks | Percentage | Description                                                |
| ---------- | ----: | ---------- | ---------------------------------------------------------- |
| medium     |    21 | 7.5%       | Dependency installation, straightforward fixes, unit tests |
| hard       |   245 | 87.8%      | Multi-file changes, cross-repo reasoning, runbooks         |
| expert     |    13 | 4.7%       | Kernel/debug fault localization and highest-complexity tasks |

---

## 5. Task Curation Methodology

### 5.1 Task Provenance

The 370 tasks in CodeScaleBench fall into two broad provenance categories:

**SDLC tasks (150 tasks across 9 suites):** The majority are fully original tasks authored for CodeScaleBench, each grounded in a real repository at a pinned commit and targeting a genuine development scenario (a real bug, a real missing feature, a real documentation gap) identified through analysis of repository issues, PRs, and codebases on GitHub. A smaller number of tasks are adapted from or inspired by existing benchmarks while retaining CSB-specific instructions and verifiers:

- 8 dependency-installation tasks adapted from DIBench patterns
- 5 Linux kernel fault-localization tasks with a custom 10-point rubric from the LinuxFL benchmark
- 6 code-review tasks using synthetic defect injection (null-deref, resource-leak, etc.) from the Qodo Git Code Review benchmark
- 1 task sourced from TheAgentCompany (bustub-hyperloglog-impl-001)

All tasks, regardless of inspiration source, use CSB-authored instructions and CSB-built verifiers running inside the CSB Docker environment.

**Org tasks (220 tasks):** Derived from a custom **Use Case Registry** (`configs/use_case_registry.json`) for cross-repository code intelligence. Each use case was validated against Sourcegraph's actual search capabilities and curated into a benchmark task with oracle ground truth. These tasks specifically target org-scale scenarios where information is distributed across 3-20 repositories. Suite sizes use DOE-driven Neyman-optimal allocation to maximize statistical power per suite.

### 5.2 GitHub Usage for Task Sourcing

All tasks are grounded in real open-source codebases hosted on GitHub. The task authoring process involved:

1. **Repository and commit selection**: For each task, a specific repository and commit were chosen to provide a realistic development context. Repositories range from large monorepos (kubernetes/kubernetes, torvalds/linux) to mid-size projects (django/django, grafana/grafana) to cross-ecosystem polyrepos (Apache Kafka + Flink + Camel). Commits are pinned to ensure reproducibility.

2. **Scenario identification**: Task scenarios were identified by examining real repository activity -- open issues, merged PRs, documentation gaps, architectural patterns, and known bugs. For example, PyTorch compiler fusion tasks were modeled on real PRs (e.g., PR #167499); code review tasks inject synthetic defects modeled on real-world vulnerability patterns (null-deref, resource-leak, race-condition, injection, etc.).

3. **Org repo sets**: Cross-repository tasks use curated **repo set fixtures** (`fixtures/repo_sets/*.json`) defining 11 ecosystems (kubernetes-ecosystem, apache-kafka-ecosystem, compiler-toolchain, mozilla-firefox, etc.). Each repo set specifies the repositories, their relationships, and the Sourcegraph mirror names used for MCP access.

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

Ground truth serves two distinct purposes in CodeScaleBench, and it is important to distinguish them:

1. **Task scoring (verifiers)**: For Org artifact tasks, ground truth is used _directly_ in scoring -- `oracle_checks.py` compares the agent's `answer.json` against the oracle to compute file-set F1, symbol recall, chain recall, etc. (see Section 7.4). For SDLC direct tasks, ground truth is embedded in the verifier itself -- the test suite, expected defects, or rubric criteria define what "correct" means, and the verifier scores against those expectations without referencing a separate ground truth registry.

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

**SDLC tasks (150 tasks)** use a unified extractor (`_gt_sdlc()`) that walks the 6-level priority chain described above. For most tasks, ground truth files come from `ground_truth.json` or are extracted from `instruction.md` via regex patterns matching file path references. Specialized handling exists for specific task patterns:

- **Bug-fix tasks** (csb_sdlc_fix): Ground truth extracted from `solution/solve.sh` patches or `expected_changes.json`, identifying which files should be modified
- **Code-review tasks** (csb_sdlc_test): `expected_defects.json` provides structured defect annotations (file, line range, defect type)
- **Fault-localization tasks** (csb_sdlc_debug): Ground truth file paths extracted from `instruction.md`

**Org tasks (220 tasks)** use `oracle_answer.json` as the authoritative source, providing structured ground truth with files, symbols, dependency chains, and keywords (see Section 6.5).

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

### 6.5 CodeScaleBench-Org Oracle System

Org tasks use a **closed-world oracle** system with 7 deterministic check functions:

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

All 220 Org tasks passed this validation before inclusion.

### 6.8 Oracle Calibration

Beyond the fail2pass gate (Section 6.7), oracle calibration validates that check functions produce meaningful score discrimination on **partial** answers — a subset of oracle items must produce a score strictly between 0.0 and 1.0, confirming the scoring function rewards incremental progress.

Because both configs have **information parity** — baseline receives all repos cloned locally in `/workspace`, while MCP accesses the same repos via Sourcegraph MCP tools — the oracle measures how effectively the agent discovers and assembles cross-repo information, not whether the information is accessible at all. The 12-task starter pack confirmed that baseline agents can and do achieve non-zero scores (mean 0.722) using local search tools alone, while MCP agents achieve higher scores on average (mean 0.884) — see Section 11.1 for full results. Org tasks are designed to measure tool-assisted _search quality_ across polyrepo codebases, not information access gaps.

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
 │  /tests/eval.sh  (Org tasks)                    │
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

Each SDLC task has a custom `test.sh` tailored to its evaluation needs. Four major patterns cover the 150 tasks:

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

### 7.4 CodeScaleBench-Org Task Verifiers (eval.sh + oracle_checks.py)

All 220 Org tasks use an identical `eval.sh` template that delegates scoring to `oracle_checks.py`:

```bash
# eval.sh (uniform across all Org tasks)
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
| `oracle_checks.py`            | Deterministic oracle scoring (file F1, symbol recall, chain recall, provenance, keyword recall) with 3-pass repo normalization            | All Org tasks             |

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
| **oracle-checks** | 0.0--1.0    | Org (artifact)                         | Composite mean of file/symbol/chain/keyword checks                          |
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

**Scale**: ~180 mirrors in the `sg-evals` organization (inventory evolves over time) covering benchmark repo/version needs.

### 9.6 Execution Infrastructure

| Component         | Implementation                                 |
| ----------------- | ---------------------------------------------- |
| **Runner**        | Harbor (Docker-based task isolation)                          |
| **Cloud Exec**    | Daytona SDK 0.148.0 (default); local Docker for 18 sweap-image tasks |
| **Agent**         | Claude Code (Claude Haiku 4.5)                               |
| **MCP Endpoint**  | Sourcegraph `.api/mcp/v1`                                    |
| **Time Limits**   | 300--1,800 seconds per task                                  |
| **Parallelism**   | 62 task pairs (124 sandboxes) on Daytona; 12 slots local     |
| **Multi-Account** | Round-robin across 3 Max subscription accounts               |
| **Token Auth**    | OAuth with 30-minute refresh margin                          |
| **Results**       | `runs/staging/` → promote to `runs/official/`                |

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

## 11. Results

### 11.1 Data Availability

This section reflects the refreshed analysis export generated on **March 3, 2026** from `runs/analysis`:
- Valid scored rows in export: **1,281**
- Historical rows in `all_tasks`: **1,822**
- Paired baseline/MCP tasks with both sides present: **370**
- Suites represented: **20** (9 SDLC + 11 Org)

Compared with prior drafts, this is a different analysis slice and should be treated as the current snapshot for reward/time/cost metrics below.

**V1 → V2 changes:** The V1 report (Feb 27) used 251 tasks with single-trial data. V2 expands to 370 tasks with multi-run averaging, which reduces sampling noise and yields narrower confidence intervals with different point estimates. The old `csb_sdlc_build` suite was split into `csb_sdlc_feature` (23 tasks) and `csb_sdlc_refactor` (16 tasks) to better align with SDLC phases. The Org suites grew from 81 to 220 tasks through scaffolding, promotion, and DOE rebalancing.

### 11.2 SDLC Suite Results (Paired Comparison)

Paired deltas for SDLC suites in the refreshed analysis set (computed from per-task means across all available runs, with variance on per-task deltas and 95% bootstrap CIs):

| Suite | n | Mean Reward Delta (MCP - Baseline) | Var(Δ Reward) | 95% CI |
|-------|---|-------------------------------------|---------------|--------|
| csb_sdlc_understand | 10 | +0.1148 | 0.089103 | [-0.0415, +0.3147] |
| csb_sdlc_refactor | 16 | +0.1029 | 0.256679 | [-0.1519, +0.3425] |
| csb_sdlc_fix | 26 | +0.0986 | 0.055532 | [+0.0165, +0.1967] |
| csb_sdlc_design | 14 | +0.0514 | 0.091786 | [-0.1051, +0.2131] |
| csb_sdlc_document | 13 | +0.0415 | 0.007517 | [-0.0038, +0.0900] |
| csb_sdlc_feature | 23 | +0.0130 | 0.118041 | [-0.1134, +0.1604] |
| csb_sdlc_test | 18 | -0.0113 | 0.037797 | [-0.0972, +0.0831] |
| csb_sdlc_debug | 18 | -0.0372 | 0.017479 | [-0.0909, +0.0300] |
| csb_sdlc_secure | 12 | -0.0500 | 0.012604 | [-0.1167, +0.0104] |

**SDLC total (weighted by paired task count)**: **+0.0363** across **n=150** paired tasks, 95% CI **[-0.0083, +0.0835]**.

### 11.3 Org Suite Results (Paired Comparison)

Paired deltas for Org suites in the refreshed analysis set:

| Suite | n | Mean Reward Delta (MCP - Baseline) | Var(Δ Reward) | 95% CI |
|-------|---|-------------------------------------|---------------|--------|
| csb_org_incident | 20 | +0.1125 | 0.056807 | [+0.0246, +0.2305] |
| csb_org_security | 24 | +0.1057 | 0.055106 | [+0.0250, +0.2102] |
| csb_org_org | 15 | +0.0568 | 0.015604 | [-0.0067, +0.1180] |
| csb_org_crossrepo_tracing | 22 | +0.0514 | 0.035013 | [-0.0040, +0.1407] |
| csb_org_migration | 26 | +0.0381 | 0.020784 | [-0.0087, +0.1006] |
| csb_org_crossorg | 15 | +0.0252 | 0.004410 | [-0.0094, +0.0572] |
| csb_org_compliance | 18 | +0.0153 | 0.012530 | [-0.0353, +0.0707] |
| csb_org_onboarding | 28 | +0.0083 | 0.029982 | [-0.0503, +0.0782] |
| csb_org_domain | 20 | -0.0165 | 0.006946 | [-0.0523, +0.0209] |
| csb_org_crossrepo | 14 | -0.0242 | 0.003717 | [-0.0558, +0.0073] |
| csb_org_platform | 18 | -0.0287 | 0.009930 | [-0.0800, +0.0113] |

**Org total (weighted by paired task count)**: **+0.0339** across **n=220** paired tasks, 95% CI **[+0.0133, +0.0571]**.

**Overall paired delta**: **+0.0349** across **n=370** paired tasks, 95% CI **[+0.0130, +0.0579]**.

### 11.4 V1 → V2 Results Comparison

The refreshed analysis set supersedes the prior V2 numeric snapshot in this section. The key directional change from the old write-up is that reward deltas remain positive overall while efficiency metrics (time/cost) are now adverse in the current slice.

| Metric | Refreshed Value |
|--------|------------------|
| Paired tasks | 370 |
| Overall reward delta | +0.0349 (95% CI: [+0.0130, +0.0579]) |
| SDLC reward delta | +0.0363 (95% CI: [-0.0083, +0.0835]) |
| Org reward delta | +0.0339 (95% CI: [+0.0133, +0.0571]) |
| Reward-delta variance | 0.048985 |
| Mean wall-clock delta | -36.22s |
| Mean agent-execution delta | -101.06s |

### 11.5 Information Retrieval Metrics

The retrieval pipeline was rerun over the analysis-set adapter input (`runs/_analysis_eval_input2`) using `normalize_retrieval_events.py` and `retrieval_eval_pipeline.py`.

**Aggregate File-Level IR Metrics:**

| Metric | Mean | Median | Std | n |
|--------|------|--------|-----|---|
| File Recall | 0.4598 | 0.4444 | 0.4226 | 311 |
| MRR | 0.3644 | 0.0833 | 0.4325 | 311 |
| MAP | 0.2514 | 0.0670 | 0.3451 | 311 |
| Context Efficiency | 0.1958 | 0.0545 | 0.2658 | 311 |
| Precision@1 | 0.2926 | 0.0000 | 0.4557 | 311 |
| Recall@5 | 0.2431 | 0.0000 | 0.3577 | 311 |
| nDCG@10 | 0.3298 | 0.0000 | 0.3908 | 311 |

Pipeline coverage summary:
- Event files: **799**
- Computable tasks: **311**
- Skipped for missing GT: **488**
- Parse errors: **0**

This indicates retrieval quality remains moderate on computable tasks, but ground-truth availability is still the main bottleneck for broader retrieval coverage.

**IR aggregates by configuration type (baseline vs MCP):**

| Config Type | n | File Recall | MRR | MAP | Context Efficiency |
|-------------|---|-------------|-----|-----|--------------------|
| baseline | 132 | 0.3295 | 0.3462 | 0.2307 | 0.1843 |
| mcp | 179 | 0.5558 | 0.3778 | 0.2667 | 0.2043 |

MCP runs show higher recall and slightly higher ranking/efficiency metrics on computable retrieval tasks.

### 11.6 Correlation Analysis

Correlation was recomputed from the refreshed retrieval analysis output (`docs/analysis/ir_analysis_analysis_set_20260303.json`):

| Correlation | Value |
|-------------|-------|
| Spearman rho (MRR delta vs reward delta) | +0.1295 |
| p-value | 0.1533 |
| Paired tasks with both retrieval sides | 2 |

Current interpretation: no statistically significant retrieval-outcome correlation signal yet in the paired subset, largely because paired retrieval coverage is still sparse.

### 11.7 Reward by Language

Per-language results are computed from per-task means (multiple runs averaged first), and variance is reported on per-task reward deltas:

| Language | n | BL Mean | MCP Mean | Δ Reward | Var(Δ Reward) |
|----------|---|---------|----------|----------|---------------|
| Go | 134 | 0.459 | 0.511 | +0.052 | 0.049442 |
| C++ | 73 | 0.481 | 0.490 | +0.008 | 0.026095 |
| Java | 57 | 0.483 | 0.502 | +0.019 | 0.030897 |
| Python | 55 | 0.456 | 0.527 | +0.070 | 0.088567 |
| Rust | 12 | 0.429 | 0.452 | +0.023 | 0.006496 |
| C | 10 | 0.702 | 0.718 | +0.016 | 0.009334 |
| JavaScript | 8 | 0.407 | 0.542 | +0.135 | 0.123174 |
| TypeScript | 7 | 0.588 | 0.448 | -0.140 | 0.013694 |

Largest positive deltas are in JavaScript/Python/Go; TypeScript remains the strongest negative outlier.

### 11.8 Reward by Difficulty

| Difficulty | n | BL Mean | MCP Mean | Δ Reward | Var(Δ Reward) |
|-----------|---|---------|----------|----------|---------------|
| Hard | 338 | 0.474 | 0.512 | +0.038 | 0.046768 |
| Expert | 21 | 0.663 | 0.605 | -0.057 | 0.070557 |
| Medium | 11 | 0.307 | 0.421 | +0.115 | 0.053039 |

Difficulty is assigned by the `rescore_difficulty.py` pipeline, which combines code complexity, codebase size, and ground-truth depth into a composite score:

```
raw = 0.4 * size_score + 0.4 * complexity_score + 0.2 * ground_truth_depth_score
difficulty = "medium" if raw < 0.35 else "hard" if raw < 0.75 else "expert"
```

The benchmark remains dominated by hard tasks. In this refreshed aggregation, hard and medium are positive on reward delta, while expert remains negative.

### 11.9 Impact by Codebase Size

Codebase-size analysis in the refreshed pass uses two available proxies:
1) `context_length` bins from task metadata, and
2) `files_count` bins.

**By context-length bin:**

| Context Length Bin | n | BL Mean | MCP Mean | Δ Reward | Var(Δ Reward) |
|--------------------|---|---------|----------|----------|---------------|
| <100K tokens | 222 | 0.400 | 0.433 | +0.034 | 0.026862 |
| 100K-1M tokens | 98 | 0.639 | 0.670 | +0.031 | 0.093518 |
| unknown | 50 | 0.523 | 0.571 | +0.048 | 0.059717 |

MCP reward delta is positive across all context-size bins in this refreshed slice.

**By files-count bin:**

| Files Count Bin | n | BL Mean | MCP Mean | Δ Reward | Var(Δ Reward) |
|----------------|---|---------|----------|----------|---------------|
| <10 | 168 | 0.327 | 0.375 | +0.048 | 0.032454 |
| 10–100 | 91 | 0.676 | 0.699 | +0.023 | 0.097068 |
| unknown | 111 | 0.550 | 0.575 | +0.025 | 0.034117 |

Across available bins, MCP reward delta is positive, with the strongest lift in low-file-count tasks.

### 11.10 MCP Tool Usage Patterns

Based on all MCP run rows in the refreshed analysis (`n=910`):

**Overall usage:**
- Mean total tool calls per run: 32.12
- Mean MCP tool calls per run: 22.46
- Mean local tool calls per run: 9.58
- Mean MCP ratio: 0.7974
- Mean keyword searches: 8.76/run
- Mean NLS searches: 1.11/run
- Mean Deep Search calls: 0.0057/run

Top tools by total calls:

| Tool | Total Calls |
|------|-------------|
| `mcp__sourcegraph__sg_read_file` | 8,605 |
| `mcp__sourcegraph__sg_keyword_search` | 7,993 |
| `Bash` | 5,146 |
| `mcp__sourcegraph__sg_list_files` | 2,449 |
| `Read` | 1,310 |
| `Write` | 1,272 |
| `mcp__sourcegraph__sg_nls_search` | 997 |
| `Edit` | 715 |

The dominant pattern is unchanged: keyword search + read-file dominate MCP usage, and Deep Search remains near-zero.

### 11.11 Cost Analysis

Token-based cost in this refreshed snapshot is derived from the `analysis_set_metrics_20260303.json` paired analysis.

| Metric | Value |
|--------|-------|
| Paired tasks with cost deltas | 369 |
| Mean paired cost delta (MCP vs baseline) | **+$0.040/task** |
| Mean paired cost delta (%; per-task mean) | **+17.67%** |
| Cost delta (% of means) | **+13.49%** |

Cost is slightly higher in MCP on this refreshed slice.

**Cost per benchmark suite (per-task multi-run means):**

| Suite | n | BL $/task | MCP $/task | Δ $/task | Var(Δ $/task) |
|------|---|-----------|------------|----------|---------------|
| csb_org_compliance | 18 | 0.2679 | 0.2521 | -0.0158 | 0.003486 |
| csb_org_crossorg | 15 | 0.2756 | 0.2136 | -0.0620 | 0.017902 |
| csb_org_crossrepo | 14 | 0.2575 | 0.2523 | -0.0052 | 0.005375 |
| csb_org_crossrepo_tracing | 22 | 0.2478 | 0.2187 | -0.0292 | 0.003282 |
| csb_org_domain | 20 | 0.2108 | 0.2258 | +0.0150 | 0.003268 |
| csb_org_incident | 20 | 0.2465 | 0.1989 | -0.0476 | 0.007914 |
| csb_org_migration | 26 | 0.2534 | 0.2501 | -0.0033 | 0.009546 |
| csb_org_onboarding | 28 | 0.1029 | 0.1049 | +0.0020 | 0.000860 |
| csb_org_org | 15 | 0.2362 | 0.2193 | -0.0169 | 0.001710 |
| csb_org_platform | 18 | 0.1940 | 0.2149 | +0.0209 | 0.001999 |
| csb_org_security | 24 | 0.2167 | 0.2146 | -0.0020 | 0.003105 |
| csb_sdlc_debug | 18 | 0.3669 | 0.4569 | +0.0901 | 0.023810 |
| csb_sdlc_design | 14 | 0.4100 | 0.3590 | -0.0510 | 0.097988 |
| csb_sdlc_document | 13 | 0.2669 | 0.2974 | +0.0305 | 0.014390 |
| csb_sdlc_feature | 23 | 0.4965 | 0.7079 | +0.2114 | 0.183988 |
| csb_sdlc_fix | 26 | 0.5997 | 0.7057 | +0.1059 | 0.065870 |
| csb_sdlc_refactor | 15 | 0.3194 | 0.7173 | +0.3980 | 0.147469 |
| csb_sdlc_secure | 12 | 0.4825 | 0.5657 | +0.0832 | 0.030859 |
| csb_sdlc_test | 18 | 0.2641 | 0.2976 | +0.0335 | 0.015625 |
| csb_sdlc_understand | 10 | 0.3519 | 0.4475 | +0.0956 | 0.022037 |

### 11.12 Timing Analysis

Timing in the refreshed snapshot:

| Metric | Value |
|--------|-------|
| Paired tasks with timing deltas | 370 |
| Baseline mean wall clock | **367.11s** |
| MCP mean wall clock | **330.89s** |
| Mean paired wall-clock delta | **−36.22s** |
| Wall-clock delta (% of means) | **−9.87%** |
| Mean paired agent-execution delta | **−101.06s** |

MCP is faster on both wall-clock and agent-execution in the refreshed per-task averaged analysis.

---

## 12. Threats to Validity

### 12.1 Internal Validity

| Threat                        | Mitigation                                                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Agent non-determinism**     | 3+ independent runs per task per config; per-task means reduce sampling noise; bootstrap CIs on paired deltas |
| **Verifier limitations**      | Multiple verifier types per task category; optional LLM judge layer; QA audit process (6 dimensions)           |
| **Instruction contamination** | Automated checking for MCP/Sourcegraph references in baseline instructions                                     |
| **Infrastructure confounds**  | Error fingerprinting (12 patterns) separates infra failures from task failures                                 |
| **Preamble effects**          | V5 preamble isolated: leads with truncation constraint, avoids prescriptive workflow                           |

In addition to the six-dimension QA framework, we run an explicit ABC audit via `scripts/abc_audit.py` that scores criteria across three dimensions: **Task Validity**, **Outcome Validity**, and **Reporting**. The ABC audit is used as a structured benchmark-quality gate and complements pre-flight/runtime task validation.

### 12.2 External Validity

| Threat                  | Mitigation                                                                                    |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| **Single agent**        | Framework supports 6 agent harnesses (Claude Code, Codex, Cursor, Gemini, Copilot, OpenHands) |
| **Single MCP provider** | MCP protocol is standardized; framework can accommodate other providers                       |
| **Task selection bias** | Transparent MCP benefit scoring; systematic selection criteria documented                     |
| **Repository coverage** | 50+ repos across 10 languages, including enterprise-scale monorepos; 370 tasks spanning 20 suites |

### 12.3 Construct Validity

| Threat                                   | Discussion                                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Truncated source vs. real enterprise** | Truncation simulates the MCP use case but doesn't perfectly model partial local context     |
| **Time limits**                          | Fixed limits may disadvantage MCP when remote API latency adds overhead                     |
| **Oracle completeness**                  | Closed-world oracles may miss valid alternative solutions                                   |
| **Scoring normalization**                | Different verifier types (test-ratio, checklist, similarity) may not be directly comparable |
| **Within-task variance**                 | V2 uses 3+ runs per task, enabling per-task averaging that reduces within-task noise; two-level hierarchical bootstrap could further separate task-level and run-level variance |

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

CodeScaleBench was itself primarily developed using Claude Code, creating a meta-recursive situation: an AI coding agent building a benchmark to evaluate AI coding agents' use of code intelligence tools. This section documents the development process for both methodological transparency and as a case study in AI-assisted benchmark construction.

### 14.2 Development Timeline

```
 Jan 30 ─── Feb 3 ─── Feb 6 ─── Feb 10 ─── Feb 15 ─── Feb 20 ─── Feb 25 ─── Mar 2 ── Mar 3
    │          │         │          │           │           │          │          │         │
    ▼          ▼         ▼          ▼           ▼           ▼          ▼          ▼         ▼
  Paper     Task      QA Audit   Trace      Enterprise  V5 Preamble  Oracle    Rename    V2 Report
  draft +   selection  (28       audit,     expansion,  sg_only      curation  CCB→CSB   370/370
  initial   pipeline,  issues),  SG_base    governance  Dockerfile   complete  DOE       coverage,
  PRD       SDLC       verifier  dropped,   simulation  redesign     for 73    rebalance multi-run
            taxonomy,  bugs,     Opus 4.6                             MCP tasks 370 tasks  analysis
            5→3 cfg    mirrors   reruns                                         Daytona
```

### 14.3 Scale of Claude Code Usage

The development produced **700+ conversation sessions** (JSONL transcripts) spanning January 30 -- March 3, 2026. Claude Code was used to:

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

5. **Oracle auto-curation** (Feb 24): Claude Code designed the Sourcegraph-query-based oracle curation pipeline and validated all 220 Org tasks (81 initial tasks expanded to 220 via scaffolding, promotion, and DOE-driven Neyman-optimal rebalancing).

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

**Bootstrap CI methodology**: All confidence intervals reported in Section 11 use the percentile bootstrap method on paired deltas of per-task means. For each canonical task, the per-config mean reward is computed across all valid runs (3+ per config). The delta is then `mean(reward_mcp) - mean(reward_baseline)`. The vector of 370 per-task deltas is resampled with replacement 10,000 times (seed=42 for reproducibility), the mean is computed for each resample, and the 2.5th and 97.5th percentiles of the bootstrap distribution define the 95% CI bounds. This non-parametric approach makes no normality assumption, which is appropriate for bounded [0, 1] reward data that often exhibits bimodal distributions. Per-task averaging across multiple runs reduces within-task variance from agent non-determinism. Tasks with infrastructure errors (agent never executed) are excluded from paired analysis. The computation is implemented in `scripts/compute_bootstrap_cis.py` and the core bootstrap function in `scripts/csb_metrics/statistics.py:bootstrap_ci()`.

### Appendix B: Task ID Naming Conventions

| Suite Type    | Pattern                       | Example                         |
| ------------- | ----------------------------- | ------------------------------- |
| SDLC          | `{repo}-{desc}-{phase}-{NNN}` | `kubernetes-scheduler-arch-001` |
| Org    | `ccx-{family}-{NNN}`          | `ccx-dep-trace-001`             |
| SWE-bench Pro | `{org}__{repo}-{issue}`       | `django__django-16820`          |

### Appendix C: CodeScaleBench-Org Task ID Registry

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
| Oracle        | oracle-checks | `mean(check_scores)`                                                        | Org tasks          |

### Appendix E: QA Audit Framework (6 Dimensions)

This report uses two complementary audit layers: (1) the operational six-dimension QA audit below, and (2) an explicit ABC audit (`scripts/abc_audit.py`) across Task Validity, Outcome Validity, and Reporting.

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
| **CSB**             | CodeScaleBench                                                                     |
| **Harbor**          | Docker-based task isolation runner                                                   |
| **MCP**             | Model Context Protocol -- standard interface for connecting agents to external tools |
| **SDLC**            | Software Development Lifecycle                                                       |
| **SG**              | Sourcegraph                                                                          |
| **MRR**             | Mean Reciprocal Rank                                                                 |
| **nDCG**            | Normalized Discounted Cumulative Gain                                                |
| **MAP**             | Mean Average Precision                                                               |
| **TTFR**            | Time to First Relevant file                                                          |
| **Oracle**          | Exhaustive ground truth specification for Org tasks                           |
| **sg-evals**        | GitHub organization hosting version-pinned repository mirrors                        |
| **Preamble**        | Instructions prepended to task description for MCP-augmented agents                  |
| **Clone-at-verify** | Pattern where full repo is cloned at verification time (not during agent execution)  |

---
