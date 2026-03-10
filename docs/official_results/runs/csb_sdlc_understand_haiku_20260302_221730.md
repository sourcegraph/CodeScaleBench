# csb_sdlc_understand_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `10`
- Mean reward: `0.522`
- Pass rate: `0.700`
- Scorer families: `checklist (4), continuous (2), repo_state_heuristic (2), semantic_similarity (1), unknown (1)`
- Output contracts: `answer_json_bridge (6), answer_json_native (2), repo_state (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [cilium-project-orient-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--cilium-project-orient-001--19b4c3f1af.html) | `failed` | 0.000 | `None` | `checklist` | `answer_json_bridge` | - | - | traj, tx |
| [envoy-request-routing-qa-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--envoy-request-routing-qa-001--e31ea2f9e1.html) | `failed` | 0.000 | `None` | `checklist` | `answer_json_bridge` | - | - | traj, tx |
| [kafka-contributor-workflow-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--kafka-contributor-workflow-001--6183c6ce88.html) | `failed` | 0.000 | `None` | `continuous` | `answer_json_bridge` | - | - | traj, tx |
| [argocd-arch-orient-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--argocd-arch-orient-001--d0f444989d.html) | `passed` | 0.710 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [cilium-ebpf-fault-qa-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--cilium-ebpf-fault-qa-001--c48b2238eb.html) | `passed` | 0.870 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [django-composite-field-recover-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--django-composite-field-recover-001--456cd189e4.html) | `passed` | 0.400 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 60 | traj, tx |
| [django-template-inherit-recall-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--django-template-inherit-recall-001--7af6a086ed.html) | `passed` | 0.800 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.000 | 57 | traj, tx |
| [kafka-build-orient-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--kafka-build-orient-001--4397a29a35.html) | `passed` | 0.770 | `None` | `continuous` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [numpy-dtype-localize-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--numpy-dtype-localize-001--744297289a.html) | `passed` | 0.717 | `None` | `semantic_similarity` | `repo_state` | 0.000 | 53 | traj, tx |
| [terraform-plan-pipeline-qa-001](../tasks/csb_sdlc_understand_haiku_20260302_221730--baseline-local-direct--terraform-plan-pipeline-qa-001--bebaebb434.html) | `passed` | 0.950 | `None` | `-` | `-` | 0.000 | 48 | traj, tx |

## mcp-remote-direct

- Valid tasks: `7`
- Mean reward: `0.787`
- Pass rate: `1.000`
- Scorer families: `checklist (3), continuous (2), repo_state_heuristic (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (5), answer_json_native (1), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_cilium-ebpf-fault-qa-001_nnyhvi](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_cilium-ebpf-fault-qa-001_nnyhvi--ca4cdfe001.html) | `passed` | 0.800 | `None` | `checklist` | `answer_json_bridge` | 0.966 | 29 | traj, tx |
| [mcp_cilium-project-orient-001_ffmygj](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_cilium-project-orient-001_ffmygj--2faae45381.html) | `passed` | 0.970 | `None` | `checklist` | `answer_json_bridge` | 0.963 | 27 | traj, tx |
| [mcp_django-template-inherit-recall-001_bbepsu](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_django-template-inherit-recall-001_bbepsu--2286be13f7.html) | `passed` | 0.250 | `None` | `repo_state_heuristic` | `answer_json_native` | 0.150 | 100 | traj, tx |
| [mcp_envoy-request-routing-qa-001_7dwajw](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_envoy-request-routing-qa-001_7dwajw--1c34b13b45.html) | `passed` | 0.910 | `None` | `checklist` | `answer_json_bridge` | 0.972 | 36 | traj, tx |
| [mcp_kafka-build-orient-001_ifrnit](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_kafka-build-orient-001_ifrnit--b060a5a4fb.html) | `passed` | 0.840 | `None` | `continuous` | `answer_json_bridge` | 0.962 | 26 | traj, tx |
| [mcp_kafka-contributor-workflow-001_v352ni](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_kafka-contributor-workflow-001_v352ni--3d3104569f.html) | `passed` | 0.890 | `None` | `continuous` | `answer_json_bridge` | 0.947 | 19 | traj, tx |
| [mcp_numpy-dtype-localize-001_hauwan](../tasks/csb_sdlc_understand_haiku_20260302_221730--mcp-remote-direct--mcp_numpy-dtype-localize-001_hauwan--ee590ec5fb.html) | `passed` | 0.850 | `None` | `semantic_similarity` | `repo_state` | 0.906 | 32 | traj, tx |
