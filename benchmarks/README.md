# CodeContextBench Benchmarks

This directory contains SDLC-aligned suites plus MCP-unique org-scale retrieval suites. The canonical selected task catalog is in [`selected_benchmark_tasks.json`](../configs/selected_benchmark_tasks.json) (currently 251 selected tasks across 19 suites).

See [`docs/TASK_SELECTION.md`](../docs/TASK_SELECTION.md) for selection methodology.

---

## SDLC Suite Overview

| Suite | SDLC Phase | Tasks | Description |
|-------|-----------|------:|-------------|
| `ccb_understand` | Requirements & Discovery | 20 | Codebase comprehension, onboarding, Q&A, knowledge recovery |
| `ccb_design` | Architecture & Design | 20 | Architecture analysis, dependency graphs, change impact |
| `ccb_fix` | Bug Repair | 25 | Diagnosing and fixing real bugs across production codebases |
| `ccb_build` | Feature & Refactoring | 25 | New features, refactoring, dependency management |
| `ccb_test` | Testing & QA | 20 | Code review, performance testing, code search validation, test generation |
| `ccb_document` | Documentation | 20 | API references, architecture docs, migration guides, runbooks |
| `ccb_secure` | Security & Compliance | 20 | CVE analysis, reachability, governance, access control |
| `ccb_debug` | Debugging & Investigation | 20 | Root cause tracing, fault localization, provenance |
| **Total** | | **170** | |

---

## MCP-Unique Suite Overview (Selected Catalog)

These suites measure cross-repo discovery, tracing, and org-scale code intelligence use cases. Counts below reflect the current selected catalog in [`selected_benchmark_tasks.json`](../configs/selected_benchmark_tasks.json) (some suite directories may contain additional draft/deferred tasks that are not selected).

| Suite | Tasks | Description |
|-------|------:|-------------|
| `ccb_mcp_compliance` | 7 | Compliance, audit, and provenance workflows |
| `ccb_mcp_crossorg` | 5 | Cross-org discovery and authoritative repo identification |
| `ccb_mcp_crossrepo` | 1 | Legacy cross-repo discovery/tracing task (compatibility) |
| `ccb_mcp_crossrepo_tracing` | 9 | Cross-repo dependency tracing and symbol resolution |
| `ccb_mcp_domain` | 10 | Domain-specific lineage and analysis workflows |
| `ccb_mcp_incident` | 11 | Incident debugging across services and repos |
| `ccb_mcp_migration` | 7 | Framework and platform migrations across repos |
| `ccb_mcp_onboarding` | 11 | Onboarding, architecture comprehension, API discovery |
| `ccb_mcp_org` | 5 | Org-wide coding correctness tasks requiring broad context |
| `ccb_mcp_platform` | 5 | Platform/devtools and tribal-knowledge discovery |
| `ccb_mcp_security` | 10 | Vulnerability remediation and security analysis at org scale |
| **Total MCP-Unique (selected)** | **81** | |

For suite taxonomy, authoring, and oracle evaluation details, see [`docs/MCP_UNIQUE_TASKS.md`](../docs/MCP_UNIQUE_TASKS.md).

---

## ccb_understand (20 tasks) — Requirements & Discovery

Codebase comprehension, natural-language Q&A, onboarding exercises, and knowledge recovery tasks.

