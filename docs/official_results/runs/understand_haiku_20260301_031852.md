# understand_haiku_20260301_031852

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.649`
- Pass rate: `0.800`
- Scorer families: `checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1), unknown (1)`
- Output contracts: `answer_json_bridge (6), answer_json_native (2), repo_state (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-composite-field-recover-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--django-composite-field-recover-001--71ba6bcb9a.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 27 | traj, tx |
| [kafka-build-orient-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--kafka-build-orient-001--13ec2a4c45.html) | `failed` | 0.000 | `False` | `continuous` | `answer_json_bridge` | 0.000 | 98 | traj, tx |
| [argocd-arch-orient-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--argocd-arch-orient-001--ac9bc07fc5.html) | `passed` | 0.710 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--cilium-ebpf-fault-qa-001--43199106e5.html) | `passed` | 0.870 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 52 | traj, tx |
| [cilium-project-orient-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--cilium-project-orient-001--e5abfa8c12.html) | `passed` | 0.910 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 47 | traj, tx |
| [django-template-inherit-recall-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--django-template-inherit-recall-001--ad6c5a9164.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 61 | traj, tx |
| [envoy-request-routing-qa-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--envoy-request-routing-qa-001--2d5de3bea4.html) | `passed` | 0.910 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 47 | traj, tx |
| [kafka-contributor-workflow-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--kafka-contributor-workflow-001--ffe83e27b4.html) | `passed` | 0.920 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 25 | traj, tx |
| [numpy-dtype-localize-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--numpy-dtype-localize-001--3b6dd09c22.html) | `passed` | 0.417 | `True` | `semantic_similarity` | `repo_state` | 0.000 | 57 | traj, tx |
| [terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260301_031852--baseline-local-direct--terraform-plan-pipeline-qa-001--5b2ddfc120.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.000 | 41 | traj, tx |

## mcp-remote-direct

- Valid tasks: `20`
- Mean reward: `0.832`
- Pass rate: `0.950`
- Scorer families: `unknown (11), checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1)`
- Output contracts: `unknown (11), answer_json_bridge (6), answer_json_native (2), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_django-template-inherit-recall-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_django-template-inherit-recall-001--006851d5d6.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_native` | - | - | traj, tx |
| [sgonly_argocd-arch-orient-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_argocd-arch-orient-001--bc4eec5ce8.html) | `passed` | 0.770 | `True` | `checklist` | `answer_json_bridge` | 0.976 | 41 | traj, tx |
| [sgonly_argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_argocd-sync-reconcile-qa-001--c255132cf8.html) | `passed` | 0.880 | `True` | `-` | `-` | 0.969 | 32 | traj, tx |
| [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_cilium-ebpf-datapath-handoff-001--1a9ea896b0.html) | `passed` | 0.930 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
| [sgonly_cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_cilium-ebpf-fault-qa-001--943d4e8a2f.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.963 | 27 | traj, tx |
| [sgonly_cilium-project-orient-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_cilium-project-orient-001--4998f6e04e.html) | `passed` | 0.920 | `True` | `checklist` | `answer_json_bridge` | 0.971 | 35 | traj, tx |
| [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_django-composite-field-recover-001--dbd67007c9.html) | `passed` | 0.400 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.318 | 85 | traj, tx |
| [sgonly_envoy-contributor-workflow-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_envoy-contributor-workflow-001--07f65f30b6.html) | `passed` | 0.960 | `True` | `-` | `-` | 0.864 | 22 | traj, tx |
| [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001--c3b6560a8f.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [sgonly_envoy-filter-chain-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_envoy-filter-chain-qa-001--9242102f11.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.955 | 22 | traj, tx |
| [sgonly_envoy-request-routing-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_envoy-request-routing-qa-001--70ced73f10.html) | `passed` | 0.910 | `True` | `checklist` | `answer_json_bridge` | 0.957 | 23 | traj, tx |
| [sgonly_istio-xds-serving-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_istio-xds-serving-qa-001--10f54c0e37.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.974 | 39 | traj, tx |
| [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001--6f5896d4a1.html) | `passed` | 0.850 | `True` | `-` | `-` | 0.826 | 23 | traj, tx |
| [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_kafka-build-orient-001--d7062d5eab.html) | `passed` | 0.910 | `True` | `continuous` | `answer_json_bridge` | 0.964 | 28 | traj, tx |
| [sgonly_kafka-contributor-workflow-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_kafka-contributor-workflow-001--770360f80d.html) | `passed` | 0.820 | `True` | `continuous` | `answer_json_bridge` | 0.957 | 23 | traj, tx |
| [sgonly_kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_kafka-message-lifecycle-qa-001--72879a9ea1.html) | `passed` | 0.910 | `True` | `-` | `-` | 0.971 | 34 | traj, tx |
| [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_numpy-dtype-localize-001--f659ab2aa1.html) | `passed` | 1.000 | `True` | `semantic_similarity` | `repo_state` | 0.912 | 34 | traj, tx |
| [sgonly_terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_terraform-plan-pipeline-qa-001--ee1300b5e3.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.952 | 21 | traj, tx |
| [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001--cb812c335a.html) | `passed` | 0.710 | `True` | `-` | `-` | 0.941 | 34 | traj, tx |
| [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260301_031852--mcp-remote-direct--sgonly_vscode-ext-host-qa-001--733fc95c59.html) | `passed` | 0.890 | `True` | `-` | `-` | 0.955 | 22 | traj, tx |
