# ccb_understand

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_understand_haiku_022426](../runs/ccb_understand_haiku_022426.md) | `baseline` | 13 | 0.592 | 0.692 |
| [ccb_understand_haiku_022426](../runs/ccb_understand_haiku_022426.md) | `mcp` | 13 | 0.841 | 1.000 |
| [understand_haiku_20260224_001815](../runs/understand_haiku_20260224_001815.md) | `baseline-local-direct` | 13 | 0.592 | 0.692 |
| [understand_haiku_20260224_001815](../runs/understand_haiku_20260224_001815.md) | `mcp-remote-direct` | 13 | 0.841 | 1.000 |
| [understand_haiku_20260225_211346](../runs/understand_haiku_20260225_211346.md) | `baseline-local-direct` | 7 | 0.789 | 1.000 |
| [understand_haiku_20260225_211346](../runs/understand_haiku_20260225_211346.md) | `mcp-remote-direct` | 7 | 0.870 | 1.000 |

## Tasks

| Run | Config | Task | Status | Reward | MCP Ratio |
|---|---|---|---|---:|---:|
| `ccb_understand_haiku_022426` | `baseline` | [argocd-arch-orient-001](../tasks/ccb_understand_haiku_022426--baseline--argocd-arch-orient-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [argocd-sync-reconcile-qa-001](../tasks/ccb_understand_haiku_022426--baseline--argocd-sync-reconcile-qa-001.md) | `passed` | 0.920 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [cilium-ebpf-datapath-handoff-001](../tasks/ccb_understand_haiku_022426--baseline--cilium-ebpf-datapath-handoff-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [cilium-ebpf-fault-qa-001](../tasks/ccb_understand_haiku_022426--baseline--cilium-ebpf-fault-qa-001.md) | `passed` | 0.770 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [cilium-project-orient-001](../tasks/ccb_understand_haiku_022426--baseline--cilium-project-orient-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [django-template-inherit-recall-001](../tasks/ccb_understand_haiku_022426--baseline--django-template-inherit-recall-001.md) | `passed` | 0.250 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [envoy-contributor-workflow-001](../tasks/ccb_understand_haiku_022426--baseline--envoy-contributor-workflow-001.md) | `passed` | 0.970 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [envoy-filter-chain-qa-001](../tasks/ccb_understand_haiku_022426--baseline--envoy-filter-chain-qa-001.md) | `passed` | 0.970 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [envoy-request-routing-qa-001](../tasks/ccb_understand_haiku_022426--baseline--envoy-request-routing-qa-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [istio-xds-serving-qa-001](../tasks/ccb_understand_haiku_022426--baseline--istio-xds-serving-qa-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [kafka-contributor-workflow-001](../tasks/ccb_understand_haiku_022426--baseline--kafka-contributor-workflow-001.md) | `passed` | 0.950 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [kafka-message-lifecycle-qa-001](../tasks/ccb_understand_haiku_022426--baseline--kafka-message-lifecycle-qa-001.md) | `passed` | 0.860 | 0.000 |
| `ccb_understand_haiku_022426` | `baseline` | [terraform-plan-pipeline-qa-001](../tasks/ccb_understand_haiku_022426--baseline--terraform-plan-pipeline-qa-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_argocd-arch-orient-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_argocd-arch-orient-001.md) | `passed` | 0.810 | 0.977 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_argocd-sync-reconcile-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_argocd-sync-reconcile-qa-001.md) | `passed` | 0.830 | 0.970 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_cilium-ebpf-datapath-handoff-001.md) | `passed` | 0.830 | 0.968 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_cilium-ebpf-fault-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_cilium-ebpf-fault-qa-001.md) | `passed` | 0.820 | 0.973 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_cilium-project-orient-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_cilium-project-orient-001.md) | `passed` | 0.960 | 0.974 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_django-template-inherit-recall-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_django-template-inherit-recall-001.md) | `passed` | 0.250 | 0.143 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_envoy-contributor-workflow-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_envoy-contributor-workflow-001.md) | `passed` | 0.910 | 0.955 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_envoy-filter-chain-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_envoy-filter-chain-qa-001.md) | `passed` | 0.880 | 0.967 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_envoy-request-routing-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_envoy-request-routing-qa-001.md) | `passed` | 0.870 | 0.971 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_istio-xds-serving-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_istio-xds-serving-qa-001.md) | `passed` | 1.000 | 0.971 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_kafka-contributor-workflow-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_kafka-contributor-workflow-001.md) | `passed` | 0.820 | 0.955 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_kafka-message-lifecycle-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_kafka-message-lifecycle-qa-001.md) | `passed` | 1.000 | 0.972 |
| `ccb_understand_haiku_022426` | `mcp` | [sgonly_terraform-plan-pipeline-qa-001](../tasks/ccb_understand_haiku_022426--mcp--sgonly_terraform-plan-pipeline-qa-001.md) | `passed` | 0.950 | 0.971 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [argocd-arch-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--argocd-arch-orient-001.md) | `failed` | 0.000 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--argocd-sync-reconcile-qa-001.md) | `passed` | 0.920 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-ebpf-datapath-handoff-001.md) | `passed` | 1.000 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-ebpf-fault-qa-001.md) | `passed` | 0.770 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [cilium-project-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-project-orient-001.md) | `failed` | 0.000 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [django-template-inherit-recall-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--django-template-inherit-recall-001.md) | `passed` | 0.250 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [envoy-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-contributor-workflow-001.md) | `passed` | 0.970 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [envoy-filter-chain-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-filter-chain-qa-001.md) | `passed` | 0.970 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [envoy-request-routing-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-request-routing-qa-001.md) | `failed` | 0.000 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [istio-xds-serving-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--istio-xds-serving-qa-001.md) | `passed` | 1.000 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [kafka-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--kafka-contributor-workflow-001.md) | `passed` | 0.950 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--kafka-message-lifecycle-qa-001.md) | `passed` | 0.860 | 0.000 |
| `understand_haiku_20260224_001815` | `baseline-local-direct` | [terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--terraform-plan-pipeline-qa-001.md) | `failed` | 0.000 | 0.000 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_argocd-arch-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_argocd-arch-orient-001.md) | `passed` | 0.810 | 0.977 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_argocd-sync-reconcile-qa-001.md) | `passed` | 0.830 | 0.970 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-ebpf-datapath-handoff-001.md) | `passed` | 0.830 | 0.968 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-ebpf-fault-qa-001.md) | `passed` | 0.820 | 0.973 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_cilium-project-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-project-orient-001.md) | `passed` | 0.960 | 0.974 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_django-template-inherit-recall-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_django-template-inherit-recall-001.md) | `passed` | 0.250 | 0.143 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_envoy-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-contributor-workflow-001.md) | `passed` | 0.910 | 0.955 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_envoy-filter-chain-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-filter-chain-qa-001.md) | `passed` | 0.880 | 0.967 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_envoy-request-routing-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-request-routing-qa-001.md) | `passed` | 0.870 | 0.971 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_istio-xds-serving-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_istio-xds-serving-qa-001.md) | `passed` | 1.000 | 0.971 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_kafka-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-contributor-workflow-001.md) | `passed` | 0.820 | 0.955 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-message-lifecycle-qa-001.md) | `passed` | 1.000 | 0.972 |
| `understand_haiku_20260224_001815` | `mcp-remote-direct` | [sgonly_terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_terraform-plan-pipeline-qa-001.md) | `passed` | 0.950 | 0.971 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [django-composite-field-recover-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--django-composite-field-recover-001.md) | `passed` | 0.400 | 0.000 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--envoy-ext-authz-handoff-001.md) | `passed` | 0.770 | 0.000 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--k8s-cri-containerd-reason-001.md) | `passed` | 0.850 | 0.000 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [kafka-build-orient-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--kafka-build-orient-001.md) | `passed` | 0.840 | 0.000 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [numpy-dtype-localize-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--numpy-dtype-localize-001.md) | `passed` | 1.000 | 0.000 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [terraform-state-backend-handoff-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--terraform-state-backend-handoff-001.md) | `passed` | 0.710 | 0.000 |
| `understand_haiku_20260225_211346` | `baseline-local-direct` | [vscode-ext-host-qa-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--vscode-ext-host-qa-001.md) | `passed` | 0.950 | 0.000 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_django-composite-field-recover-001.md) | `passed` | 0.750 | 0.290 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001.md) | `passed` | 0.830 | 0.960 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001.md) | `passed` | 0.850 | 0.857 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_kafka-build-orient-001.md) | `passed` | 0.870 | 0.955 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_numpy-dtype-localize-001.md) | `passed` | 1.000 | 0.957 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001.md) | `passed` | 0.830 | 0.969 |
| `understand_haiku_20260225_211346` | `mcp-remote-direct` | [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_vscode-ext-host-qa-001.md) | `passed` | 0.960 | 0.963 |