| Task | Focus |
|------|-------|
| `argocd-arch-orient-001` | Explore Argo CD architecture |
| `argocd-sync-reconcile-qa-001` | Trace Argo CD sync reconciliation |
| `cilium-ebpf-datapath-handoff-001` | Document eBPF datapath subsystem |
| `cilium-ebpf-fault-qa-001` | Explain eBPF fault isolation |
| `cilium-project-orient-001` | Explore Cilium project structure |
| `django-composite-field-recover-001` | Add composite field validator |
| `django-template-inherit-recall-001` | Fix template inheritance regression |
| `envoy-contributor-workflow-001` | Learn Envoy contributor workflow |
| `envoy-ext-authz-handoff-001` | Document ext_authz filter ownership |
| `envoy-filter-chain-qa-001` | Explain HTTP filter chain architecture |
| `envoy-request-routing-qa-001` | Trace Envoy request routing path |
| `istio-xds-serving-qa-001` | Explain xDS serving architecture |
| `k8s-cri-containerd-reason-001` | Trace K8s CRI containerd implementation |
| `kafka-build-orient-001` | Explore Kafka build system |
| `kafka-contributor-workflow-001` | Learn Kafka contribution process |
| `kafka-message-lifecycle-qa-001` | Trace Kafka message lifecycle |
| `numpy-dtype-localize-001` | Trace nullable integer dtype incompatibility |
| `terraform-plan-pipeline-qa-001` | Explain terraform plan pipeline |
| `terraform-state-backend-handoff-001` | Document state backend subsystem |
| `vscode-ext-host-qa-001` | Explain extension host isolation |

---

## ccb_design (20 tasks) — Architecture & Design

Architecture analysis, dependency chain tracing, change impact assessment, and design proposals.

| Task | Focus |
|------|-------|
| `camel-routing-arch-001` | Trace Camel message routing architecture |
| `django-modeladmin-impact-001` | Find ModelAdmin.get_list_filter overrides |
| `django-orm-query-arch-001` | Map Django ORM query compilation pipeline |
| `django-pre-validate-signal-design-001` | Add pre-validation Django model signal |
| `django-rate-limit-design-001` | Implement rate limiting middleware correctly |
| `envoy-routeconfig-dep-chain-001` | Follow RouteConfiguration definition chain |
| `envoy-stream-aggregated-sym-001` | Find StreamAggregatedResources callers |
| `etcd-grpc-api-upgrade-001` | Migrate grpc.Dial to grpc.NewClient |
| `flink-checkpoint-arch-001` | Map Flink checkpoint coordination |
| `flipt-protobuf-metadata-design-001` | Add protobuf evaluation metadata field |
| `flipt-transitive-deps-001` | List transitive package dependencies |
| `k8s-crd-lifecycle-arch-001` | Trace K8s CRD lifecycle ecosystem |
| `k8s-dra-allocation-impact-001` | Analyze DRA AllocationMode API impact |
| `k8s-scheduler-arch-001` | Explain K8s scheduler architecture |
| `k8s-sharedinformer-sym-001` | Locate SharedInformer factory usages |
| `k8s-typemeta-dep-chain-001` | Trace TypeMeta dependency chain |
| `kafka-flink-streaming-arch-001` | Trace Kafka-Flink streaming data flow |
| `postgres-query-exec-arch-001` | Trace PostgreSQL query execution pipeline |
| `quantlib-barrier-pricing-arch-001` | Trace QuantLib barrier option pricing |
| `terraform-provider-iface-sym-001` | Find provider.Provider implementations |

---

## ccb_fix (25 tasks) — Bug Repair

Diagnosing and fixing real bugs across production codebases (SWE-bench Pro, PyTorch, large repos).

