# PRD: SDLC-Aligned Suite Reorganization

**Status:** Implemented (2026-02-18)
**Author:** Benchmark Engineering
**Date:** 2026-02-17
**Stakeholders:** Benchmark maintainers, evaluation consumers, paper authors

**Current state:** CodeContextBench now has **157 tasks** in **8 SDLC-phase suites**. Canonical task list: `configs/selected_benchmark_tasks.json` (v2.0). This PRD is retained for rationale and migration history.

---

## 1. Problem Statement (Pre-Reorganization)

CodeContextBench previously organized 186 tasks across 17 suites named by their *origin* (swebenchpro, pytorch, tac, dibench) or by a narrow *capability* (navprove, codereview, linuxflbench). That created three problems:

1. **Unclear SDLC mapping.** Stakeholders cannot quickly answer "how well do we cover the design phase?" because architecture tasks are scattered across `ccb_largerepo`, `ccb_crossrepo`, `ccb_enterprise`, and `ccb_investigation`.

2. **Imbalanced suite sizes.** Suite sizes range from 3 (sweperf) to 36 (swebenchpro). This distorts per-suite aggregate metrics and makes cross-suite comparisons unreliable.

3. **Weak enterprise justification.** The current naming does not map to enterprise development workflows. A CISO or VP Engineering evaluating the benchmark cannot see at a glance that their team's activities -- code review, security triage, architecture analysis, onboarding -- are each represented by a dedicated, balanced evaluation suite.

## 2. Goals

| # | Goal | Measure of Success |
|---|------|-------------------|
| G1 | Every suite maps to one recognizable SDLC phase | Suite names and descriptions self-evidently correspond to enterprise workflow stages |
| G2 | Balanced suite sizes | Phase 1: all suites between 13 and 25 tasks; Phase 2+: all suites between 15 and 25 tasks (target: 20) |
| G3 | No task belongs to more than one suite | Clean 1:1 mapping from task ID to suite |
| G4 | Preserve evaluation continuity | Every retained task keeps its `task.toml`, verifier, and Dockerfile unchanged |
| G5 | Identify and plan for coverage gaps | Each suite has a "planned growth" section for new tasks |
| G6 | Use MCP as a monitoring signal, not a hard gate | Suite-level MCP is reported and reviewed; low-MCP suites require written rationale and follow-up plans |

## 3. Non-Goals

- Changing task content, verifiers, or scoring semantics (those are unchanged).
- Creating new tasks in this phase (gap tasks are identified but built in Phase 2).
- Modifying the 2-config evaluation matrix (baseline, SG_full).
- Removing archived suites (locobench, repoqa, dependeval, k8sdocs remain in `benchmarks/archive/`).

## 4. Proposed Suite Structure

### 4.1 Eight SDLC-Aligned Suites

| Suite | SDLC Phase | Description | Phase 1 Tasks | Target |
|-------|-----------|-------------|:---:|:---:|
| **ccb_understand** | Requirements & Discovery | Map unfamiliar codebases, answer architectural questions, onboard to projects, recover institutional knowledge | 20 | 20 |
| **ccb_design** | Architecture & Design | Analyze system architecture, evaluate design trade-offs, trace dependency graphs, assess change impact | 20 | 20 |
| **ccb_fix** | Implementation -- Bug Repair | Diagnose and fix real bugs in production codebases, from single-file patches to multi-module debugging | 25 | 25 |
| **ccb_build** | Implementation -- Feature & Refactoring | Build new features, refactor existing code, manage build dependencies, implement cross-cutting changes | 25 | 25 |
| **ccb_test** | Testing & Quality Assurance | Review code for defects, assess performance, validate code quality, write tests | 14 | 20 |
| **ccb_document** | Documentation | Generate API references, architecture guides, and migration documentation from source code | 13 | 20 |
| **ccb_secure** | Security & Compliance | Analyze CVEs, assess vulnerability reachability, enforce governance policies, implement access controls | 20 | 20 |
| **ccb_debug** | Debugging & Investigation | Trace root causes through deep causal chains, navigate provenance, localize faults in large systems | 20 | 20 |

**Phase 1 total:** 157 tasks (from the current frozen inventory snapshot, retiring 29 lowest-signal tasks)
**Phase 2 target:** 165 tasks (filling `ccb_test` and `ccb_document` to 20 each)

### 4.2 Suite Size Constraints

