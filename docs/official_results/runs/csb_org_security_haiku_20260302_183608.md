# csb_org_security_haiku_20260302_183608

## baseline-local-direct

- Valid tasks: `6`
- Mean reward: `0.588`
- Pass rate: `0.833`
- Scorer families: `oracle_checks (3), unknown (3)`
- Output contracts: `answer_json_native (3), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-011](../tasks/csb_org_security_haiku_20260302_183608--baseline-local-direct--ccx-vuln-remed-011--a3a491b448.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 6 | traj, tx |
| [ccx-vuln-remed-014](../tasks/csb_org_security_haiku_20260302_183608--baseline-local-direct--ccx-vuln-remed-014--a2a2db72a7.html) | `passed` | 0.400 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 63 | traj, tx |
| [ccx-vuln-remed-281](../tasks/csb_org_security_haiku_20260302_183608--baseline-local-direct--ccx-vuln-remed-281--0f8bec6aff.html) | `passed` | 0.764 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 19 | traj, tx |
| [ccx-vuln-remed-282](../tasks/csb_org_security_haiku_20260302_183608--baseline-local-direct--ccx-vuln-remed-282--dd1ec57cf5.html) | `passed` | 0.741 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 32 | traj, tx |
| [ccx-vuln-remed-283](../tasks/csb_org_security_haiku_20260302_183608--baseline-local-direct--ccx-vuln-remed-283--c446791705.html) | `passed` | 0.776 | `True` | `-` | `-` | 0.000 | 28 | traj, tx |
| [ccx-vuln-remed-284](../tasks/csb_org_security_haiku_20260302_183608--baseline-local-direct--ccx-vuln-remed-284--47da2b39d8.html) | `passed` | 0.850 | `True` | `-` | `-` | 0.000 | 23 | traj, tx |

## mcp-remote-direct

- Valid tasks: `6`
- Mean reward: `0.771`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (3), unknown (3)`
- Output contracts: `answer_json_native (3), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-vuln-remed-011_cfl3do](../tasks/csb_org_security_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-vuln-remed-011_cfl3do--fec26d59ea.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.909 | 22 | traj, tx |
| [mcp_ccx-vuln-remed-014_boi84b](../tasks/csb_org_security_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-vuln-remed-014_boi84b--0783fe7379.html) | `passed` | 0.500 | `True` | `oracle_checks` | `answer_json_native` | 0.839 | 62 | traj, tx |
| [mcp_ccx-vuln-remed-281_t8iugs](../tasks/csb_org_security_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-vuln-remed-281_t8iugs--5372ba0c35.html) | `passed` | 0.650 | `True` | `oracle_checks` | `answer_json_native` | 0.909 | 22 | traj, tx |
| [mcp_ccx-vuln-remed-282_yellqt](../tasks/csb_org_security_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-vuln-remed-282_yellqt--97b9510644.html) | `passed` | 0.850 | `True` | `oracle_checks` | `answer_json_native` | 0.972 | 36 | traj, tx |
| [mcp_ccx-vuln-remed-283_i0kw47](../tasks/csb_org_security_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-vuln-remed-283_i0kw47--5a72c8ba30.html) | `passed` | 0.833 | `True` | `-` | `-` | 0.962 | 26 | traj, tx |
| [mcp_ccx-vuln-remed-284_m9fe3z](../tasks/csb_org_security_haiku_20260302_183608--mcp-remote-direct--mcp_ccx-vuln-remed-284_m9fe3z--029603506a.html) | `passed` | 0.792 | `True` | `-` | `-` | 0.960 | 25 | traj, tx |
