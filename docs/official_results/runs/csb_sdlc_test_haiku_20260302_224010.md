# csb_sdlc_test_haiku_20260302_224010

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.615`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [test-coverage-gap-001](../tasks/csb_sdlc_test_haiku_20260302_224010--baseline-local-direct--test-coverage-gap-001--e95bb0a00f.html) | `passed` | 0.860 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [test-integration-002](../tasks/csb_sdlc_test_haiku_20260302_224010--baseline-local-direct--test-integration-002--a6b923eeab.html) | `passed` | 0.370 | `None` | `-` | `-` | 0.000 | 48 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.490`
- Pass rate: `1.000`
- Scorer families: `unknown (2)`
- Output contracts: `unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_openhands-search-file-test-001_pjw2co](../tasks/csb_sdlc_test_haiku_20260302_224010--mcp-remote-direct--mcp_openhands-search-file-test-001_pjw2co--bd79a97e3c.html) | `passed` | 0.200 | `True` | `-` | `-` | 0.184 | 38 | traj, tx |
| [mcp_test-integration-002_h5qdvy](../tasks/csb_sdlc_test_haiku_20260302_224010--mcp-remote-direct--mcp_test-integration-002_h5qdvy--2de98baa30.html) | `passed` | 0.780 | `True` | `-` | `-` | 0.743 | 35 | traj, tx |