| Constraint | Phase 1 | Phase 2+ | Rationale |
|-----------|---------|----------|-----------|
| **Minimum** | 13 | 15 | Phase 1: >=13 gives meaningful confidence intervals at p<0.05; Phase 2+: 15 once gap tasks are authored |
| **Target** | 20 | 20 | Balance: 8 suites x 20 = 160 tasks; manageable run time (~3h per suite per config) |
| **Maximum** | 25 | 25 | Ceiling: caps the two implementation suites where task supply is naturally larger |

### 4.3 Selection Criteria for Capped Suites

When a source suite contributes more tasks than a target suite can accept, selection follows this priority order:

1. **Coverage constraints first** -- language families covered, difficulty mix maintained, and repository cap enforced
2. **Task-shape diversity** -- include both single-file and multi-file change tasks where available
3. **Language diversity** -- at least 3 languages per suite; proportional representation within language
4. **Repository diversity** -- no single repository contributes more than 40% of a suite
5. **Difficulty range** -- at least 2 difficulty levels represented per suite

Tie-breakers (applied in order for tasks that still tie after criteria above):
1. Lower current repository share in target suite
2. Underrepresented language
3. Underrepresented difficulty band
4. Underrepresented verifier type
5. Higher MCP benefit score
6. Lexicographic `task_id` (stable fallback)

---

## 5. Detailed Task Migration

### 5.1 ccb_understand -- Requirements & Discovery (20 tasks)

Understanding unfamiliar codebases: answering questions about architecture, data flow, and debugging scenarios; onboarding to projects; recovering fragmented knowledge.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| onboard-handoff-001 | ccb_onboarding | Team handoff | C++ | 0.86 |
| onboard-handoff-002 | ccb_onboarding | Team handoff | Go | 0.86 |
| onboard-handoff-003 | ccb_onboarding | Team handoff | Go | 0.86 |
| onboard-orient-001 | ccb_onboarding | Codebase orientation | Go | 0.83 |
| onboard-orient-002 | ccb_onboarding | Codebase orientation | Go | 0.83 |
| onboard-orient-003 | ccb_onboarding | Codebase orientation | Java | 0.83 |
| onboard-workflow-001 | ccb_onboarding | Workflow discovery | C++ | 0.77 |
| onboard-workflow-002 | ccb_onboarding | Workflow discovery | Java | 0.77 |
| nlqa-arch-001 | ccb_nlqa | Architecture Q&A | C++ | 0.86 |
| nlqa-arch-002 | ccb_nlqa | Architecture Q&A | Go | 0.86 |
| nlqa-arch-003 | ccb_nlqa | Architecture Q&A | Go | 0.86 |
| nlqa-debug-001 | ccb_nlqa | Debug Q&A | TypeScript | 0.79 |
| nlqa-debug-002 | ccb_nlqa | Debug Q&A | Go | 0.79 |
| nlqa-flow-001 | ccb_nlqa | Data flow Q&A | Java | 0.85 |
| nlqa-flow-002 | ccb_nlqa | Data flow Q&A | C++ | 0.85 |
| nlqa-flow-003 | ccb_nlqa | Data flow Q&A | Go | 0.85 |
| institutional-memory-001 | ccb_enterprise | Institutional memory | Python | 0.82 |
| knowledge-fragmentation-001 | ccb_enterprise | Knowledge fragmentation | Python | 0.88 |
| bug_localization_01 | ccb_crossrepo | Cross-repo bug localization | Python | 0.90 |
| cross_file_reasoning_01 | ccb_crossrepo | Cross-file reasoning | Go | 0.92 |

**Languages:** Go (7), C++ (3), Python (3), Java (3), TypeScript (1), mixed (3)
**Verifier types:** Weighted checklist (16), similarity (4)
**Avg MCP score:** 0.85

### 5.2 ccb_design -- Architecture & Design Analysis (20 tasks)

