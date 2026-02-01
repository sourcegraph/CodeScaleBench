# Kubernetes Documentation Generation Benchmark

## Overview

This benchmark evaluates AI coding agents on documentation generation and update tasks for the Kubernetes codebase. The design leverages the extensive Kubernetes ecosystem to test how well agents can understand complex distributed systems code and produce accurate, comprehensive documentation.

## Benchmark Design

### Core Hypothesis

**Agents with access to Sourcegraph code intelligence tools (Deep Search, keyword search, NLS search) will produce more accurate and comprehensive documentation than baseline agents, because MCP tools can discover related context from other packages and repositories.**

### Key Design Constraint: Indexed Code Access

Sourcegraph's cloud index contains the **full** Kubernetes organization including all documentation.

#### ⚠️ Critical Limitation: Deep Search Cannot Be Filtered

**Deep Search is a conversational AI that internally queries the index.**
We cannot intercept or modify its internal searches - filtering only works for keyword/regex search.

```
Agent: "How does PodTopologySpread work?"
         │
         ▼
  ┌────────────────────────────────────────────────────────┐
  │  Deep Search (Sourcegraph's internal AI)               │
  │                                                        │
  │  1. Internally queries index                           │
  │  2. Finds doc.go, KEPs, READMEs ← CANNOT PREVENT      │
  │  3. Synthesizes answer with doc content                │
  │                                                        │
  │  ❌ Cannot intercept internal queries                  │
  │  ❌ Filtering response doesn't remove incorporated     │
  │     knowledge                                          │
  └────────────────────────────────────────────────────────┘
```

#### Practical Benchmark Approaches

| Approach                       | Deterministic? | Deep Search? | Effort |
| ------------------------------ | -------------- | ------------ | ------ |
| **A. Keyword search only**     | ✅ Yes         | ❌ Disabled  | Low    |
| **B. Self-hosted Sourcegraph** | ✅ Yes         | ✅ Yes       | High   |
| **C. Accept limitation**       | ⚠️ No          | ✅ Yes       | Low    |

**Option A: Keyword Search Only (Deterministic)**

Disable Deep Search, use only keyword/regex search with filtering proxy.
Tests: _Can filtered keyword search help agents find code patterns?_

**Option B: Self-Hosted Sourcegraph (Fully Deterministic)**

Run Sourcegraph locally with a stripped Kubernetes fork indexed.
Tests: _Can Deep Search help when docs don't exist in the index?_

```bash
# Automated script to create stripped fork
./scripts/create_stripped_kubernetes_fork.sh \
  --github-user YOUR_GITHUB_USERNAME \
  --repo-name kubernetes-stripped

# This will:
# 1. Clone kubernetes/kubernetes
# 2. Strip all documentation (doc.go, README.md, KEPs, etc.)
# 3. Push to github.com/YOUR_USERNAME/kubernetes-stripped
# 4. Print instructions for adding to Sourcegraph
```

After indexing, configure MCP to search ONLY the stripped repo:

```
repo:^github\.com/YOUR_USERNAME/kubernetes-stripped$
```

**Option C: Accept Limitation, Measure Quality (Pragmatic)**

Use Deep Search as-is with a different hypothesis:

- Don't claim agent "couldn't find" existing docs
- Measure: Does MCP produce BETTER docs than baseline?

