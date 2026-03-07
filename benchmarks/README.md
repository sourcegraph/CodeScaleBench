# CodeScaleBench Benchmarks

This directory contains SDLC-aligned suites plus Org org-scale retrieval suites. The canonical task catalog is in [`selected_benchmark_tasks.json`](../configs/selected_benchmark_tasks.json) (370 tasks across 20 suites: 150 SDLC + 220 Org). Suite sizes use DOE-driven Neyman-optimal allocation to maximize statistical power per suite.

See [`docs/TASK_SELECTION.md`](../docs/TASK_SELECTION.md) for selection methodology.

---

## SDLC Suite Overview

| Suite | SDLC Phase | Tasks | Description |
|-------|-----------|------:|-------------|
| `csb_sdlc_fix` | Bug Repair | 26 | Diagnosing and fixing real bugs across production codebases |
| `csb_sdlc_feature` | Feature Implementation | 23 | New features, interface implementation, big-code features |
| `csb_sdlc_debug` | Debugging & Investigation | 18 | Root cause tracing, fault localization, provenance |
| `csb_sdlc_test` | Testing & QA | 18 | Code review, performance testing, code search validation, test generation |
| `csb_sdlc_refactor` | Cross-File Refactoring | 16 | Cross-file refactoring, enterprise dependency refactoring, rename refactoring |
| `csb_sdlc_design` | Architecture & Design | 14 | Architecture analysis, dependency graphs, change impact |
| `csb_sdlc_document` | Documentation | 13 | API references, architecture docs, migration guides, runbooks |
| `csb_sdlc_secure` | Security & Compliance | 12 | CVE analysis, reachability, governance, access control |
| `csb_sdlc_understand` | Requirements & Discovery | 10 | Codebase comprehension, onboarding, Q&A, knowledge recovery |
| **Total** | | **150** | |

---

## CodeScaleBench-Org Suite Overview

These suites measure cross-repo discovery, tracing, and org-scale code intelligence use cases.

| Suite | Tasks | Description |
|-------|------:|-------------|
| `csb_org_onboarding` | 28 | Onboarding, architecture comprehension, API discovery |
| `csb_org_migration` | 26 | Framework and platform migrations across repos |
| `csb_org_security` | 24 | Vulnerability remediation and security analysis at org scale |
| `csb_org_crossrepo_tracing` | 22 | Cross-repo dependency tracing and symbol resolution |
| `csb_org_domain` | 20 | Domain-specific lineage and analysis workflows |
| `csb_org_incident` | 20 | Incident debugging across services and repos |
| `csb_org_compliance` | 18 | Compliance, audit, and provenance workflows |
| `csb_org_platform` | 18 | Platform/devtools and tribal-knowledge discovery |
| `csb_org_crossorg` | 15 | Cross-org discovery and authoritative repo identification |
| `csb_org_org` | 15 | Org-wide coding correctness tasks requiring broad context |
| `csb_org_crossrepo` | 14 | Cross-repo search, dependency discovery, impact analysis |
| **Total** | **220** | |

For suite taxonomy, authoring, and oracle evaluation details, see [`docs/ORG_TASKS.md`](../docs/ORG_TASKS.md).

---

## csb_sdlc_fix (26 tasks) — Bug Repair

Diagnosing and fixing real bugs across production codebases (SWE-bench Pro, PyTorch, large repos).

| Task | Focus |
|------|-------|
| `ansible-abc-imports-fix-001` | Inconsistent collection ABC imports |
| `ansible-module-respawn-fix-001` | Module respawn under compatible interpreters |
| `django-modelchoice-fk-fix-001` | Fix ModelChoiceField ForeignKey rendering |
| `django-select-for-update-fix-001` | Django select_for_update ORM crash |
| `envoy-dfp-host-leak-fix-001` | Dynamic forward proxy host header memory leak |
| `envoy-udp-proxy-cds-fix-001` | UDP proxy crash on dynamic CDS/EDS cluster update |
| `flink-window-late-data-fix-001` | Flink window late data handling fix |
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
| `pytorch-cudnn-version-fix-001` | Expose cuDNN runtime version |
| `pytorch-dynamo-keyerror-fix-001` | Fix dynamo keyerror and attribute |
| `pytorch-release-210-fix-001` | Release 2.10 bug fix changes |
| `pytorch-relu-gelu-fusion-fix-001` | Revert Inductor ReLU/GELU fusions |
| `pytorch-tracer-graph-cleanup-fix-001` | Cleanup graphs for failed tracer outputs |
| `terraform-plan-null-unknown-fix-001` | Terraform plan null/unknown value rendering |