Analyzing system architecture at scale, tracing dependency graphs, evaluating change impact, and resolving cross-repository relationships.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| big-code-camel-arch-001 | ccb_largerepo | Architecture analysis | Java | 0.90 |
| big-code-cross-capmarkets-arch-001 | ccb_largerepo | Architecture analysis | Java | 0.90 |
| big-code-cross-k8s-arch-001 | ccb_largerepo | Architecture analysis | Go | 0.90 |
| big-code-django-arch-001 | ccb_largerepo | Architecture analysis | Python | 0.90 |
| big-code-flink-arch-001 | ccb_largerepo | Architecture analysis | Java | 0.90 |
| big-code-k8s-arch-001 | ccb_largerepo | Architecture analysis | Go | 0.90 |
| big-code-pg-arch-001 | ccb_largerepo | Architecture analysis | C | 0.90 |
| big-code-quantlib-arch-001 | ccb_largerepo | Architecture analysis | C++ | 0.90 |
| crossrepo-chain-001 | ccb_crossrepo | Dependency chain | Go | 0.92 |
| crossrepo-chain-002 | ccb_crossrepo | Dependency chain | Go | 0.92 |
| crossrepo-sym-001 | ccb_crossrepo | Symbol resolution | Go | 0.88 |
| crossrepo-sym-002 | ccb_crossrepo | Symbol resolution | C++ | 0.88 |
| crossrepo-sym-003 | ccb_crossrepo | Symbol resolution | Go | 0.88 |
| api_upgrade_01 | ccb_crossrepo | API upgrade analysis | Go | 0.88 |
| dep-impact-001 | ccb_enterprise | Impact analysis | Python | 0.92 |
| dep-discovery-001 | ccb_enterprise | Dependency discovery | Go | 0.85 |
| stale-architecture-001 | ccb_enterprise | Stale architecture | Python | 0.85 |
| polyglot-ecosystem-001 | ccb_enterprise | Polyglot analysis | Go | 0.86 |
| conflicting-docs-001 | ccb_enterprise | Conflicting docs | Python | 0.78 |
| inv-impact-001 | ccb_investigation | Impact analysis | Go | 0.92 |

**Languages:** Go (10), Python (3), Java (3), C++ (2), C (1), mixed (1)
**Verifier types:** IR checklist (8), F1 JSON (6), weighted checklist (4), similarity (2)
**Avg MCP score:** 0.89

### 5.3 ccb_fix -- Bug Diagnosis & Repair (25 tasks)

Finding, understanding, and fixing real bugs across production codebases. Ranges from single-file patches to multi-module debugging requiring deep code comprehension.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| *15 selected from ccb_swebenchpro* | ccb_swebenchpro | Bug fix | Multi | 0.59-0.76 |
| sgt-008 | ccb_pytorch | Bug fix | C++ | 0.81 |
| sgt-010 | ccb_pytorch | Bug fix | C++ | 0.61 |
| sgt-003 | ccb_pytorch | Bug fix | C++ | 0.58 |
| sgt-002 | ccb_pytorch | Bug fix | C++ | 0.57 |
| sgt-014 | ccb_pytorch | Bug fix | C++ | 0.57 |
| big-code-django-bug-001 | ccb_largerepo | Debugging | Python | 0.87 |
| big-code-k8s-bug-001 | ccb_largerepo | Debugging | Go | 0.87 |
| big-code-kafka-bug-001 | ccb_largerepo | Debugging | Java | 0.87 |
| multi-team-ownership-001 | ccb_enterprise | Multi-team bug fix | Python | 0.83 |
| multi-team-ownership-002 | ccb_enterprise | Multi-team bug fix | Go | 0.83 |

**SWE-bench Pro selection (15 from 36):** Coverage-first selection with MCP as tie-breaker. Hard constraints: at least 1 task per language family (Go, TypeScript, Python, JavaScript), at most 4 tasks per repository, and mixed task shapes (single-file and multi-file fixes). Target difficulty mix: ~40% hard, ~40% medium, <=20% easy.

**Languages:** Go (5+), TypeScript (3+), Python (3+), C++ (5), JavaScript (2+), Java (1)
**Verifier types:** test-ratio (15), diff-similarity (5), checklist (5)
**Avg MCP score:** 0.72

### 5.4 ccb_build -- Feature Engineering & Refactoring (25 tasks)

