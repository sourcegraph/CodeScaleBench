# csb_org_security_haiku_20260228_012337

## baseline-local-direct

- Valid tasks: `7`
- Mean reward: `0.420`
- Pass rate: `0.714`
- Scorer families: `oracle_checks (4), unknown (3)`
- Output contracts: `answer_json_native (4), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-vuln-remed-011](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-011--27a5610d74.html) | `failed` | 0.000 | `None` | `-` | `-` | 0.000 | 7 | traj, tx |
| [ccx-vuln-remed-014](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-014--972b27d5d4.html) | `failed` | 0.000 | `None` | `oracle_checks` | `answer_json_native` | 0.000 | 48 | traj, tx |
| [ccx-vuln-remed-012](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-012--f7551eeab7.html) | `passed` | 0.494 | `None` | `-` | `-` | 0.000 | 42 | traj, tx |
| [ccx-vuln-remed-013](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-013--433ee7d657.html) | `passed` | 0.056 | `None` | `-` | `-` | 0.000 | 31 | traj, tx |
| [ccx-vuln-remed-105](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-105--e689b5bfc5.html) | `passed` | 0.587 | `None` | `oracle_checks` | `answer_json_native` | 0.000 | 33 | traj, tx |
| [ccx-vuln-remed-111](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-111--c4b698a6c9.html) | `passed` | 1.000 | `None` | `oracle_checks` | `answer_json_native` | 0.000 | 40 | traj, tx |
| [ccx-vuln-remed-126](../tasks/csb_org_security_haiku_20260228_012337--baseline-local-direct--ccx-vuln-remed-126--227122f8a3.html) | `passed` | 0.806 | `None` | `oracle_checks` | `answer_json_native` | 0.000 | 48 | traj, tx |

## mcp-remote-direct

- Valid tasks: `5`
- Mean reward: `0.690`
- Pass rate: `1.000`
- Scorer families: `unknown (3), oracle_checks (2)`
- Output contracts: `unknown (3), answer_json_native (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_CCX-vuln-remed-012_KDiwHr](../tasks/csb_org_security_haiku_20260228_012337--mcp-remote-direct--mcp_CCX-vuln-remed-012_KDiwHr--47c452305c.html) | `passed` | 0.500 | `None` | `-` | `-` | 0.939 | 33 | traj, tx |
| [mcp_CCX-vuln-remed-013_exPwzs](../tasks/csb_org_security_haiku_20260228_012337--mcp-remote-direct--mcp_CCX-vuln-remed-013_exPwzs--cc880eb6f4.html) | `passed` | 0.742 | `None` | `-` | `-` | 0.938 | 32 | traj, tx |
| [mcp_CCX-vuln-remed-105_mBXXD3](../tasks/csb_org_security_haiku_20260228_012337--mcp-remote-direct--mcp_CCX-vuln-remed-105_mBXXD3--b8673f5a99.html) | `passed` | 0.709 | `None` | `oracle_checks` | `answer_json_native` | 0.917 | 24 | traj, tx |
| [mcp_ccx-vuln-remed-011_pzmpsW](../tasks/csb_org_security_haiku_20260228_012337--mcp-remote-direct--mcp_ccx-vuln-remed-011_pzmpsW--ecbfd452c3.html) | `passed` | 1.000 | `None` | `-` | `-` | 0.933 | 15 | traj, tx |
| [mcp_ccx-vuln-remed-014_mOWOl9](../tasks/csb_org_security_haiku_20260228_012337--mcp-remote-direct--mcp_ccx-vuln-remed-014_mOWOl9--3fe53ab087.html) | `passed` | 0.500 | `None` | `oracle_checks` | `answer_json_native` | 0.971 | 35 | traj, tx |
