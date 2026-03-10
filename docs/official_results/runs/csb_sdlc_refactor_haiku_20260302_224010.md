# csb_sdlc_refactor_haiku_20260302_224010

## baseline-local-direct

- Valid tasks: `11`
- Mean reward: `0.682`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (8), ir_checklist (2), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (11)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [cilium-endpoint-manager-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--cilium-endpoint-manager-refac-001--04bee7205a.html) | `passed` | 0.333 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 122 | traj, tx |
| [django-request-factory-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--django-request-factory-refac-001--2fcf93e02a.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [envoy-listener-manager-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--envoy-listener-manager-refac-001--642e0df7ff.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 35 | traj, tx |
| [flipt-dep-refactor-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--flipt-dep-refactor-001--9b9cb92781.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 60 | traj, tx |
| [flipt-flagexists-refactor-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--flipt-flagexists-refactor-001--8dfd79dea5.html) | `passed` | 0.550 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 34 | traj, tx |
| [kafka-batch-accumulator-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--kafka-batch-accumulator-refac-001--0f0cd2db18.html) | `passed` | 0.160 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 51 | traj, tx |
| [pandas-index-engine-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--pandas-index-engine-refac-001--e6d3a94b61.html) | `passed` | 0.667 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 88 | traj, tx |
| [prometheus-query-engine-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--prometheus-query-engine-refac-001--ec62a09d66.html) | `passed` | 0.833 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 42 | traj, tx |
| [python-http-class-naming-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--python-http-class-naming-refac-001--06530ade2a.html) | `passed` | 0.920 | `None` | `semantic_similarity` | `answer_json_bridge` | 0.000 | 93 | traj, tx |
| [strata-fx-european-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--strata-fx-european-refac-001--ea56da1711.html) | `passed` | 0.540 | `None` | `ir_checklist` | `answer_json_bridge` | 0.000 | 37 | traj, tx |
| [terraform-eval-context-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224010--baseline-local-direct--terraform-eval-context-refac-001--9f34f2a8ff.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 105 | traj, tx |

## mcp-remote-direct

- Valid tasks: `11`
- Mean reward: `0.602`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (7), ir_checklist (3), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (11)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_cilium-endpoint-manager-refac-001_ztdnpu](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_cilium-endpoint-manager-refac-001_ztdnpu--13d676b61b.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.596 | 47 | traj, tx |
| [mcp_django-request-factory-refac-001_jmgt1c](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_django-request-factory-refac-001_jmgt1c--b08f8a0f05.html) | `passed` | 0.167 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.250 | 56 | traj, tx |
| [mcp_flipt-dep-refactor-001_puguip](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_flipt-dep-refactor-001_puguip--9bc9c272d2.html) | `passed` | 0.270 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.418 | 55 | traj, tx |
| [mcp_flipt-flagexists-refactor-001_ejtvd6](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_flipt-flagexists-refactor-001_ejtvd6--f6484d0f30.html) | `passed` | 0.850 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.271 | 85 | traj, tx |
| [mcp_k8s-score-normalizer-refac-001_awc9zq](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_k8s-score-normalizer-refac-001_awc9zq--89679b9c1a.html) | `passed` | 0.820 | `True` | `ir_checklist` | `answer_json_bridge` | 0.324 | 139 | traj, tx |
| [mcp_kafka-batch-accumulator-refac-001_6i5iwi](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_kafka-batch-accumulator-refac-001_6i5iwi--d17335dcb5.html) | `passed` | 0.240 | `True` | `ir_checklist` | `answer_json_bridge` | 0.133 | 83 | traj, tx |
| [mcp_prometheus-query-engine-refac-001_w9nz8f](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_prometheus-query-engine-refac-001_w9nz8f--bd12f15926.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.400 | 70 | traj, tx |
| [mcp_python-http-class-naming-refac-001_e5c0x5](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_python-http-class-naming-refac-001_e5c0x5--5983948add.html) | `passed` | 0.600 | `True` | `semantic_similarity` | `answer_json_bridge` | 0.069 | 101 | traj, tx |
| [mcp_pytorch-optimizer-foreach-refac-001_jbuvm7](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_pytorch-optimizer-foreach-refac-001_jbuvm7--fab6f50911.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.412 | 34 | traj, tx |
| [mcp_strata-fx-european-refac-001_8kwebd](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_strata-fx-european-refac-001_8kwebd--234ef9da03.html) | `passed` | 0.670 | `True` | `ir_checklist` | `answer_json_bridge` | 0.760 | 25 | traj, tx |
| [mcp_terraform-eval-context-refac-001_s6tw1m](../tasks/csb_sdlc_refactor_haiku_20260302_224010--mcp-remote-direct--mcp_terraform-eval-context-refac-001_s6tw1m--10c2901327.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.121 | 66 | traj, tx |