Building new capabilities, refactoring existing code, managing build dependencies, and implementing cross-cutting changes.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| big-code-k8s-001 | ccb_largerepo | Feature implementation | Go | 0.90 |
| big-code-servo-001 | ccb_largerepo | Feature implementation | Rust | 0.90 |
| big-code-trt-001 | ccb_largerepo | Feature implementation | Python/C++ | 0.90 |
| big-code-vsc-001 | ccb_largerepo | Feature implementation | TypeScript | 0.90 |
| big-code-camel-feat-001 | ccb_largerepo | Feature implementation | Java | 0.90 |
| big-code-flink-feat-001 | ccb_largerepo | Feature implementation | Java | 0.90 |
| big-code-strata-feat-001 | ccb_largerepo | Feature implementation | Java | 0.90 |
| big-code-k8s-refac-001 | ccb_largerepo | Refactoring | Go | 0.87 |
| big-code-kafka-refac-001 | ccb_largerepo | Refactoring | Java | 0.87 |
| big-code-rust-refac-001 | ccb_largerepo | Refactoring | Rust | 0.87 |
| big-code-strata-refac-001 | ccb_largerepo | Refactoring | Java | 0.87 |
| crossrepo-impl-001 | ccb_crossrepo | Cross-repo implementation | Go | 0.88 |
| crossrepo-impl-002 | ccb_crossrepo | Cross-repo implementation | Go | 0.88 |
| refactor_rename_01 | ccb_crossrepo | Cross-repo rename | Python | 0.87 |
| dep-refactor-001 | ccb_enterprise | Dependency refactoring | Go | 0.89 |
| dep-refactor-002 | ccb_enterprise | Dependency refactoring | Go | 0.89 |
| tac-buffer-pool-manager | ccb_tac | Feature implementation | C++ | 0.49 |
| dibench-csharp-dotnetkoans | ccb_dibench | Dependency inference | C# | 0.73 |
| dibench-csharp-irongut-codecoveragesummary | ccb_dibench | Dependency inference | C# | 0.73 |
| dibench-js-eslint-markdown | ccb_dibench | Dependency inference | JavaScript | 0.73 |
| dibench-js-motdotla-dotenv-expand | ccb_dibench | Dependency inference | JavaScript | 0.73 |
| dibench-python-inducer-cgen | ccb_dibench | Dependency inference | Python | 0.73 |
| dibench-python-rhinosec-iamactionhunter | ccb_dibench | Dependency inference | Python | 0.73 |
| dibench-rust-mitsuhiko-similar-asserts | ccb_dibench | Dependency inference | Rust | 0.73 |
| dibench-rust-rusticata-pcap-parser | ccb_dibench | Dependency inference | Rust | 0.73 |

**Languages:** Go (5), Java (5), Rust (3), Python (3), C++ (2), C# (2), JavaScript (2), TypeScript (1), mixed (2)
**Verifier types:** IR checklist (7), similarity (4), test-ratio (8), checklist (4), diff (2)
**Avg MCP score:** 0.83

### 5.5 ccb_test -- Testing & Quality Assurance (14 tasks, growing to 20)

Reviewing code for injected defects, assessing performance, validating quality, and finding specific code patterns.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| cr-aspnetcore-001 | ccb_codereview | Code review | C# | 0.84 |
| cr-calcom-001 | ccb_codereview | Code review | TypeScript | 0.83 |
| cr-envoy-001 | ccb_codereview | Code review | C++ | 0.72 |
| cr-ghost-001 | ccb_codereview | Code review | JavaScript | 0.82 |
| cr-security-001 | ccb_codereview | Code review | C | 0.72 |
| cr-security-002 | ccb_codereview | Code review | Java | 0.72 |
| cr-terraform-001 | ccb_codereview | Code review | Go | 0.72 |
| cr-vscode-001 | ccb_codereview | Code review | TypeScript | 0.72 |
| sweperf-001 | ccb_sweperf | Performance testing | Python | 0.46 |
| sweperf-002 | ccb_sweperf | Performance testing | Python | 0.46 |
| sweperf-003 | ccb_sweperf | Performance testing | Python | 0.46 |
| tac-find-in-codebase-1 | ccb_tac | Code search validation | C++ | 0.58 |
| tac-find-in-codebase-2 | ccb_tac | Code search validation | C++ | 0.58 |
| tac-write-unit-test | ccb_tac | Test writing | Python | 0.47 |

**Languages:** C++ (3), Python (4), TypeScript (2), C# (1), JavaScript (1), C (1), Go (1), Java (1)
**Verifier types:** F1-hybrid (8), external (3), deterministic (3)
**Avg MCP score:** 0.65
**Gap:** 6 tasks needed to reach target of 20 (see Section 7)

### 5.6 ccb_document -- Documentation Generation (13 tasks, growing to 20)

Generating accurate API documentation, architecture guides, and migration plans by reading and understanding source code.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| docgen-api-001 | ccb_docgen | API reference | TypeScript | 0.85 |
| docgen-api-002 | ccb_docgen | API reference | Go | 0.85 |
| docgen-api-003 | ccb_docgen | API reference | Java | 0.85 |
| docgen-arch-001 | ccb_docgen | Architecture doc | C++ | 0.87 |
| docgen-arch-002 | ccb_docgen | Architecture doc | Go | 0.87 |
| docgen-arch-003 | ccb_docgen | Architecture doc | Go | 0.87 |
| docgen-k8s-apiserver-001 | ccb_docgen | Package docs | Go | 0.87 |
| docgen-k8s-applyconfig-001 | ccb_docgen | Package docs | Go | 0.87 |
| docgen-k8s-clientgo-001 | ccb_docgen | Package docs | Go | 0.87 |
| docgen-k8s-cm-001 | ccb_docgen | Package docs | Go | 0.87 |
| docgen-k8s-fairqueuing-001 | ccb_docgen | Package docs | Go | 0.87 |
| docgen-migration-001 | ccb_docgen | Migration guide | Go | 0.80 |
| docgen-migration-002 | ccb_docgen | Migration guide | C++ | 0.80 |

