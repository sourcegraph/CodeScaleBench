# csb_sdlc_test_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.225`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [test-coverage-gap-001](../tasks/csb_sdlc_test_haiku_20260302_221730--baseline-local-direct--test-coverage-gap-001--bf0d1ae214.html) | `passed` | 0.080 | `None` | `repo_state_heuristic` | `answer_json_bridge` | - | - | traj, tx |
| [test-integration-002](../tasks/csb_sdlc_test_haiku_20260302_221730--baseline-local-direct--test-integration-002--b24700b82d.html) | `passed` | 0.370 | `None` | `-` | `-` | 0.000 | 61 | traj, tx |

## mcp-remote-direct

- Valid tasks: `1`
- Mean reward: `0.900`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_test-coverage-gap-001_7jagwr](../tasks/csb_sdlc_test_haiku_20260302_221730--mcp-remote-direct--mcp_test-coverage-gap-001_7jagwr--2231f52d5f.html) | `passed` | 0.900 | `None` | `repo_state_heuristic` | `answer_json_bridge` | 0.962 | 26 | traj, tx |
