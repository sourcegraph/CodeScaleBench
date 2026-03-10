# csb_sdlc_feature_haiku_20260301_230048

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.478`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (2), f1 (1)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [k8s-runtime-object-impl-001](../tasks/csb_sdlc_feature_haiku_20260301_230048--baseline-local-direct--k8s-runtime-object-impl-001--713c626699.html) | `passed` | 0.100 | `True` | `f1` | `answer_json_bridge` | 0.000 | 28 | traj, tx |
| [postgres-copy-csv-header-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_230048--baseline-local-direct--postgres-copy-csv-header-feat-001--e48c6e3134.html) | `passed` | 0.333 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 81 | traj, tx |
| [vscode-custom-fold-region-feat-001](../tasks/csb_sdlc_feature_haiku_20260301_230048--baseline-local-direct--vscode-custom-fold-region-feat-001--be1757314a.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 74 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.375`
- Pass rate: `0.500`
- Scorer families: `repo_state_heuristic (3), f1 (1)`
- Output contracts: `answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_k8s-runtime-object-impl-001_d6mxfb](../tasks/csb_sdlc_feature_haiku_20260301_230048--mcp-remote-direct--mcp_k8s-runtime-object-impl-001_d6mxfb--246e64c76b.html) | `failed` | 0.000 | `False` | `f1` | `answer_json_bridge` | 0.804 | 56 | traj, tx |
| [mcp_servo-css-container-query-feat-001_rcptyj](../tasks/csb_sdlc_feature_haiku_20260301_230048--mcp-remote-direct--mcp_servo-css-container-query-feat-001_rcptyj--3b54c5892a.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.301 | 93 | traj, tx |
| [mcp_postgres-copy-csv-header-feat-001_24czch](../tasks/csb_sdlc_feature_haiku_20260301_230048--mcp-remote-direct--mcp_postgres-copy-csv-header-feat-001_24czch--0531b27580.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.589 | 95 | traj, tx |
| [mcp_vscode-custom-fold-region-feat-001_xyssfw](../tasks/csb_sdlc_feature_haiku_20260301_230048--mcp-remote-direct--mcp_vscode-custom-fold-region-feat-001_xyssfw--4d49ffce8e.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.525 | 61 | traj, tx |
