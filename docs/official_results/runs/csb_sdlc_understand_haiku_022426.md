# csb_sdlc_understand_haiku_022426

## baseline-local-direct

- Valid tasks: `7`
- Mean reward: `0.281`
- Pass rate: `0.429`
- Scorer families: `checklist (4), continuous (1), repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (5), answer_json_native (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [argocd-arch-orient-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--argocd-arch-orient-001--beb560871a.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | 0.000 | 187 | traj, tx |
| [cilium-project-orient-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--cilium-project-orient-001--fb310c5b94.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [envoy-request-routing-qa-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--envoy-request-routing-qa-001--d58d9d2756.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | 0.000 | 57 | traj, tx |
| [terraform-plan-pipeline-qa-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--terraform-plan-pipeline-qa-001--e61ba44ae5.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 5 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--cilium-ebpf-fault-qa-001--8109fbb68c.html) | `passed` | 0.770 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [django-template-inherit-recall-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--django-template-inherit-recall-001--41ce4b8584.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 94 | traj, tx |
| [kafka-contributor-workflow-001](../tasks/csb_sdlc_understand_haiku_022426--baseline--kafka-contributor-workflow-001--004c55d483.html) | `passed` | 0.950 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 23 | traj, tx |

## mcp-remote-direct

- Valid tasks: `13`
- Mean reward: `0.841`
- Pass rate: `1.000`
- Scorer families: `unknown (7), checklist (4), continuous (1), repo_state_heuristic (1)`
- Output contracts: `unknown (7), answer_json_bridge (5), answer_json_native (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [sgonly_argocd-arch-orient-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_argocd-arch-orient-001--1e8019e65d.html) | `passed` | 0.810 | `True` | `checklist` | `answer_json_bridge` | 0.977 | 44 | traj, tx |
| [sgonly_argocd-sync-reconcile-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_argocd-sync-reconcile-qa-001--8bba048de0.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.970 | 33 | traj, tx |
| [sgonly_cilium-ebpf-datapath-handoff-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_cilium-ebpf-datapath-handoff-001--f951b9baa4.html) | `passed` | 0.830 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
| [sgonly_cilium-ebpf-fault-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_cilium-ebpf-fault-qa-001--a51bdc3ad9.html) | `passed` | 0.820 | `True` | `checklist` | `answer_json_bridge` | 0.973 | 37 | traj, tx |
| [sgonly_cilium-project-orient-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_cilium-project-orient-001--618b7a5a29.html) | `passed` | 0.960 | `True` | `checklist` | `answer_json_bridge` | 0.974 | 39 | traj, tx |
| [sgonly_django-template-inherit-recall-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_django-template-inherit-recall-001--e6bc2cd346.html) | `passed` | 0.250 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.143 | 98 | traj, tx |
| [sgonly_envoy-contributor-workflow-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_envoy-contributor-workflow-001--a145d94465.html) | `passed` | 0.910 | `True` | `-` | `-` | 0.955 | 22 | traj, tx |
| [sgonly_envoy-filter-chain-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_envoy-filter-chain-qa-001--a0ce44c01e.html) | `passed` | 0.880 | `True` | `-` | `-` | 0.967 | 30 | traj, tx |
| [sgonly_envoy-request-routing-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_envoy-request-routing-qa-001--aea0752ae7.html) | `passed` | 0.870 | `True` | `checklist` | `answer_json_bridge` | 0.971 | 35 | traj, tx |
| [sgonly_istio-xds-serving-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_istio-xds-serving-qa-001--2911bfc0f0.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.971 | 34 | traj, tx |
| [sgonly_kafka-contributor-workflow-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_kafka-contributor-workflow-001--e9b52c4d24.html) | `passed` | 0.820 | `True` | `continuous` | `answer_json_bridge` | 0.955 | 22 | traj, tx |
| [sgonly_kafka-message-lifecycle-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_kafka-message-lifecycle-qa-001--f5105e8f6d.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.972 | 36 | traj, tx |
| [sgonly_terraform-plan-pipeline-qa-001](../tasks/csb_sdlc_understand_haiku_022426--mcp--sgonly_terraform-plan-pipeline-qa-001--f507478860.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.971 | 35 | traj, tx |
