# csb_org_incident_haiku_20260301_185444

## baseline-local-direct

- Valid tasks: `6`
- Mean reward: `0.426`
- Pass rate: `0.833`
- Scorer families: `oracle_checks (3), unknown (3)`
- Output contracts: `answer_json_native (3), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-incident-149](../tasks/csb_org_incident_haiku_20260301_185444--baseline-local-direct--ccx-incident-149--0fc6534ca1.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.000 | 52 | traj, tx |
| [ccx-incident-142](../tasks/csb_org_incident_haiku_20260301_185444--baseline-local-direct--ccx-incident-142--25188921cd.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.000 | 38 | traj, tx |
| [ccx-incident-143](../tasks/csb_org_incident_haiku_20260301_185444--baseline-local-direct--ccx-incident-143--ec9c4aea76.html) | `passed` | 0.143 | `True` | `-` | `-` | 0.000 | 29 | traj, tx |
| [ccx-incident-144](../tasks/csb_org_incident_haiku_20260301_185444--baseline-local-direct--ccx-incident-144--3c40dfef63.html) | `passed` | 0.316 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 26 | traj, tx |
| [ccx-incident-148](../tasks/csb_org_incident_haiku_20260301_185444--baseline-local-direct--ccx-incident-148--5f5425dc88.html) | `passed` | 0.600 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 31 | traj, tx |
| [ccx-incident-150](../tasks/csb_org_incident_haiku_20260301_185444--baseline-local-direct--ccx-incident-150--3fe91d6ab8.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 57 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.200`
- Pass rate: `0.333`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-incident-149_luou11](../tasks/csb_org_incident_haiku_20260301_185444--mcp-remote-direct--mcp_ccx-incident-149_luou11--7d76b4874d.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.951 | 41 | traj, tx |
| [mcp_ccx-incident-150_ffsz9t](../tasks/csb_org_incident_haiku_20260301_185444--mcp-remote-direct--mcp_ccx-incident-150_ffsz9t--e7e395b69b.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.932 | 44 | traj, tx |
| [mcp_ccx-incident-148_ssdsfw](../tasks/csb_org_incident_haiku_20260301_185444--mcp-remote-direct--mcp_ccx-incident-148_ssdsfw--956975d9b2.html) | `passed` | 0.600 | `True` | `oracle_checks` | `answer_json_native` | 0.909 | 44 | traj, tx |
