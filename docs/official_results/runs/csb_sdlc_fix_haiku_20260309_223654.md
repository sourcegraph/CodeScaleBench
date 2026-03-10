# csb_sdlc_fix_haiku_20260309_223654

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.000`
- Pass rate: `0.000`
- Scorer families: `repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [flink-window-late-data-fix-001](../tasks/csb_sdlc_fix_haiku_20260309_223654--baseline-local-direct--flink-window-late-data-fix-001--8bf89dc87e.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 53 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.500`
- Pass rate: `0.500`
- Scorer families: `repo_state_heuristic (1), test_ratio (1)`
- Output contracts: `answer_json_bridge (1), unspecified (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_flink-window-late-data-fix-001_1gmul7](../tasks/csb_sdlc_fix_haiku_20260309_223654--mcp-remote-direct--mcp_flink-window-late-data-fix-001_1gmul7--f3e7f46c3a.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.402 | 97 | traj, tx |
| [mcp_element-web-unread-indicators-diverge-fix-001_ahe0sp](../tasks/csb_sdlc_fix_haiku_20260309_223654--mcp-remote-direct--mcp_element-web-unread-indicators-diverge-fix-001_ahe0sp--078400a9f7.html) | `passed` | 1.000 | `True` | `test_ratio` | `unspecified` | 0.462 | 78 | traj, tx |
