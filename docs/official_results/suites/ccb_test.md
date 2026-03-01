# ccb_test

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_test_haiku_20260224_180149](../runs/ccb_test_haiku_20260224_180149.md) | `mcp-remote-direct` | 11 | 0.387 | 0.727 |
| [ccb_test_haiku_20260228_124521](../runs/ccb_test_haiku_20260228_124521.md) | `mcp-remote-direct` | 4 | 0.985 | 1.000 |
| [test_haiku_20260223_235732](../runs/test_haiku_20260223_235732.md) | `mcp-remote-direct` | 2 | 0.000 | 0.000 |
| [test_haiku_20260224_011816](../runs/test_haiku_20260224_011816.md) | `mcp-remote-direct` | 7 | 0.277 | 0.571 |
| [test_haiku_20260301_071232](../runs/test_haiku_20260301_071232.md) | `baseline-local-direct` | 16 | 0.560 | 0.812 |
| [test_haiku_20260301_071232](../runs/test_haiku_20260301_071232.md) | `mcp-remote-direct` | 8 | 0.780 | 1.000 |
| [test_haiku_20260301_192246](../runs/test_haiku_20260301_192246.md) | `baseline-local-direct` | 4 | 0.128 | 0.250 |
| [test_haiku_20260301_192246](../runs/test_haiku_20260301_192246.md) | `mcp-remote-direct` | 3 | 0.000 | 0.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [aspnetcore-code-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--aspnetcore-code-review-001.html) | [source](../../../benchmarks/ccb_test/aspnetcore-code-review-001) | `baseline-local-direct` | `passed` | 0.570 | 4 | 0.000 |
| [mcp_aspnetcore-code-review-001_f61mYC](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_aspnetcore-code-review-001_f61mYC.html) | [source](../../../benchmarks/ccb_test/aspnetcore-code-review-001) | `mcp-remote-direct` | `passed` | 0.460 | 3 | 0.250 |
| [sgonly_aspnetcore-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_aspnetcore-code-review-001.html) | [source](../../../benchmarks/ccb_test/aspnetcore-code-review-001) | `mcp-remote-direct` | `passed` | 0.460 | 3 | 0.600 |
| [calcom-code-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--calcom-code-review-001.html) | [source](../../../benchmarks/ccb_test/calcom-code-review-001) | `baseline-local-direct` | `passed` | 0.750 | 4 | 0.000 |
| [mcp_calcom-code-review-001_CKPuxH](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_calcom-code-review-001_CKPuxH.html) | [source](../../../benchmarks/ccb_test/calcom-code-review-001) | `mcp-remote-direct` | `passed` | 0.390 | 3 | 0.333 |
| [sgonly_calcom-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_calcom-code-review-001.html) | [source](../../../benchmarks/ccb_test/calcom-code-review-001) | `mcp-remote-direct` | `failed` | 0.000 | 3 | - |
| [curl-security-review-001](../tasks/test_haiku_20260301_192246--baseline-local-direct--curl-security-review-001.html) | [source](../../../benchmarks/ccb_test/curl-security-review-001) | `baseline-local-direct` | `passed` | 0.510 | 6 | 0.000 |
| [mcp_curl-security-review-001_JZZHPF](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_curl-security-review-001_JZZHPF.html) | [source](../../../benchmarks/ccb_test/curl-security-review-001) | `mcp-remote-direct` | `passed` | 0.520 | 2 | 0.812 |
| [sgonly_curl-security-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_curl-security-review-001.html) | [source](../../../benchmarks/ccb_test/curl-security-review-001) | `mcp-remote-direct` | `failed` | 0.000 | 2 | - |
| [envoy-code-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--envoy-code-review-001.html) | [source](../../../benchmarks/ccb_test/envoy-code-review-001) | `baseline-local-direct` | `passed` | 0.650 | 4 | 0.000 |
| [mcp_envoy-code-review-001_IMTReM](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_envoy-code-review-001_IMTReM.html) | [source](../../../benchmarks/ccb_test/envoy-code-review-001) | `mcp-remote-direct` | `passed` | 0.610 | 3 | 0.600 |
| [sgonly_envoy-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_envoy-code-review-001.html) | [source](../../../benchmarks/ccb_test/envoy-code-review-001) | `mcp-remote-direct` | `passed` | 0.500 | 3 | 0.722 |
| [ghost-code-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--ghost-code-review-001.html) | [source](../../../benchmarks/ccb_test/ghost-code-review-001) | `baseline-local-direct` | `passed` | 0.800 | 4 | 0.000 |
| [mcp_ghost-code-review-001_Fus02d](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_ghost-code-review-001_Fus02d.html) | [source](../../../benchmarks/ccb_test/ghost-code-review-001) | `mcp-remote-direct` | `passed` | 0.710 | 3 | 0.750 |
| [sgonly_ghost-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_ghost-code-review-001.html) | [source](../../../benchmarks/ccb_test/ghost-code-review-001) | `mcp-remote-direct` | `passed` | 0.620 | 3 | 0.870 |
| [kafka-security-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--kafka-security-review-001.html) | [source](../../../benchmarks/ccb_test/kafka-security-review-001) | `baseline-local-direct` | `passed` | 0.440 | 3 | 0.000 |
| [sgonly_kafka-security-review-001](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_kafka-security-review-001.html) | [source](../../../benchmarks/ccb_test/kafka-security-review-001) | `mcp-remote-direct` | `passed` | 0.290 | 3 | 0.800 |
| [llamacpp-context-window-search-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--llamacpp-context-window-search-001.html) | — | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [sgonly_llamacpp-context-window-search-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_llamacpp-context-window-search-001.html) | — | `mcp-remote-direct` | `failed` | 0.000 | 1 | 1.000 |
| [llamacpp-file-modify-search-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--llamacpp-file-modify-search-001.html) | — | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [sgonly_llamacpp-file-modify-search-001](../tasks/test_haiku_20260223_235732--mcp-remote-direct--sgonly_llamacpp-file-modify-search-001.html) | — | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.036 |
| [numpy-array-sum-perf-001](../tasks/test_haiku_20260301_192246--baseline-local-direct--numpy-array-sum-perf-001.html) | [source](../../../benchmarks/ccb_test/numpy-array-sum-perf-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [mcp_numpy-array-sum-perf-001_M9DWzC](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_numpy-array-sum-perf-001_M9DWzC.html) | [source](../../../benchmarks/ccb_test/numpy-array-sum-perf-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.317 |
| [sgonly_numpy-array-sum-perf-001](../tasks/test_haiku_20260301_192246--mcp-remote-direct--sgonly_numpy-array-sum-perf-001.html) | [source](../../../benchmarks/ccb_test/numpy-array-sum-perf-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.404 |
| [openhands-search-file-test-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--openhands-search-file-test-001.html) | [source](../../../benchmarks/ccb_test/openhands-search-file-test-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [sgonly_openhands-search-file-test-001](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_openhands-search-file-test-001.html) | [source](../../../benchmarks/ccb_test/openhands-search-file-test-001) | `mcp-remote-direct` | `passed` | 0.200 | 5 | 0.269 |
| [pandas-groupby-perf-001](../tasks/test_haiku_20260301_192246--baseline-local-direct--pandas-groupby-perf-001.html) | [source](../../../benchmarks/ccb_test/pandas-groupby-perf-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [mcp_pandas-groupby-perf-001_Tfai7M](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_pandas-groupby-perf-001_Tfai7M.html) | [source](../../../benchmarks/ccb_test/pandas-groupby-perf-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.122 |
| [sgonly_pandas-groupby-perf-001](../tasks/test_haiku_20260301_192246--mcp-remote-direct--sgonly_pandas-groupby-perf-001.html) | [source](../../../benchmarks/ccb_test/pandas-groupby-perf-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.269 |
| [sklearn-kmeans-perf-001](../tasks/test_haiku_20260301_192246--baseline-local-direct--sklearn-kmeans-perf-001.html) | [source](../../../benchmarks/ccb_test/sklearn-kmeans-perf-001) | `baseline-local-direct` | `failed` | 0.000 | 3 | 0.000 |
| [mcp_sklearn-kmeans-perf-001_8vdgQ3](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_sklearn-kmeans-perf-001_8vdgQ3.html) | [source](../../../benchmarks/ccb_test/sklearn-kmeans-perf-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.209 |
| [sgonly_sklearn-kmeans-perf-001](../tasks/test_haiku_20260301_192246--mcp-remote-direct--sgonly_sklearn-kmeans-perf-001.html) | [source](../../../benchmarks/ccb_test/sklearn-kmeans-perf-001) | `mcp-remote-direct` | `failed` | 0.000 | 4 | 0.250 |
| [terraform-code-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--terraform-code-review-001.html) | [source](../../../benchmarks/ccb_test/terraform-code-review-001) | `baseline-local-direct` | `passed` | 0.570 | 4 | 0.000 |
| [mcp_terraform-code-review-001_CUyETT](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_terraform-code-review-001_CUyETT.html) | [source](../../../benchmarks/ccb_test/terraform-code-review-001) | `mcp-remote-direct` | `passed` | 0.390 | 3 | 0.667 |
| [sgonly_terraform-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_terraform-code-review-001.html) | [source](../../../benchmarks/ccb_test/terraform-code-review-001) | `mcp-remote-direct` | `failed` | 0.000 | 3 | - |
| [test-coverage-gap-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--test-coverage-gap-001.html) | [source](../../../benchmarks/ccb_test/test-coverage-gap-001) | `baseline-local-direct` | `passed` | 0.860 | 4 | 0.000 |
| [mcp_test-coverage-gap-001_iGwMog](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_test-coverage-gap-001_iGwMog.html) | [source](../../../benchmarks/ccb_test/test-coverage-gap-001) | `mcp-remote-direct` | `passed` | 0.880 | 5 | 0.914 |
| [sgonly_test-coverage-gap-001](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_test-coverage-gap-001.html) | [source](../../../benchmarks/ccb_test/test-coverage-gap-001) | `mcp-remote-direct` | `passed` | 0.860 | 5 | 0.880 |
| [test-coverage-gap-002](../tasks/test_haiku_20260301_071232--baseline-local-direct--test-coverage-gap-002.html) | [source](../../../benchmarks/ccb_test/test-coverage-gap-002) | `baseline-local-direct` | `passed` | 0.940 | 3 | 0.000 |
| [mcp_test-coverage-gap-002_ZAFk7l](../tasks/ccb_test_haiku_20260228_124521--mcp-remote-direct--mcp_test-coverage-gap-002_ZAFk7l.html) | [source](../../../benchmarks/ccb_test/test-coverage-gap-002) | `mcp-remote-direct` | `passed` | 0.940 | 4 | 0.909 |
| [sgonly_test-coverage-gap-002](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_test-coverage-gap-002.html) | [source](../../../benchmarks/ccb_test/test-coverage-gap-002) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.914 |
| [test-integration-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--test-integration-001.html) | [source](../../../benchmarks/ccb_test/test-integration-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_test-integration-001_lpj5Fx](../tasks/ccb_test_haiku_20260228_124521--mcp-remote-direct--mcp_test-integration-001_lpj5Fx.html) | [source](../../../benchmarks/ccb_test/test-integration-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.528 |
| [sgonly_test-integration-001](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_test-integration-001.html) | [source](../../../benchmarks/ccb_test/test-integration-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.568 |
| [test-integration-002](../tasks/test_haiku_20260301_071232--baseline-local-direct--test-integration-002.html) | [source](../../../benchmarks/ccb_test/test-integration-002) | `baseline-local-direct` | `passed` | 0.370 | 4 | 0.000 |
| [sgonly_test-integration-002](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_test-integration-002.html) | [source](../../../benchmarks/ccb_test/test-integration-002) | `mcp-remote-direct` | `passed` | 0.890 | 4 | 0.560 |
| [test-unitgen-go-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--test-unitgen-go-001.html) | [source](../../../benchmarks/ccb_test/test-unitgen-go-001) | `baseline-local-direct` | `passed` | 0.960 | 3 | 0.000 |
| [mcp_test-unitgen-go-001_qeR5PM](../tasks/ccb_test_haiku_20260228_124521--mcp-remote-direct--mcp_test-unitgen-go-001_qeR5PM.html) | [source](../../../benchmarks/ccb_test/test-unitgen-go-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.368 |
| [sgonly_test-unitgen-go-001](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_test-unitgen-go-001.html) | [source](../../../benchmarks/ccb_test/test-unitgen-go-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.556 |
| [test-unitgen-py-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--test-unitgen-py-001.html) | [source](../../../benchmarks/ccb_test/test-unitgen-py-001) | `baseline-local-direct` | `passed` | 0.600 | 3 | 0.000 |
| [mcp_test-unitgen-py-001_IHDrIE](../tasks/ccb_test_haiku_20260228_124521--mcp-remote-direct--mcp_test-unitgen-py-001_IHDrIE.html) | [source](../../../benchmarks/ccb_test/test-unitgen-py-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.692 |
| [sgonly_test-unitgen-py-001](../tasks/test_haiku_20260301_071232--mcp-remote-direct--sgonly_test-unitgen-py-001.html) | [source](../../../benchmarks/ccb_test/test-unitgen-py-001) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.938 |
| [vscode-code-review-001](../tasks/test_haiku_20260301_071232--baseline-local-direct--vscode-code-review-001.html) | [source](../../../benchmarks/ccb_test/vscode-code-review-001) | `baseline-local-direct` | `passed` | 0.450 | 4 | 0.000 |
| [mcp_vscode-code-review-001_YRYOVM](../tasks/ccb_test_haiku_20260224_180149--mcp-remote-direct--mcp_vscode-code-review-001_YRYOVM.html) | [source](../../../benchmarks/ccb_test/vscode-code-review-001) | `mcp-remote-direct` | `passed` | 0.300 | 3 | 0.700 |
| [sgonly_vscode-code-review-001](../tasks/test_haiku_20260224_011816--mcp-remote-direct--sgonly_vscode-code-review-001.html) | [source](../../../benchmarks/ccb_test/vscode-code-review-001) | `mcp-remote-direct` | `passed` | 0.360 | 3 | 0.875 |

## Multi-Run Variance

Tasks with multiple valid runs (35 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| aspnetcore-code-review-001 | [source](../../../benchmarks/ccb_test/aspnetcore-code-review-001) | `baseline-local-direct` | 3 | 0.557 | 0.011 | 0.550, 0.550, 0.570 |
| aspnetcore-code-review-001 | [source](../../../benchmarks/ccb_test/aspnetcore-code-review-001) | `mcp-remote-direct` | 3 | 0.417 | 0.075 | 0.330, 0.460, 0.460 |
| calcom-code-review-001 | [source](../../../benchmarks/ccb_test/calcom-code-review-001) | `baseline-local-direct` | 4 | 0.725 | 0.050 | 0.750, 0.650, 0.750, 0.750 |
| calcom-code-review-001 | [source](../../../benchmarks/ccb_test/calcom-code-review-001) | `mcp-remote-direct` | 2 | 0.445 | 0.078 | 0.500, 0.390 |
| curl-security-review-001 | [source](../../../benchmarks/ccb_test/curl-security-review-001) | `baseline-local-direct` | 6 | 0.625 | 0.091 | 0.670, 0.670, 0.670, 0.510, 0.720, 0.510 |
| envoy-code-review-001 | [source](../../../benchmarks/ccb_test/envoy-code-review-001) | `baseline-local-direct` | 4 | 0.700 | 0.041 | 0.700, 0.700, 0.750, 0.650 |
| envoy-code-review-001 | [source](../../../benchmarks/ccb_test/envoy-code-review-001) | `mcp-remote-direct` | 3 | 0.593 | 0.086 | 0.670, 0.500, 0.610 |
| ghost-code-review-001 | [source](../../../benchmarks/ccb_test/ghost-code-review-001) | `baseline-local-direct` | 3 | 0.800 | 0.000 | 0.800, 0.800, 0.800 |
| ghost-code-review-001 | [source](../../../benchmarks/ccb_test/ghost-code-review-001) | `mcp-remote-direct` | 3 | 0.737 | 0.132 | 0.880, 0.620, 0.710 |
| kafka-security-review-001 | [source](../../../benchmarks/ccb_test/kafka-security-review-001) | `baseline-local-direct` | 3 | 0.440 | 0.000 | 0.440, 0.440, 0.440 |
| kafka-security-review-001 | [source](../../../benchmarks/ccb_test/kafka-security-review-001) | `mcp-remote-direct` | 3 | 0.300 | 0.135 | 0.440, 0.170, 0.290 |
| numpy-array-sum-perf-001 | [source](../../../benchmarks/ccb_test/numpy-array-sum-perf-001) | `baseline-local-direct` | 3 | 0.000 | 0.000 | 0.000, 0.000, 0.000 |
| numpy-array-sum-perf-001 | [source](../../../benchmarks/ccb_test/numpy-array-sum-perf-001) | `mcp-remote-direct` | 3 | 0.000 | 0.000 | 0.000, 0.000, 0.000 |
| openhands-search-file-test-001 | [source](../../../benchmarks/ccb_test/openhands-search-file-test-001) | `baseline-local-direct` | 3 | 0.133 | 0.231 | 0.400, 0.000, 0.000 |
| openhands-search-file-test-001 | [source](../../../benchmarks/ccb_test/openhands-search-file-test-001) | `mcp-remote-direct` | 5 | 0.120 | 0.110 | 0.000, 0.000, 0.200, 0.200, 0.200 |
| pandas-groupby-perf-001 | [source](../../../benchmarks/ccb_test/pandas-groupby-perf-001) | `baseline-local-direct` | 3 | 0.000 | 0.000 | 0.000, 0.000, 0.000 |
| pandas-groupby-perf-001 | [source](../../../benchmarks/ccb_test/pandas-groupby-perf-001) | `mcp-remote-direct` | 4 | 0.000 | 0.000 | 0.000, 0.000, 0.000, 0.000 |
| sklearn-kmeans-perf-001 | [source](../../../benchmarks/ccb_test/sklearn-kmeans-perf-001) | `baseline-local-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
| sklearn-kmeans-perf-001 | [source](../../../benchmarks/ccb_test/sklearn-kmeans-perf-001) | `mcp-remote-direct` | 4 | 0.000 | 0.000 | 0.000, 0.000, 0.000, 0.000 |
| terraform-code-review-001 | [source](../../../benchmarks/ccb_test/terraform-code-review-001) | `baseline-local-direct` | 4 | 0.632 | 0.048 | 0.620, 0.670, 0.670, 0.570 |
| terraform-code-review-001 | [source](../../../benchmarks/ccb_test/terraform-code-review-001) | `mcp-remote-direct` | 2 | 0.445 | 0.078 | 0.500, 0.390 |
| test-coverage-gap-001 | [source](../../../benchmarks/ccb_test/test-coverage-gap-001) | `baseline-local-direct` | 3 | 0.860 | 0.000 | 0.860, 0.860, 0.860 |
| test-coverage-gap-001 | [source](../../../benchmarks/ccb_test/test-coverage-gap-001) | `mcp-remote-direct` | 5 | 0.872 | 0.044 | 0.860, 0.940, 0.880, 0.820, 0.860 |
| test-coverage-gap-002 | [source](../../../benchmarks/ccb_test/test-coverage-gap-002) | `baseline-local-direct` | 3 | 0.940 | 0.000 | 0.940, 0.940, 0.940 |
| test-coverage-gap-002 | [source](../../../benchmarks/ccb_test/test-coverage-gap-002) | `mcp-remote-direct` | 4 | 0.985 | 0.030 | 1.000, 0.940, 1.000, 1.000 |
| test-integration-001 | [source](../../../benchmarks/ccb_test/test-integration-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| test-integration-001 | [source](../../../benchmarks/ccb_test/test-integration-001) | `mcp-remote-direct` | 4 | 0.990 | 0.020 | 1.000, 1.000, 0.960, 1.000 |
| test-integration-002 | [source](../../../benchmarks/ccb_test/test-integration-002) | `baseline-local-direct` | 4 | 0.370 | 0.000 | 0.370, 0.370, 0.370, 0.370 |
| test-integration-002 | [source](../../../benchmarks/ccb_test/test-integration-002) | `mcp-remote-direct` | 4 | 0.922 | 0.052 | 0.900, 0.900, 1.000, 0.890 |
| test-unitgen-go-001 | [source](../../../benchmarks/ccb_test/test-unitgen-go-001) | `baseline-local-direct` | 3 | 0.847 | 0.196 | 0.620, 0.960, 0.960 |
| test-unitgen-go-001 | [source](../../../benchmarks/ccb_test/test-unitgen-go-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| test-unitgen-py-001 | [source](../../../benchmarks/ccb_test/test-unitgen-py-001) | `baseline-local-direct` | 3 | 0.560 | 0.069 | 0.480, 0.600, 0.600 |
| test-unitgen-py-001 | [source](../../../benchmarks/ccb_test/test-unitgen-py-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| vscode-code-review-001 | [source](../../../benchmarks/ccb_test/vscode-code-review-001) | `baseline-local-direct` | 4 | 0.463 | 0.025 | 0.450, 0.450, 0.500, 0.450 |
| vscode-code-review-001 | [source](../../../benchmarks/ccb_test/vscode-code-review-001) | `mcp-remote-direct` | 3 | 0.330 | 0.030 | 0.330, 0.360, 0.300 |