---

## csb_sdlc_feature (23 tasks) — Feature Implementation

New feature implementation, interface implementation, and big-code feature tasks.

| Task | Focus |
|------|-------|
| `bustub-hyperloglog-impl-001` | Implement HyperLogLog cardinality estimator |
| `camel-fix-protocol-feat-001` | Implement camel-fix component FIX protocol |
| `cilium-policy-audit-logger-feat-001` | Implement Cilium policy audit logger |
| `cilium-policy-quota-feat-001` | Implement Cilium policy quota enforcement |
| `curl-http3-priority-feat-001` | Implement curl HTTP/3 priority support |
| `django-rate-limit-middleware-feat-001` | Implement Django rate limit middleware |
| `envoy-custom-header-filter-feat-001` | Implement Envoy custom header filter |
| `envoy-grpc-server-impl-001` | Identify gRPC server implementations |
| `flink-pricing-window-feat-001` | Implement PricingSessionWindow for trading |
| `k8s-noschedule-taint-feat-001` | Implement NoScheduleNoTraffic taint effect |
| `k8s-runtime-object-impl-001` | Find runtime.Object interface implementors |
| `numpy-rolling-median-feat-001` | Implement NumPy rolling median |
| `pandas-merge-asof-indicator-feat-001` | Implement pandas merge_asof indicator |
| `postgres-copy-csv-header-feat-001` | Implement PostgreSQL COPY CSV header support |
| `prometheus-silence-bulk-api-feat-001` | Implement Prometheus silence bulk API |
| `pytorch-gradient-noise-feat-001` | Implement PyTorch gradient noise |
| `servo-css-container-query-feat-001` | Implement Servo CSS container queries |
| `servo-scrollend-event-feat-001` | Add scrollend DOM event support |
| `strata-cds-tranche-feat-001` | Implement CDS tranche CDO product |
| `tensorrt-mxfp4-quant-feat-001` | Add W4A8_MXFP4_INT8 quantization mode |
| `terraform-compact-diff-fmt-feat-001` | Implement Terraform compact diff format |
| `vscode-custom-fold-region-feat-001` | Implement VS Code custom fold regions |
| `vscode-stale-diagnostics-feat-001` | Fix stale diagnostics after git branch |

---

## csb_sdlc_debug (18 tasks) — Debugging & Investigation

Root cause tracing, fault localization, regression provenance, and deep investigation.

| Task | Focus |
|------|-------|
| `ansible-galaxy-tar-regression-prove-001` | Find & prove: Galaxy collection tar extraction |
| `envoy-duplicate-headers-debug-001` | Trace duplicate response headers |
| `flipt-auth-cookie-regression-prove-001` | Find & prove: Flipt cookie auth |
| `grafana-table-panel-regression-001` | Hunt dashboard table panel regression |
| `istio-xds-destrul-debug-001` | Diagnose dropped xDS DestinationRule |
| `linux-acpi-backlight-fault-001` | Locate ACPI backlight brightness bug |
| `linux-hda-intel-suspend-fault-001` | Diagnose HDA Intel sound suspend |
| `linux-iwlwifi-subdevice-fault-001` | Locate iwlwifi firmware PCI subdevice |
| `linux-nfs-inode-revalidate-fault-001` | Debug NFS mount inode revalidate |
| `prometheus-queue-reshard-debug-001` | Debug remote-write queue resharding |
| `qutebrowser-adblock-cache-regression-prove-001` | Find & prove: ad-blocker cache crash |
| `qutebrowser-darkmode-threshold-regression-prove-001` | Find & prove: dark mode threshold Qt 6.4 |
| `qutebrowser-hsv-color-regression-prove-001` | Find & prove: HSV color hue scaling |
| `qutebrowser-url-regression-prove-001` | Find & prove: qutebrowser URL |
| `teleport-ssh-regression-prove-001` | Find & prove: Teleport SSH |
| `terraform-phantom-update-debug-001` | Identify phantom resource update trigger |
| `tutanota-search-regression-prove-001` | Find & prove: Tutanota search |
| `vuls-oval-regression-prove-001` | Find & prove: Vuls OVAL |

