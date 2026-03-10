# csb_sdlc_document_haiku_20260307_001927

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `1.000`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [godot-gdscript-api-docgen-001](../tasks/csb_sdlc_document_haiku_20260307_001927--baseline-local-direct--godot-gdscript-api-docgen-001--75aaab2a5a.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 11 | traj, tx |
| [grpc-channel-api-docgen-001](../tasks/csb_sdlc_document_haiku_20260307_001927--baseline-local-direct--grpc-channel-api-docgen-001--3b2f739fce.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 12 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.500`
- Pass rate: `0.500`
- Scorer families: `repo_state_heuristic (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_godot-gdscript-api-docgen-001_h6qdjv](../tasks/csb_sdlc_document_haiku_20260307_001927--mcp-remote-direct--mcp_godot-gdscript-api-docgen-001_h6qdjv--197089e207.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.700 | 10 | traj, tx |
| [mcp_grpc-channel-api-docgen-001_emgnzy](../tasks/csb_sdlc_document_haiku_20260307_001927--mcp-remote-direct--mcp_grpc-channel-api-docgen-001_emgnzy--3d3de70162.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.643 | 14 | traj, tx |