**Languages:** Go (8), C++ (2), TypeScript (1), Java (1), mixed (1)
**Verifier types:** Checklist with keyword matching (13)
**Avg MCP score:** 0.86
**Gap:** 7 tasks needed to reach target of 20 (see Section 7)

### 5.7 ccb_secure -- Security & Compliance (20 tasks)

Analyzing CVEs, assessing reachability of vulnerabilities, enforcing governance policies, and implementing security-conscious code patterns.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| sec-cve-001 | ccb_security | CVE analysis | C | 0.87 |
| sec-cve-002 | ccb_security | CVE analysis | C++ | 0.87 |
| sec-cve-003 | ccb_security | CVE analysis | Go | 0.87 |
| sec-reach-001 | ccb_security | Reachability | C | 0.88 |
| sec-reach-002 | ccb_security | Reachability | C++ | 0.88 |
| sec-reach-003 | ccb_security | Reachability | Java | 0.88 |
| sec-transitive-001 | ccb_security | Transitive deps | Go | 0.86 |
| sec-transitive-002 | ccb_security | Transitive deps | Go | 0.86 |
| audit-trail-001 | ccb_governance | Audit trail | Python | 0.80 |
| cross-team-boundary-001 | ccb_governance | Team boundary | Python | 0.83 |
| degraded-context-001 | ccb_governance | Degraded context | Go | 0.90 |
| policy-enforcement-001 | ccb_governance | Policy enforcement | Python | 0.75 |
| repo-scoped-access-001 | ccb_governance | Repo access | Python | 0.80 |
| repo-scoped-access-002 | ccb_governance | Repo access | Go | 0.80 |
| role-based-access-001 | ccb_governance | RBAC | Python | 0.80 |
| sensitive-file-exclusion-001 | ccb_governance | File exclusion | Python | 0.76 |
| big-code-django-sec-001 | ccb_largerepo | Security review | Python | 0.88 |
| big-code-kafka-sec-001 | ccb_largerepo | Security review | Java | 0.88 |
| big-code-pg-sec-001 | ccb_largerepo | Security review | C | 0.88 |
| legacy-dependency-001 | ccb_enterprise | Legacy deps | Python | 0.80 |

**Languages:** Python (8), Go (5), C (3), C++ (2), Java (2)
**Verifier types:** Checklist (12), weighted checklist (5), IR checklist (3)
**Avg MCP score:** 0.84

### 5.8 ccb_debug -- Debugging & Investigation (20 tasks)

Tracing root causes through deep causal chains, navigating code provenance, and localizing faults in large systems.

| Task ID | Source Suite | Category | Language | MCP |
|---------|-------------|----------|----------|:---:|
| navprove-ansible-vault-001 | ccb_navprove | Provenance | Python | 0.82 |
| navprove-flipt-cache-001 | ccb_navprove | Provenance | Go | 0.82 |
| navprove-qb-bookmark-001 | ccb_navprove | Provenance | Python | 0.82 |
| navprove-qb-download-001 | ccb_navprove | Provenance | Python | 0.82 |
| navprove-qb-tab-001 | ccb_navprove | Provenance | Python | 0.82 |
| navprove-qb-url-001 | ccb_navprove | Provenance | Python | 0.82 |
| navprove-teleport-ssh-001 | ccb_navprove | Provenance | Go | 0.82 |
| navprove-tutanota-search-001 | ccb_navprove | Provenance | TypeScript | 0.82 |
| navprove-vuls-oval-001 | ccb_navprove | Provenance | Go | 0.82 |
| inv-debug-001 | ccb_investigation | Cross-service debug | Go | 0.90 |
| inv-deep-001 | ccb_investigation | Deep causal chain | C++ | 0.88 |
| inv-deep-002 | ccb_investigation | Deep causal chain | Go | 0.88 |
| inv-deep-003 | ccb_investigation | Deep causal chain | Go | 0.88 |
| inv-migration-001 | ccb_investigation | Migration audit | Python | 0.88 |
| inv-regression-001 | ccb_investigation | Regression hunt | Go | 0.91 |
| lfl-acpi-207835 | ccb_linuxflbench | Kernel fault loc. | C | 0.92 |
| lfl-nfs-117651 | ccb_linuxflbench | Kernel fault loc. | C | 0.94 |
| lfl-sata-203475 | ccb_linuxflbench | Kernel fault loc. | C | 0.91 |
| lfl-sound-53441 | ccb_linuxflbench | Kernel fault loc. | C | 0.89 |
| lfl-wifi-206661 | ccb_linuxflbench | Kernel fault loc. | C | 0.89 |

