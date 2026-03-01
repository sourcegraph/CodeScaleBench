# ccb_understand

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_understand_haiku_20260227_132300](../runs/ccb_understand_haiku_20260227_132300.md) | `baseline-local-direct` | 7 | 1.000 | 1.000 |
| [ccb_understand_haiku_20260227_132300](../runs/ccb_understand_haiku_20260227_132300.md) | `mcp-remote-direct` | 12 | 0.858 | 0.917 |
| [ccb_understand_haiku_20260227_132304](../runs/ccb_understand_haiku_20260227_132304.md) | `baseline-local-direct` | 7 | 0.857 | 0.857 |
| [ccb_understand_haiku_20260227_132304](../runs/ccb_understand_haiku_20260227_132304.md) | `mcp-remote-direct` | 12 | 0.942 | 1.000 |
| [ccb_understand_haiku_20260228_124521](../runs/ccb_understand_haiku_20260228_124521.md) | `mcp-remote-direct` | 4 | 0.823 | 1.000 |
| [understand_haiku_20260224_001815](../runs/understand_haiku_20260224_001815.md) | `baseline-local-direct` | 13 | 0.592 | 0.692 |
| [understand_haiku_20260224_001815](../runs/understand_haiku_20260224_001815.md) | `mcp-remote-direct` | 13 | 0.841 | 1.000 |
| [understand_haiku_20260225_211346](../runs/understand_haiku_20260225_211346.md) | `baseline-local-direct` | 7 | 0.789 | 1.000 |
| [understand_haiku_20260225_211346](../runs/understand_haiku_20260225_211346.md) | `mcp-remote-direct` | 7 | 0.870 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [argocd-arch-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--argocd-arch-orient-001.html) | [source](../../../benchmarks/ccb_understand/argocd-arch-orient-001) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [sgonly_argocd-arch-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_argocd-arch-orient-001.html) | [source](../../../benchmarks/ccb_understand/argocd-arch-orient-001) | `mcp-remote-direct` | `passed` | 0.810 | 2 | 0.977 |
| [argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--argocd-sync-reconcile-qa-001.html) | [source](../../../benchmarks/ccb_understand/argocd-sync-reconcile-qa-001) | `baseline-local-direct` | `passed` | 0.920 | 2 | 0.000 |
| [sgonly_argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_argocd-sync-reconcile-qa-001.html) | [source](../../../benchmarks/ccb_understand/argocd-sync-reconcile-qa-001) | `mcp-remote-direct` | `passed` | 0.830 | 2 | 0.970 |
| [cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-ebpf-datapath-handoff-001.html) | [source](../../../benchmarks/ccb_understand/cilium-ebpf-datapath-handoff-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-ebpf-datapath-handoff-001.html) | [source](../../../benchmarks/ccb_understand/cilium-ebpf-datapath-handoff-001) | `mcp-remote-direct` | `passed` | 0.830 | 2 | 0.968 |
| [cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-ebpf-fault-qa-001.html) | [source](../../../benchmarks/ccb_understand/cilium-ebpf-fault-qa-001) | `baseline-local-direct` | `passed` | 0.770 | 2 | 0.000 |
| [sgonly_cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-ebpf-fault-qa-001.html) | [source](../../../benchmarks/ccb_understand/cilium-ebpf-fault-qa-001) | `mcp-remote-direct` | `passed` | 0.820 | 2 | 0.973 |
| [cilium-project-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-project-orient-001.html) | [source](../../../benchmarks/ccb_understand/cilium-project-orient-001) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [sgonly_cilium-project-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-project-orient-001.html) | [source](../../../benchmarks/ccb_understand/cilium-project-orient-001) | `mcp-remote-direct` | `passed` | 0.960 | 2 | 0.974 |
| [django-composite-field-recover-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--django-composite-field-recover-001.html) | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `baseline-local-direct` | `passed` | 0.400 | 2 | 0.000 |
| [mcp_django-composite-field-recover-001_48TtoY](../tasks/ccb_understand_haiku_20260228_124521--mcp-remote-direct--mcp_django-composite-field-recover-001_48TtoY.html) | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `mcp-remote-direct` | `passed` | 0.400 | 3 | 0.163 |
| [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_django-composite-field-recover-001.html) | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `mcp-remote-direct` | `passed` | 0.750 | 3 | 0.290 |
| [django-template-inherit-recall-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--django-template-inherit-recall-001.html) | [source](../../../benchmarks/ccb_understand/django-template-inherit-recall-001) | `baseline-local-direct` | `passed` | 0.250 | 2 | 0.000 |
| [sgonly_django-template-inherit-recall-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_django-template-inherit-recall-001.html) | [source](../../../benchmarks/ccb_understand/django-template-inherit-recall-001) | `mcp-remote-direct` | `passed` | 0.250 | 2 | 0.143 |
| [envoy-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-contributor-workflow-001.html) | [source](../../../benchmarks/ccb_understand/envoy-contributor-workflow-001) | `baseline-local-direct` | `passed` | 0.970 | 2 | 0.000 |
| [sgonly_envoy-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-contributor-workflow-001.html) | [source](../../../benchmarks/ccb_understand/envoy-contributor-workflow-001) | `mcp-remote-direct` | `passed` | 0.910 | 2 | 0.955 |
| [envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--envoy-ext-authz-handoff-001.html) | [source](../../../benchmarks/ccb_understand/envoy-ext-authz-handoff-001) | `baseline-local-direct` | `passed` | 0.770 | 2 | 0.000 |
| [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001.html) | [source](../../../benchmarks/ccb_understand/envoy-ext-authz-handoff-001) | `mcp-remote-direct` | `passed` | 0.830 | 2 | 0.960 |
| [envoy-filter-chain-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-filter-chain-qa-001.html) | [source](../../../benchmarks/ccb_understand/envoy-filter-chain-qa-001) | `baseline-local-direct` | `passed` | 0.970 | 2 | 0.000 |
| [sgonly_envoy-filter-chain-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-filter-chain-qa-001.html) | [source](../../../benchmarks/ccb_understand/envoy-filter-chain-qa-001) | `mcp-remote-direct` | `passed` | 0.880 | 2 | 0.967 |
| [envoy-pool-ready-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--envoy-pool-ready-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_envoy-pool-ready-search-001_EwEb4o](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_envoy-pool-ready-search-001_EwEb4o.html) | — | `mcp-remote-direct` | `passed` | 0.300 | 2 | 0.000 |
| [mcp_envoy-pool-ready-search-001_HxPKch](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_envoy-pool-ready-search-001_HxPKch.html) | — | `mcp-remote-direct` | `passed` | 0.300 | 2 | 0.000 |
| [envoy-request-routing-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-request-routing-qa-001.html) | [source](../../../benchmarks/ccb_understand/envoy-request-routing-qa-001) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [sgonly_envoy-request-routing-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-request-routing-qa-001.html) | [source](../../../benchmarks/ccb_understand/envoy-request-routing-qa-001) | `mcp-remote-direct` | `passed` | 0.870 | 2 | 0.971 |
| [envoy-retry-eval-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--envoy-retry-eval-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_envoy-retry-eval-search-001_QkEHtp](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_envoy-retry-eval-search-001_QkEHtp.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_envoy-retry-eval-search-001_pwYQ4g](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_envoy-retry-eval-search-001_pwYQ4g.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [firefox-cache-race-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--firefox-cache-race-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.200 |
| [mcp_firefox-cache-race-search-001_1v6Sie](../tasks/ccb_understand_haiku_20260228_124521--mcp-remote-direct--mcp_firefox-cache-race-search-001_1v6Sie.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 1 | 0.667 |
| [firefox-http-response-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--firefox-http-response-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_firefox-http-response-search-001_QRqYdt](../tasks/ccb_understand_haiku_20260228_124521--mcp-remote-direct--mcp_firefox-http-response-search-001_QRqYdt.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 1 | 0.857 |
| [grafana-field-calcs-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--grafana-field-calcs-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_grafana-field-calcs-search-001_B5oEI1](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_grafana-field-calcs-search-001_B5oEI1.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_grafana-field-calcs-search-001_LFZ6hQ](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_grafana-field-calcs-search-001_LFZ6hQ.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [istio-xds-serving-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--istio-xds-serving-qa-001.html) | [source](../../../benchmarks/ccb_understand/istio-xds-serving-qa-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [sgonly_istio-xds-serving-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_istio-xds-serving-qa-001.html) | [source](../../../benchmarks/ccb_understand/istio-xds-serving-qa-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.971 |
| [k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--k8s-cri-containerd-reason-001.html) | [source](../../../benchmarks/ccb_understand/k8s-cri-containerd-reason-001) | `baseline-local-direct` | `passed` | 0.850 | 2 | 0.000 |
| [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001.html) | [source](../../../benchmarks/ccb_understand/k8s-cri-containerd-reason-001) | `mcp-remote-direct` | `passed` | 0.850 | 2 | 0.857 |
| [k8s-eviction-sync-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--k8s-eviction-sync-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_k8s-eviction-sync-search-001_KmypBE](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_k8s-eviction-sync-search-001_KmypBE.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.714 |
| [mcp_k8s-eviction-sync-search-001_auPFDM](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_k8s-eviction-sync-search-001_auPFDM.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.625 |
| [k8s-scheduler-filter-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--k8s-scheduler-filter-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_k8s-scheduler-filter-search-001_1B4q1U](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_k8s-scheduler-filter-search-001_1B4q1U.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.667 |
| [mcp_k8s-scheduler-filter-search-001_XRD3ip](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_k8s-scheduler-filter-search-001_XRD3ip.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.800 |
| [kafka-assign-handler-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--kafka-assign-handler-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_kafka-assign-handler-search-001_VyIRYg](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_kafka-assign-handler-search-001_VyIRYg.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.833 |
| [mcp_kafka-assign-handler-search-001_1PpNNb](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_kafka-assign-handler-search-001_1PpNNb.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.778 |
| [kafka-batch-drain-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--kafka-batch-drain-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_kafka-batch-drain-search-001_ZYGXDh](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_kafka-batch-drain-search-001_ZYGXDh.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.600 |
| [mcp_kafka-batch-drain-search-001_tJsbqz](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_kafka-batch-drain-search-001_tJsbqz.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.800 |
| [kafka-build-orient-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--kafka-build-orient-001.html) | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `baseline-local-direct` | `passed` | 0.840 | 2 | 0.000 |
| [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_kafka-build-orient-001.html) | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `mcp-remote-direct` | `passed` | 0.870 | 2 | 0.955 |
| [kafka-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--kafka-contributor-workflow-001.html) | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `baseline-local-direct` | `passed` | 0.950 | 2 | 0.000 |
| [mcp_kafka-contributor-workflow-001_M1NQMf](../tasks/ccb_understand_haiku_20260228_124521--mcp-remote-direct--mcp_kafka-contributor-workflow-001_M1NQMf.html) | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `mcp-remote-direct` | `passed` | 0.890 | 3 | 0.944 |
| [sgonly_kafka-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-contributor-workflow-001.html) | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `mcp-remote-direct` | `passed` | 0.820 | 3 | 0.955 |
| [kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--kafka-message-lifecycle-qa-001.html) | [source](../../../benchmarks/ccb_understand/kafka-message-lifecycle-qa-001) | `baseline-local-direct` | `passed` | 0.860 | 2 | 0.000 |
| [sgonly_kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-message-lifecycle-qa-001.html) | [source](../../../benchmarks/ccb_understand/kafka-message-lifecycle-qa-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.972 |
| [numpy-dtype-localize-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--numpy-dtype-localize-001.html) | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_numpy-dtype-localize-001.html) | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.957 |
| [pandas-pivot-internal-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--pandas-pivot-internal-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_pandas-pivot-internal-search-001_tnxuuD](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_pandas-pivot-internal-search-001_tnxuuD.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_pandas-pivot-internal-search-001_9DdhSm](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_pandas-pivot-internal-search-001_9DdhSm.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [rust-liveness-gen-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--rust-liveness-gen-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_rust-liveness-gen-search-001_DJr9ub](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_rust-liveness-gen-search-001_DJr9ub.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_rust-liveness-gen-search-001_Aru7f4](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_rust-liveness-gen-search-001_Aru7f4.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [rust-type-tests-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--rust-type-tests-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_rust-type-tests-search-001_4Sg2dg](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_rust-type-tests-search-001_4Sg2dg.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_rust-type-tests-search-001_OKq7k3](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_rust-type-tests-search-001_OKq7k3.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.833 |
| [sklearn-fastica-fit-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--sklearn-fastica-fit-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_sklearn-fastica-fit-search-001_KSnBCG](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_sklearn-fastica-fit-search-001_KSnBCG.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_sklearn-fastica-fit-search-001_unhAKu](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_sklearn-fastica-fit-search-001_unhAKu.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |
| [terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--terraform-plan-pipeline-qa-001.html) | [source](../../../benchmarks/ccb_understand/terraform-plan-pipeline-qa-001) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [sgonly_terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_terraform-plan-pipeline-qa-001.html) | [source](../../../benchmarks/ccb_understand/terraform-plan-pipeline-qa-001) | `mcp-remote-direct` | `passed` | 0.950 | 2 | 0.971 |
| [terraform-state-backend-handoff-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--terraform-state-backend-handoff-001.html) | [source](../../../benchmarks/ccb_understand/terraform-state-backend-handoff-001) | `baseline-local-direct` | `passed` | 0.710 | 2 | 0.000 |
| [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001.html) | [source](../../../benchmarks/ccb_understand/terraform-state-backend-handoff-001) | `mcp-remote-direct` | `passed` | 0.830 | 2 | 0.969 |
| [vscode-ext-host-qa-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--vscode-ext-host-qa-001.html) | [source](../../../benchmarks/ccb_understand/vscode-ext-host-qa-001) | `baseline-local-direct` | `passed` | 0.950 | 2 | 0.000 |
| [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_vscode-ext-host-qa-001.html) | [source](../../../benchmarks/ccb_understand/vscode-ext-host-qa-001) | `mcp-remote-direct` | `passed` | 0.960 | 2 | 0.963 |
| [vscode-keybinding-merge-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--vscode-keybinding-merge-search-001.html) | — | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [mcp_vscode-keybinding-merge-search-001_yI3kCw](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_vscode-keybinding-merge-search-001_yI3kCw.html) | — | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.000 |
| [mcp_vscode-keybinding-merge-search-001_ZZiuGd](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_vscode-keybinding-merge-search-001_ZZiuGd.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |

## Multi-Run Variance

Tasks with multiple valid runs (9 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| django-composite-field-recover-001 | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `baseline-local-direct` | 2 | 0.400 | 0.000 | 0.400, 0.400 |
| django-composite-field-recover-001 | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `mcp-remote-direct` | 2 | 0.575 | 0.247 | 0.750, 0.400 |
| envoy-ext-authz-handoff-001 | [source](../../../benchmarks/ccb_understand/envoy-ext-authz-handoff-001) | `mcp-remote-direct` | 2 | 0.830 | 0.000 | 0.830, 0.830 |
| k8s-cri-containerd-reason-001 | [source](../../../benchmarks/ccb_understand/k8s-cri-containerd-reason-001) | `baseline-local-direct` | 2 | 0.850 | 0.000 | 0.850, 0.850 |
| kafka-build-orient-001 | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `baseline-local-direct` | 2 | 0.780 | 0.085 | 0.720, 0.840 |
| kafka-contributor-workflow-001 | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `mcp-remote-direct` | 2 | 0.855 | 0.050 | 0.820, 0.890 |
| numpy-dtype-localize-001 | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `mcp-remote-direct` | 2 | 0.967 | 0.047 | 0.933, 1.000 |
| terraform-state-backend-handoff-001 | [source](../../../benchmarks/ccb_understand/terraform-state-backend-handoff-001) | `mcp-remote-direct` | 2 | 0.730 | 0.141 | 0.630, 0.830 |
| vscode-ext-host-qa-001 | [source](../../../benchmarks/ccb_understand/vscode-ext-host-qa-001) | `baseline-local-direct` | 2 | 0.975 | 0.035 | 1.000, 0.950 |
