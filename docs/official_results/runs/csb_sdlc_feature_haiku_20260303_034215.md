# csb_sdlc_feature_haiku_20260303_034215

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.833`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [numpy-rolling-median-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_034215--baseline-local-direct--numpy-rolling-median-feat-001--8e6be6da44.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 68 | traj, tx |
| [pandas-merge-asof-indicator-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_034215--baseline-local-direct--pandas-merge-asof-indicator-feat-001--c663cafdc4.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 57 | traj, tx |
| [prometheus-silence-bulk-api-feat-001](../tasks/csb_sdlc_feature_haiku_20260303_034215--baseline-local-direct--prometheus-silence-bulk-api-feat-001--9d2cfdbedc.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 129 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.778`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_numpy-rolling-median-feat-001_voi8r3](../tasks/csb_sdlc_feature_haiku_20260303_034215--mcp-remote-direct--mcp_numpy-rolling-median-feat-001_voi8r3--92c1180bd8.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.224 | 67 | traj, tx |
| [mcp_pandas-merge-asof-indicator-feat-001_yswvqh](../tasks/csb_sdlc_feature_haiku_20260303_034215--mcp-remote-direct--mcp_pandas-merge-asof-indicator-feat-001_yswvqh--d9a65ca9a5.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.566 | 99 | traj, tx |
| [mcp_prometheus-silence-bulk-api-feat-001_eszxcy](../tasks/csb_sdlc_feature_haiku_20260303_034215--mcp-remote-direct--mcp_prometheus-silence-bulk-api-feat-001_eszxcy--402ecc6333.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.421 | 95 | traj, tx |
