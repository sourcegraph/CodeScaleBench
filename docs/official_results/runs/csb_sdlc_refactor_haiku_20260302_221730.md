# csb_sdlc_refactor_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `14`
- Mean reward: `0.451`
- Pass rate: `0.714`
- Scorer families: `repo_state_heuristic (10), ir_checklist (3), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (14)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [envoy-listener-manager-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--envoy-listener-manager-refac-001--a3373f19c7.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 26 | traj, tx |
| [python-http-class-naming-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--python-http-class-naming-refac-001--da0b6a8a8b.html) | `failed` | 0.000 | `None` | `semantic_similarity` | `answer_json_bridge` | - | - | traj, tx |
| [strata-fx-european-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--strata-fx-european-refac-001--e3de751883.html) | `failed` | 0.000 | `None` | `ir_checklist` | `answer_json_bridge` | - | - | traj, tx |
| [terraform-eval-context-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--terraform-eval-context-refac-001--272f930b98.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [cilium-endpoint-manager-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--cilium-endpoint-manager-refac-001--9f411a9529.html) | `passed` | 0.667 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 115 | traj, tx |
| [django-request-factory-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--django-request-factory-refac-001--04f14f7e5e.html) | `passed` | 0.667 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [flipt-dep-refactor-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--flipt-dep-refactor-001--84cc640889.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 170 | traj, tx |
| [flipt-flagexists-refactor-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--flipt-flagexists-refactor-001--12c2e89c12.html) | `passed` | 0.550 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [istio-discovery-server-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--istio-discovery-server-refac-001--471059fdd9.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 61 | traj, tx |
| [k8s-score-normalizer-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--k8s-score-normalizer-refac-001--6113b483af.html) | `passed` | 0.650 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 77 | traj, tx |
| [kafka-batch-accumulator-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--kafka-batch-accumulator-refac-001--36f42f2b42.html) | `passed` | 0.620 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 90 | traj, tx |
| [pandas-index-engine-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--pandas-index-engine-refac-001--4e783cf8bd.html) | `passed` | 0.667 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 161 | traj, tx |
| [prometheus-query-engine-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--prometheus-query-engine-refac-001--04b34c14b4.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 50 | traj, tx |
| [pytorch-optimizer-foreach-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_221730--baseline-local-direct--pytorch-optimizer-foreach-refac-001--9533fbe5fb.html) | `passed` | 0.167 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 77 | traj, tx |

## mcp-remote-direct

- Valid tasks: `10`
- Mean reward: `0.754`
- Pass rate: `0.900`
- Scorer families: `repo_state_heuristic (7), ir_checklist (2), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (10)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_envoy-listener-manager-refac-001_jq9w9x](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_envoy-listener-manager-refac-001_jq9w9x--c2f74fa446.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.385 | 109 | traj, tx |
| [mcp_flipt-dep-refactor-001_6rlpds](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_flipt-dep-refactor-001_6rlpds--897521e0ec.html) | `passed` | 0.440 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.165 | 121 | traj, tx |
| [mcp_istio-discovery-server-refac-001_s5eugu](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_istio-discovery-server-refac-001_s5eugu--85817f487b.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.185 | 54 | traj, tx |
| [mcp_kafka-batch-accumulator-refac-001_gmivwy](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_kafka-batch-accumulator-refac-001_gmivwy--bd5038ad57.html) | `passed` | 0.770 | `None` | `ir_checklist` | `answer_json_bridge` | 0.489 | 45 | traj, tx |
| [mcp_kubernetes-scheduler-profile-refac-001_shjdur](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_kubernetes-scheduler-profile-refac-001_shjdur--3dd15e5665.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.299 | 77 | traj, tx |
| [mcp_numpy-array-dispatch-refac-001_5ilst3](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_numpy-array-dispatch-refac-001_5ilst3--96fd543a0f.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.271 | 48 | traj, tx |
| [mcp_prometheus-query-engine-refac-001_hipadl](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_prometheus-query-engine-refac-001_hipadl--d533bff192.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.474 | 97 | traj, tx |
| [mcp_python-http-class-naming-refac-001_46ovpx](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_python-http-class-naming-refac-001_46ovpx--130fb60072.html) | `passed` | 0.960 | `None` | `semantic_similarity` | `answer_json_bridge` | 0.139 | 72 | traj, tx |
| [mcp_strata-fx-european-refac-001_wb1vm8](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_strata-fx-european-refac-001_wb1vm8--3ecbf1a17d.html) | `passed` | 0.700 | `None` | `ir_checklist` | `answer_json_bridge` | 0.333 | 57 | traj, tx |
| [mcp_terraform-eval-context-refac-001_qdndvq](../tasks/csb_sdlc_refactor_haiku_20260302_221730--mcp-remote-direct--mcp_terraform-eval-context-refac-001_qdndvq--82b6968699.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.170 | 47 | traj, tx |