**Note:** 3 investigation tasks (inv-deep-001/002/003) are newly activated from 8 unregistered tasks on disk. The remaining 5 unregistered tasks (inv-interaction-001/002/003, inv-regression-001b, inv-regression-002) are Phase 2 expansion candidates.

**Languages:** Python (5), Go (6), C (5), C++ (1), TypeScript (1), mixed (2)
**Verifier types:** Weighted checklist (15), checklist (5)
**Avg MCP score:** 0.86

---

## 6. Retired Tasks (29)

Tasks removed from active evaluation due to suite size constraints and low marginal signal.

### 6.1 SWE-bench Pro (21 tasks retired from 36)

The 15 retained tasks are selected for coverage quality first, with MCP used only as a tie-breaker after constraints are satisfied. The 21 retired tasks remain in `benchmarks/archive/ccb_swebenchpro_retired/` for reproducibility.

**Selection rule:** coverage-first Top-15, subject to:
- At least 1 task per language family (Go, TypeScript, Python, JavaScript)
- Target difficulty mix: ~40% hard, ~40% medium, <=20% easy
- At most 4 tasks from any single repository
- Include both single-file and multi-file patch tasks
- Use MCP only as tie-breaker

### 6.2 PyTorch (6 tasks retired from 11)

5 retained by difficulty and bug-shape coverage, with MCP as secondary tie-breaker: sgt-008 (hard, 0.81), sgt-010 (hard, 0.61), sgt-003 (hard, 0.58), sgt-002 (medium, 0.57), sgt-014 (medium, 0.57). The remaining 6 medium-difficulty tasks are retired as lower-signal duplicates for this phase.

### 6.3 Other (2 tasks retired)

| Task | Suite | Reason |
|------|-------|--------|
| simple_test_01 | ccb_crossrepo | Smoke test (easy difficulty, MCP 0.55); no evaluation signal |
| tac-dependency-change | ccb_tac | Lowest MCP score in benchmark (0.44); excluded TAC tasks (copilot-arena, troubleshoot) already removed |

**tac-implement-hyperloglog** (MCP 0.49) was also a retirement candidate but is retained in `ccb_build` to maintain C++ representation for feature implementation tasks.

---

## 7. Gap Analysis & Planned Growth (Phase 2)

### 7.1 Suites Below Target

| Suite | Phase 1 | Target | Gap | Planned New Tasks |
|-------|:---:|:---:|:---:|---|
| ccb_test | 14 | 20 | 6 | Test generation: unit test writing (2), integration test authoring (2), test coverage gap analysis (2) |
| ccb_document | 13 | 20 | 7 | Inline docstring generation (2), changelog generation (2), onboarding guide authoring (1), runbook writing (2) |

### 7.2 New Task Design Requirements

All Phase 2 tasks must satisfy the existing framework constraints:

| Requirement | Specification |
|------------|---------------|
| **Repository** | Must use a repo already in the benchmark's Sourcegraph index (kubernetes, django, envoy, kafka, prometheus, grafana, flipt, etc.) OR a new public repo with >50K lines |
| **Commit pin** | `pre_fix_rev` in `task.toml` pinned to exact commit hash |
| **Cross-file reasoning** | Correct solution requires reading files from >= 3 directories |
| **Verifier** | Must use one of the three proven patterns (weighted checklist, F1 JSON, diff-based code change); no LLM-only scoring |
| **MCP benefit score** | Reported as a monitoring metric; low scores must include written rationale and follow-up plan |
| **Determinism** | Ground truth derivable from the pinned commit; no subjective quality judgments |
| **Partial credit** | Continuous scoring (0.0-1.0) with weighted components; no binary pass/fail |
| **Negative checks** | Ground truth must include at least 2 patterns that penalize incorrect conclusions |

### 7.3 Full SDLC Coverage Roadmap (Phase 3)

Gaps identified in the prior audit that would extend suites beyond the current task pool. These are longer-term additions gated on repo selection and verifier design.

