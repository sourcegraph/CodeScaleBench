# csb_org_security_haiku_20260302_183602

## baseline-local-direct

- Valid tasks: `6`
- Mean reward: `0.515`
- Pass rate: `0.667`
- Scorer families: `oracle_checks (3), unknown (3)`
- Output contracts: `answer_json_native (3), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-011](../tasks/csb_org_security_haiku_20260302_183602--baseline-local-direct--ccx-vuln-remed-011--22446253b1.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 12 | traj, tx |
| [ccx-vuln-remed-014](../tasks/csb_org_security_haiku_20260302_183602--baseline-local-direct--ccx-vuln-remed-014--4951a4c2e4.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.000 | 55 | traj, tx |
| [ccx-vuln-remed-281](../tasks/csb_org_security_haiku_20260302_183602--baseline-local-direct--ccx-vuln-remed-281--58c60080fc.html) | `passed` | 0.673 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 20 | traj, tx |
| [ccx-vuln-remed-282](../tasks/csb_org_security_haiku_20260302_183602--baseline-local-direct--ccx-vuln-remed-282--7ffe3a2aed.html) | `passed` | 0.750 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 34 | traj, tx |
| [ccx-vuln-remed-283](../tasks/csb_org_security_haiku_20260302_183602--baseline-local-direct--ccx-vuln-remed-283--544e3d0066.html) | `passed` | 0.758 | `True` | `-` | `-` | 0.000 | 30 | traj, tx |
| [ccx-vuln-remed-284](../tasks/csb_org_security_haiku_20260302_183602--baseline-local-direct--ccx-vuln-remed-284--3de1c76df3.html) | `passed` | 0.912 | `True` | `-` | `-` | 0.000 | 22 | traj, tx |

## mcp-remote-direct

- Valid tasks: `6`
- Mean reward: `0.697`
- Pass rate: `0.833`
- Scorer families: `oracle_checks (3), unknown (3)`
- Output contracts: `answer_json_native (3), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-vuln-remed-014_6h4ekr](../tasks/csb_org_security_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-vuln-remed-014_6h4ekr--dbe52376f8.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.704 | 27 | traj, tx |
| [mcp_ccx-vuln-remed-011_twgsxw](../tasks/csb_org_security_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-vuln-remed-011_twgsxw--9b81bbfe77.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.947 | 19 | traj, tx |
| [mcp_ccx-vuln-remed-281_kxptse](../tasks/csb_org_security_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-vuln-remed-281_kxptse--593cba1972.html) | `passed` | 0.733 | `True` | `oracle_checks` | `answer_json_native` | 0.929 | 14 | traj, tx |
| [mcp_ccx-vuln-remed-282_ttdc2g](../tasks/csb_org_security_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-vuln-remed-282_ttdc2g--9347892ed4.html) | `passed` | 0.833 | `True` | `oracle_checks` | `answer_json_native` | 0.926 | 27 | traj, tx |
| [mcp_ccx-vuln-remed-283_af6mg3](../tasks/csb_org_security_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-vuln-remed-283_af6mg3--e45179bbe6.html) | `passed` | 0.776 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [mcp_ccx-vuln-remed-284_hbtosv](../tasks/csb_org_security_haiku_20260302_183602--mcp-remote-direct--mcp_ccx-vuln-remed-284_hbtosv--eeb59ea0e6.html) | `passed` | 0.838 | `True` | `-` | `-` | 0.967 | 30 | traj, tx |
