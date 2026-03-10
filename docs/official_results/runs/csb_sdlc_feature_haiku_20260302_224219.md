# csb_sdlc_feature_haiku_20260302_224219

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.833`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [curl-http3-priority-feat-001](../tasks/csb_sdlc_feature_haiku_20260302_224219--baseline-local-direct--curl-http3-priority-feat-001--a15eafc04f.html) | `passed` | 0.833 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 132 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.620`
- Pass rate: `1.000`
- Scorer families: `ir_checklist (2), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_camel-fix-protocol-feat-001_uskyxf](../tasks/csb_sdlc_feature_haiku_20260302_224219--mcp-remote-direct--mcp_camel-fix-protocol-feat-001_uskyxf--71ddb91b04.html) | `passed` | 0.350 | `True` | `ir_checklist` | `answer_json_bridge` | 0.451 | 71 | traj, tx |
| [mcp_flink-pricing-window-feat-001_mi19l0](../tasks/csb_sdlc_feature_haiku_20260302_224219--mcp-remote-direct--mcp_flink-pricing-window-feat-001_mi19l0--30d47c6291.html) | `passed` | 0.510 | `True` | `ir_checklist` | `answer_json_bridge` | 0.375 | 48 | traj, tx |
| [mcp_terraform-compact-diff-fmt-feat-001_m8mxxm](../tasks/csb_sdlc_feature_haiku_20260302_224219--mcp-remote-direct--mcp_terraform-compact-diff-fmt-feat-001_m8mxxm--730a2b3a87.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.373 | 51 | traj, tx |
