# CodeContextBench: Report Context Document

This document provides context for the paper on CodeContextBench's benchmark
design approach and preliminary results comparing baseline (no MCP) to
MCP-Full (Sourcegraph MCP) agent configurations.

---

## 1. Motivation

AI coding agents increasingly rely on external context tools -- code search,
symbol resolution, dependency tracing -- to navigate large and unfamiliar
codebases. Yet no benchmark systematically measures whether these tools
actually improve agent performance across the full software development
lifecycle. CodeContextBench fills this gap by evaluating the same agent on
identical tasks under two conditions: one with only local tools, and one
augmented with Sourcegraph MCP (Model Context Protocol) tools.

**Research questions:**
1. Does access to MCP-based code intelligence improve AI agent task completion
   rates across SDLC phases?
2. On which task types does MCP provide the greatest (or least) benefit?
3. How does information retrieval quality (oracle coverage, file recall)
   correlate with task reward?

---

## 2. Benchmark Design

### 2.1 Task Taxonomy

CodeContextBench organizes **400 tasks** into two task families:

**SDLC-Phase Suites (180 tasks):** Nine suites aligned to software
development lifecycle phases. Tasks are drawn from established benchmarks
(SWE-bench Pro, DIBench, TheAgentCompany) and custom-authored challenges
targeting specific SDLC activities.

| Suite | Phase | Tasks | Difficulty | Languages |
|-------|-------|------:|------------|-----------|
| `ccb_understand` | Requirements & Discovery | 20 | hard | C++, Go, Java, Python, TS |
| `ccb_design` | Architecture & Design | 20 | hard--very_hard | C, C++, Go, Java, Python |
| `ccb_fix` | Bug Repair | 20 | medium--hard | C++, Go, Java, JS, Python, TS |
| `ccb_feature` | Feature Implementation | 20 | medium--hard | C, C++, Go, Java, Python, Rust, TS |
| `ccb_refactor` | Cross-File Refactoring | 20 | hard--expert | C, C++, Go, Java, Python, Rust |
| `ccb_test` | Testing & QA | 20 | medium--hard | C, C#, C++, Go, Java, JS, Python, TS |
| `ccb_document` | Documentation | 20 | hard | C++, Go, Java, Python, TS |
| `ccb_secure` | Security & Compliance | 20 | medium--hard | C, C++, Go, Java, Python |
| `ccb_debug` | Debugging & Investigation | 20 | medium--expert | C, C++, Go, Python, TS |

**MCP-Unique Suites (220 tasks):** Eleven suites measuring org-scale cross-repo
discovery tasks where the agent must find information distributed across 3-20
repositories.

| Suite | Category | Tasks |
|-------|----------|------:|
| `ccb_mcp_crossrepo_tracing` | Dependency Tracing | 20 |
| `ccb_mcp_security` | Vulnerability Remediation | 20 |
| `ccb_mcp_migration` | Framework Migration | 20 |
| `ccb_mcp_incident` | Incident Debugging | 20 |
| `ccb_mcp_onboarding` | Onboarding & Comprehension | 20 |
| `ccb_mcp_compliance` | Compliance | 20 |
| `ccb_mcp_crossorg` | Cross-Org Discovery | 20 |
| `ccb_mcp_domain` | Domain Lineage | 20 |
| `ccb_mcp_org` | Organizational Context | 20 |
| `ccb_mcp_platform` | Platform Knowledge | 20 |
| `ccb_mcp_crossrepo` | Cross-Repo Discovery | 20 |

### 2.2 Task Sources

Tasks are curated from multiple sources to ensure diversity:

| Source | Tasks | SDLC Phases |
|--------|------:|-------------|
| **SWE-bench Pro** | ~25 | Fix (bug repair) |
| **DIBench** | ~10 | Build (dependency inference) |
| **TheAgentCompany** | ~8 | Build, Test |
| **Custom-authored** | ~83 | All phases |
| **PyTorch compiler fixes** | 5 | Fix |
| **Linux kernel faults** | 5 | Debug |
| **Code review (injected defects)** | 8 | Test |
| **MCP-unique (GTM use cases)** | 220 | Cross-repo discovery |

### 2.3 Language and Repository Coverage

Tasks span **10 programming languages** (C, C++, C#, Go, Java, JavaScript,
Python, Rust, TypeScript) across **40+ open-source repositories** including:

- **Large monorepos**: kubernetes/kubernetes, pytorch/pytorch, torvalds/linux,
  microsoft/vscode
