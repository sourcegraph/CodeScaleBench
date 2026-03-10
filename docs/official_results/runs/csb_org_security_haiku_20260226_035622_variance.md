# csb_org_security_haiku_20260226_035622_variance

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.514`
- Pass rate: `1.000`
- Scorer families: `unknown (1)`
- Output contracts: `unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-012](../tasks/csb_org_security_haiku_20260226_035622_variance--baseline-local-direct--ccx-vuln-remed-012--ca0715f5e2.html) | `passed` | 0.514 | `True` | `-` | `-` | 0.000 | 37 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.578`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (2)`
- Output contracts: `answer_json_native (2), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_CCX-vuln-remed-012_9JwGrW](../tasks/csb_org_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-012_9JwGrW--b61422210c.html) | `passed` | 0.397 | `True` | `-` | `-` | 0.889 | 36 | traj, tx |
| [mcp_CCX-vuln-remed-013_Kmqlzc](../tasks/csb_org_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-013_Kmqlzc--12240e2914.html) | `passed` | 0.105 | `True` | `-` | `-` | 0.971 | 35 | traj, tx |
| [mcp_CCX-vuln-remed-105_79Rpkl](../tasks/csb_org_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-105_79Rpkl--5f84c1c298.html) | `passed` | 0.809 | `True` | `oracle_checks` | `answer_json_native` | 0.952 | 21 | traj, tx |
| [mcp_CCX-vuln-remed-111_u7rGCx](../tasks/csb_org_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-111_u7rGCx--4c569d8e61.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.846 | 13 | traj, tx |
