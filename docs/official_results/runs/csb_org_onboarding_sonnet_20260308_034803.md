# csb_org_onboarding_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.853`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (3), semantic_retrieval_qa (2)`
- Output contracts: `answer_json_native (3), solution_json (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-onboard-103](../tasks/csb_org_onboarding_sonnet_20260308_034803--baseline-local-direct--ccx-onboard-103--280ea94800.html) | `passed` | 0.657 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 15 | traj, tx |
| [ccx-onboard-109](../tasks/csb_org_onboarding_sonnet_20260308_034803--baseline-local-direct--ccx-onboard-109--3ee87039e7.html) | `passed` | 0.857 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 25 | traj, tx |
| [ccx-onboard-134](../tasks/csb_org_onboarding_sonnet_20260308_034803--baseline-local-direct--ccx-onboard-134--d42873db30.html) | `passed` | 0.750 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 16 | traj, tx |
| [ccx-onboard-search-207](../tasks/csb_org_onboarding_sonnet_20260308_034803--baseline-local-direct--ccx-onboard-search-207--37a85e1fa6.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.000 | 7 | traj, tx |
| [ccx-onboard-search-210](../tasks/csb_org_onboarding_sonnet_20260308_034803--baseline-local-direct--ccx-onboard-search-210--b97c9b9c1c.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.000 | 8 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.764`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (3)`
- Output contracts: `answer_json_native (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-onboard-103_mt1ker](../tasks/csb_org_onboarding_sonnet_20260308_034803--mcp-remote-direct--mcp_ccx-onboard-103_mt1ker--2cf7773a02.html) | `passed` | 0.685 | `True` | `oracle_checks` | `answer_json_native` | 0.556 | 9 | traj, tx |
| [mcp_ccx-onboard-109_ud8tsw](../tasks/csb_org_onboarding_sonnet_20260308_034803--mcp-remote-direct--mcp_ccx-onboard-109_ud8tsw--a1b2074af2.html) | `passed` | 0.930 | `True` | `oracle_checks` | `answer_json_native` | 0.556 | 9 | traj, tx |
| [mcp_ccx-onboard-134_kme9ga](../tasks/csb_org_onboarding_sonnet_20260308_034803--mcp-remote-direct--mcp_ccx-onboard-134_kme9ga--40cf04baaf.html) | `passed` | 0.679 | `True` | `oracle_checks` | `answer_json_native` | 0.600 | 10 | traj, tx |
