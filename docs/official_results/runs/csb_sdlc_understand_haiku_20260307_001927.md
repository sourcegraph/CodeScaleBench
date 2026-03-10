# csb_sdlc_understand_haiku_20260307_001927

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.100`
- Pass rate: `1.000`
- Scorer families: `continuous (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [grafana-platform-orient-001](../tasks/csb_sdlc_understand_haiku_20260307_001927--baseline-local-direct--grafana-platform-orient-001--16fbb3af0f.html) | `passed` | 0.100 | `True` | `continuous` | `answer_json_bridge` | 0.000 | 46 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.550`
- Pass rate: `1.000`
- Scorer families: `continuous (1), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_clickhouse-mergetree-arch-understand-001_usammb](../tasks/csb_sdlc_understand_haiku_20260307_001927--mcp-remote-direct--mcp_clickhouse-mergetree-arch-understand-001_usammb--8d6fcb01d6.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.667 | 27 | traj, tx |
| [mcp_grafana-platform-orient-001_x3rfg9](../tasks/csb_sdlc_understand_haiku_20260307_001927--mcp-remote-direct--mcp_grafana-platform-orient-001_x3rfg9--99b834893f.html) | `passed` | 0.100 | `True` | `continuous` | `answer_json_bridge` | 0.979 | 48 | traj, tx |