```
┌─────────────────────────────────────────────────────────────────────┐
│                     WHAT EACH AGENT SEES                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  BASELINE AGENT                    MCP-ENABLED AGENT                │
│  ───────────────                   ──────────────────               │
│  Local files only:                 Local files + Sourcegraph:       │
│                                                                     │
│  ┌─────────────────┐               ┌─────────────────┐              │
│  │ Target Package  │               │ Target Package  │              │
│  │ (STRIPPED)      │               │ (STRIPPED)      │              │
│  │ - No doc.go     │               │ - No doc.go     │              │
│  │ - No README     │               │ - No README     │              │
│  └─────────────────┘               └────────┬────────┘              │
│                                             │                       │
│                                             ▼                       │
│                                    ┌─────────────────┐              │
│                                    │ Sourcegraph MCP │              │
│                                    │ (Deep Search)   │              │
│                                    └────────┬────────┘              │
│                                             │                       │
│                              ┌──────────────┼──────────────┐        │
│                              ▼              ▼              ▼        │
│                    ┌──────────────┐ ┌────────────┐ ┌────────────┐   │
│                    │ Related KEPs │ │ API Docs   │ │ Framework  │   │
│                    │ (preserved)  │ │ (preserved)│ │ Docs       │   │
│                    └──────────────┘ └────────────┘ └────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Evaluation Methodology

1. **Ground Truth**: Existing Kubernetes documentation (KEPs, README files, doc.go files, API reference docs)
2. **Task Input**: Target package with docs stripped + task prompt
3. **Related Context**: Preserved in Sourcegraph index (different packages/repos)
4. **Comparison**: Agent-generated docs vs. ground truth using LLM judge + metrics

```
┌──────────────────────────────────────────────────────────────────┐
│                    BENCHMARK ARCHITECTURE                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐     ┌─────────────────┐                   │
│   │ Kubernetes Code │────▶│ Strip Docs Tool │                   │
│   │   (Original)    │     │                 │                   │
│   └─────────────────┘     └────────┬────────┘                   │
│                                    │                             │
│                    ┌───────────────┴───────────────┐            │
│                    ▼                               ▼            │
│   ┌─────────────────────────┐   ┌─────────────────────────┐    │
│   │   Baseline Claude       │   │   Claude + Sourcegraph  │    │
│   │   (No MCP tools)        │   │   (MCP Deep Search)     │    │
│   │                         │   │                         │    │
│   │ Input: Undocumented     │   │ Input: Undocumented     │    │
│   │        code only        │   │        code + tools     │    │
│   └───────────┬─────────────┘   └───────────┬─────────────┘    │
│               │                             │                   │
│               ▼                             ▼                   │
│   ┌─────────────────────────┐   ┌─────────────────────────┐    │
│   │  Generated Docs (A)     │   │  Generated Docs (B)     │    │
│   └───────────┬─────────────┘   └───────────┬─────────────┘    │
│               │                             │                   │
│               └──────────────┬──────────────┘                   │
│                              ▼                                  │
│              ┌───────────────────────────────┐                  │
│              │       LLM Judge + Metrics     │                  │
│              │                               │                  │
│              │  Compare against Ground Truth │                  │
│              │  (Original Kubernetes Docs)   │                  │
│              └───────────────────────────────┘                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Task Categories

### Category 1: Package Documentation (doc.go)

**Complexity: Medium | MCP Value: High**

Generate `doc.go` package documentation for undocumented packages.

