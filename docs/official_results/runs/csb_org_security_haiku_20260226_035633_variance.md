# csb_org_security_haiku_20260226_035633_variance

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.586`
- Pass rate: `1.000`
- Scorer families: `unknown (1)`
- Output contracts: `unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-012](../tasks/csb_org_security_haiku_20260226_035633_variance--baseline-local-direct--ccx-vuln-remed-012--e7539d99c9.html) | `passed` | 0.586 | `True` | `-` | `-` | 0.000 | 38 | traj, tx |

## mcp-remote-direct

- Valid tasks: `4`
- Mean reward: `0.731`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (2)`
- Output contracts: `answer_json_native (2), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_CCX-vuln-remed-012_6P8wqO](../tasks/csb_org_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-012_6P8wqO--eac0f63a26.html) | `passed` | 0.563 | `True` | `-` | `-` | 0.973 | 37 | traj, tx |
| [mcp_CCX-vuln-remed-013_JtNIGY](../tasks/csb_org_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-013_JtNIGY--d24eec4fc3.html) | `passed` | 0.624 | `True` | `-` | `-` | 0.958 | 24 | traj, tx |
| [mcp_CCX-vuln-remed-105_JZsxbp](../tasks/csb_org_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-105_JZsxbp--b46941ea2f.html) | `passed` | 0.737 | `True` | `oracle_checks` | `answer_json_native` | 0.909 | 22 | traj, tx |
| [mcp_CCX-vuln-remed-111_gpcSkd](../tasks/csb_org_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-111_gpcSkd--eab93f2d57.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.846 | 13 | traj, tx |
