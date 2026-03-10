# csb_org_incident_haiku_20260302_014939

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.222`
- Pass rate: `0.333`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-incident-149](../tasks/csb_org_incident_haiku_20260302_014939--baseline-local-direct--ccx-incident-149--462ee619ab.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.000 | 54 | traj, tx |
| [ccx-incident-150](../tasks/csb_org_incident_haiku_20260302_014939--baseline-local-direct--ccx-incident-150--e49bc1e134.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 48 | traj, tx |
| [ccx-incident-148](../tasks/csb_org_incident_haiku_20260302_014939--baseline-local-direct--ccx-incident-148--2d8f42164e.html) | `passed` | 0.667 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 31 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.167`
- Pass rate: `0.333`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-incident-149_p47d3o](../tasks/csb_org_incident_haiku_20260302_014939--mcp-remote-direct--mcp_ccx-incident-149_p47d3o--09edc34eea.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.971 | 34 | traj, tx |
| [mcp_ccx-incident-150_gijbkw](../tasks/csb_org_incident_haiku_20260302_014939--mcp-remote-direct--mcp_ccx-incident-150_gijbkw--5a9a7e22fa.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.930 | 43 | traj, tx |
| [mcp_ccx-incident-148_umltvw](../tasks/csb_org_incident_haiku_20260302_014939--mcp-remote-direct--mcp_ccx-incident-148_umltvw--3b83cef7df.html) | `passed` | 0.500 | `True` | `oracle_checks` | `answer_json_native` | 0.926 | 27 | traj, tx |
