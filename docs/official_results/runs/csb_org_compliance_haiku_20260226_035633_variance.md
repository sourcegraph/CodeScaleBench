# csb_org_compliance_haiku_20260226_035633_variance

## baseline-local-direct

- Valid tasks: `1`
- Mean reward: `0.356`
- Pass rate: `1.000`
- Scorer families: `unknown (1)`
- Output contracts: `unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-compliance-051](../tasks/csb_org_compliance_haiku_20260226_035633_variance--baseline-local-direct--ccx-compliance-051--eb7ab882bc.html) | `passed` | 0.356 | `True` | `-` | `-` | 0.000 | 44 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.806`
- Pass rate: `1.000`
- Scorer families: `unknown (2), oracle_checks (1)`
- Output contracts: `unknown (2), answer_json_native (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_CCX-compliance-053_fgVrO8](../tasks/csb_org_compliance_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-compliance-053_fgVrO8--9b2365efe8.html) | `passed` | 0.726 | `True` | `oracle_checks` | `answer_json_native` | 0.962 | 26 | traj, tx |
| [mcp_ccx-compliance-051_90WMYT](../tasks/csb_org_compliance_haiku_20260226_035633_variance--mcp-remote-direct--mcp_ccx-compliance-051_90WMYT--70a7eaa492.html) | `passed` | 0.846 | `True` | `-` | `-` | 0.932 | 44 | traj, tx |
| [mcp_ccx-compliance-057-ds_UoO29X](../tasks/csb_org_compliance_haiku_20260226_035633_variance--mcp-remote-direct--mcp_ccx-compliance-057-ds_UoO29X--788cff66c9.html) | `passed` | 0.844 | `True` | `-` | `-` | 0.957 | 23 | traj, tx |
