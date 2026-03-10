# csb_sdlc_feature_haiku_20260302_005828

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.222`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [servo-css-container-query-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_005828--baseline-local-direct--servo-css-container-query-feat-001--712114a709.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 151 | traj, tx |
| [postgres-copy-csv-header-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_005828--baseline-local-direct--postgres-copy-csv-header-feat-001--bef5c6a774.html) | `passed` | 0.333 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 67 | traj, tx |
| [vscode-custom-fold-region-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_005828--baseline-local-direct--vscode-custom-fold-region-feat-001--9530e10301.html) | `passed` | 0.333 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 97 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.500`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_servo-css-container-query-feat-001_sf6eht](../tasks/csb_sdlc_feature_haiku_20260302_005828--mcp-remote-direct--mcp_servo-css-container-query-feat-001_sf6eht--706f1a1fbf.html) | `failed` | 0.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.454 | 108 | traj, tx |
| [mcp_postgres-copy-csv-header-feat-001_r4p1kx](../tasks/csb_sdlc_feature_haiku_20260302_005828--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_r4p1kx--b9e66a15e0.html) | `passed` | 0.500 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.253 | 83 | traj, tx |
| [mcp_vscode-custom-fold-region-feat-001_0utr7t](../tasks/csb_sdlc_feature_haiku_20260302_005828--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_0utr7t--6be7f6ded4.html) | `passed` | 1.000 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.245 | 94 | traj, tx |
