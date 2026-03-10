# csb_sdlc_feature_haiku_20260301_212230

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.500`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [servo-css-container-query-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_212230--baseline-local-direct--servo-css-container-query-feat-001--29b3fdc3db.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 178 | traj, tx |
| [postgres-copy-csv-header-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_212230--baseline-local-direct--postgres-copy-csv-header-feat-001--f2bc70ab34.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 91 | traj, tx |
| [vscode-custom-fold-region-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_212230--baseline-local-direct--vscode-custom-fold-region-feat-001--af15d480b6.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 74 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.500`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_servo-css-container-query-feat-001_cmlod2](../tasks/csb_sdlc_feature_haiku_20260301_212230--mcp-remote-direct--mcp_servo-css-container-query-feat-001_cmlod2--3e5c762f6f.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.128 | 109 | traj, tx |
| [mcp_postgres-copy-csv-header-feat-001_hl7ox9](../tasks/csb_sdlc_feature_haiku_20260301_212230--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_hl7ox9--e6fb7f9594.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.512 | 82 | traj, tx |
| [mcp_vscode-custom-fold-region-feat-001_qrch5q](../tasks/csb_sdlc_feature_haiku_20260301_212230--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_qrch5q--4df17c81ea.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.583 | 72 | traj, tx |