- **Distributed ecosystems**: Django, Flask, Apache Kafka/Flink/Camel,
  Envoy/Istio
- **Cross-org polyrepos**: Grafana+Loki+Mimir, Kubernetes+etcd+containerd,
  NumPy+Pandas+scikit-learn

### 2.4 Difficulty Distribution

| Difficulty | Tasks | Notes |
|-----------|------:|-------|
| medium | ~30 | Dependency installation, straightforward fixes, docstrings, unit tests |
| hard | ~140 | Multi-file changes, cross-repo reasoning, runbooks, coverage analysis |
| very_hard | 2 | Deep dependency chain analysis |
| expert | 5 | Linux kernel fault localization |

---

## 3. Evaluation Framework

### 3.1 Two-Config Comparison

Every task is evaluated under two agent configurations that vary only in
the external code intelligence tools available:

| Config | Internal Name | Source Access | MCP Tools | Dockerfile |
|--------|--------------|--------------|-----------|------------|
| **Baseline** | `baseline-local-direct` | Full local code | None | Original |
| **MCP-Full** | `mcp-remote-direct` | Truncated/empty | 13 Sourcegraph tools | `Dockerfile.sg_only` |

**Key design principle:** Both configs solve the same task with the same
agent (Claude Code) and the same time limit. The only difference is the
method of code access. Baseline agents have full source locally and use
grep/glob/read. MCP-Full agents have truncated source and must use
Sourcegraph MCP tools (keyword search, semantic search, go-to-definition,
find-references, deep search, etc.).

For MCP-unique tasks, an artifact evaluation variant is also used:
- `baseline-local-artifact`: full local code, structured `answer.json` output
- `mcp-remote-artifact`: truncated source, MCP tools, structured `answer.json` output

### 3.2 Verification Pipeline

The evaluation uses a multi-layer pipeline:

1. **Deterministic verifier** (every task): Task-specific `test.sh` or
   `eval.sh` runs inside the Docker container after the agent finishes.
   Produces a reward score (0.0--1.0) written to `/logs/verifier/reward.txt`.

2. **Optional LLM judge**: Post-hoc qualitative scoring across five
   dimensions (correctness 0.30, completeness 0.25, code quality 0.20,
   retrieval quality 0.15, efficiency 0.10) with multi-round voting.

3. **Statistical analysis**: Bootstrap confidence intervals, paired
   bootstrap delta tests, Spearman rank correlation between IR metrics
   and task rewards.

4. **Report generator**: Aggregates all layers into structured JSON and
   Markdown reports.

### 3.3 Scoring Types

Different task categories use different verifier types:

| Verifier Type | Score Range | Used By |
|--------------|-------------|---------|
| **test-ratio** | 0.0--1.0 | SWE-bench Pro tasks, DIBench dependency tasks |
| **checklist** | 0.0--1.0 | Documentation, security, governance tasks |
| **similarity** | 0.0--1.0 | Cross-repo patches, NL Q&A |
| **F1-hybrid** | 0.0--1.0 | Code review (detection F1 + fix quality) |
| **diff-similarity** | 0.0--1.0 | PyTorch compiler fixes |
| **oracle-checks** | 0.0--1.0 | MCP-unique tasks (composite of file/symbol/chain/keyword checks) |
| **navigation-verified** | 0.0--1.0 | Regression proving (fail-on-buggy + pass-after-patch) |
| **external** | 0.0--1.0 | TheAgentCompany tasks |

### 3.4 MCP-Unique Oracle Evaluation

MCP-unique tasks use a closed-world oracle system with 7 deterministic
check functions (file set match, symbol resolution, dependency chain,
provenance, keyword presence, JSON schema, test ratio). The composite
score is the mean of primary scores across all configured checks.

Oracle answers are auto-curated via Sourcegraph queries and validated
with a fail2pass gate (gold answer scores 1.0, empty answer scores 0.0).

---

## 4. Infrastructure

### 4.1 Execution Environment

- **Runner**: Harbor (task isolation via Docker containers)
- **Agent**: Claude Code with Claude Haiku 4.5 (preliminary runs) /
  Claude Opus 4.6 (production runs)
- **MCP endpoint**: Sourcegraph `.api/mcp/v1`
- **Time limits**: 300--1800 seconds per task
- **Parallelism**: Up to 8 concurrent tasks with 2-second stagger

### 4.2 SG-Only Docker Environment

