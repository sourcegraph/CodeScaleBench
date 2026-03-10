# csb_org_security_haiku_022126

## baseline-local-artifact

- Valid tasks: `2`
- Mean reward: `0.500`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (1), unknown (1)`
- Output contracts: `answer_json_native (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-011](../tasks/csb_org_security_haiku_022126--baseline--ccx-vuln-remed-011--e88de5bdc5.html) | `passed` | 0.750 | `True` | `-` | `-` | 0.000 | 23 | traj, tx |
| [ccx-vuln-remed-014](../tasks/csb_org_security_haiku_022126--baseline--ccx-vuln-remed-014--a103e3bc6a.html) | `passed` | 0.250 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 87 | traj, tx |

## mcp-remote-artifact

- Valid tasks: `2`
- Mean reward: `0.821`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (1), unknown (1)`
- Output contracts: `answer_json_native (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-011](../tasks/csb_org_security_haiku_022126--mcp--ccx-vuln-remed-011--c00bb8282c.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.971 | 35 | traj, tx |
| [ccx-vuln-remed-014](../tasks/csb_org_security_haiku_022126--mcp--ccx-vuln-remed-014--2ce84aa850.html) | `passed` | 0.643 | `True` | `oracle_checks` | `answer_json_native` | 0.976 | 41 | traj, tx |
