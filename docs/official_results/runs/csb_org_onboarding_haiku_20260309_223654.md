# csb_org_onboarding_haiku_20260309_223654

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.767`
- Pass rate: `0.667`
- Scorer families: `semantic_retrieval_qa (3)`
- Output contracts: `solution_json (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-onboard-search-210](../tasks/csb_org_onboarding_haiku_20260309_223654--baseline-local-direct--ccx-onboard-search-210--bab909fc1a.html) | `failed` | 0.300 | `False` | `semantic_retrieval_qa` | `solution_json` | 0.000 | 13 | traj, tx |
| [ccx-onboard-search-207](../tasks/csb_org_onboarding_haiku_20260309_223654--baseline-local-direct--ccx-onboard-search-207--17dd2ae6e4.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.444 | 9 | traj, tx |
| [ccx-onboard-search-208](../tasks/csb_org_onboarding_haiku_20260309_223654--baseline-local-direct--ccx-onboard-search-208--46a11bde4a.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.000 | 10 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `1.000`
- Pass rate: `1.000`
- Scorer families: `semantic_retrieval_qa (3)`
- Output contracts: `solution_json (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_ccx-onboard-search-207_gqu7wa](../tasks/csb_org_onboarding_haiku_20260309_223654--mcp-remote-direct--mcp_ccx-onboard-search-207_gqu7wa--baf9ab27de.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.800 | 10 | traj, tx |
| [mcp_ccx-onboard-search-208_wh7gt5](../tasks/csb_org_onboarding_haiku_20260309_223654--mcp-remote-direct--mcp_ccx-onboard-search-208_wh7gt5--1fef441289.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.667 | 6 | traj, tx |
| [mcp_ccx-onboard-search-210_hesjp4](../tasks/csb_org_onboarding_haiku_20260309_223654--mcp-remote-direct--mcp_ccx-onboard-search-210_hesjp4--a3c125ebe4.html) | `passed` | 1.000 | `True` | `semantic_retrieval_qa` | `solution_json` | 0.800 | 10 | traj, tx |
