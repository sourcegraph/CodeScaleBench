# understand_haiku_20260224_001815

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.309`
- Pass rate: `0.500`
- Scorer families: `checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1), unknown (1)`
- Output contracts: `answer_json_bridge (6), answer_json_native (2), repo_state (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [argocd-arch-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--argocd-arch-orient-001--0fad4dc79c.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | 0.000 | 187 | traj, tx |
| [cilium-project-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-project-orient-001--2fe02a8c1f.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [envoy-request-routing-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--envoy-request-routing-qa-001--54348ff65f.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | 0.000 | 57 | traj, tx |
| [numpy-dtype-localize-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--numpy-dtype-localize-001--1403eb4913.html) | `failed` | 0.000 | `False` | `semantic_similarity` | `repo_state` | - | - | traj, tx |
| [terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--terraform-plan-pipeline-qa-001--decb27940a.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 5 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--cilium-ebpf-fault-qa-001--d2bb82864b.html) | `passed` | 0.770 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [django-composite-field-recover-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--django-composite-field-recover-001--e027bd0fa4.html) | `passed` | 0.400 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 68 | traj, tx |
| [django-template-inherit-recall-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--django-template-inherit-recall-001--40ba1cf271.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 94 | traj, tx |
| [kafka-build-orient-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--kafka-build-orient-001--a0c9d1bd42.html) | `passed` | 0.720 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 224 | traj, tx |
| [kafka-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--baseline-local-direct--kafka-contributor-workflow-001--b939b2c1bd.html) | `passed` | 0.950 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 23 | traj, tx |

## mcp-remote-direct

- Valid tasks: `20`
- Mean reward: `0.679`
- Pass rate: `0.850`
- Scorer families: `unknown (11), checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1)`
- Output contracts: `unknown (11), answer_json_bridge (6), answer_json_native (2), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001--4a790e8861.html) | `failed` | 0.000 | `False` | `-` | `-` | - | - | traj, tx |
| [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-build-orient-001--dfe9b187ea.html) | `failed` | 0.000 | `False` | `continuous` | `answer_json_bridge` | - | - | traj, tx |
| [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_vscode-ext-host-qa-001--28ad25ae34.html) | `failed` | 0.000 | `False` | `-` | `-` | - | - | traj, tx |
| [sgonly_argocd-arch-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_argocd-arch-orient-001--cd1be157ad.html) | `passed` | 0.810 | `True` | `checklist` | `answer_json_bridge` | 0.977 | 44 | traj, tx |
| [sgonly_argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_argocd-sync-reconcile-qa-001--260c6da173.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.970 | 33 | traj, tx |
| [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-ebpf-datapath-handoff-001--4e6c85e61c.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
| [sgonly_cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-ebpf-fault-qa-001--67bc6f0c22.html) | `passed` | 0.820 | `True` | `checklist` | `answer_json_bridge` | 0.973 | 37 | traj, tx |
| [sgonly_cilium-project-orient-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_cilium-project-orient-001--c6fc49d4ec.html) | `passed` | 0.960 | `True` | `checklist` | `answer_json_bridge` | 0.974 | 39 | traj, tx |
| [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_django-composite-field-recover-001--32c6d9dd96.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_native` | - | - | traj, tx |
| [sgonly_django-template-inherit-recall-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_django-template-inherit-recall-001--090d5900f7.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.143 | 98 | traj, tx |
| [sgonly_envoy-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-contributor-workflow-001--b8a7d2f398.html) | `passed` | 0.910 | `True` | `-` | `-` | 0.955 | 22 | traj, tx |
| [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001--8aac1d2890.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.955 | 22 | traj, tx |
| [sgonly_envoy-filter-chain-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-filter-chain-qa-001--2afcf01ce7.html) | `passed` | 0.880 | `True` | `-` | `-` | 0.967 | 30 | traj, tx |
| [sgonly_envoy-request-routing-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_envoy-request-routing-qa-001--231c24fecd.html) | `passed` | 0.870 | `True` | `checklist` | `answer_json_bridge` | 0.971 | 35 | traj, tx |
| [sgonly_istio-xds-serving-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_istio-xds-serving-qa-001--c66818bfa4.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.971 | 34 | traj, tx |
| [sgonly_kafka-contributor-workflow-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-contributor-workflow-001--bf3454a001.html) | `passed` | 0.820 | `True` | `continuous` | `answer_json_bridge` | 0.955 | 22 | traj, tx |
| [sgonly_kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_kafka-message-lifecycle-qa-001--af24ae3d41.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.972 | 36 | traj, tx |
| [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_numpy-dtype-localize-001--13ac46e084.html) | `passed` | 0.933 | `True` | `semantic_similarity` | `repo_state` | 0.966 | 29 | traj, tx |
| [sgonly_terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_terraform-plan-pipeline-qa-001--65759d92ba.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.971 | 35 | traj, tx |
| [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260224_001815--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001--89539aef71.html) | `passed` | 0.630 | `True` | `-` | `-` | 0.964 | 28 | traj, tx |