---

## csb_sdlc_test (18 tasks) — Testing & QA

Code review with injected defects, performance testing, and code search validation.

| Task | Focus |
|------|-------|
| `aspnetcore-code-review-001` | Code review: ASP.NET Core |
| `calcom-code-review-001` | Code review: Cal.com |
| `curl-security-review-001` | Code review: curl security |
| `envoy-code-review-001` | Code review: Envoy |
| `ghost-code-review-001` | Code review: Ghost |
| `kafka-security-review-001` | Code review: Kafka security |
| `numpy-array-sum-perf-001` | Optimize array sum function |
| `openhands-search-file-test-001` | Write search_file function tests |
| `pandas-groupby-perf-001` | Accelerate groupby aggregate |
| `sklearn-kmeans-perf-001` | Speed up K-means clustering |
| `terraform-code-review-001` | Code review: Terraform |
| `test-coverage-gap-001` | Analyze test coverage gaps: Envoy HTTP connection manager |
| `test-coverage-gap-002` | Map test coverage gaps: Kafka consumer group coordinator |
| `test-integration-001` | Write integration tests: Flipt evaluation API |
| `test-integration-002` | Write integration tests: Navidrome media scanner |
| `test-unitgen-go-001` | Generate unit tests: Kubernetes storage value package |
| `test-unitgen-py-001` | Generate unit tests: Django cache middleware |
| `vscode-code-review-001` | Code review: VS Code |

---

## csb_sdlc_refactor (16 tasks) — Cross-File Refactoring

Cross-file refactoring, enterprise dependency refactoring, and rename refactoring tasks.

| Task | Focus |
|------|-------|
| `cilium-endpoint-manager-refac-001` | Refactor Cilium endpoint manager |
| `django-request-factory-refac-001` | Refactor Django request factory |
| `envoy-listener-manager-refac-001` | Refactor Envoy listener manager |
| `flipt-dep-refactor-001` | Dependency refactoring (Flipt) |
| `flipt-flagexists-refactor-001` | Add FlagExists to ReadOnlyFlagStore (Flipt) |
| `istio-discovery-server-refac-001` | Refactor Istio discovery server |
| `k8s-score-normalizer-refac-001` | Rename ScoreExtensions to ScoreNormalizer |
| `kafka-batch-accumulator-refac-001` | Rename RecordAccumulator to BatchAccumulator |
| `kubernetes-scheduler-profile-refac-001` | Refactor Kubernetes scheduler profile |
| `numpy-array-dispatch-refac-001` | Refactor NumPy array dispatch |
| `pandas-index-engine-refac-001` | Refactor pandas index engine |
| `prometheus-query-engine-refac-001` | Refactor Prometheus query engine |
| `python-http-class-naming-refac-001` | Standardize HTTP class naming |
| `pytorch-optimizer-foreach-refac-001` | Refactor PyTorch optimizer foreach |
| `strata-fx-european-refac-001` | Rename FxVanillaOption to FxEuropeanOption |
| `terraform-eval-context-refac-001` | Refactor Terraform eval context |

---

## csb_sdlc_design (14 tasks) — Architecture & Design

Architecture analysis, dependency chain tracing, change impact assessment, and design proposals.

