# csb_sdlc_feature_haiku_20260302_004743

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.444`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [servo-css-container-query-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_004743--baseline-local-direct--servo-css-container-query-feat-001--5464bad332.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 136 | traj, tx |
| [postgres-copy-csv-header-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_004743--baseline-local-direct--postgres-copy-csv-header-feat-001--f66a2e1d4b.html) | `passed` | 0.333 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [vscode-custom-fold-region-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_004743--baseline-local-direct--vscode-custom-fold-region-feat-001--a85bd1070a.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 64 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.500`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_servo-css-container-query-feat-001_9uogue](../tasks/csb_sdlc_feature_haiku_20260302_004743--mcp-remote-direct--mcp_servo-css-container-query-feat-001_9uogue--ce2f032fc5.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.625 | 64 | traj, tx |
| [mcp_postgres-copy-csv-header-feat-001_twvjfw](../tasks/csb_sdlc_feature_haiku_20260302_004743--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_twvjfw--9b0d56abfb.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.553 | 76 | traj, tx |
| [mcp_vscode-custom-fold-region-feat-001_1nsegg](../tasks/csb_sdlc_feature_haiku_20260302_004743--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_1nsegg--9119651371.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.567 | 67 | traj, tx |
