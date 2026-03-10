# csb_sdlc_test_haiku_20260307_001927

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.833`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [bazel-starlark-eval-test-001](../tasks/csb_sdlc_test_haiku_20260307_001927--baseline-local-direct--bazel-starlark-eval-test-001--1a13da722e.html) | `passed` | 0.667 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 18 | traj, tx |
| [cockroach-kv-txn-test-001](../tasks/csb_sdlc_test_haiku_20260307_001927--baseline-local-direct--cockroach-kv-txn-test-001--5b1e818750.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 60 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.917`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1), unknown (1)`
- Output contracts: `answer_json_bridge (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_bazel-starlark-eval-test-001_nf3x5v](../tasks/csb_sdlc_test_haiku_20260307_001927--mcp-remote-direct--mcp_bazel-starlark-eval-test-001_nf3x5v--01e9f510c2.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.393 | 28 | traj, tx |
| [mcp_cockroach-kv-txn-test-001_zdcckh](../tasks/csb_sdlc_test_haiku_20260307_001927--mcp-remote-direct--mcp_cockroach-kv-txn-test-001_zdcckh--5787542f09.html) | `passed` | 0.833 | `True` | `-` | `-` | 0.517 | 29 | traj, tx |
