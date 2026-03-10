# csb_sdlc_debug_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.800`
- Pass rate: `1.000`
- Scorer families: `checklist (4), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (5)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [linux-acpi-backlight-fault-001](../tasks/csb_sdlc_debug_sonnet_20260308_034803--baseline-local-direct--linux-acpi-backlight-fault-001--3f7f66d176.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [linux-hda-intel-suspend-fault-001](../tasks/csb_sdlc_debug_sonnet_20260308_034803--baseline-local-direct--linux-hda-intel-suspend-fault-001--2705cec5fe.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 46 | traj, tx |
| [linux-iwlwifi-subdevice-fault-001](../tasks/csb_sdlc_debug_sonnet_20260308_034803--baseline-local-direct--linux-iwlwifi-subdevice-fault-001--9a71061105.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 7 | traj, tx |
| [linux-nfs-inode-revalidate-fault-001](../tasks/csb_sdlc_debug_sonnet_20260308_034803--baseline-local-direct--linux-nfs-inode-revalidate-fault-001--d1c328e14b.html) | `passed` | 0.300 | `True` | `checklist` | `answer_json_bridge` | 0.000 | 84 | traj, tx |
| [tidb-query-plan-regression-debug-001](../tasks/csb_sdlc_debug_sonnet_20260308_034803--baseline-local-direct--tidb-query-plan-regression-debug-001--814e8d1d5c.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 29 | traj, tx |

## mcp-remote-direct

- Valid tasks: `5`
- Mean reward: `0.740`
- Pass rate: `1.000`
- Scorer families: `checklist (4), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (5)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_linux-acpi-backlight-fault-001_gaj5iy](../tasks/csb_sdlc_debug_sonnet_20260308_034803--mcp-remote-direct--mcp_linux-acpi-backlight-fault-001_gaj5iy--ce2c5c2a8e.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.273 | 11 | traj, tx |
| [mcp_linux-hda-intel-suspend-fault-001_xthkiv](../tasks/csb_sdlc_debug_sonnet_20260308_034803--mcp-remote-direct--mcp_linux-hda-intel-suspend-fault-001_xthkiv--f81039e44c.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.654 | 26 | traj, tx |
| [mcp_linux-iwlwifi-subdevice-fault-001_p16pbc](../tasks/csb_sdlc_debug_sonnet_20260308_034803--mcp-remote-direct--mcp_linux-iwlwifi-subdevice-fault-001_p16pbc--8f7c4afce0.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.333 | 12 | traj, tx |
| [mcp_linux-nfs-inode-revalidate-fault-001_pprbxy](../tasks/csb_sdlc_debug_sonnet_20260308_034803--mcp-remote-direct--mcp_linux-nfs-inode-revalidate-fault-001_pprbxy--4b226a5ff6.html) | `passed` | 0.300 | `True` | `checklist` | `answer_json_bridge` | 0.820 | 50 | traj, tx |
| [mcp_tidb-query-plan-regression-debug-001_iudlmb](../tasks/csb_sdlc_debug_sonnet_20260308_034803--mcp-remote-direct--mcp_tidb-query-plan-regression-debug-001_iudlmb--3dc444e1b3.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.828 | 29 | traj, tx |
