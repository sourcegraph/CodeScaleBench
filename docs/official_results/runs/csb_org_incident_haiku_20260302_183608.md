# csb_org_incident_haiku_20260302_183608

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.619`
- Pass rate: `0.667`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-incident-031](../tasks/csb_org_incident_haiku_20260302_183608--baseline-local-direct--ccx-incident-031--82c51a820e.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 27 | traj, tx |
| [ccx-incident-034](../tasks/csb_org_incident_haiku_20260302_183608--baseline-local-direct--ccx-incident-034--291ddfc268.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 15 | traj, tx |
| [ccx-incident-037](../tasks/csb_org_incident_haiku_20260302_183608--baseline-local-direct--ccx-incident-037--9ad31fd108.html) | `passed` | 0.857 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 23 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.929`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-incident-031_rh47jm](../tasks/csb_org_incident_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-incident-031_rh47jm--2d372de3c0.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.714 | 7 | traj, tx |
| [mcp_ccx-incident-034_ymfwzo](../tasks/csb_org_incident_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-incident-034_ymfwzo--c8b91b14c2.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.875 | 16 | traj, tx |
| [mcp_ccx-incident-037_xjp2fj](../tasks/csb_org_incident_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-incident-037_xjp2fj--f8ffc6734a.html) | `passed` | 0.788 | `True` | `oracle_checks` | `answer_json_native` | 0.917 | 12 | traj, tx |