| Task | Focus |
|------|-------|
| `ansible-abc-imports-fix-001` | Inconsistent collection ABC imports |
| `ansible-module-respawn-fix-001` | Module respawn under compatible interpreters |
| `django-modelchoice-fk-fix-001` | Fix ModelChoiceField ForeignKey rendering |
| `django-select-for-update-fix-001` | Django select_for_update ORM crash |
| `flipt-cockroachdb-backend-fix-001` | Support CockroachDB first-class backend |
| `flipt-ecr-auth-oci-fix-001` | Dynamic AWS ECR authentication OCI |
| `flipt-eval-latency-fix-001` | Add evaluation latency tracking |
| `flipt-otlp-exporter-fix-001` | Add OTLP exporter support tracing |
| `flipt-trace-sampling-fix-001` | Add sampling ratio propagator config |
| `k8s-dra-scheduler-event-fix-001` | K8s DRA scheduler event handling |
| `kafka-producer-bufpool-fix-001` | Kafka producer buffer pool race condition |
| `navidrome-windows-log-fix-001` | Windows log output line ending normalization |
| `nodebb-notif-dropdown-fix-001` | Notifications dropdown category selector |
| `nodebb-plugin-validate-fix-001` | Plugin activation identifier validation |
| `openlibrary-fntocli-adapter-fix-001` | FnToCLI adapter list inputs paths |
| `openlibrary-search-query-fix-001` | Work search query parsing normalization |
| `openlibrary-solr-boolean-fix-001` | Solr boolean clause limit alignment |
| `envoy-dfp-host-leak-fix-001` | Dynamic forward proxy host header memory leak |
| `envoy-udp-proxy-cds-fix-001` | UDP proxy crash on dynamic CDS/EDS cluster update |
| `terraform-plan-null-unknown-fix-001` | Terraform plan null/unknown value rendering |
| `pytorch-cudnn-version-fix-001` | Expose cuDNN runtime version |
| `pytorch-dynamo-keyerror-fix-001` | Fix dynamo keyerror and attribute |
| `pytorch-release-210-fix-001` | Release 2.10 bug fix changes |
| `pytorch-relu-gelu-fusion-fix-001` | Revert Inductor ReLU/GELU fusions |
| `pytorch-tracer-graph-cleanup-fix-001` | Cleanup graphs for failed tracer outputs |

---

## ccb_build (25 tasks) — Feature & Refactoring

New feature implementation, code refactoring, and dependency management tasks.

| Task | Focus |
|------|-------|
| `bustub-hyperloglog-impl-001` | Implement HyperLogLog cardinality estimator |
| `camel-fix-protocol-feat-001` | Implement camel-fix component FIX protocol |
| `cgen-deps-install-001` | Set required package configuration |
| `codecoverage-deps-install-001` | Configure project dependency versions |
| `flipt-flagexists-refactor-001` | Add FlagExists to ReadOnlyFlagStore (Flipt) |
| `dotenv-expand-deps-install-001` | Fix build system dependencies |
| `dotnetkoans-deps-install-001` | Edit build dependencies, tests pass |
| `envoy-grpc-server-impl-001` | Identify gRPC server implementations |
| `eslint-markdown-deps-install-001` | Add missing package dependencies |
| `flink-pricing-window-feat-001` | Implement PricingSessionWindow for trading |
| `flipt-dep-refactor-001` | Dependency refactoring (Flipt) |
| `python-http-class-naming-refac-001` | Standardize HTTP class naming |
| `iamactionhunter-deps-install-001` | Resolve missing dependencies build |
| `k8s-noschedule-taint-feat-001` | Implement NoScheduleNoTraffic taint effect |
| `k8s-runtime-object-impl-001` | Find runtime.Object interface implementors |
| `k8s-score-normalizer-refac-001` | Rename ScoreExtensions to ScoreNormalizer |
| `kafka-batch-accumulator-refac-001` | Rename RecordAccumulator to BatchAccumulator |
| `pcap-parser-deps-install-001` | Setup library dependencies correctly |
| `rust-subtype-relation-refac-001` | Rename SubtypePredicate to SubtypeRelation |
| `servo-scrollend-event-feat-001` | Add scrollend DOM event support |
| `similar-asserts-deps-install-001` | Configure Cargo dependency resolution |
| `strata-cds-tranche-feat-001` | Implement CDS tranche CDO product |
| `strata-fx-european-refac-001` | Rename FxVanillaOption to FxEuropeanOption |
| `tensorrt-mxfp4-quant-feat-001` | Add W4A8_MXFP4_INT8 quantization mode |
| `vscode-stale-diagnostics-feat-001` | Fix stale diagnostics after git branch |

---

## ccb_test (20 tasks) — Testing & QA