| Task | Focus |
|------|-------|
| `camel-routing-arch-001` | Trace Camel message routing architecture |
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
| `k8s-typemeta-dep-chain-001` | Trace TypeMeta dependency chain |
| `kafka-flink-streaming-arch-001` | Trace Kafka-Flink streaming data flow |
| `postgres-query-exec-arch-001` | Trace PostgreSQL query execution pipeline |

---

## csb_sdlc_document (13 tasks) — Documentation

API reference generation, architecture documentation, and migration guide creation.

| Task | Focus |
|------|-------|
| `docgen-changelog-002` | Generate Flipt release notes |
| `docgen-inline-002` | Generate Javadoc for Kafka record batch serialization |
| `docgen-runbook-001` | Generate operational runbook for Prometheus TSDB compaction |
| `envoy-arch-doc-gen-001` | Envoy architecture documentation |
| `envoy-migration-doc-gen-001` | Envoy migration guide generation |
| `istio-arch-doc-gen-001` | Istio architecture documentation |
| `k8s-apiserver-doc-gen-001` | K8s API server documentation |
| `k8s-applyconfig-doc-gen-001` | K8s ApplyConfig documentation |
| `k8s-clientgo-doc-gen-001` | K8s client-go documentation |
| `k8s-fairqueuing-doc-gen-001` | K8s fair queuing documentation |
| `k8s-kubelet-cm-doc-gen-001` | Kubelet container manager architecture guide |
| `kafka-api-doc-gen-001` | Kafka API reference generation |
| `terraform-arch-doc-gen-001` | Terraform architecture documentation |

---

## csb_sdlc_secure (12 tasks) — Security & Compliance

CVE analysis, vulnerability reachability, governance enforcement, and access control.

| Task | Focus |
|------|-------|
| `curl-cve-triage-001` | curl CVE triage and analysis |
| `curl-vuln-reachability-001` | curl vulnerability reachability |
| `django-audit-trail-implement-001` | Django audit trail implementation |
| `django-cross-team-boundary-001` | Django cross-team boundary enforcement |
| `django-legacy-dep-vuln-001` | Django legacy dependency vulnerability |
| `django-repo-scoped-access-001` | Django repo-scoped access control |
| `django-role-based-access-001` | Django role-based access |
| `django-sensitive-file-exclusion-001` | Django sensitive file exclusion |
| `flipt-degraded-context-fix-001` | Flipt error handling, missing deps |
| `flipt-repo-scoped-access-001` | Flipt repo-scoped access control |
| `grpcurl-transitive-vuln-001` | grpcurl transitive vulnerability |
| `kafka-sasl-auth-audit-001` | Analyze Kafka SASL authentication flow |

---

## csb_sdlc_understand (10 tasks) — Requirements & Discovery

Codebase comprehension, natural-language Q&A, onboarding exercises, and knowledge recovery tasks.

| Task | Focus |
|------|-------|
| `argocd-arch-orient-001` | Explore Argo CD architecture |
| `cilium-ebpf-fault-qa-001` | Explain eBPF fault isolation |
| `cilium-project-orient-001` | Explore Cilium project structure |
| `django-composite-field-recover-001` | Add composite field validator |
| `django-template-inherit-recall-001` | Fix template inheritance regression |
| `envoy-request-routing-qa-001` | Trace Envoy request routing path |
| `kafka-build-orient-001` | Explore Kafka build system |
| `kafka-contributor-workflow-001` | Learn Kafka contribution process |
| `numpy-dtype-localize-001` | Trace nullable integer dtype incompatibility |
| `terraform-plan-pipeline-qa-001` | Explain terraform plan pipeline |

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
# Run all 370 canonical tasks across 2 configs
bash configs/run_selected_tasks.sh

# Run a single SDLC phase
bash configs/run_selected_tasks.sh --benchmark csb_sdlc_fix

# Single task
harbor run --path benchmarks/csb_sdlc_feature/servo-scrollend-event-feat-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [`docs/CONFIGS.md`](../docs/CONFIGS.md) for the full tool-by-tool breakdown of each config.
