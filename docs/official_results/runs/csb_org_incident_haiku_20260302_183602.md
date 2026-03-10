# csb_org_incident_haiku_20260302_183602

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.630`
- Pass rate: `0.667`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-incident-031](../tasks/csb_org_incident_haiku_20260302_183602--baseline-local-direct--ccx-incident-031--208cab0f36.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 12 | traj, tx |
| [ccx-incident-034](../tasks/csb_org_incident_haiku_20260302_183602--baseline-local-direct--ccx-incident-034--4f1e0eed3d.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 16 | traj, tx |
| [ccx-incident-037](../tasks/csb_org_incident_haiku_20260302_183602--baseline-local-direct--ccx-incident-037--98b9b0de69.html) | `passed` | 0.889 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 27 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.968`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-incident-031_9kvbtf](../tasks/csb_org_incident_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-incident-031_9kvbtf--ec761c2448.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.750 | 8 | traj, tx |
| [mcp_ccx-incident-034_zlurib](../tasks/csb_org_incident_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-incident-034_zlurib--60eac37c50.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.929 | 14 | traj, tx |
| [mcp_ccx-incident-037_niqjhz](../tasks/csb_org_incident_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-incident-037_niqjhz--1b73bd589f.html) | `passed` | 0.903 | `True` | `oracle_checks` | `answer_json_native` | 0.867 | 15 | traj, tx |
