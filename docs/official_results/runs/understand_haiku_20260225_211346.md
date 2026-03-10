# understand_haiku_20260225_211346

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.747`
- Pass rate: `1.000`
- Scorer families: `continuous (1), repo_state_heuristic (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (1), answer_json_native (1), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [django-composite-field-recover-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--django-composite-field-recover-001--fcaef53257.html) | `passed` | 0.400 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 63 | traj, tx |
| [kafka-build-orient-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--kafka-build-orient-001--790e34b142.html) | `passed` | 0.840 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 73 | traj, tx |
| [numpy-dtype-localize-001](../tasks/understand_haiku_20260225_211346--baseline-local-direct--numpy-dtype-localize-001--197b3cfa63.html) | `passed` | 1.000 | `True` | `semantic_similarity` | `repo_state` | 0.000 | 41 | traj, tx |

## mcp-remote-direct

- Valid tasks: `7`
- Mean reward: `0.870`
- Pass rate: `1.000`
- Scorer families: `unknown (4), continuous (1), repo_state_heuristic (1), semantic_similarity (1)`
- Output contracts: `unknown (4), answer_json_bridge (1), answer_json_native (1), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_django-composite-field-recover-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_django-composite-field-recover-001--c85b520845.html) | `passed` | 0.750 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.290 | 69 | traj, tx |
| [sgonly_envoy-ext-authz-handoff-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_envoy-ext-authz-handoff-001--168738fd88.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.960 | 25 | traj, tx |
| [sgonly_k8s-cri-containerd-reason-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_k8s-cri-containerd-reason-001--d2f6913b6a.html) | `passed` | 0.850 | `True` | `-` | `-` | 0.857 | 28 | traj, tx |
| [sgonly_kafka-build-orient-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_kafka-build-orient-001--f42b44d94b.html) | `passed` | 0.870 | `True` | `continuous` | `answer_json_bridge` | 0.955 | 22 | traj, tx |
| [sgonly_numpy-dtype-localize-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_numpy-dtype-localize-001--944a245415.html) | `passed` | 1.000 | `True` | `semantic_similarity` | `repo_state` | 0.957 | 47 | traj, tx |
| [sgonly_terraform-state-backend-handoff-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_terraform-state-backend-handoff-001--826124c0f8.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.969 | 32 | traj, tx |
| [sgonly_vscode-ext-host-qa-001](../tasks/understand_haiku_20260225_211346--mcp-remote-direct--sgonly_vscode-ext-host-qa-001--e340125b2b.html) | `passed` | 0.960 | `True` | `-` | `-` | 0.963 | 27 | traj, tx |
