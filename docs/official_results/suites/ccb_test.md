# ccb_test

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_test_haiku_022326](../runs/ccb_test_haiku_022326.md) | `baseline` | 9 | 0.472 | 0.778 |
| [ccb_test_haiku_022326](../runs/ccb_test_haiku_022326.md) | `mcp` | 8 | 0.555 | 0.625 |
| [ccb_test_haiku_20260224_180149](../runs/ccb_test_haiku_20260224_180149.md) | `baseline-local-direct` | 11 | 0.486 | 0.727 |
| [ccb_test_haiku_20260224_180149](../runs/ccb_test_haiku_20260224_180149.md) | `mcp-remote-direct` | 11 | 0.387 | 0.727 |
| [test_haiku_20260223_235732](../runs/test_haiku_20260223_235732.md) | `baseline-local-direct` | 9 | 0.472 | 0.778 |
| [test_haiku_20260223_235732](../runs/test_haiku_20260223_235732.md) | `mcp-remote-direct` | 9 | 0.593 | 0.667 |
| [test_haiku_20260224_011816](../runs/test_haiku_20260224_011816.md) | `mcp-remote-direct` | 11 | 0.262 | 0.455 |

## Tasks

| Run | Config | Task | Status | Reward | MCP Ratio |
|---|---|---|---|---:|---:|
| `ccb_test_haiku_022326` | `baseline` | [kafka-security-review-001](../tasks/ccb_test_haiku_022326--baseline--kafka-security-review-001.md) | `passed` | 0.440 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [llamacpp-context-window-search-001](../tasks/ccb_test_haiku_022326--baseline--llamacpp-context-window-search-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [llamacpp-file-modify-search-001](../tasks/ccb_test_haiku_022326--baseline--llamacpp-file-modify-search-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [openhands-search-file-test-001](../tasks/ccb_test_haiku_022326--baseline--openhands-search-file-test-001.md) | `passed` | 0.400 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [test-coverage-gap-002](../tasks/ccb_test_haiku_022326--baseline--test-coverage-gap-002.md) | `passed` | 0.940 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [test-integration-001](../tasks/ccb_test_haiku_022326--baseline--test-integration-001.md) | `passed` | 1.000 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [test-integration-002](../tasks/ccb_test_haiku_022326--baseline--test-integration-002.md) | `passed` | 0.370 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [test-unitgen-go-001](../tasks/ccb_test_haiku_022326--baseline--test-unitgen-go-001.md) | `passed` | 0.620 | 0.000 |
| `ccb_test_haiku_022326` | `baseline` | [test-unitgen-py-001](../tasks/ccb_test_haiku_022326--baseline--test-unitgen-py-001.md) | `passed` | 0.480 | 0.000 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_kafka-security-review-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_kafka-security-review-001.md) | `passed` | 0.440 | 0.857 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_llamacpp-context-window-search-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_llamacpp-context-window-search-001.md) | `failed` | 0.000 | 1.000 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_llamacpp-file-modify-search-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_llamacpp-file-modify-search-001.md) | `failed` | 0.000 | 0.036 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_openhands-search-file-test-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_openhands-search-file-test-001.md) | `failed` | 0.000 | 0.119 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_test-coverage-gap-002](../tasks/ccb_test_haiku_022326--mcp--sgonly_test-coverage-gap-002.md) | `passed` | 1.000 | 0.964 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_test-integration-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_test-integration-001.md) | `passed` | 1.000 | 0.567 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_test-unitgen-go-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_test-unitgen-go-001.md) | `passed` | 1.000 | 0.312 |
| `ccb_test_haiku_022326` | `mcp` | [sgonly_test-unitgen-py-001](../tasks/ccb_test_haiku_022326--mcp--sgonly_test-unitgen-py-001.md) | `passed` | 1.000 | 0.333 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [aspnetcore-code-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--aspnetcore-code-review-001.md) | `passed` | 0.550 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [calcom-code-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--calcom-code-review-001.md) | `passed` | 0.650 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [curl-security-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--curl-security-review-001.md) | `passed` | 0.670 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [envoy-code-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--envoy-code-review-001.md) | `passed` | 0.700 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [ghost-code-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--ghost-code-review-001.md) | `passed` | 0.800 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [numpy-array-sum-perf-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--numpy-array-sum-perf-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [pandas-groupby-perf-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--pandas-groupby-perf-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [sklearn-kmeans-perf-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--sklearn-kmeans-perf-001.md) | `failed` | 0.000 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [terraform-code-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--terraform-code-review-001.md) | `passed` | 0.670 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [test-coverage-gap-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--test-coverage-gap-001.md) | `passed` | 0.860 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `baseline-local-direct` | [vscode-code-review-001](../tasks/ccb_test_haiku_20260224_180149--baseline-local-direct--vscode-code-review-001.md) | `passed` | 0.450 | 0.000 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_aspnetcore-code-review-001_f61mYC](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_aspnetcore-code-review-001_f61mYC.md) | `passed` | 0.460 | 0.250 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_calcom-code-review-001_CKPuxH](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_calcom-code-review-001_CKPuxH.md) | `passed` | 0.390 | 0.333 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_curl-security-review-001_JZZHPF](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_curl-security-review-001_JZZHPF.md) | `passed` | 0.520 | 0.812 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_envoy-code-review-001_IMTReM](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_envoy-code-review-001_IMTReM.md) | `passed` | 0.610 | 0.600 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_ghost-code-review-001_Fus02d](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_ghost-code-review-001_Fus02d.md) | `passed` | 0.710 | 0.750 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_numpy-array-sum-perf-001_M9DWzC](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_numpy-array-sum-perf-001_M9DWzC.md) | `failed` | 0.000 | 0.317 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_pandas-groupby-perf-001_Tfai7M](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_pandas-groupby-perf-001_Tfai7M.md) | `failed` | 0.000 | 0.122 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_sklearn-kmeans-perf-001_8vdgQ3](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_sklearn-kmeans-perf-001_8vdgQ3.md) | `failed` | 0.000 | 0.209 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_terraform-code-review-001_CUyETT](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_terraform-code-review-001_CUyETT.md) | `passed` | 0.390 | 0.667 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_test-coverage-gap-001_iGwMog](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_test-coverage-gap-001_iGwMog.md) | `passed` | 0.880 | 0.914 |
| `ccb_test_haiku_20260224_180149` | `mcp-remote-direct` | [mcp_vscode-code-review-001_YRYOVM](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_vscode-code-review-001_YRYOVM.md) | `passed` | 0.300 | 0.700 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [kafka-security-review-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--kafka-security-review-001.md) | `passed` | 0.440 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [llamacpp-context-window-search-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--llamacpp-context-window-search-001.md) | `failed` | 0.000 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [llamacpp-file-modify-search-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--llamacpp-file-modify-search-001.md) | `failed` | 0.000 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [openhands-search-file-test-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--openhands-search-file-test-001.md) | `passed` | 0.400 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [test-coverage-gap-002](../tasks/test_haiku_20260223_235732--baseline-local-direct--test-coverage-gap-002.md) | `passed` | 0.940 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [test-integration-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--test-integration-001.md) | `passed` | 1.000 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [test-integration-002](../tasks/test_haiku_20260223_235732--baseline-local-direct--test-integration-002.md) | `passed` | 0.370 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [test-unitgen-go-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--test-unitgen-go-001.md) | `passed` | 0.620 | 0.000 |
| `test_haiku_20260223_235732` | `baseline-local-direct` | [test-unitgen-py-001](../tasks/test_haiku_20260223_235732--baseline-local-direct--test-unitgen-py-001.md) | `passed` | 0.480 | 0.000 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_kafka-security-review-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_kafka-security-review-001.md) | `passed` | 0.440 | 0.857 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_llamacpp-context-window-search-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_llamacpp-context-window-search-001.md) | `failed` | 0.000 | 1.000 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_llamacpp-file-modify-search-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_llamacpp-file-modify-search-001.md) | `failed` | 0.000 | 0.036 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_openhands-search-file-test-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_openhands-search-file-test-001.md) | `failed` | 0.000 | 0.119 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_test-coverage-gap-002](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_test-coverage-gap-002.md) | `passed` | 1.000 | 0.964 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_test-integration-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_test-integration-001.md) | `passed` | 1.000 | 0.567 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_test-integration-002](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_test-integration-002.md) | `passed` | 0.900 | 0.778 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_test-unitgen-go-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_test-unitgen-go-001.md) | `passed` | 1.000 | 0.312 |
| `test_haiku_20260223_235732` | `mcp-remote-direct` | [sgonly_test-unitgen-py-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_test-unitgen-py-001.md) | `passed` | 1.000 | 0.333 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_aspnetcore-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_aspnetcore-code-review-001.md) | `passed` | 0.460 | 0.600 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_calcom-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_calcom-code-review-001.md) | `failed` | 0.000 | - |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_curl-security-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_curl-security-review-001.md) | `failed` | 0.000 | - |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_envoy-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_envoy-code-review-001.md) | `passed` | 0.500 | 0.722 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_ghost-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_ghost-code-review-001.md) | `passed` | 0.620 | 0.870 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_numpy-array-sum-perf-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_numpy-array-sum-perf-001.md) | `failed` | 0.000 | - |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_pandas-groupby-perf-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_pandas-groupby-perf-001.md) | `failed` | 0.000 | 0.594 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_sklearn-kmeans-perf-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_sklearn-kmeans-perf-001.md) | `failed` | 0.000 | 0.308 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_terraform-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_terraform-code-review-001.md) | `failed` | 0.000 | - |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_test-coverage-gap-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_test-coverage-gap-001.md) | `passed` | 0.940 | 0.966 |
| `test_haiku_20260224_011816` | `mcp-remote-direct` | [sgonly_vscode-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_vscode-code-review-001.md) | `passed` | 0.360 | 0.875 |
