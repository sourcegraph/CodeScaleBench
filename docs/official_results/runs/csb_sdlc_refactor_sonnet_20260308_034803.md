# csb_sdlc_refactor_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `18`
- Mean reward: `0.769`
- Pass rate: `0.944`
- Scorer families: `repo_state_heuristic (14), ir_checklist (3), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (18)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [flipt-flagexists-refactor-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--flipt-flagexists-refactor-001--3277b720dc.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 37 | traj, tx |
| [beam-pipeline-builder-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--beam-pipeline-builder-refac-001--2f664dad85.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 27 | traj, tx |
| [cilium-endpoint-manager-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--cilium-endpoint-manager-refac-001--eba94587c7.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [django-request-factory-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--django-request-factory-refac-001--931298c85a.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 58 | traj, tx |
| [envoy-listener-manager-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--envoy-listener-manager-refac-001--7ac3217e88.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 43 | traj, tx |
| [flipt-dep-refactor-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--flipt-dep-refactor-001--2750c298aa.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [istio-discovery-server-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--istio-discovery-server-refac-001--38ad5faa98.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 16 | traj, tx |
| [k8s-score-normalizer-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--k8s-score-normalizer-refac-001--7f61313ec5.html) | `passed` | 0.600 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 48 | traj, tx |
| [kafka-batch-accumulator-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--kafka-batch-accumulator-refac-001--89d7a571a6.html) | `passed` | 0.770 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 71 | traj, tx |
| [kubernetes-scheduler-profile-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--kubernetes-scheduler-profile-refac-001--63b32523ec.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 27 | traj, tx |
| [numpy-array-dispatch-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--numpy-array-dispatch-refac-001--7782ef36f3.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 29 | traj, tx |
| [pandas-index-engine-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--pandas-index-engine-refac-001--346cf95806.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [prometheus-query-engine-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--prometheus-query-engine-refac-001--58fda14d42.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 22 | traj, tx |
| [python-http-class-naming-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--python-http-class-naming-refac-001--445d982ba3.html) | `passed` | 0.840 | `True` | `semantic_similarity` | `answer_json_bridge` | 0.000 | 132 | traj, tx |
| [pytorch-optimizer-foreach-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--pytorch-optimizer-foreach-refac-001--ea9bb01bc4.html) | `passed` | 0.333 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 55 | traj, tx |
| [roslyn-symbol-resolver-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--roslyn-symbol-resolver-refac-001--1fee75a652.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 64 | traj, tx |
| [strata-fx-european-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--strata-fx-european-refac-001--f90f3a8d9e.html) | `passed` | 0.790 | `True` | `ir_checklist` | `answer_json_bridge` | 0.000 | 60 | traj, tx |
| [terraform-eval-context-refac-001](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--baseline-local-direct--terraform-eval-context-refac-001--d4e9b6314b.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 21 | traj, tx |

## mcp-remote-direct

- Valid tasks: `15`
- Mean reward: `0.671`
- Pass rate: `0.867`
- Scorer families: `repo_state_heuristic (13), ir_checklist (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (15)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_flipt-flagexists-refactor-001_yev47o](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_flipt-flagexists-refactor-001_yev47o--f69e69d755.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.406 | 32 | traj, tx |
| [mcp_python-http-class-naming-refac-001_05zbxy](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_python-http-class-naming-refac-001_05zbxy--419a8e1aa6.html) | `failed` | 0.000 | `False` | `semantic_similarity` | `answer_json_bridge` | 0.541 | 61 | traj, tx |
| [mcp_beam-pipeline-builder-refac-001_xrnoxx](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_beam-pipeline-builder-refac-001_xrnoxx--06b817a477.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.333 | 18 | traj, tx |
| [mcp_cilium-endpoint-manager-refac-001_aglk11](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_cilium-endpoint-manager-refac-001_aglk11--0066ab6c1f.html) | `passed` | 0.333 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.158 | 38 | traj, tx |
| [mcp_django-request-factory-refac-001_2gmblk](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_django-request-factory-refac-001_2gmblk--05df3d535a.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.297 | 101 | traj, tx |
| [mcp_envoy-listener-manager-refac-001_ef92lv](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-listener-manager-refac-001_ef92lv--ea993b7887.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.354 | 65 | traj, tx |
| [mcp_flipt-dep-refactor-001_pvka0n](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_flipt-dep-refactor-001_pvka0n--9944165813.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.377 | 61 | traj, tx |
| [mcp_istio-discovery-server-refac-001_ulpkvj](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_istio-discovery-server-refac-001_ulpkvj--ab149fd316.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.479 | 96 | traj, tx |
| [mcp_k8s-score-normalizer-refac-001_3miume](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-score-normalizer-refac-001_3miume--36d48b91d8.html) | `passed` | 0.730 | `True` | `ir_checklist` | `answer_json_bridge` | 0.576 | 33 | traj, tx |
| [mcp_kubernetes-scheduler-profile-refac-001_2rsjrw](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_kubernetes-scheduler-profile-refac-001_2rsjrw--201310fc36.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.469 | 64 | traj, tx |
| [mcp_numpy-array-dispatch-refac-001_fje09x](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_numpy-array-dispatch-refac-001_fje09x--439dea1245.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.104 | 106 | traj, tx |
| [mcp_pandas-index-engine-refac-001_ivcc0q](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_pandas-index-engine-refac-001_ivcc0q--b3feb780ba.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.092 | 76 | traj, tx |
| [mcp_prometheus-query-engine-refac-001_l5qhef](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_prometheus-query-engine-refac-001_l5qhef--b6c3ffeda9.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.205 | 78 | traj, tx |
| [mcp_pytorch-optimizer-foreach-refac-001_zuqv9g](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_pytorch-optimizer-foreach-refac-001_zuqv9g--62d63a5b6a.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.349 | 43 | traj, tx |
| [mcp_roslyn-symbol-resolver-refac-001_mi8bux](../tasks/csb_sdlc_refactor_sonnet_20260308_034803--mcp-remote-direct--mcp_roslyn-symbol-resolver-refac-001_mi8bux--b498318b3a.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.556 | 27 | traj, tx |
