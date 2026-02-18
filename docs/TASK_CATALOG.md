# CodeContextBench Task Catalog

A detailed reference for every benchmark task in CodeContextBench. This document covers all **157 tasks** organized across **8 SDLC-phase suites**.

**Selection methodology:** Tasks were chosen via stratified sampling across benchmarks, covering all SDLC phases. Each task is scored for MCP benefit using a weighted combination of context complexity (0.25), cross-file dependencies (0.30), semantic search potential (0.20), and tool-chain weight (0.25). See `docs/TASK_SELECTION.md` for full scoring methodology.

**Source of truth:** `configs/selected_benchmark_tasks.json` (version 2.0, 2026-02-18).

---

## Table of Contents

1. [ccb_understand (20 tasks)](#1-ccb_understand--requirements--discovery)
2. [ccb_design (20 tasks)](#2-ccb_design--architecture--design)
3. [ccb_fix (25 tasks)](#3-ccb_fix--bug-repair)
4. [ccb_build (25 tasks)](#4-ccb_build--feature--refactoring)
5. [ccb_test (14 tasks)](#5-ccb_test--testing--qa)
6. [ccb_document (13 tasks)](#6-ccb_document--documentation)
7. [ccb_secure (20 tasks)](#7-ccb_secure--security--compliance)
8. [ccb_debug (20 tasks)](#8-ccb_debug--debugging--investigation)
9. [Summary Statistics](#summary-statistics)

---

## 1. ccb_understand -- Requirements & Discovery

**Focus:** Codebase comprehension, natural-language Q&A, onboarding, knowledge discovery, and institutional memory recovery. Tasks require the agent to explain architecture, trace data flows, orient in unfamiliar projects, and recover fragmented knowledge.

**20 tasks** | Languages: C++, Go, Java, Python, TypeScript | Difficulty: hard (all tasks)

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| argocd-arch-orient-001 | Go | hard | argoproj/argo-cd | Codebase orientation |
| argocd-sync-reconcile-qa-001 | Go | hard | argoproj/argo-cd | Data flow explanation |
| cilium-ebpf-datapath-handoff-001 | Go | hard | cilium/cilium | Team handoff |
| cilium-ebpf-fault-qa-001 | Go | hard | cilium/cilium | Debug root cause Q&A |
| cilium-project-orient-001 | Go | hard | cilium/cilium | Codebase orientation |
| django-composite-field-recover-001 | Python | hard | django/django | Knowledge fragmentation recovery |
| django-template-inherit-recall-001 | Python | hard | django/django | Institutional memory recall |
| envoy-contributor-workflow-001 | C++ | hard | envoyproxy/envoy | Workflow discovery |
| envoy-ext-authz-handoff-001 | C++ | hard | envoyproxy/envoy | Team handoff |
| envoy-filter-chain-qa-001 | C++ | hard | envoyproxy/envoy | Architecture Q&A |
| envoy-request-routing-qa-001 | C++ | hard | envoyproxy/envoy | Data flow explanation |
| istio-xds-serving-qa-001 | Go | hard | istio/istio | Architecture Q&A |
| k8s-cri-containerd-reason-001 | Go | hard | kubernetes, containerd | Cross-file reasoning |
| kafka-build-orient-001 | Java | hard | apache/kafka | Codebase orientation |
| kafka-contributor-workflow-001 | Java | hard | apache/kafka | Workflow discovery |
| kafka-message-lifecycle-qa-001 | Java | hard | apache/kafka | Data flow explanation |
| numpy-dtype-localize-001 | Go | hard | numpy, pandas, scikit-learn | Bug localization |
| terraform-plan-pipeline-qa-001 | Go | hard | hashicorp/terraform | Architecture Q&A |
| terraform-state-backend-handoff-001 | Go | hard | hashicorp/terraform | Team handoff |
| vscode-ext-host-qa-001 | TypeScript | hard | microsoft/vscode | Debug root cause Q&A |

---

## 2. ccb_design -- Architecture & Design

**Focus:** Architecture analysis, dependency mapping, cross-repo reasoning, impact analysis, symbol resolution, and design-level decision-making. Tasks require the agent to understand system structure, trace dependency chains, and resolve cross-codebase symbols.

**20 tasks** | Languages: C, C++, Go, Java, Python | Difficulty: hard--very_hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| camel-routing-arch-001 | Java | hard | apache/camel | Architectural understanding |
| django-modeladmin-impact-001 | Python | hard | django/django | Dependency impact analysis |
| django-orm-query-arch-001 | Python | hard | django/django | Architectural understanding |
| django-pre-validate-signal-design-001 | Python | hard | django/django | Stale architecture navigation |
| django-rate-limit-design-001 | Python | hard | django/django | Conflicting documentation resolution |
| envoy-routeconfig-dep-chain-001 | Go | very_hard | envoyproxy/go-control-plane | Dependency chain analysis |
| envoy-stream-aggregated-sym-001 | Go | hard | kubernetes/kubernetes | Cross-repo symbol resolution |
| etcd-grpc-api-upgrade-001 | Go | hard | etcd, kubernetes, containerd | API upgrade planning |
| flink-checkpoint-arch-001 | Java | hard | apache/flink | Architectural understanding |
| flipt-protobuf-metadata-design-001 | Go | hard | flipt-io/flipt | Polyglot ecosystem analysis |
| flipt-transitive-deps-001 | Go | hard | flipt-io/flipt | Dependency discovery |
| k8s-crd-lifecycle-arch-001 | Go | hard | kubernetes/kubernetes | Architectural understanding |
| k8s-dra-allocation-impact-001 | Go | hard | kubernetes/kubernetes | Impact analysis |
| k8s-scheduler-arch-001 | Go | hard | kubernetes/kubernetes | Architectural understanding |
| k8s-sharedinformer-sym-001 | C++ | hard | envoyproxy/envoy | Cross-repo symbol resolution |
| k8s-typemeta-dep-chain-001 | Go | very_hard | kubernetes/kubernetes | Dependency chain analysis |
| kafka-flink-streaming-arch-001 | Java | hard | apache/kafka | Architectural understanding |
| postgres-query-exec-arch-001 | C | hard | postgres/postgres | Architectural understanding |
| quantlib-barrier-pricing-arch-001 | C++ | hard | lballabio/QuantLib | Architectural understanding |
| terraform-provider-iface-sym-001 | Go | hard | hashicorp/terraform | Cross-repo symbol resolution |

---

## 3. ccb_fix -- Bug Repair

**Focus:** Fix real bugs from production open-source repositories. Includes SWE-bench Pro patches, PyTorch compiler/runtime fixes, enterprise multi-team ownership bugs, and large-codebase debugging fixes.

**25 tasks** | Languages: C++, Go, Java, JavaScript, Python, TypeScript | Difficulty: medium--hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| ansible-abc-imports-fix-001 | Python | hard | ansible/ansible | SWE-bench Pro bug fix |
| ansible-module-respawn-fix-001 | Python | hard | ansible/ansible | SWE-bench Pro bug fix |
| django-modelchoice-fk-fix-001 | Python | hard | django/django | Multi-team ownership bug |
| django-select-for-update-fix-001 | Python | hard | django/django | Large-codebase bug investigation |
| flipt-cockroachdb-backend-fix-001 | Go | hard | flipt-io/flipt | SWE-bench Pro bug fix |
| flipt-ecr-auth-oci-fix-001 | Go | hard | flipt-io/flipt | SWE-bench Pro bug fix |
| flipt-eval-latency-fix-001 | Go | hard | flipt-io/flipt | Multi-team ownership bug |
| flipt-otlp-exporter-fix-001 | Go | hard | flipt-io/flipt | SWE-bench Pro bug fix |
| flipt-trace-sampling-fix-001 | Go | hard | flipt-io/flipt | SWE-bench Pro bug fix |
| k8s-dra-scheduler-event-fix-001 | Go | hard | kubernetes/kubernetes | Large-codebase bug investigation |
| kafka-producer-bufpool-fix-001 | Java | hard | apache/kafka | Large-codebase bug investigation |
| navidrome-windows-log-fix-001 | Go | hard | navidrome/navidrome | SWE-bench Pro bug fix |
| nodebb-notif-dropdown-fix-001 | JavaScript | hard | NodeBB/NodeBB | SWE-bench Pro bug fix |
| nodebb-plugin-validate-fix-001 | JavaScript | hard | NodeBB/NodeBB | SWE-bench Pro bug fix |
| openlibrary-fntocli-adapter-fix-001 | Python | hard | internetarchive/openlibrary | SWE-bench Pro bug fix |
| openlibrary-search-query-fix-001 | Python | hard | internetarchive/openlibrary | SWE-bench Pro bug fix |
| openlibrary-solr-boolean-fix-001 | Python | hard | internetarchive/openlibrary | SWE-bench Pro bug fix |
| protonmail-conv-testhooks-fix-001 | TypeScript | hard | protonmail/webclients | SWE-bench Pro bug fix |
| protonmail-dropdown-sizing-fix-001 | TypeScript | hard | protonmail/webclients | SWE-bench Pro bug fix |
| protonmail-holiday-calendar-fix-001 | TypeScript | hard | protonmail/webclients | SWE-bench Pro bug fix |
| pytorch-cudnn-version-fix-001 | C++ | hard | pytorch/pytorch | Cross-module bug fix |
| pytorch-dynamo-keyerror-fix-001 | C++ | medium | pytorch/pytorch | Cross-module bug fix |
| pytorch-release-210-fix-001 | C++ | hard | pytorch/pytorch | Cross-module bug fix |
| pytorch-relu-gelu-fusion-fix-001 | C++ | medium | pytorch/pytorch | Cross-module bug fix |
| pytorch-tracer-graph-cleanup-fix-001 | C++ | hard | pytorch/pytorch | Cross-module bug fix |

---

## 4. ccb_build -- Feature & Refactoring

**Focus:** Feature implementation, cross-file refactoring, dependency installation, and interface implementation. Tasks span from adding missing build dependencies to implementing new features in 1GB+ codebases.

**25 tasks** | Languages: C#, C++, Go, Java, JavaScript, Python/C++, Rust, TypeScript | Difficulty: medium--hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| bustub-hyperloglog-impl-001 | C++ | hard | cmu-db/bustub | Feature implementation |
| camel-fix-protocol-feat-001 | Java | hard | apache/camel | Feature implementation |
| cgen-deps-install-001 | Python | medium | inducer/cgen | Dependency inference |
| codecoverage-deps-install-001 | C# | medium | irongut/CodeCoverageSummary | Dependency inference |
| django-dep-refactor-001 | Go | hard | flipt-io/flipt | Enterprise dependency refactor |
| dotenv-expand-deps-install-001 | JavaScript | medium | motdotla/dotenv-expand | Dependency inference |
| dotnetkoans-deps-install-001 | C# | medium | DotNetKoans/DotNetKoans | Dependency inference |
| envoy-grpc-server-impl-001 | Go | hard | envoyproxy/go-control-plane | Interface implementation |
| eslint-markdown-deps-install-001 | JavaScript | medium | eslint/markdown | Dependency inference |
| flink-pricing-window-feat-001 | Java | hard | apache/flink | Feature implementation |
| flipt-dep-refactor-001 | Go | hard | flipt-io/flipt | Enterprise dependency refactor |
| python-http-class-naming-refac-001 | Go | hard | django, flask, requests | Cross-repo refactoring |
| iamactionhunter-deps-install-001 | Python | medium | RhinoSecurityLabs/IAMActionHunter | Dependency inference |
| k8s-noschedule-taint-feat-001 | Go | hard | kubernetes/kubernetes | Large-codebase feature |
| k8s-runtime-object-impl-001 | Go | hard | kubernetes/kubernetes | Interface implementation |
| k8s-score-normalizer-refac-001 | Go | hard | kubernetes/kubernetes | Cross-file refactoring |
| kafka-batch-accumulator-refac-001 | Java | hard | apache/kafka | Cross-file refactoring |
| pcap-parser-deps-install-001 | Rust | medium | rusticata/pcap-parser | Dependency inference |
| rust-subtype-relation-refac-001 | Rust | hard | rust-lang/rust | Cross-file refactoring |
| servo-scrollend-event-feat-001 | Rust | hard | servo/servo | Large-codebase feature |
| similar-asserts-deps-install-001 | Rust | medium | mitsuhiko/similar-asserts | Dependency inference |
| strata-cds-tranche-feat-001 | Java | hard | OpenGamma/Strata | Feature implementation |
| strata-fx-european-refac-001 | Java | hard | OpenGamma/Strata | Cross-file refactoring |
| tensorrt-mxfp4-quant-feat-001 | Python, C++ | hard | NVIDIA/TensorRT-LLM | Large-codebase feature |
| vscode-stale-diagnostics-feat-001 | TypeScript | hard | microsoft/vscode | Large-codebase feature |

---

## 5. ccb_test -- Testing & QA

**Focus:** Code review with injected defects, codebase search, performance optimization profiling, and unit test writing. Tasks test the agent's ability to detect bugs, write tests, find code patterns, and optimize performance.

**14 tasks** | Languages: C, C#, C++, Go, Java, JavaScript, Python, TypeScript | Difficulty: medium--hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| aspnetcore-code-review-001 | C# | hard | dotnet/aspnetcore | Code review |
| calcom-code-review-001 | TypeScript | hard | calcom/cal.com | Code review |
| envoy-code-review-001 | C++ | hard | envoyproxy/envoy | Code review |
| ghost-code-review-001 | JavaScript | hard | agentic-review-benchmarks/benchmark-pr-mapping | Code review |
| llamacpp-context-window-search-001 | C++ | medium | ggerganov/llama.cpp | Codebase search |
| llamacpp-file-modify-search-001 | C++ | medium | ggerganov/llama.cpp | Codebase search |
| numpy-array-sum-perf-001 | Python | medium | numpy/numpy | Performance optimization |
| openhands-search-file-test-001 | Python | medium | All-Hands-AI/OpenHands | Unit test writing |
| pandas-groupby-perf-001 | Python | medium | pandas-dev/pandas | Performance optimization |
| curl-security-review-001 | C | hard | curl/curl | Security code review |
| kafka-security-review-001 | Java | hard | apache/kafka | Security code review |
| sklearn-kmeans-perf-001 | Python | hard | scikit-learn/scikit-learn | Performance optimization |
| terraform-code-review-001 | Go | hard | hashicorp/terraform | Code review |
| vscode-code-review-001 | TypeScript | hard | microsoft/vscode | Code review |

**Code review scoring:** `0.5 * detection_F1 + 0.5 * fix_score`. Each code review task clones a real open-source repository at a pinned commit, then injects realistic defects. The agent must detect defects (structured `review.json`) and fix them.

**Performance scoring:** `runtime_reduction = 1 - (optimized_runtime / baseline_runtime)`.

---

## 6. ccb_document -- Documentation

**Focus:** Generate accurate API documentation, architecture guides, and migration plans by reading and understanding source code. Tasks require deep codebase comprehension to produce comprehensive documentation.

**13 tasks** | Languages: C++, Go, Java, TypeScript | Difficulty: hard (all tasks)

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| vscode-api-doc-gen-001 | TypeScript | hard | microsoft/vscode | API reference |
| cilium-api-doc-gen-001 | Go | hard | cilium/cilium | API reference |
| kafka-api-doc-gen-001 | Java | hard | apache/kafka | API reference |
| envoy-arch-doc-gen-001 | C++ | hard | envoyproxy/envoy | Architecture documentation |
| istio-arch-doc-gen-001 | Go | hard | istio/istio | Architecture documentation |
| terraform-arch-doc-gen-001 | Go | hard | hashicorp/terraform | Architecture documentation |
| k8s-apiserver-doc-gen-001 | Go | hard | kubernetes/kubernetes | K8s package documentation |
| k8s-applyconfig-doc-gen-001 | Go | hard | kubernetes/kubernetes | K8s package documentation |
| k8s-clientgo-doc-gen-001 | Go | hard | kubernetes/kubernetes | K8s package documentation |
| k8s-controller-mgr-doc-gen-001 | Go | hard | kubernetes/kubernetes | K8s package documentation |
| k8s-fairqueuing-doc-gen-001 | Go | hard | kubernetes/kubernetes | K8s package documentation |
| terraform-migration-doc-gen-001 | Go | hard | hashicorp/terraform | Migration guide |
| envoy-migration-doc-gen-001 | C++ | hard | envoyproxy/envoy | Migration guide |

---

## 7. ccb_secure -- Security & Compliance

**Focus:** Security vulnerability triage (CVE analysis), reachability assessment, transitive dependency analysis, governance compliance (access control, audit trails, policy enforcement), and sensitive file exclusion.

**20 tasks** | Languages: C, C++, Go, Java, Python | Difficulty: medium--hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| django-audit-trail-implement-001 | Python | hard | django/django | Audit trail implementation |
| django-cross-team-boundary-001 | Python | hard | django/django | Cross-team boundary enforcement |
| curl-cve-triage-001 | C | hard | curl/curl | CVE triage |
| envoy-cve-triage-001 | C++ | hard | envoyproxy/envoy | CVE triage |
| golang-net-cve-triage-001 | Go | hard | golang/net | CVE triage |
| django-csrf-session-audit-001 | Python | hard | django/django | Security audit |
| flipt-degraded-context-fix-001 | Go | hard | flipt-io/flipt | Degraded context handling |
| kafka-sasl-auth-audit-001 | Java | hard | apache/kafka | Security audit |
| django-legacy-dep-vuln-001 | Python | hard | django/django | Legacy dependency analysis |
| django-policy-enforcement-001 | Python | hard | django/django | Policy enforcement |
| postgres-client-auth-audit-001 | C | hard | postgres/postgres | Security audit |
| django-repo-scoped-access-001 | Python | medium | django/django | Repository-scoped access |
| flipt-repo-scoped-access-001 | Go | hard | flipt-io/flipt | Repository-scoped access |
| django-role-based-access-001 | Python | hard | django/django | Role-based access control |
| django-sensitive-file-exclusion-001 | Python | medium | django/django | Sensitive file exclusion |
| wish-transitive-vuln-001 | Go | hard | charmbracelet/wish | Transitive dependency analysis |
| grpcurl-transitive-vuln-001 | Go | hard | fullstorydev/grpcurl | Transitive dependency analysis |
| curl-vuln-reachability-001 | C | hard | curl/curl | Vulnerability reachability |
| envoy-vuln-reachability-001 | C++ | hard | envoyproxy/envoy | Vulnerability reachability |
| kafka-vuln-reachability-001 | Java | hard | apache/kafka | Vulnerability reachability |

---

## 8. ccb_debug -- Debugging & Investigation

**Focus:** Deep debugging, fault localization, regression hunting, causal chain tracing, and navigation-verified regression proving. Includes Linux kernel fault localization (expert difficulty) and navigation-verified tasks where the agent must both locate a bug and write a regression test.

**20 tasks** | Languages: C, C++, Go, Python, TypeScript | Difficulty: medium--expert

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| ansible-vault-regression-prove-001 | Python | hard | ansible/ansible | Navigation-verified regression |
| django-admins-migration-audit-001 | Python | medium | django/django | Migration audit |
| envoy-duplicate-headers-debug-001 | C++ | hard | envoyproxy/envoy | Deep causal chain |
| flipt-cache-regression-prove-001 | Go | hard | flipt-io/flipt | Navigation-verified regression |
| grafana-table-panel-regression-001 | Go | hard | grafana/grafana | Regression hunt |
| istio-xds-destrul-debug-001 | Go | hard | istio/istio | Deep causal chain |
| linux-acpi-backlight-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-hda-intel-suspend-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-iwlwifi-subdevice-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-nfs-inode-revalidate-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-ssd-trim-timeout-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| prometheus-queue-reshard-debug-001 | Go | hard | prometheus/prometheus | Cross-service debug |
| qutebrowser-bookmark-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
| qutebrowser-download-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
| qutebrowser-tab-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
| qutebrowser-url-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
| teleport-ssh-regression-prove-001 | Go | hard | gravitational/teleport | Navigation-verified regression |
| terraform-phantom-update-debug-001 | Go | hard | hashicorp/terraform | Deep causal chain |
| tutanota-search-regression-prove-001 | TypeScript | hard | tutao/tutanota | Navigation-verified regression |
| vuls-oval-regression-prove-001 | Go | hard | future-architect/vuls | Navigation-verified regression |

**Navigation-verified scoring:** Phase 1 (test fails on buggy code, 0.5 pts) + Phase 2 (test passes after patch, 0.5 pts). Majority-of-3 voting per phase.

**Kernel fault localization:** 30-minute time limit per task. Agent must identify exact source file(s) and function(s) responsible for hardware/driver failures in the ~28K-file Linux kernel.

---

## Summary Statistics

| Suite | Tasks | Difficulty Range | Languages | Description |
|-------|-------|-----------------|-----------|-------------|
| ccb_understand | 20 | hard | C++, Go, Java, Python, TS | Comprehension, Q&A, onboarding |
| ccb_design | 20 | hard--very_hard | C, C++, Go, Java, Python | Architecture, dependency mapping |
| ccb_fix | 25 | medium--hard | C++, Go, Java, JS, Python, TS | Bug fixes, SWE-bench Pro patches |
| ccb_build | 25 | medium--hard | C#, C++, Go, Java, JS, Python/C++, Rust, TS | Features, refactoring, deps |
| ccb_test | 14 | medium--hard | C, C#, C++, Go, Java, JS, Python, TS | Code review, testing, perf |
| ccb_document | 13 | hard | C++, Go, Java, TS | API docs, arch guides, migration |
| ccb_secure | 20 | medium--hard | C, C++, Go, Java, Python | CVE triage, governance, access |
| ccb_debug | 20 | medium--expert | C, C++, Go, Python, TS | Fault localization, regression |

**Total active tasks:** 157
**Languages covered:** C, C++, C#, Go, Java, JavaScript, Python, Rust, TypeScript
**SDLC phases covered:** Requirements & Discovery, Architecture & Design, Bug Repair, Feature Implementation, Refactoring, Testing & QA, Documentation, Security & Compliance, Debugging & Investigation
