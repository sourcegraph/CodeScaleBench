# csb_org_security_haiku_20260226_035628_variance

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.367`
- Pass rate: `1.000`
- Scorer families: `unknown (1)`
- Output contracts: `unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-012](../tasks/csb_org_security_haiku_20260226_035628_variance--baseline-local-direct--ccx-vuln-remed-012--e1d4db7a05.html) | `passed` | 0.367 | `None` | `-` | `-` | 0.000 | 20 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.767`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (2)`
- Output contracts: `answer_json_native (2), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_CCX-vuln-remed-012_6fFmnM](../tasks/csb_org_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-012_6fFmnM--aa1328ca4d.html) | `passed` | 0.533 | `None` | `-` | `-` | 0.909 | 22 | traj, tx |
| [mcp_CCX-vuln-remed-013_LoBHLI](../tasks/csb_org_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-013_LoBHLI--ee68154ea2.html) | `passed` | 0.749 | `None` | `-` | `-` | 0.963 | 27 | traj, tx |
| [mcp_CCX-vuln-remed-105_aQMP88](../tasks/csb_org_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-105_aQMP88--acee4d768c.html) | `passed` | 0.784 | `None` | `oracle_checks` | `answer_json_native` | 0.971 | 35 | traj, tx |
| [mcp_CCX-vuln-remed-111_AFyYzp](../tasks/csb_org_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-111_AFyYzp--7229a13294.html) | `passed` | 1.000 | `None` | `oracle_checks` | `answer_json_native` | 0.909 | 11 | traj, tx |
