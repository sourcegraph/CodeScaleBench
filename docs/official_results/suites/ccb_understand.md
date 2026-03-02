# ccb_understand

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_understand_haiku_20260227_132300](../runs/ccb_understand_haiku_20260227_132300.md) | `baseline-local-direct` | 7 | 1.000 | 1.000 |
| [ccb_understand_haiku_20260227_132300](../runs/ccb_understand_haiku_20260227_132300.md) | `mcp-remote-direct` | 12 | 0.858 | 0.917 |
| [ccb_understand_haiku_20260227_132304](../runs/ccb_understand_haiku_20260227_132304.md) | `baseline-local-direct` | 7 | 0.857 | 0.857 |
| [ccb_understand_haiku_20260227_132304](../runs/ccb_understand_haiku_20260227_132304.md) | `mcp-remote-direct` | 12 | 0.942 | 1.000 |
| [ccb_understand_haiku_20260228_124521](../runs/ccb_understand_haiku_20260228_124521.md) | `mcp-remote-direct` | 4 | 0.823 | 1.000 |
| [understand_haiku_20260301_071233](../runs/understand_haiku_20260301_071233.md) | `baseline-local-direct` | 20 | 0.884 | 1.000 |
| [understand_haiku_20260301_071233](../runs/understand_haiku_20260301_071233.md) | `mcp-remote-direct` | 20 | 0.850 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [argocd-arch-orient-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--argocd-arch-orient-001.html) | [source](../../../benchmarks/ccb_understand/argocd-arch-orient-001) | `baseline-local-direct` | `passed` | 0.750 | 4 | 0.000 |
| [sgonly_argocd-arch-orient-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_argocd-arch-orient-001.html) | [source](../../../benchmarks/ccb_understand/argocd-arch-orient-001) | `mcp-remote-direct` | `passed` | 0.770 | 4 | 0.973 |
| [argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--argocd-sync-reconcile-qa-001.html) | — | `baseline-local-direct` | `passed` | 0.820 | 4 | 0.000 |
| [sgonly_argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_argocd-sync-reconcile-qa-001.html) | — | `mcp-remote-direct` | `passed` | 0.870 | 4 | 0.969 |
| [cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--cilium-ebpf-datapath-handoff-001.html) | — | `baseline-local-direct` | `passed` | 0.830 | 4 | 0.000 |
| [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_cilium-ebpf-datapath-handoff-001.html) | — | `mcp-remote-direct` | `passed` | 0.900 | 4 | 0.935 |
| [cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--cilium-ebpf-fault-qa-001.html) | [source](../../../benchmarks/ccb_understand/cilium-ebpf-fault-qa-001) | `baseline-local-direct` | `passed` | 0.800 | 4 | 0.000 |
| [sgonly_cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_cilium-ebpf-fault-qa-001.html) | [source](../../../benchmarks/ccb_understand/cilium-ebpf-fault-qa-001) | `mcp-remote-direct` | `passed` | 0.850 | 4 | 0.963 |
| [cilium-project-orient-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--cilium-project-orient-001.html) | [source](../../../benchmarks/ccb_understand/cilium-project-orient-001) | `baseline-local-direct` | `passed` | 0.960 | 4 | 0.000 |
| [sgonly_cilium-project-orient-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_cilium-project-orient-001.html) | [source](../../../benchmarks/ccb_understand/cilium-project-orient-001) | `mcp-remote-direct` | `passed` | 0.910 | 4 | 0.923 |
| [django-composite-field-recover-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--django-composite-field-recover-001.html) | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `baseline-local-direct` | `passed` | 0.900 | 4 | 0.000 |
| [mcp_django-composite-field-recover-001_48TtoY](../tasks/ccb_understand_haiku_20260228_124521--mcp-remote-direct--mcp_django-composite-field-recover-001_48TtoY.html) | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `mcp-remote-direct` | `passed` | 0.400 | 5 | 0.163 |
| [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_django-composite-field-recover-001.html) | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `mcp-remote-direct` | `passed` | 0.400 | 5 | 0.279 |
| [django-template-inherit-recall-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--django-template-inherit-recall-001.html) | [source](../../../benchmarks/ccb_understand/django-template-inherit-recall-001) | `baseline-local-direct` | `passed` | 0.800 | 4 | 0.000 |
| [sgonly_django-template-inherit-recall-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_django-template-inherit-recall-001.html) | [source](../../../benchmarks/ccb_understand/django-template-inherit-recall-001) | `mcp-remote-direct` | `passed` | 0.800 | 4 | 0.309 |
| [envoy-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--envoy-contributor-workflow-001.html) | — | `baseline-local-direct` | `passed` | 0.940 | 4 | 0.000 |
| [sgonly_envoy-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-contributor-workflow-001.html) | — | `mcp-remote-direct` | `passed` | 0.940 | 4 | 0.900 |
| [envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--envoy-ext-authz-handoff-001.html) | — | `baseline-local-direct` | `passed` | 0.890 | 4 | 0.000 |
| [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001.html) | — | `mcp-remote-direct` | `passed` | 0.830 | 4 | 0.950 |
| [envoy-filter-chain-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--envoy-filter-chain-qa-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_envoy-filter-chain-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-filter-chain-qa-001.html) | — | `mcp-remote-direct` | `passed` | 0.960 | 4 | 0.973 |
| [envoy-pool-ready-search-001](../tasks/ccb_understand_haiku_20260227_132300--baseline-local-direct--envoy-pool-ready-search-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_envoy-pool-ready-search-001_EwEb4o](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_envoy-pool-ready-search-001_EwEb4o.html) | — | `mcp-remote-direct` | `passed` | 0.300 | 2 | 0.000 |
| [mcp_envoy-pool-ready-search-001_HxPKch](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_envoy-pool-ready-search-001_HxPKch.html) | — | `mcp-remote-direct` | `passed` | 0.300 | 2 | 0.000 |
| [envoy-request-routing-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--envoy-request-routing-qa-001.html) | [source](../../../benchmarks/ccb_understand/envoy-request-routing-qa-001) | `baseline-local-direct` | `passed` | 0.960 | 4 | 0.000 |
| [sgonly_envoy-request-routing-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-request-routing-qa-001.html) | [source](../../../benchmarks/ccb_understand/envoy-request-routing-qa-001) | `mcp-remote-direct` | `passed` | 0.910 | 4 | 0.975 |
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
| [istio-xds-serving-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--istio-xds-serving-qa-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_istio-xds-serving-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_istio-xds-serving-qa-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.968 |
| [k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--k8s-cri-containerd-reason-001.html) | — | `baseline-local-direct` | `passed` | 0.850 | 4 | 0.000 |
| [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001.html) | — | `mcp-remote-direct` | `passed` | 0.850 | 4 | 0.846 |
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
| [kafka-build-orient-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--kafka-build-orient-001.html) | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `baseline-local-direct` | `passed` | 0.840 | 4 | 0.000 |
| [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-build-orient-001.html) | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `mcp-remote-direct` | `passed` | 0.770 | 4 | 0.963 |
| [kafka-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--kafka-contributor-workflow-001.html) | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `baseline-local-direct` | `passed` | 0.950 | 4 | 0.000 |
| [mcp_kafka-contributor-workflow-001_M1NQMf](../tasks/ccb_understand_haiku_20260228_124521--mcp-remote-direct--mcp_kafka-contributor-workflow-001_M1NQMf.html) | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `mcp-remote-direct` | `passed` | 0.890 | 5 | 0.944 |
| [sgonly_kafka-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-contributor-workflow-001.html) | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `mcp-remote-direct` | `passed` | 0.820 | 5 | 0.944 |
| [kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--kafka-message-lifecycle-qa-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-message-lifecycle-qa-001.html) | — | `mcp-remote-direct` | `passed` | 0.890 | 4 | 0.967 |
| [numpy-dtype-localize-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--numpy-dtype-localize-001.html) | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `baseline-local-direct` | `passed` | 0.783 | 4 | 0.000 |
| [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_numpy-dtype-localize-001.html) | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `mcp-remote-direct` | `passed` | 0.850 | 4 | 0.939 |
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
| [terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--terraform-plan-pipeline-qa-001.html) | [source](../../../benchmarks/ccb_understand/terraform-plan-pipeline-qa-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_terraform-plan-pipeline-qa-001.html) | [source](../../../benchmarks/ccb_understand/terraform-plan-pipeline-qa-001) | `mcp-remote-direct` | `passed` | 0.950 | 4 | 0.935 |
| [terraform-state-backend-handoff-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--terraform-state-backend-handoff-001.html) | — | `baseline-local-direct` | `passed` | 0.660 | 4 | 0.000 |
| [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001.html) | — | `mcp-remote-direct` | `passed` | 0.730 | 4 | 0.903 |
| [vscode-ext-host-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--vscode-ext-host-qa-001.html) | — | `baseline-local-direct` | `passed` | 0.950 | 4 | 0.000 |
| [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_vscode-ext-host-qa-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.957 |
| [vscode-keybinding-merge-search-001](../tasks/ccb_understand_haiku_20260227_132304--baseline-local-direct--vscode-keybinding-merge-search-001.html) | — | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [mcp_vscode-keybinding-merge-search-001_yI3kCw](../tasks/ccb_understand_haiku_20260227_132300--mcp-remote-direct--mcp_vscode-keybinding-merge-search-001_yI3kCw.html) | — | `mcp-remote-direct` | `failed` | 0.000 | 2 | 0.000 |
| [mcp_vscode-keybinding-merge-search-001_ZZiuGd](../tasks/ccb_understand_haiku_20260227_132304--mcp-remote-direct--mcp_vscode-keybinding-merge-search-001_ZZiuGd.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.000 |

## Multi-Run Variance

Tasks with multiple valid runs (20 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| argocd-arch-orient-001 | [source](../../../benchmarks/ccb_understand/argocd-arch-orient-001) | `baseline-local-direct` | 3 | 0.487 | 0.422 | 0.000, 0.710, 0.750 |
| argocd-arch-orient-001 | [source](../../../benchmarks/ccb_understand/argocd-arch-orient-001) | `mcp-remote-direct` | 3 | 0.783 | 0.023 | 0.810, 0.770, 0.770 |
| cilium-ebpf-fault-qa-001 | [source](../../../benchmarks/ccb_understand/cilium-ebpf-fault-qa-001) | `baseline-local-direct` | 3 | 0.813 | 0.051 | 0.770, 0.870, 0.800 |
| cilium-ebpf-fault-qa-001 | [source](../../../benchmarks/ccb_understand/cilium-ebpf-fault-qa-001) | `mcp-remote-direct` | 3 | 0.890 | 0.096 | 0.820, 1.000, 0.850 |
| cilium-project-orient-001 | [source](../../../benchmarks/ccb_understand/cilium-project-orient-001) | `baseline-local-direct` | 3 | 0.623 | 0.540 | 0.000, 0.910, 0.960 |
| cilium-project-orient-001 | [source](../../../benchmarks/ccb_understand/cilium-project-orient-001) | `mcp-remote-direct` | 3 | 0.930 | 0.026 | 0.960, 0.920, 0.910 |
| django-composite-field-recover-001 | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `baseline-local-direct` | 4 | 0.425 | 0.369 | 0.400, 0.400, 0.000, 0.900 |
| django-composite-field-recover-001 | [source](../../../benchmarks/ccb_understand/django-composite-field-recover-001) | `mcp-remote-direct` | 4 | 0.487 | 0.175 | 0.750, 0.400, 0.400, 0.400 |
| django-template-inherit-recall-001 | [source](../../../benchmarks/ccb_understand/django-template-inherit-recall-001) | `baseline-local-direct` | 3 | 0.617 | 0.318 | 0.250, 0.800, 0.800 |
| django-template-inherit-recall-001 | [source](../../../benchmarks/ccb_understand/django-template-inherit-recall-001) | `mcp-remote-direct` | 2 | 0.525 | 0.389 | 0.250, 0.800 |
| envoy-request-routing-qa-001 | [source](../../../benchmarks/ccb_understand/envoy-request-routing-qa-001) | `baseline-local-direct` | 3 | 0.623 | 0.540 | 0.000, 0.910, 0.960 |
| envoy-request-routing-qa-001 | [source](../../../benchmarks/ccb_understand/envoy-request-routing-qa-001) | `mcp-remote-direct` | 3 | 0.897 | 0.023 | 0.870, 0.910, 0.910 |
| kafka-build-orient-001 | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `baseline-local-direct` | 4 | 0.600 | 0.404 | 0.720, 0.840, 0.000, 0.840 |
| kafka-build-orient-001 | [source](../../../benchmarks/ccb_understand/kafka-build-orient-001) | `mcp-remote-direct` | 3 | 0.850 | 0.072 | 0.870, 0.910, 0.770 |
| kafka-contributor-workflow-001 | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `baseline-local-direct` | 3 | 0.940 | 0.017 | 0.950, 0.920, 0.950 |
| kafka-contributor-workflow-001 | [source](../../../benchmarks/ccb_understand/kafka-contributor-workflow-001) | `mcp-remote-direct` | 4 | 0.838 | 0.035 | 0.820, 0.890, 0.820, 0.820 |
| numpy-dtype-localize-001 | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `baseline-local-direct` | 3 | 0.733 | 0.295 | 1.000, 0.417, 0.783 |
| numpy-dtype-localize-001 | [source](../../../benchmarks/ccb_understand/numpy-dtype-localize-001) | `mcp-remote-direct` | 4 | 0.946 | 0.071 | 0.933, 1.000, 1.000, 0.850 |
| terraform-plan-pipeline-qa-001 | [source](../../../benchmarks/ccb_understand/terraform-plan-pipeline-qa-001) | `baseline-local-direct` | 3 | 0.650 | 0.564 | 0.000, 0.950, 1.000 |
| terraform-plan-pipeline-qa-001 | [source](../../../benchmarks/ccb_understand/terraform-plan-pipeline-qa-001) | `mcp-remote-direct` | 3 | 0.950 | 0.000 | 0.950, 0.950, 0.950 |
