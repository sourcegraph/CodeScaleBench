# csb_sdlc_debug_haiku_20260303_180441

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.000`
- Pass rate: `0.000`
- Scorer families: `checklist (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [linux-hda-intel-suspend-fault-001](../tasks/csb_sdlc_debug_haiku_20260303_180441--baseline-local-direct--linux-hda-intel-suspend-fault-001--8851f5dc2f.html) | `failed` | 0.000 | `False` | `checklist` | `answer_json_bridge` | - | - | traj, tx |

## mcp-remote-direct

- Valid tasks: `1`
- Mean reward: `0.700`
- Pass rate: `1.000`
- Scorer families: `checklist (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_linux-hda-intel-suspend-fault-001_j537le](../tasks/csb_sdlc_debug_haiku_20260303_180441--mcp-remote-direct--mcp_linux-hda-intel-suspend-fault-001_j537le--00baae8b46.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.816 | 38 | traj, tx |