| Task ID     | Package                        | Ground Truth                                                                                       | Difficulty |
| ----------- | ------------------------------ | -------------------------------------------------------------------------------------------------- | ---------- |
| pkg-doc-001 | `pkg/kubelet/cm`               | [doc.go](https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/cm/doc.go)               | Medium     |
| pkg-doc-002 | `pkg/kubelet/kuberuntime`      | [doc.go](https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/kuberuntime/doc.go)      | Medium     |
| pkg-doc-003 | `pkg/volume`                   | [doc.go](https://github.com/kubernetes/kubernetes/blob/master/pkg/volume/doc.go)                   | Easy       |
| pkg-doc-004 | `pkg/controller/podautoscaler` | [doc.go](https://github.com/kubernetes/kubernetes/blob/master/pkg/controller/podautoscaler/doc.go) | Hard       |

### Category 2: Scheduler Plugin Documentation

**Complexity: High | MCP Value: Very High**

Document scheduler framework plugins that lack comprehensive README files.

| Task ID       | Plugin              | Target Files                        | Ground Truth                 |
| ------------- | ------------------- | ----------------------------------- | ---------------------------- |
| sched-doc-001 | `podtopologyspread` | plugin.go, filtering.go, scoring.go | KEP-20190221 + code comments |
| sched-doc-002 | `interpodaffinity`  | plugin.go, filtering.go, scoring.go | API docs + code comments     |
| sched-doc-003 | `noderesources`     | fit.go, least_allocated.go          | API docs + code comments     |
| sched-doc-004 | `defaultpreemption` | preemption.go                       | KEP + code comments          |

### Category 3: Controller Deep-Dive Documentation

**Complexity: Very High | MCP Value: Very High**

Create comprehensive documentation for internal controllers.

| Task ID      | Controller           | Components                                | Ground Truth      |
| ------------ | -------------------- | ----------------------------------------- | ----------------- |
| ctrl-doc-001 | Garbage Collector    | graph.go, graph_builder.go, operations.go | KEP + design docs |
| ctrl-doc-002 | Node Lifecycle       | node_lifecycle_controller.go              | API docs + code   |
| ctrl-doc-003 | Volume Attach/Detach | attach_detach_controller.go, reconciler/  | CSI KEPs          |
| ctrl-doc-004 | Persistent Volume    | pv_controller.go, pv_controller_base.go   | Storage KEPs      |

### Category 4: Kubelet Resource Manager Documentation

**Complexity: Very High | MCP Value: Very High**

Document kubelet's resource management subsystems.

| Task ID         | Subsystem        | Files                             | Ground Truth         |
| --------------- | ---------------- | --------------------------------- | -------------------- |
| kubelet-doc-001 | Topology Manager | topology*manager.go, policy*\*.go | KEP-0035             |
| kubelet-doc-002 | CPU Manager      | cpu_manager.go, policy_static.go  | KEP + community docs |
| kubelet-doc-003 | Memory Manager   | memory*manager.go, policy*\*.go   | KEP + community docs |
| kubelet-doc-004 | Device Manager   | devicemanager/                    | Device plugin docs   |

### Category 5: API Feature Documentation

**Complexity: Medium-High | MCP Value: High**

Document API features based on implementation.

| Task ID     | Feature              | Implementation Files                        | Ground Truth   |
| ----------- | -------------------- | ------------------------------------------- | -------------- |
| api-doc-001 | Server-Side Apply    | pkg/apiserver/apply/                        | KEP-0006       |
| api-doc-002 | Aggregated Discovery | staging/src/k8s.io/kube-aggregator/         | KEP + API docs |
| api-doc-003 | Watch Bookmarks      | staging/src/k8s.io/apiserver/pkg/storage/   | KEP-20190206   |
| api-doc-004 | CRD Validation       | staging/src/k8s.io/apiextensions-apiserver/ | KEP + API docs |

### Category 6: Feature Gate Documentation Update

**Complexity: Medium | MCP Value: High**

Update feature gate documentation based on recent changes.

| Task ID    | Feature Gate                  | PR Reference   | Documentation Target |
| ---------- | ----------------------------- | -------------- | -------------------- |
| fg-doc-001 | TrafficDistribution           | commit 3176ef2 | types.go comments    |
| fg-doc-002 | VolumeAttributesClass         | PR #134556     | Feature docs         |
| fg-doc-003 | CSIServiceAccountTokenSecrets | PR #134826     | CSI driver docs      |
| fg-doc-004 | SchedulerAsyncAPICalls        | PR #135903     | Scheduler docs       |

## Ground Truth Sources

### Primary Sources (Authoritative)

1. **KEPs (Kubernetes Enhancement Proposals)**

   - Repository: `github.com/kubernetes/enhancements`
   - Location: `keps/sig-*/`
   - Format: Markdown with structured sections

2. **Existing doc.go Files**

   - Location: `pkg/*/doc.go`
   - Format: Go package documentation

3. **API Reference Documentation**
   - Generated from: `staging/src/k8s.io/api/`
   - Published: https://kubernetes.io/docs/reference/

### Secondary Sources (Context)

1. **Community Documentation**

   - Repository: `github.com/kubernetes/community`
   - Location: `contributors/devel/sig-*/`

2. **Website Documentation**
   - Repository: `github.com/kubernetes/website`
   - Location: `content/en/docs/`

## Evaluation Metrics

### 1. Accuracy Score (0-100)

- Technical correctness of statements
- Correct understanding of code behavior
- Proper identification of edge cases

### 2. Completeness Score (0-100)

- Coverage of all major components
- Inclusion of configuration options
- API surface documentation

### 3. Clarity Score (0-100)

- Readability and organization
- Appropriate examples
- Clear explanations

### 4. Ground Truth Similarity (0-100)

- Semantic similarity to existing docs
- Coverage of key concepts from KEPs
- Alignment with official terminology

### LLM Judge Prompt Template

```
You are evaluating documentation generated by an AI agent against ground truth Kubernetes documentation.

## Task
Evaluate the generated documentation for:
1. Technical Accuracy (0-100): Are the technical details correct?
2. Completeness (0-100): Does it cover all important aspects?
3. Clarity (0-100): Is it well-organized and readable?
4. Ground Truth Alignment (0-100): Does it align with official documentation?

## Ground Truth Documentation
{ground_truth}

## Generated Documentation
{generated_doc}

## Code Context
{code_context}

Provide scores and detailed justification for each criterion.
```

## Setup Instructions

### Prerequisites

1. Clone kubernetes/kubernetes repository
2. Clone kubernetes/enhancements repository
3. Configure Sourcegraph access tokens

### Stripping Documentation

Two modes are available:

**1. Surgical Strip (Recommended)** - Only strip target packages

```bash
# Strip only the target package, preserve all other documentation
python scripts/strip_k8s_docs.py \
  --source /path/to/kubernetes \
  --output /path/to/kubernetes-task \
  --packages pkg/scheduler/framework/plugins/podtopologyspread \
  --target-only
```

This preserves:

- KEPs in kubernetes/enhancements (if indexed)
- API documentation in staging/src/k8s.io/api/
- Framework documentation in pkg/scheduler/framework/
- Related plugin documentation

**2. Full Strip** - Remove all documentation (for creating a stripped fork)

```bash
# Strip all documentation from the repository
python scripts/strip_k8s_docs.py \
  --source /path/to/kubernetes \
  --output /path/to/kubernetes-undoc \
  --preserve-structure
```

### Running Tasks

```bash
# Baseline agent (no MCP)
harbor run \
  --path benchmarks/kubernetes_docs/pkg-doc-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1

# Agent with Sourcegraph MCP
harbor run \
  --path benchmarks/kubernetes_docs/pkg-doc-001 \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

## Task File Structure

```
benchmarks/kubernetes_docs/
├── README.md                          # This file
├── GROUND_TRUTH.md                    # Ground truth collection guide
├── scripts/
│   ├── strip_k8s_docs.py             # Remove docs from k8s codebase
│   ├── extract_ground_truth.py       # Extract KEPs and docs
│   └── evaluate_docs.py              # LLM judge evaluation
├── pkg-doc-001/
│   ├── task.yaml                     # Task definition
│   ├── TASK.md                       # Human-readable task
│   ├── ground_truth/
│   │   ├── doc.go                    # Original documentation
│   │   └── kep_context.md            # Relevant KEP excerpts
│   └── context/
│       └── pkg_kubelet_cm/           # Undocumented code files
├── sched-doc-001/
│   ├── task.yaml
│   ├── TASK.md
│   ├── ground_truth/
│   │   ├── kep-20190221.md           # Pod Topology Spread KEP
│   │   └── api_docs.md               # API reference excerpts
│   └── context/
│       └── podtopologyspread/        # Undocumented plugin code
└── ...
```

## Example Task: pkg-doc-001

### task.yaml

```yaml
id: pkg-doc-001
name: "Container Manager Package Documentation"
category: package-documentation
difficulty: medium
repository: kubernetes/kubernetes
target_path: pkg/kubelet/cm

task_description: |
  Generate comprehensive package documentation (doc.go) for the
  kubelet container manager package. The documentation should explain:
  - Package purpose and responsibilities
  - Key interfaces and types
  - Relationship to other kubelet packages
  - Platform-specific considerations (Linux, Windows)

expected_output:
  type: doc.go
  location: pkg/kubelet/cm/doc.go

ground_truth:
  primary: ground_truth/doc.go
  keps: []
  related_docs:
    - https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/

evaluation_criteria:
  - Correctly identifies container manager responsibilities
  - Mentions cgroup management
  - Covers QoS enforcement
  - References resource allocation (CPU, memory, devices)
  - Notes platform differences

mcp_expected_value: high
rationale: |
  Deep Search can discover related packages, KEPs about resource management,
  and community documentation about kubelet internals that would inform
  comprehensive package documentation.
```

### TASK.md

```markdown
# Task: Container Manager Package Documentation

## Objective

Create a `doc.go` file for the `pkg/kubelet/cm` package that provides
comprehensive package-level documentation.

## Context

The container manager package is responsible for managing containers
on a Kubernetes node. You have access to the source code files in this
package but the existing documentation has been removed.

## Requirements

1. Write a doc.go file following Go documentation conventions
2. Explain the package's purpose and responsibilities
3. Document key types and interfaces
4. Note any platform-specific behavior
5. Reference related packages as appropriate

## Files Available

- pkg/kubelet/cm/\*.go (excluding doc.go)
- pkg/kubelet/cm/_/_.go (subpackages)

## Deliverable

A single `doc.go` file with comprehensive package documentation.
```

## Why This Benchmark Tests MCP Value

### Without MCP (Baseline)

- Agent only sees undocumented code in the task directory
- Must infer purpose from function names, types, and logic
- Cannot access KEPs, design docs, or related packages
- Limited understanding of Kubernetes conventions

### With MCP (Sourcegraph Tools)

- Can search for related documentation in kubernetes/enhancements
- Can find similar packages and their documentation
- Can discover community design discussions
- Can understand cross-package relationships
- Can find historical context from commit messages

## Related Work

This benchmark builds on:

- [CodeContextBench big_code_mcp](../big_code_mcp/) - Large codebase tasks
- [dependeval](../dependeval_benchmark/) - Multi-file reasoning
- [10figure](../10figure/) - Enterprise codebase understanding

## References

1. [Kubernetes Enhancement Proposals](https://github.com/kubernetes/enhancements)
2. [Kubernetes Community Docs](https://github.com/kubernetes/community)
3. [Go Documentation Conventions](https://go.dev/doc/comment)
4. [Kubernetes Contributor Guide](https://github.com/kubernetes/community/tree/master/contributors/devel)