Code review with injected defects, performance testing, and code search validation.

| Task | Focus |
|------|-------|
| `aspnetcore-code-review-001` | Code review: ASP.NET Core |
| `calcom-code-review-001` | Code review: Cal.com |
| `envoy-code-review-001` | Code review: Envoy |
| `ghost-code-review-001` | Code review: Ghost |
| `llamacpp-context-window-search-001` | Find PR improving context window |
| `llamacpp-file-modify-search-001` | Locate recent file modification PR |
| `numpy-array-sum-perf-001` | Optimize array sum function |
| `openhands-search-file-test-001` | Write search_file function tests |
| `pandas-groupby-perf-001` | Accelerate groupby aggregate |
| `curl-security-review-001` | Code review: curl security |
| `kafka-security-review-001` | Code review: Kafka security |
| `sklearn-kmeans-perf-001` | Speed up K-means clustering |
| `test-coverage-gap-001` | Analyze test coverage gaps: Envoy HTTP connection manager |
| `test-coverage-gap-002` | Map test coverage gaps: Kafka consumer group coordinator |
| `test-integration-001` | Write integration tests: Flipt evaluation API |
| `test-integration-002` | Write integration tests: Navidrome media scanner |
| `test-unitgen-go-001` | Generate unit tests: Kubernetes storage value package |
| `test-unitgen-py-001` | Generate unit tests: Django cache middleware |
| `terraform-code-review-001` | Code review: Terraform |
| `vscode-code-review-001` | Code review: VS Code |

---

## ccb_document (20 tasks) — Documentation

API reference generation, architecture documentation, and migration guide creation.

| Task | Focus |
|------|-------|
| `cilium-api-doc-gen-001` | Cilium API reference generation |
| `docgen-changelog-001` | Generate Terraform changelog |
| `docgen-changelog-002` | Generate Flipt release notes |
| `docgen-inline-001` | Generate Python docstrings for Django cache middleware |
| `docgen-inline-002` | Generate Javadoc for Kafka record batch serialization |
| `docgen-onboard-001` | Generate onboarding guide for Istio control plane |
| `docgen-runbook-001` | Generate operational runbook for Prometheus TSDB compaction |
| `docgen-runbook-002` | Generate troubleshooting runbook for Envoy connection pools |
| `envoy-arch-doc-gen-001` | Envoy architecture documentation |
| `envoy-migration-doc-gen-001` | Envoy migration guide generation |
| `istio-arch-doc-gen-001` | Istio architecture documentation |
| `k8s-apiserver-doc-gen-001` | K8s API server documentation |
| `k8s-applyconfig-doc-gen-001` | K8s ApplyConfig documentation |
| `k8s-clientgo-doc-gen-001` | K8s client-go documentation |
| `k8s-kubelet-cm-doc-gen-001` | Kubelet container manager architecture guide |
| `k8s-fairqueuing-doc-gen-001` | K8s fair queuing documentation |
| `kafka-api-doc-gen-001` | Kafka API reference generation |
| `terraform-arch-doc-gen-001` | Terraform architecture documentation |
| `terraform-migration-doc-gen-001` | Terraform migration guide generation |
| `vscode-api-doc-gen-001` | VS Code API reference generation |

---

## ccb_secure (20 tasks) — Security & Compliance

CVE analysis, vulnerability reachability, governance enforcement, and access control.