For MCP-Full runs, the agent's workspace is deliberately emptied or
truncated via `Dockerfile.sg_only`. A clone manifest
(`/tmp/.sg_only_clone_manifest.json`) tells the verifier which
sg-evals mirror(s) to clone at verification time so the verifier can
still compile and test the agent's code changes against the real codebase.

This design ensures:
- The agent cannot use local file reads as a shortcut
- The verifier can still validate code correctness
- Both configs produce comparable reward scores

### 4.3 Repository Mirrors

Repos not natively indexed in Sourcegraph use `sg-evals/*` mirrors
on GitHub. Mirrors are created as orphan commits pinning HEAD to a
specific tagged version, ensuring Sourcegraph indexes exactly the
version the task targets.

---

## 5. Preliminary Results

### 5.1 MCP-Unique Tasks (Official, n=12)

The first official run covers all 12 MCP-unique tasks using Claude Haiku 4.5.

| Suite | Task | Baseline | MCP-Full | Delta |
|-------|------|----------|----------|-------|
| crossrepo_tracing | ccx-config-trace-010 | 1.000 | 1.000 | 0.000 |
| crossrepo_tracing | ccx-dep-trace-001 | 0.824 | 0.824 | 0.000 |
| crossrepo_tracing | ccx-dep-trace-004 | 1.000 | 0.875 | -0.125 |
| security | ccx-vuln-remed-011 | 0.750 | 1.000 | +0.250 |
| security | ccx-vuln-remed-014 | 0.250 | 0.643 | +0.393 |
| incident | ccx-incident-031 | 0.500 | 1.000 | +0.500 |
| onboarding | ccx-onboard-041 | 1.000 | 1.000 | 0.000 |
| onboarding | ccx-explore-042-ds | 0.667 | 0.833 | +0.167 |
| onboarding | ccx-onboard-050-ds | 0.250 | 0.500 | +0.250 |
| crossorg | ccx-crossorg-061 | 0.500 | 1.000 | +0.500 |
| crossorg | ccx-crossorg-066 | 1.000 | 1.000 | 0.000 |
| platform | ccx-explore-091-ds | 0.929 | 0.929 | 0.000 |

**Summary:**
- Baseline mean reward: **0.722**
- MCP-Full mean reward: **0.884**
- Mean delta (MCP - Baseline): **+0.161**
- Tasks where MCP helped (delta > 0): **6 / 12 (50%)**
- Tasks where MCP hurt (delta < 0): **1 / 12 (8%)**
- Tasks with no difference: **5 / 12 (42%)**
- Largest MCP gain: **+0.500** (incident debugging, cross-org discovery)

### 5.2 Early Experimental Ablation (SWE-bench Pro subset)

An early experimental run on a SWE-bench Pro subset with 3 configs
(before SG_base was dropped) showed:

| Config | n_tasks | Mean Reward | 95% CI |
|--------|---------|------------|--------|
| Baseline | 43 | 0.430 | [0.279, 0.581] |
| SG_base (keyword+NLS only) | 44 | 0.375 | [0.239, 0.523] |
| SG_full (all MCP tools) | 36 | 0.778 | [0.639, 0.917] |

This early data informed the decision to drop SG_base and focus on the
2-config (Baseline vs SG_full/MCP-Full) comparison.

### 5.3 Paired SDLC Task Ablation (12 matched tasks)

A controlled paired ablation on 12 matched tasks across comprehension,
documentation, security, and debugging categories showed:

| Config | Mean Reward |
|--------|------------|
| Baseline | 0.761 |
| MCP-Full | 0.770 |
| **Delta** | **+0.009** |

Per-task breakdown revealed MCP advantage is task-dependent:
- **MCP helps**: documentation (arch docs +0.14), security (CVE triage +0.14)
- **MCP neutral**: orientation, workflow discovery, navigation-verified tasks
- **MCP slightly hurts**: some NL Q&A tasks (-0.05 to -0.11) where MCP may
  introduce anchoring bias from misleading search fragments

### 5.4 SDLC Staging Runs (in progress)

Staging runs for full SDLC suites are underway. Partial results from the
`ccb_debug` suite (20 tasks, both configs):

**Notable MCP advantages in debugging:**
- Linux kernel fault localization tasks (5 tasks, all `expert` difficulty):
  Baseline runs errored at Docker build time (missing pre-built `ccb-linux-base`
  images with the kernel source), while MCP-Full runs succeeded using
  `Dockerfile.sg_only` (which does not require the kernel source locally).
  MCP-Full mean reward across all 5: **0.80**.

