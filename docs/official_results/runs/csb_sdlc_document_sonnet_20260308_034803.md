# csb_sdlc_document_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `11`
- Mean reward: `0.833`
- Pass rate: `1.000`
- Scorer families: `checklist (7), continuous (2), repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (11)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [docgen-inline-002](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--docgen-inline-002--430ebb4fd2.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 50 | traj, tx |
| [envoy-arch-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--envoy-arch-doc-gen-001--682f05119c.html) | `passed` | 0.970 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [envoy-migration-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--envoy-migration-doc-gen-001--7b860065b8.html) | `passed` | 0.880 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 41 | traj, tx |
| [godot-gdscript-api-docgen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--godot-gdscript-api-docgen-001--0efd86f892.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 12 | traj, tx |
| [grpc-channel-api-docgen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--grpc-channel-api-docgen-001--42faecce09.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [k8s-apiserver-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--k8s-apiserver-doc-gen-001--6c394007f8.html) | `passed` | 0.650 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 45 | traj, tx |
| [k8s-applyconfig-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--k8s-applyconfig-doc-gen-001--8b4a01c284.html) | `passed` | 0.900 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 49 | traj, tx |
| [k8s-clientgo-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--k8s-clientgo-doc-gen-001--f1a8cafabb.html) | `passed` | 0.750 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 33 | traj, tx |
| [k8s-fairqueuing-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--k8s-fairqueuing-doc-gen-001--be0553df09.html) | `passed` | 0.400 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 49 | traj, tx |
| [k8s-kubelet-cm-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--k8s-kubelet-cm-doc-gen-001--7f62dbb19d.html) | `passed` | 0.650 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 35 | traj, tx |
| [kafka-api-doc-gen-001](../tasks/csb_sdlc_document_sonnet_20260308_034803--baseline-local-direct--kafka-api-doc-gen-001--726720f3c7.html) | `passed` | 0.960 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 6 | traj, tx |

## mcp-remote-direct

- Valid tasks: `11`
- Mean reward: `0.704`
- Pass rate: `1.000`
- Scorer families: `checklist (7), continuous (2), repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (11)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_docgen-inline-002_5fqflj](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_docgen-inline-002_5fqflj--4996b7f1a8.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.455 | 22 | traj, tx |
| [mcp_envoy-arch-doc-gen-001_h9ddwm](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-arch-doc-gen-001_h9ddwm--486b38433c.html) | `passed` | 0.960 | `True` | `checklist` | `answer_json_bridge` | 0.893 | 28 | traj, tx |
| [mcp_envoy-migration-doc-gen-001_uxznff](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-migration-doc-gen-001_uxznff--b0a0a8541f.html) | `passed` | 0.630 | `True` | `continuous` | `answer_json_bridge` | 0.800 | 30 | traj, tx |
| [mcp_godot-gdscript-api-docgen-001_9uhee2](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_godot-gdscript-api-docgen-001_9uhee2--17e18d70c6.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.579 | 19 | traj, tx |
| [mcp_grpc-channel-api-docgen-001_h3ukz6](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_grpc-channel-api-docgen-001_h3ukz6--e987d51761.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.300 | 10 | traj, tx |
| [mcp_k8s-apiserver-doc-gen-001_aasyns](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-apiserver-doc-gen-001_aasyns--96c126a8ee.html) | `passed` | 0.650 | `True` | `checklist` | `answer_json_bridge` | 0.915 | 47 | traj, tx |
| [mcp_k8s-applyconfig-doc-gen-001_7aufiw](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_7aufiw--8fd6b1afc5.html) | `passed` | 0.650 | `True` | `checklist` | `answer_json_bridge` | 0.907 | 43 | traj, tx |
| [mcp_k8s-clientgo-doc-gen-001_wbaimp](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_wbaimp--23f050f340.html) | `passed` | 0.480 | `True` | `checklist` | `answer_json_bridge` | 0.897 | 39 | traj, tx |
| [mcp_k8s-fairqueuing-doc-gen-001_ruzvou](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_ruzvou--e072c700e8.html) | `passed` | 0.170 | `True` | `checklist` | `answer_json_bridge` | 0.885 | 26 | traj, tx |
| [mcp_k8s-kubelet-cm-doc-gen-001_dxc5kq](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_k8s-kubelet-cm-doc-gen-001_dxc5kq--a1223495af.html) | `passed` | 0.300 | `True` | `checklist` | `answer_json_bridge` | 0.902 | 41 | traj, tx |
| [mcp_kafka-api-doc-gen-001_lldj8l](../tasks/csb_sdlc_document_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-api-doc-gen-001_lldj8l--24a0ff73c1.html) | `passed` | 0.900 | `True` | `continuous` | `answer_json_bridge` | 0.765 | 17 | traj, tx |
