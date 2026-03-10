# understand_haiku_20260301_071233

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.874`
- Pass rate: `1.000`
- Scorer families: `checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1), unknown (1)`
- Output contracts: `answer_json_bridge (6), answer_json_native (2), repo_state (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [argocd-arch-orient-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--argocd-arch-orient-001--a72b696644.html) | `passed` | 0.750 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--cilium-ebpf-fault-qa-001--fde7858137.html) | `passed` | 0.800 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 45 | traj, tx |
| [cilium-project-orient-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--cilium-project-orient-001--5d4fd71f83.html) | `passed` | 0.960 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 45 | traj, tx |
| [django-composite-field-recover-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--django-composite-field-recover-001--78dd6fdd65.html) | `passed` | 0.900 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 69 | traj, tx |
| [django-template-inherit-recall-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--django-template-inherit-recall-001--2790695b54.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 100 | traj, tx |
| [envoy-request-routing-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--envoy-request-routing-qa-001--33b8e821ce.html) | `passed` | 0.960 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [kafka-build-orient-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--kafka-build-orient-001--488dd03754.html) | `passed` | 0.840 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 34 | traj, tx |
| [kafka-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--kafka-contributor-workflow-001--38c95f54a4.html) | `passed` | 0.950 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 20 | traj, tx |
| [numpy-dtype-localize-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--numpy-dtype-localize-001--b632b1c2a0.html) | `passed` | 0.783 | `True` | `semantic_similarity` | `repo_state` | 0.000 | 57 | traj, tx |
| [terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260301_071233--baseline-local-direct--terraform-plan-pipeline-qa-001--35b2b9b590.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 47 | traj, tx |

## mcp-remote-direct

- Valid tasks: `32`
- Mean reward: `0.900`
- Pass rate: `1.000`
- Scorer families: `unknown (23), checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1)`
- Output contracts: `unknown (23), answer_json_bridge (6), answer_json_native (2), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_argocd-arch-orient-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_argocd-arch-orient-001--531ca111e7.html) | `passed` | 0.770 | `True` | `checklist` | `answer_json_bridge` | 0.973 | 37 | traj, tx |
| [sgonly_argocd-sync-reconcile-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_argocd-sync-reconcile-qa-001--fbfb95519c.html) | `passed` | 0.870 | `True` | `-` | `-` | 0.969 | 32 | traj, tx |
| [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_cilium-ebpf-datapath-handoff-001--6781418bd2.html) | `passed` | 0.900 | `True` | `-` | `-` | 0.935 | 31 | traj, tx |
| [sgonly_cilium-ebpf-fault-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_cilium-ebpf-fault-qa-001--6b07a31221.html) | `passed` | 0.850 | `True` | `checklist` | `answer_json_bridge` | 0.963 | 27 | traj, tx |
| [sgonly_cilium-project-orient-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_cilium-project-orient-001--075c9c61c2.html) | `passed` | 0.910 | `True` | `checklist` | `answer_json_bridge` | 0.923 | 26 | traj, tx |
| [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_django-composite-field-recover-001--c444a59336.html) | `passed` | 0.400 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.279 | 86 | traj, tx |
| [sgonly_django-template-inherit-recall-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_django-template-inherit-recall-001--d45fb051df.html) | `passed` | 0.800 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.309 | 68 | traj, tx |
| [sgonly_envoy-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-contributor-workflow-001--5b037ab028.html) | `passed` | 0.940 | `True` | `-` | `-` | 0.900 | 20 | traj, tx |
| [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001--71c73f5f6f.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.950 | 20 | traj, tx |
| [sgonly_envoy-filter-chain-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-filter-chain-qa-001--0a4b1e6e75.html) | `passed` | 0.960 | `True` | `-` | `-` | 0.973 | 37 | traj, tx |
| [sgonly_envoy-pool-ready-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-pool-ready-search-001--1ab2a48d5e.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.750 | 8 | traj, tx |
| [sgonly_envoy-request-routing-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-request-routing-qa-001--bf2a4e69d1.html) | `passed` | 0.910 | `True` | `checklist` | `answer_json_bridge` | 0.975 | 40 | traj, tx |
| [sgonly_envoy-retry-eval-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_envoy-retry-eval-search-001--2918c29657.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.800 | 5 | traj, tx |
| [sgonly_grafana-field-calcs-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_grafana-field-calcs-search-001--dc43cd7402.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.667 | 6 | traj, tx |
| [sgonly_istio-xds-serving-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_istio-xds-serving-qa-001--6d3f4ff569.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
| [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001--4c89884272.html) | `passed` | 0.850 | `True` | `-` | `-` | 0.846 | 26 | traj, tx |
| [sgonly_k8s-eviction-sync-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_k8s-eviction-sync-search-001--89f9d66f4c.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.750 | 4 | traj, tx |
| [sgonly_k8s-scheduler-filter-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_k8s-scheduler-filter-search-001--71e80fc93c.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.667 | 6 | traj, tx |
| [sgonly_kafka-assign-handler-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-assign-handler-search-001--6f2f298344.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.778 | 9 | traj, tx |
| [sgonly_kafka-batch-drain-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-batch-drain-search-001--498f6a0855.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.714 | 7 | traj, tx |
| [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-build-orient-001--69ee27d49f.html) | `passed` | 0.770 | `True` | `continuous` | `answer_json_bridge` | 0.963 | 27 | traj, tx |
| [sgonly_kafka-contributor-workflow-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-contributor-workflow-001--4d22745993.html) | `passed` | 0.820 | `True` | `continuous` | `answer_json_bridge` | 0.944 | 18 | traj, tx |
| [sgonly_kafka-message-lifecycle-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_kafka-message-lifecycle-qa-001--7873ad4108.html) | `passed` | 0.890 | `True` | `-` | `-` | 0.967 | 30 | traj, tx |
| [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_numpy-dtype-localize-001--0a88145f57.html) | `passed` | 0.850 | `True` | `semantic_similarity` | `repo_state` | 0.939 | 33 | traj, tx |
| [sgonly_pandas-pivot-internal-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_pandas-pivot-internal-search-001--48f39e3807.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.600 | 5 | traj, tx |
| [sgonly_rust-liveness-gen-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_rust-liveness-gen-search-001--2a9deddfdd.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.750 | 8 | traj, tx |
| [sgonly_rust-type-tests-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_rust-type-tests-search-001--e27487b54a.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.818 | 11 | traj, tx |
| [sgonly_sklearn-fastica-fit-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_sklearn-fastica-fit-search-001--530fda57d4.html) | `passed` | 0.800 | `True` | `-` | `-` | 0.800 | 5 | traj, tx |
| [sgonly_terraform-plan-pipeline-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_terraform-plan-pipeline-qa-001--3dd38d11de.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.935 | 31 | traj, tx |
| [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001--3f02e0d098.html) | `passed` | 0.730 | `True` | `-` | `-` | 0.903 | 31 | traj, tx |
| [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_vscode-ext-host-qa-001--2badb36332.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.957 | 23 | traj, tx |
| [sgonly_vscode-keybinding-merge-search-001](../tasks/understand_haiku_20260301_071233--mcp-remote-direct--sgonly_vscode-keybinding-merge-search-001--e964e14a78.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.600 | 5 | traj, tx |
