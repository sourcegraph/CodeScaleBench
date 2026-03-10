# csb_sdlc_refactor_haiku_20260302_224219

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.500`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [cilium-endpoint-manager-refac-001](../tasks/csb_sdlc_refactor_haiku_20260302_224219--baseline-local-direct--cilium-endpoint-manager-refac-001--68327a00fa.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 62 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.222`
- Pass rate: `0.667`
- Scorer families: `repo_state_heuristic (3)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_flipt-dep-refactor-001_46vpsm](../tasks/csb_sdlc_refactor_haiku_20260302_224219--mcp-remote-direct--mcp_flipt-dep-refactor-001_46vpsm--667d24dc24.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.412 | 51 | traj, tx |
| [mcp_cilium-endpoint-manager-refac-001_ym1dg6](../tasks/csb_sdlc_refactor_haiku_20260302_224219--mcp-remote-direct--mcp_cilium-endpoint-manager-refac-001_ym1dg6--7f9b5f5d81.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.149 | 74 | traj, tx |
| [mcp_pytorch-optimizer-foreach-refac-001_s8fauj](../tasks/csb_sdlc_refactor_haiku_20260302_224219--mcp-remote-direct--mcp_pytorch-optimizer-foreach-refac-001_s8fauj--9508534093.html) | `passed` | 0.167 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.375 | 32 | traj, tx |
