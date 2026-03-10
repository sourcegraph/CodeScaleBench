# csb_sdlc_feature_haiku_20260301_230003

## baseline-local-direct

- Valid tasks: `4`
- Mean reward: `0.358`
- Pass rate: `0.750`
- Scorer families: `repo_state_heuristic (3), f1 (1)`
- Output contracts: `answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [servo-css-container-query-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_230003--baseline-local-direct--servo-css-container-query-feat-001--3d649c70e7.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 89 | traj, tx |
| [k8s-runtime-object-impl-001](../tasks/csb_sdlc_feature_haiku_20260301_230003--baseline-local-direct--k8s-runtime-object-impl-001--8d4a6b2164.html) | `passed` | 0.100 | `None` | `f1` | `answer_json_bridge` | 0.000 | 27 | traj, tx |
| [postgres-copy-csv-header-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_230003--baseline-local-direct--postgres-copy-csv-header-feat-001--8d95db72d4.html) | `passed` | 0.333 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 69 | traj, tx |
| [vscode-custom-fold-region-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_230003--baseline-local-direct--vscode-custom-fold-region-feat-001--b363221269.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 93 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.407`
- Pass rate: `0.750`
- Scorer families: `repo_state_heuristic (3), f1 (1)`
- Output contracts: `answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_servo-css-container-query-feat-001_d2rk25](../tasks/csb_sdlc_feature_haiku_20260301_230003--mcp-remote-direct--mcp_servo-css-container-query-feat-001_d2rk25--0c8257cc9c.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.632 | 76 | traj, tx |
| [mcp_k8s-runtime-object-impl-001_v3doff](../tasks/csb_sdlc_feature_haiku_20260301_230003--mcp-remote-direct--mcp_k8s-runtime-object-impl-001_v3doff--8145814699.html) | `passed` | 0.130 | `None` | `f1` | `answer_json_bridge` | 0.810 | 42 | traj, tx |
| [mcp_postgres-copy-csv-header-feat-001_ergdpr](../tasks/csb_sdlc_feature_haiku_20260301_230003--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_ergdpr--7febbd67a5.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.424 | 139 | traj, tx |
| [mcp_vscode-custom-fold-region-feat-001_9bhijx](../tasks/csb_sdlc_feature_haiku_20260301_230003--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_9bhijx--85de685282.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.397 | 63 | traj, tx |