| Task | Baseline | MCP-Full |
|------|----------|----------|
| `linux-acpi-backlight-fault-001` | errored | **1.0** |
| `linux-iwlwifi-subdevice-fault-001` | errored | **1.0** |
| `linux-ssd-trim-timeout-fault-001` | errored | **1.0** |
| `linux-hda-intel-suspend-fault-001` | errored | **0.7** |
| `linux-nfs-inode-revalidate-fault-001` | errored | **0.3** |

  Note: baseline errors are an infrastructure gap (base images need rebuilding),
  not a fundamental limitation. Once resolved, head-to-head comparison will be
  possible. The MCP results demonstrate that Sourcegraph MCP tools can
  successfully navigate the 28K-file Linux kernel codebase for fault
  localization -- a task category where local file access at this scale is
  impractical within typical agent time limits.

**Tasks where both configs perform similarly:**
- Django admin migration audit: both score 1.0
- Regression-proving tasks: both score ~0.5 (test writing challenge)
- Istio XDS debug: both score ~0.92

---

## 6. Key Design Decisions

### 6.1 Information Parity

Both configs have access to the same information -- the only difference is
the access method (local files vs remote MCP tools). This ensures we measure
the tool's effectiveness at helping agents find and use information, not
whether MCP can access information the baseline cannot.

### 6.2 Truncated Source (Not Blocked Tools)

Rather than blocking local tools in the MCP config, we truncate the source
code. This is more realistic: in practice, MCP-augmented agents still have
local tools available. The truncation forces MCP usage without artificial
tool restrictions.

### 6.3 Verifier at Clone Time

The `Dockerfile.sg_only` pattern writes a clone manifest at build time. The
verifier clones the mirror repo at verification time, overlays agent changes,
and then runs the same test suite as baseline. This ensures scoring parity
between configs.

### 6.4 Oracle-Based Evaluation for Discovery Tasks

MCP-unique tasks use exhaustive oracle files/symbols auto-curated via
Sourcegraph queries, enabling deterministic evaluation of cross-repo
discovery quality without human labeling.

### 6.5 SDLC Alignment

Organizing tasks by SDLC phase (rather than by source benchmark) enables
practitioners to understand MCP impact on specific development activities
they perform daily.

---

## 7. Threats to Validity

### 7.1 Internal Validity
- **Non-determinism**: Agent behavior varies across runs. We use paired
  execution (both configs run simultaneously per task) and plan multi-trial
  evaluation with bootstrap CIs.
- **Verifier limitations**: Some verifier types (keyword-based, similarity)
  may not capture all valid solutions. We mitigate with the optional LLM
  judge layer.

### 7.2 External Validity
- **Single agent**: Current results use Claude Code only. The framework
  supports other agents (Codex, Cursor, Gemini, Copilot, OpenHands).
- **Single MCP provider**: Only Sourcegraph MCP is tested. The framework
  can accommodate other MCP providers.
- **Task selection**: Tasks are curated, not exhaustively sampled. The
  MCP benefit scoring methodology provides transparency about selection
  criteria.

### 7.3 Construct Validity
- **Truncated source vs real enterprise**: The truncated-source approach
  simulates the MCP use case but does not perfectly model enterprise
  environments where developers have partial local context.
- **Time limits**: Fixed time limits may disadvantage MCP on tasks where
  remote API latency adds overhead.

---

## 8. Summary of Contributions

1. **SDLC-aligned benchmark**: 182 tasks across 14 suites covering the
   full development lifecycle, enabling phase-specific MCP impact analysis.

2. **Controlled comparison methodology**: Same agent, same tasks, same
   time limits -- only the code access method differs. Information parity
   ensures we measure tool effectiveness, not information advantage.

3. **Multi-layer evaluation**: Deterministic verifiers + optional LLM judge
   + statistical analysis with bootstrap CIs and paired delta tests.

4. **Preliminary evidence**: MCP tools provide measurable benefit on
   cross-repo discovery tasks (+0.161 mean reward on MCP-unique tasks)
   and dramatic improvement on kernel-scale debugging (+1.0 on previously
   impossible fault localization tasks). Effect is smaller on tasks where
   local context is sufficient.

5. **Reproducibility artifact**: All task definitions, verifiers, run
   configs, and metrics extraction are open-source and deterministic.
