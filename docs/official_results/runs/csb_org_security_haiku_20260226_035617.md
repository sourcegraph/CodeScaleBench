# csb_org_security_haiku_20260226_035617

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.433`
- Pass rate: `1.000`
- Scorer families: `unknown (1)`
- Output contracts: `unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-012](../tasks/csb_org_security_haiku_20260226_035617--baseline-local-direct--ccx-vuln-remed-012--8274abd977.html) | `passed` | 0.433 | `True` | `-` | `-` | 0.000 | 27 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.744`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (2)`
- Output contracts: `answer_json_native (2), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_CCX-vuln-remed-012_lrLTYc](../tasks/csb_org_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-012_lrLTYc--6ec5faf763.html) | `passed` | 0.463 | `True` | `-` | `-` | 0.923 | 26 | traj, tx |
| [mcp_CCX-vuln-remed-013_WOkHxn](../tasks/csb_org_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-013_WOkHxn--bab70a3b31.html) | `passed` | 0.705 | `True` | `-` | `-` | 0.926 | 27 | traj, tx |
| [mcp_CCX-vuln-remed-105_1RoC5v](../tasks/csb_org_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-105_1RoC5v--3482191c55.html) | `passed` | 0.809 | `True` | `oracle_checks` | `answer_json_native` | 0.958 | 24 | traj, tx |
| [mcp_CCX-vuln-remed-111_7hdRBX](../tasks/csb_org_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-111_7hdRBX--39a18b2d85.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.966 | 29 | traj, tx |