| Gap Area | Target Suite | Planned Tasks | Design Pattern | Expected MCP |
|----------|-------------|:---:|---|:---:|
| CI/CD pipeline authoring & debugging | ccb_build | 4 | Diff + YAML validation | 0.80-0.85 |
| Database schema migration | ccb_build | 3 | Code change + execution | 0.83-0.87 |
| Incident response / production triage | ccb_debug | 3 | Weighted checklist | 0.88-0.92 |
| API design & contract analysis | ccb_design | 3 | F1 JSON + checklist | 0.85-0.90 |
| Observability instrumentation | ccb_build | 3 | Diff verification | 0.80-0.85 |
| Deprecated API migration | ccb_build | 3 | F1 + diff hybrid | 0.85-0.90 |
| Architecture Decision Records | ccb_design | 3 | Weighted checklist | 0.90-0.94 |

**Note:** Phase 3 additions would push some suites above the 25-task cap. At that point, the lowest-signal existing tasks rotate out to maintain the cap.

---

## 8. Migration Plan

### 8.1 Directory Structure

Current structure (organized by source):

```
benchmarks/
  ccb_swebenchpro/    # 36 tasks
  ccb_largerepo/      # 25 tasks
  ccb_docgen/         # 13 tasks
  ...17 directories
```

New structure (organized by SDLC phase):

```
benchmarks/
  ccb_understand/     # 20 tasks
  ccb_design/         # 20 tasks
  ccb_fix/            # 25 tasks
  ccb_build/          # 25 tasks
  ccb_test/           # 14 tasks (growing to 20)
  ccb_document/       # 13 tasks (growing to 20)
  ccb_secure/         # 20 tasks
  ccb_debug/          # 20 tasks
  archive/            # retired + previously archived
```

### 8.2 Migration Integrity Rules

1. **Task files unchanged.** `instruction.md`, `task.toml`, `tests/`, `environment/`, and `solution/` are moved as-is. No content modifications.

2. **No `task.toml` mutation for provenance.** Provenance is recorded only in `migration_map.json` and derived reports.

3. **MANIFEST.json regenerated.** Each new suite gets a fresh `MANIFEST.json` via `scripts/generate_manifest.py`.

4. **selected_benchmark_tasks.json rebuilt.** Canonical task selection rebuilt with new `benchmark` field values.

5. **Config runners replaced.** 17 per-suite runners replaced by 8 new runners:
   ```
   configs/understand_2config.sh
   configs/design_2config.sh
   configs/fix_2config.sh
   configs/build_2config.sh
   configs/test_2config.sh
   configs/document_2config.sh
   configs/secure_2config.sh
   configs/debug_2config.sh
   ```

6. **Provenance mapping.** A `migration_map.json` at repo root records `{old_suite/task_id: new_suite/task_id}` for every task, enabling historical run comparison.

### 8.3 Validation Checklist

| Step | Command | Pass Criteria |
|------|---------|---------------|
| 1 | `python3 scripts/validate_tasks_preflight.py --all` | Zero errors across all 8 suites |
| 2 | `python3 scripts/sync_task_metadata.py --fix` | All task.toml metadata in sync |
| 3 | `python3 scripts/generate_manifest.py` | 8 valid MANIFEST.json files |
| 4 | `python3 scripts/docs_consistency_check.py` | No stale references to old suite names |
| 5 | `configs/validate_one_per_benchmark.sh --smoke-runtime` | 1 task per suite builds and verifies |
| 6 | Run snapshot coverage check (see `docs/QA_PROCESS.md` Section 8) against `docs/migration_inventory_snapshot.json` and `migration_map.json` | `coverage == 100%` (zero missing task IDs) |

---

## 9. Impact on Existing Runs & Reporting

### 9.1 Historical Comparisons

All prior runs used the 17-suite structure. To compare with new runs:

- Use `migration_map.json` to map old task IDs to new suites.
- Cross-suite aggregate metrics (e.g., "ccb_largerepo average reward") must be recomputed using the new suite membership.
- Per-task metrics are unchanged; only the grouping changes.

**Recompute command:**
```bash
python3 scripts/recompute_historical_suites.py \
    --migration-map migration_map.json \
    --run-dir runs/official/<run_name> \
    --output runs/official/<run_name>/recomputed_suites.json
```

**Inputs:**
- `migration_map.json` -- mapping version used for recomputation (recorded in output)
- `runs/official/<run_name>/` -- directory containing per-task `result.json` files

**Output:** `recomputed_suites.json` with per-suite aggregate metrics using the new 8-suite grouping. The output includes a `migration_map_version` field referencing the mapping file's `metadata.created_date` for provenance.