| Task | Focus |
|------|-------|
| `curl-cve-triage-001` | curl CVE triage and analysis |
| `curl-vuln-reachability-001` | curl vulnerability reachability |
| `django-audit-trail-implement-001` | Django audit trail implementation |
| `django-cross-team-boundary-001` | Django cross-team boundary enforcement |
| `django-csrf-session-audit-001` | Analyze Django CSRF/session security |
| `django-legacy-dep-vuln-001` | Django legacy dependency vulnerability |
| `django-policy-enforcement-001` | Django policy enforcement |
| `django-repo-scoped-access-001` | Django repo-scoped access control |
| `django-role-based-access-001` | Django role-based access |
| `django-sensitive-file-exclusion-001` | Django sensitive file exclusion |
| `envoy-cve-triage-001` | Envoy CVE triage and analysis |
| `envoy-vuln-reachability-001` | Envoy vulnerability reachability |
| `flipt-degraded-context-fix-001` | Flipt error handling, missing deps |
| `flipt-repo-scoped-access-001` | Flipt repo-scoped access control |
| `golang-net-cve-triage-001` | golang/net CVE triage and analysis |
| `grpcurl-transitive-vuln-001` | grpcurl transitive vulnerability |
| `kafka-sasl-auth-audit-001` | Analyze Kafka SASL authentication flow |
| `kafka-vuln-reachability-001` | Kafka vulnerability reachability |
| `postgres-client-auth-audit-001` | Analyze PostgreSQL client auth pipeline |
| `wish-transitive-vuln-001` | wish transitive vulnerability |

---

## ccb_debug (20 tasks) — Debugging & Investigation

Root cause tracing, fault localization, regression provenance, and deep investigation.

| Task | Focus |
|------|-------|
| `ansible-galaxy-tar-regression-prove-001` | Find & prove: Galaxy collection tar extraction |
| `django-admins-migration-audit-001` | Audit Django ADMINS/MANAGERS migration |
| `envoy-duplicate-headers-debug-001` | Trace duplicate response headers |
| `flipt-auth-cookie-regression-prove-001` | Find & prove: Flipt cookie auth |
| `grafana-table-panel-regression-001` | Hunt dashboard table panel regression |
| `istio-xds-destrul-debug-001` | Diagnose dropped xDS DestinationRule |
| `linux-acpi-backlight-fault-001` | Locate ACPI backlight brightness bug |
| `linux-hda-intel-suspend-fault-001` | Diagnose HDA Intel sound suspend |
| `linux-iwlwifi-subdevice-fault-001` | Locate iwlwifi firmware PCI subdevice |
| `linux-nfs-inode-revalidate-fault-001` | Debug NFS mount inode revalidate |
| `linux-ssd-trim-timeout-fault-001` | Fix Samsung SSD TRIM timeout issue |
| `prometheus-queue-reshard-debug-001` | Debug remote-write queue resharding |
| `qutebrowser-hsv-color-regression-prove-001` | Find & prove: HSV color hue scaling |
| `qutebrowser-adblock-cache-regression-prove-001` | Find & prove: ad-blocker cache crash |
| `qutebrowser-darkmode-threshold-regression-prove-001` | Find & prove: dark mode threshold Qt 6.4 |
| `qutebrowser-url-regression-prove-001` | Find & prove: qutebrowser URL |
| `teleport-ssh-regression-prove-001` | Find & prove: Teleport SSH |
| `terraform-phantom-update-debug-001` | Identify phantom resource update trigger |
| `tutanota-search-regression-prove-001` | Find & prove: Tutanota search |
| `vuls-oval-regression-prove-001` | Find & prove: Vuls OVAL |

---

## Task Directory Structure

Each task follows this layout:

```
{task-name}/
  task.toml          # Task metadata: id, language, difficulty, timeouts
  instruction.md     # Agent instructions (what to do)
  environment/       # Dockerfile and build context
  tests/             # test.sh, ground truth, eval scripts
  solution/          # Reference solution (optional)
```

---

## Running Benchmarks

```bash
# Run all selected tasks across 2 configs (currently 251 entries in selected_benchmark_tasks.json)
bash configs/run_selected_tasks.sh

# Run a single SDLC phase
bash configs/run_selected_tasks.sh --benchmark ccb_fix

# Single task
harbor run --path benchmarks/ccb_build/servo-scrollend-event-feat-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [`docs/CONFIGS.md`](../docs/CONFIGS.md) for the full tool-by-tool breakdown of each config.
