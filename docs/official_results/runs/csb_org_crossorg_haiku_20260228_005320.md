# csb_org_crossorg_haiku_20260228_005320

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.466`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (3)`
- Output contracts: `answer_json_native (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-crossorg-062](../tasks/csb_org_crossorg_haiku_20260228_005320--baseline-local-direct--ccx-crossorg-062--37fe74d12c.html) | `passed` | 0.692 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 43 | traj, tx |
| [ccx-crossorg-121](../tasks/csb_org_crossorg_haiku_20260228_005320--baseline-local-direct--ccx-crossorg-121--032198469d.html) | `passed` | 0.343 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 26 | traj, tx |
| [ccx-crossorg-132](../tasks/csb_org_crossorg_haiku_20260228_005320--baseline-local-direct--ccx-crossorg-132--2c10cef234.html) | `passed` | 0.365 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 50 | traj, tx |

## mcp-remote-direct

- Valid tasks: `5`
- Mean reward: `0.434`
- Pass rate: `0.800`
- Scorer families: `oracle_checks (3), unknown (2)`
- Output contracts: `answer_json_native (3), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-crossorg-066_hRabbC](../tasks/csb_org_crossorg_haiku_20260228_005320--mcp-remote-direct--mcp_ccx-crossorg-066_hRabbC--20c2555525.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.600 | 5 | traj, tx |
| [mcp_CCX-crossorg-062_8dsjzk](../tasks/csb_org_crossorg_haiku_20260228_005320--mcp-remote-direct--mcp_CCX-crossorg-062_8dsjzk--a57de1b506.html) | `passed` | 0.661 | `True` | `oracle_checks` | `answer_json_native` | 0.969 | 32 | traj, tx |
| [mcp_CCX-crossorg-121_CHYvre](../tasks/csb_org_crossorg_haiku_20260228_005320--mcp-remote-direct--mcp_CCX-crossorg-121_CHYvre--e8e26e3c29.html) | `passed` | 0.343 | `True` | `oracle_checks` | `answer_json_native` | 0.938 | 16 | traj, tx |
| [mcp_CCX-crossorg-132_1sh8k7](../tasks/csb_org_crossorg_haiku_20260228_005320--mcp-remote-direct--mcp_CCX-crossorg-132_1sh8k7--3aa41866de.html) | `passed` | 0.417 | `True` | `oracle_checks` | `answer_json_native` | 0.964 | 28 | traj, tx |
| [mcp_ccx-crossorg-061_uTKYpz](../tasks/csb_org_crossorg_haiku_20260228_005320--mcp-remote-direct--mcp_ccx-crossorg-061_uTKYpz--53ad4d282b.html) | `passed` | 0.750 | `True` | `-` | `-` | 0.927 | 41 | traj, tx |
