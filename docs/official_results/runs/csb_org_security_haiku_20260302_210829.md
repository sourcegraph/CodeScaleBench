# csb_org_security_haiku_20260302_210829

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.000`
- Pass rate: `0.000`
- Scorer families: `unknown (1)`
- Output contracts: `unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-166](../tasks/csb_org_security_haiku_20260302_210829--baseline-local-direct--ccx-vuln-remed-166--37551d61ee.html) | `failed` | 0.000 | `None` | `-` | `-` | - | - | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.158`
- Pass rate: `0.667`
- Scorer families: `unknown (2), oracle_checks (1)`
- Output contracts: `unknown (2), answer_json_native (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-vuln-remed-161_ki0hwa](../tasks/csb_org_security_haiku_20260302_210829--mcp-remote-direct--mcp_ccx-vuln-remed-161_ki0hwa--fad23e933e.html) | `failed` | 0.000 | `None` | `oracle_checks` | `answer_json_native` | 1.000 | 1 | traj, tx |
| [mcp_ccx-vuln-remed-164_ortnn6](../tasks/csb_org_security_haiku_20260302_210829--mcp-remote-direct--mcp_ccx-vuln-remed-164_ortnn6--aa2475bc63.html) | `passed` | 0.111 | `None` | `-` | `-` | 0.929 | 28 | traj, tx |
| [mcp_ccx-vuln-remed-166_vjh9u3](../tasks/csb_org_security_haiku_20260302_210829--mcp-remote-direct--mcp_ccx-vuln-remed-166_vjh9u3--b1ca4e74cc.html) | `passed` | 0.364 | `None` | `-` | `-` | 0.917 | 12 | traj, tx |
