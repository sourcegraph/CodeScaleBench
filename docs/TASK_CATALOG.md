# CodeScaleBench Task Catalog

A detailed reference for benchmark tasks in CodeScaleBench. This document catalogs the **150 SDLC tasks** organized across **9 SDLC-phase suites** (plus 220 Org tasks across 11 suites = **370 total**). Suite sizes use DOE-driven Neyman-optimal allocation. The unified selection file (`configs/selected_benchmark_tasks.json`) contains all 370 canonical tasks.

**Selection methodology:** Tasks were chosen via stratified sampling across benchmarks, covering all SDLC phases. Each task is scored for MCP benefit using a weighted combination of context complexity (0.25), cross-file dependencies (0.30), semantic search potential (0.20), and tool-chain weight (0.25). See `docs/TASK_SELECTION.md` for full scoring methodology.

---

## Table of Contents

1. [csb_sdlc_understand (10 tasks)](#1-csb_sdlc_understand--requirements--discovery)
2. [csb_sdlc_design (14 tasks)](#2-csb_sdlc_design--architecture--design)
3. [csb_sdlc_fix (26 tasks)](#3-csb_sdlc_fix--bug-repair)
4. [csb_sdlc_feature (23 tasks)](#4-csb_sdlc_feature--feature-implementation)
5. [csb_sdlc_refactor (16 tasks)](#5-csb_sdlc_refactor--cross-file-refactoring)
6. [csb_sdlc_test (18 tasks)](#6-csb_sdlc_test--testing--qa)
7. [csb_sdlc_document (13 tasks)](#7-csb_sdlc_document--documentation)
8. [csb_sdlc_secure (12 tasks)](#8-csb_sdlc_secure--security--compliance)
9. [csb_sdlc_debug (18 tasks)](#9-csb_sdlc_debug--debugging--investigation)
10. [Summary Statistics](#summary-statistics)

---

## 1. csb_sdlc_understand -- Requirements & Discovery

**Focus:** Codebase comprehension, natural-language Q&A, onboarding, knowledge discovery, and institutional memory recovery. Tasks require the agent to explain architecture, trace data flows, orient in unfamiliar projects, and recover fragmented knowledge.

**10 tasks** | Languages: C++, Go, Java, Python, TypeScript | Difficulty: hard (all tasks)

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
| numpy-dtype-localize-001 | Python | hard | numpy, pandas, scikit-learn | Bug localization |
| terraform-plan-pipeline-qa-001 | Go | hard | hashicorp/terraform | Architecture Q&A |
| terraform-state-backend-handoff-001 | Go | hard | hashicorp/terraform | Team handoff |
| vscode-ext-host-qa-001 | TypeScript | hard | microsoft/vscode | Debug root cause Q&A |

---

## 2. csb_sdlc_design -- Architecture & Design

**Focus:** Architecture analysis, dependency mapping, cross-repo reasoning, impact analysis, symbol resolution, and design-level decision-making. Tasks require the agent to understand system structure, trace dependency chains, and resolve cross-codebase symbols.

**14 tasks** | Languages: C, C++, Go, Java, Python | Difficulty: hard--expert

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
| k8s-sharedinformer-sym-001 | Go | hard | kubernetes/kubernetes | Cross-repo symbol resolution |
| k8s-typemeta-dep-chain-001 | Go | very_hard | kubernetes/kubernetes | Dependency chain analysis |
| kafka-flink-streaming-arch-001 | Java | hard | apache/kafka | Architectural understanding |
| postgres-query-exec-arch-001 | C | hard | postgres/postgres | Architectural understanding |
| quantlib-barrier-pricing-arch-001 | C++ | hard | lballabio/QuantLib | Architectural understanding |
| terraform-provider-iface-sym-001 | Go | hard | hashicorp/terraform | Cross-repo symbol resolution |

---

## 3. csb_sdlc_fix -- Bug Repair

**Focus:** Fix real bugs from production open-source repositories. Includes SWE-bench Pro patches, PyTorch compiler/runtime fixes, enterprise multi-team ownership bugs, and large-codebase debugging fixes.

**26 tasks** | Languages: C++, Go, Java, JavaScript, Python, TypeScript | Difficulty: medium--hard

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
| envoy-dfp-host-leak-fix-001 | C++ | hard | envoyproxy/envoy | Dynamic forward proxy host header memory leak |
| envoy-udp-proxy-cds-fix-001 | C++ | hard | envoyproxy/envoy | UDP proxy crash on dynamic CDS/EDS update |
| terraform-plan-null-unknown-fix-001 | Go | hard | hashicorp/terraform | Plan null/unknown value rendering |
| pytorch-cudnn-version-fix-001 | C++ | hard | pytorch/pytorch | Cross-module bug fix |
| pytorch-dynamo-keyerror-fix-001 | C++ | medium | pytorch/pytorch | Cross-module bug fix |
| pytorch-release-210-fix-001 | C++ | hard | pytorch/pytorch | Cross-module bug fix |
| pytorch-relu-gelu-fusion-fix-001 | C++ | medium | pytorch/pytorch | Cross-module bug fix |
| pytorch-tracer-graph-cleanup-fix-001 | C++ | hard | pytorch/pytorch | Cross-module bug fix |

---

## 4. csb_sdlc_feature -- Feature Implementation

**Focus:** Feature implementation, interface implementation, and adding new capabilities to large codebases. Tasks range from implementing new API endpoints and middleware to adding features in 1GB+ monorepos.

**23 tasks** | Languages: C, C++, Go, Java, Python, Python/C++, Rust, TypeScript | Difficulty: medium--hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| bustub-hyperloglog-impl-001 | C++ | hard | cmu-db/bustub | Feature implementation |
| camel-fix-protocol-feat-001 | Java | expert | apache/camel | Feature implementation |
| cilium-policy-audit-logger-feat-001 | Go | hard | cilium/cilium | Feature implementation |
| cilium-policy-quota-feat-001 | Go | expert | cilium/cilium | Feature implementation |
| curl-http3-priority-feat-001 | C | expert | curl/curl | Feature implementation |
| django-rate-limit-middleware-feat-001 | Python | hard | django/django | Feature implementation |
| envoy-custom-header-filter-feat-001 | C++ | expert | envoyproxy/envoy | Feature implementation |
| envoy-grpc-server-impl-001 | Go | hard | envoyproxy/go-control-plane | Interface implementation |
| flink-pricing-window-feat-001 | Java | expert | apache/flink | Feature implementation |
| k8s-noschedule-taint-feat-001 | Go | hard | kubernetes/kubernetes | Large-codebase feature |
| k8s-runtime-object-impl-001 | Go | hard | kubernetes/kubernetes | Interface implementation |
| numpy-rolling-median-feat-001 | Python | expert | numpy/numpy | Feature implementation |
| pandas-merge-asof-indicator-feat-001 | Python | hard | pandas-dev/pandas | Feature implementation |
| prometheus-silence-bulk-api-feat-001 | Go | hard | prometheus/prometheus | Feature implementation |
| pytorch-gradient-noise-feat-001 | Python | hard | pytorch/pytorch | Feature implementation |
| servo-scrollend-event-feat-001 | Rust | hard | servo/servo | Large-codebase feature |
| strata-cds-tranche-feat-001 | Java | expert | OpenGamma/Strata | Feature implementation |
| tensorrt-mxfp4-quant-feat-001 | Python, C++ | hard | NVIDIA/TensorRT-LLM | Large-codebase feature |
| terraform-compact-diff-fmt-feat-001 | Go | hard | hashicorp/terraform | Feature implementation |
| vscode-stale-diagnostics-feat-001 | TypeScript | hard | microsoft/vscode | Large-codebase feature |

---

## 5. csb_sdlc_refactor -- Cross-File Refactoring

**Focus:** Symbol renaming, module extraction, and cross-file restructuring. Tasks require identifying all references to a symbol across multiple files and consistently renaming or extracting them while maintaining compilation.

**16 tasks** | Languages: C, C++, Go, Java, Python, Rust | Difficulty: medium--hard

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| cilium-endpoint-manager-refac-001 | Go | expert | cilium/cilium | Cross-file refactoring |
| curl-multi-process-refac-001 | C | hard | curl/curl | Cross-file refactoring |
| django-request-factory-refac-001 | Python | hard | django/django | Cross-file refactoring |
| envoy-listener-manager-refac-001 | C++ | expert | envoyproxy/envoy | Cross-file refactoring |
| etcd-raft-storage-refac-001 | Go | hard | etcd-io/etcd | Cross-file refactoring |
| flipt-dep-refactor-001 | Go | hard | flipt-io/flipt | Enterprise dependency refactor |
| flipt-flagexists-refactor-001 | Go | hard | flipt-io/flipt | Enterprise dependency refactor |
| istio-discovery-server-refac-001 | Go | hard | istio/istio | Cross-file refactoring |
| k8s-score-normalizer-refac-001 | Go | hard | kubernetes/kubernetes | Cross-file refactoring |
| kafka-batch-accumulator-refac-001 | Java | hard | apache/kafka | Cross-file refactoring |
| kubernetes-scheduler-profile-refac-001 | Go | hard | kubernetes/kubernetes | Cross-file refactoring |
| numpy-array-dispatch-refac-001 | Python | expert | numpy/numpy | Cross-file refactoring |
| pandas-index-engine-refac-001 | Python | hard | pandas-dev/pandas | Cross-file refactoring |
| prometheus-query-engine-refac-001 | Go | hard | prometheus/prometheus | Cross-file refactoring |
| python-http-class-naming-refac-001 | Python | hard | django, flask, requests | Cross-repo refactoring |
| pytorch-optimizer-foreach-refac-001 | Python | expert | pytorch/pytorch | Cross-file refactoring |
| rust-subtype-relation-refac-001 | Rust | hard | rust-lang/rust | Cross-file refactoring |
| scikit-learn-estimator-tags-refac-001 | Python | expert | scikit-learn/scikit-learn | Cross-file refactoring |
| strata-fx-european-refac-001 | Java | hard | OpenGamma/Strata | Cross-file refactoring |
| terraform-eval-context-refac-001 | Go | hard | hashicorp/terraform | Cross-file refactoring |

---

## 6. csb_sdlc_test -- Testing & QA

**Focus:** Code review with injected defects, codebase search, performance optimization profiling, and unit test writing. Tasks test the agent's ability to detect bugs, write tests, find code patterns, and optimize performance.

**18 tasks** | Languages: C, C#, C++, Go, Java, JavaScript, Python, TypeScript | Difficulty: medium--hard

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
| test-coverage-gap-001 | C++ | hard | envoyproxy/envoy | Coverage gap analysis |
| test-coverage-gap-002 | Java | hard | apache/kafka | Coverage gap analysis |
| test-integration-002 | Go | hard | navidrome/navidrome | Integration test authoring |
| test-unitgen-go-001 | Go | hard | kubernetes/kubernetes | Unit test generation |
| test-unitgen-py-001 | Python | medium | django/django | Unit test generation |
| test-integration-001 | Go | hard | flipt-io/flipt | Integration test authoring |

**Code review scoring:** `0.5 * detection_F1 + 0.5 * fix_score`. Each code review task clones a real open-source repository at a pinned commit, then injects realistic defects. The agent must detect defects (structured `review.json`) and fix them.

**Performance scoring:** `runtime_reduction = 1 - (optimized_runtime / baseline_runtime)`.

---

## 7. csb_sdlc_document -- Documentation

**Focus:** Generate accurate API documentation, architecture guides, and migration plans by reading and understanding source code. Tasks require deep codebase comprehension to produce comprehensive documentation.

**13 tasks** | Languages: C++, Go, Java, Python, TypeScript | Difficulty: hard

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
| k8s-kubelet-cm-doc-gen-001 | Go | hard | kubernetes/kubernetes | Kubelet container manager documentation |
| k8s-fairqueuing-doc-gen-001 | Go | hard | kubernetes/kubernetes | K8s package documentation |
| terraform-migration-doc-gen-001 | Go | hard | hashicorp/terraform | Migration guide |
| envoy-migration-doc-gen-001 | C++ | hard | envoyproxy/envoy | Migration guide |
| docgen-inline-001 | Python | medium | django/django | Inline docstring generation |
| docgen-inline-002 | Java | hard | apache/kafka | Inline docstring generation |
| docgen-changelog-001 | Go | hard | hashicorp/terraform | Changelog generation |
| docgen-changelog-002 | Go | hard | flipt-io/flipt | Changelog generation |
| docgen-onboard-001 | Go | hard | istio/istio | Onboarding guide |
| docgen-runbook-001 | Go | hard | prometheus/prometheus | Runbook writing |
| docgen-runbook-002 | C++ | hard | envoyproxy/envoy | Runbook writing |

---

## 8. csb_sdlc_secure -- Security & Compliance

**Focus:** Security vulnerability triage (CVE analysis), reachability assessment, transitive dependency analysis, governance compliance (access control, audit trails, policy enforcement), and sensitive file exclusion.

**12 tasks** | Languages: C, C++, Go, Java, Python | Difficulty: medium--hard

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

## 9. csb_sdlc_debug -- Debugging & Investigation

**Focus:** Deep debugging, fault localization, regression hunting, causal chain tracing, and navigation-verified regression proving. Includes Linux kernel fault localization (expert difficulty) and navigation-verified tasks where the agent must both locate a bug and write a regression test.

**18 tasks** | Languages: C, C++, Go, Python, TypeScript | Difficulty: medium--expert

| Task ID | Lang | Difficulty | Repository | Category |
|---------|------|-----------|------------|----------|
| ansible-galaxy-tar-regression-prove-001 | Python | hard | ansible/ansible | Navigation-verified regression |
| django-admins-migration-audit-001 | Python | medium | django/django | Migration audit |
| envoy-duplicate-headers-debug-001 | C++ | hard | envoyproxy/envoy | Deep causal chain |
| flipt-auth-cookie-regression-prove-001 | Go | hard | flipt-io/flipt | Navigation-verified regression |
| grafana-table-panel-regression-001 | Go | hard | grafana/grafana | Regression hunt |
| istio-xds-destrul-debug-001 | Go | hard | istio/istio | Deep causal chain |
| linux-acpi-backlight-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-hda-intel-suspend-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-iwlwifi-subdevice-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-nfs-inode-revalidate-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| linux-ssd-trim-timeout-fault-001 | C | expert | torvalds/linux | Kernel fault localization |
| prometheus-queue-reshard-debug-001 | Go | hard | prometheus/prometheus | Cross-service debug |
| qutebrowser-hsv-color-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
| qutebrowser-adblock-cache-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
| qutebrowser-darkmode-threshold-regression-prove-001 | Python | hard | qutebrowser/qutebrowser | Navigation-verified regression |
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
| csb_sdlc_fix | 26 | medium--hard | C++, Go, Java, JS, Python, TS | Bug fixes, SWE-bench Pro patches |
| csb_sdlc_feature | 23 | medium--hard | C, C++, Go, Java, Python, Python/C++, Rust, TS | Feature implementation, interface impl |
| csb_sdlc_debug | 18 | medium--expert | C, C++, Go, Python, TS | Fault localization, regression |
| csb_sdlc_test | 18 | medium--hard | C, C#, C++, Go, Java, JS, Python, TS | Code review, testing, perf, coverage analysis |
| csb_sdlc_refactor | 16 | medium--hard | C, C++, Go, Java, Python, Rust | Cross-file renaming, module extraction |
| csb_sdlc_design | 14 | hard--expert | C, C++, Go, Java, Python | Architecture, dependency mapping |
| csb_sdlc_document | 13 | hard | C++, Go, Java, Python, TS | API docs, arch guides, migration, runbooks |
| csb_sdlc_secure | 12 | medium--hard | C, C++, Go, Java, Python | CVE triage, governance, access |
| csb_sdlc_understand | 10 | hard | C++, Go, Java, Python, TS | Comprehension, Q&A, onboarding |

**Total canonical tasks:** 150 (SDLC) + 220 (Org) = 370
**Languages covered:** C, C++, C#, Go, Java, JavaScript, Python, Rust, TypeScript
**SDLC phases covered:** Requirements & Discovery, Architecture & Design, Bug Repair, Feature Implementation, Refactoring, Testing & QA, Documentation, Security & Compliance, Debugging & Investigation
