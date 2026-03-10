# csb_sdlc_test_haiku_20260224_180149

## baseline-local-direct

- Valid tasks: `11`
- Mean reward: `0.486`
- Pass rate: `0.727`
- Scorer families: `f1_hybrid (6), unknown (4), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (7), unknown (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [numpy-array-sum-perf-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--numpy-array-sum-perf-001--765d5ee1e1.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 107 | traj, tx |
| [pandas-groupby-perf-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--pandas-groupby-perf-001--0a0ef28b8a.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 94 | traj, tx |
| [sklearn-kmeans-perf-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--sklearn-kmeans-perf-001--cb9bd8e89b.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 41 | traj, tx |
| [aspnetcore-code-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--aspnetcore-code-review-001--b1771b432d.html) | `passed` | 0.550 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 5 | traj, tx |
| [calcom-code-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--calcom-code-review-001--4bbaee43e1.html) | `passed` | 0.650 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [curl-security-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--curl-security-review-001--6868394a07.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.000 | 17 | traj, tx |
| [envoy-code-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--envoy-code-review-001--cb338dd27d.html) | `passed` | 0.700 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [ghost-code-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--ghost-code-review-001--661fa17b13.html) | `passed` | 0.800 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [terraform-code-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--terraform-code-review-001--f10e2c7fd5.html) | `passed` | 0.670 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 7 | traj, tx |
| [test-coverage-gap-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--test-coverage-gap-001--a894241a51.html) | `passed` | 0.860 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 35 | traj, tx |
| [vscode-code-review-001](../tasks/csb_sdlc_test_haiku_20260224_180149--baseline-local-direct--vscode-code-review-001--8a2eb643c9.html) | `passed` | 0.450 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 12 | traj, tx |

## mcp-remote-direct

- Valid tasks: `11`
- Mean reward: `0.387`
- Pass rate: `0.727`
- Scorer families: `f1_hybrid (6), unknown (4), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (7), unknown (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_numpy-array-sum-perf-001_M9DWzC](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_numpy-array-sum-perf-001_M9DWzC--8379cbae9c.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.317 | 41 | traj, tx |
| [mcp_pandas-groupby-perf-001_Tfai7M](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_pandas-groupby-perf-001_Tfai7M--aaf72cacc3.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.122 | 90 | traj, tx |
| [mcp_sklearn-kmeans-perf-001_8vdgQ3](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_sklearn-kmeans-perf-001_8vdgQ3--fd3243b36c.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.209 | 43 | traj, tx |
| [mcp_aspnetcore-code-review-001_f61mYC](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_aspnetcore-code-review-001_f61mYC--151cc585d6.html) | `passed` | 0.460 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.250 | 8 | traj, tx |
| [mcp_calcom-code-review-001_CKPuxH](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_calcom-code-review-001_CKPuxH--cf05a21b9b.html) | `passed` | 0.390 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.333 | 9 | traj, tx |
| [mcp_curl-security-review-001_JZZHPF](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_curl-security-review-001_JZZHPF--f121523d39.html) | `passed` | 0.520 | `True` | `-` | `-` | 0.812 | 48 | traj, tx |
| [mcp_envoy-code-review-001_IMTReM](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_envoy-code-review-001_IMTReM--b2434536a5.html) | `passed` | 0.610 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.600 | 15 | traj, tx |
| [mcp_ghost-code-review-001_Fus02d](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_ghost-code-review-001_Fus02d--97b1333084.html) | `passed` | 0.710 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.750 | 4 | traj, tx |
| [mcp_terraform-code-review-001_CUyETT](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_terraform-code-review-001_CUyETT--084456eab6.html) | `passed` | 0.390 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.667 | 6 | traj, tx |
| [mcp_test-coverage-gap-001_iGwMog](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_test-coverage-gap-001_iGwMog--7e35366844.html) | `passed` | 0.880 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.914 | 35 | traj, tx |
| [mcp_vscode-code-review-001_YRYOVM](../tasks/csb_sdlc_test_haiku_20260224_180149--mcp-remote-direct--mcp_vscode-code-review-001_YRYOVM--0fc664074c.html) | `passed` | 0.300 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.700 | 10 | traj, tx |
