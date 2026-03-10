# csb_sdlc_refactor_haiku_20260307_001927

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.583`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [beam-pipeline-builder-refac-001](../tasks/csb_sdlc_refactor_haiku_20260307_001927--baseline-local-direct--beam-pipeline-builder-refac-001--92805d88e7.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 31 | traj, tx |
| [roslyn-symbol-resolver-refac-001](../tasks/csb_sdlc_refactor_haiku_20260307_001927--baseline-local-direct--roslyn-symbol-resolver-refac-001--23bb3a0c80.html) | `passed` | 0.167 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 66 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.500`
- Pass rate: `0.500`
- Scorer families: `repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_roslyn-symbol-resolver-refac-001_glq8fn](../tasks/csb_sdlc_refactor_haiku_20260307_001927--mcp-remote-direct--mcp_roslyn-symbol-resolver-refac-001_glq8fn--427c84c90d.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.556 | 27 | traj, tx |
| [mcp_beam-pipeline-builder-refac-001_qwwxjb](../tasks/csb_sdlc_refactor_haiku_20260307_001927--mcp-remote-direct--mcp_beam-pipeline-builder-refac-001_qwwxjb--9640c45e4f.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.206 | 34 | traj, tx |