### 9.2 Reporting Changes

| Document | Change Required |
|----------|----------------|
| `TASK_CATALOG.md` | Rewrite: 8 sections instead of 17 |
| `TASK_SELECTION.md` | Update SDLC phase table, selection targets |
| `README.md` | Update suite table |
| `CONFIGS.md` | Update runner references |
| `SCORING_SEMANTICS.md` | Reorganize by new suite names |
| `LEADERBOARD.md` | Add per-SDLC-phase breakdowns |
| Eval report generator | Update suite grouping logic |

---

## 10. Success Metrics

| Metric | Current State | Phase 1 Target | Phase 2 Target |
|--------|:---:|:---:|:---:|
| Suites | 17 | 8 | 8 |
| Min suite size | 3 | 13 | 15 |
| Max suite size | 36 | 25 | 25 |
| Size std dev | 8.9 | 4.3 | 2.5 |
| SDLC phases covered | ambiguous (origin-named) | 8 explicitly named | 8 explicitly named |
| Avg MCP score (all tasks) | 0.76 | 0.81 (coverage-first rebalancing and retirement of lowest-signal tasks) | 0.82 |
| Active tasks | 186 | 157 | 165 |
| Tasks requiring Phase 3 | -- | -- | ~20 (gap tasks) |

---

## 11. Timeline

| Phase | Scope | Duration | Dependencies |
|-------|-------|----------|-------------|
| **Phase 1a** | Create `migration_map.json`, move task directories | 1 week | None |
| **Phase 1b** | Rebuild manifests, update configs, and emit provenance map | 1 week | Phase 1a |
| **Phase 1c** | Update documentation, run full validation | 1 week | Phase 1b |
| **Phase 2** | Author 13 new tasks for `ccb_test` and `ccb_document` | 3-4 weeks | Phase 1c |
| **Phase 3** | Author ~20 gap tasks (CI/CD, migration, incident, API, observability) | 6-8 weeks | Phase 2 |

---

## 12. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| Historical run comparisons break | Medium | High | `migration_map.json` + recompute script for historical aggregation |
| Retired SWE-bench Pro tasks questioned by reviewers | Medium | Medium | Document selection criteria; archive tasks remain reproducible |
| Phase 2 new tasks show low MCP benefit | Low | Low | Treat MCP as monitoring signal; require rationale + follow-up plan, but gate on verifier quality/determinism and preflight + smoke |
| Suite names conflict with external benchmark names | Low | Low | All prefixed `ccb_`; no collisions with SWE-bench, TAC, etc. |
| Verifier regressions from task moves | High | Low | `validate_one_per_benchmark.sh --smoke-runtime` validates every suite after migration |

---

## 13. Appendix: Complete Source-to-Target Mapping

Summary of how each current suite's tasks are distributed:

Note: totals in this appendix reflect the working draft inventory snapshot used for this PRD. Final migration checks use snapshot coverage (`100% of frozen task IDs`), not a hard-coded task count.

| Source Suite | Total | ccb_understand | ccb_design | ccb_fix | ccb_build | ccb_test | ccb_document | ccb_secure | ccb_debug | Retired |
|-------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| ccb_swebenchpro | 36 | | | 15 | | | | | | 21 |
| ccb_largerepo | 25 | | 8 | 3 | 11 | | | 3 | | |
| ccb_docgen | 13 | | | | | | 13 | | | |
| ccb_crossrepo | 12 | 2 | 6 | | 3 | | | | | 1 |
| ccb_enterprise | 12 | 2 | 5 | 2 | 2 | | | 1 | | |
| ccb_pytorch | 11 | | | 5 | | | | | | 6 |
| ccb_navprove | 9 | | | | | | | | 9 | |
| ccb_codereview | 8 | | | | | 8 | | | | |
| ccb_dibench | 8 | | | | 8 | | | | | |
| ccb_governance | 8 | | | | | | | 8 | | |
| ccb_nlqa | 8 | 8 | | | | | | | | |
| ccb_onboarding | 8 | 8 | | | | | | | | |
| ccb_security | 8 | | | | | | | 8 | | |
| ccb_tac | 6 | | | | 1 | 3 | | | | 1+1 excluded |
| ccb_linuxflbench | 5 | | | | | | | | 5 | |
| ccb_investigation | 4+3 | | 1 | | | | | | 6 | |
| ccb_sweperf | 3 | | | | | 3 | | | | |
| **Total** | **186+3** | **20** | **20** | **25** | **25** | **14** | **13** | **20** | **20** | **29+2** |
