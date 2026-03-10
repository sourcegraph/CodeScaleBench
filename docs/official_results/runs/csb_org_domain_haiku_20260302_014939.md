# csb_org_domain_haiku_20260302_014939

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.080`
- Pass rate: `0.500`
- Scorer families: `oracle_checks (1), unknown (1)`
- Output contracts: `answer_json_native (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-domain-155](../tasks/csb_org_domain_haiku_20260302_014939--baseline-local-direct--ccx-domain-155--3ce4fb6f27.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.000 | 33 | traj, tx |
| [ccx-domain-154](../tasks/csb_org_domain_haiku_20260302_014939--baseline-local-direct--ccx-domain-154--f5c1d42e6b.html) | `passed` | 0.160 | `True` | `-` | `-` | 0.000 | 49 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.000`
- Pass rate: `0.000`
- Scorer families: `oracle_checks (1), unknown (1)`
- Output contracts: `answer_json_native (1), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-domain-154_n9wxac](../tasks/csb_org_domain_haiku_20260302_014939--mcp-remote-direct--mcp_ccx-domain-154_n9wxac--acc68123fc.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.967 | 30 | traj, tx |
| [mcp_ccx-domain-155_uyskpn](../tasks/csb_org_domain_haiku_20260302_014939--mcp-remote-direct--mcp_ccx-domain-155_uyskpn--29e3bcf7c1.html) | `failed` | 0.000 | `False` | `oracle_checks` | `answer_json_native` | 0.970 | 33 | traj, tx |
