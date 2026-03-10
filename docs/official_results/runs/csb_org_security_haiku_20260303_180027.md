# csb_org_security_haiku_20260303_180027

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.000`
- Pass rate: `0.000`
- Scorer families: `oracle_checks (1)`
- Output contracts: `answer_json_native (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-014](../tasks/csb_org_security_haiku_20260303_180027--baseline-local-direct--ccx-vuln-remed-014--be0deb1553.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | - | - | traj, tx |

## mcp-remote-direct

- Valid tasks: `1`
- Mean reward: `0.667`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (1)`
- Output contracts: `answer_json_native (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-vuln-remed-014_hdn8z1](../tasks/csb_org_security_haiku_20260303_180027--mcp-remote-direct--mcp_ccx-vuln-remed-014_hdn8z1--a8e148f77c.html) | `passed` | 0.667 | `True` | `oracle_checks` | `answer_json_native` | 0.957 | 23 | traj, tx |
